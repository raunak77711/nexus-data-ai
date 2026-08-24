"""The Data Quality Doctor: what is wrong with this file, and how bad is it.

WHY THIS IS A SEPARATE MODULE from core.insights, which already has a quality
pass. Those two things look similar and are not. `insights` answers "what is
interesting about this data" and its quality cards compete for space against
trends and correlations -- a dataset with a fascinating seasonal pattern will
push its own missing-value problem off the list, which is correct behaviour for
a findings feed and wrong behaviour for an audit. This module answers a
different question -- "can I trust this file, and what would I have to fix" --
and it answers it exhaustively rather than interestingly. Nothing here is
ranked away.

THE SCORE
---------
One number, 0-100, and it is the honest kind: it is computed from penalties
that are each attributable to a named issue, so "87" always decomposes into a
list a user can read. A score assembled from a weighting nobody can see is a
decoration, and this one is meant to be argued with.

Penalties are proportional to how much of the data an issue touches, not flat.
A duplicate row in a million is not the same event as a duplicate row in ten,
and a checker that scores them identically will be ignored within a week.

THE FIX CONTRACT
----------------
An issue may carry a `fix`, which is a *proposal*, never an action. It names an
operation in core.cleaner and the arguments to run it with. This module never
touches the frame. The separation matters because the product promises the
original dataset is preserved and that changes are reviewed before they are
applied -- a detector that could also mutate would make that promise a matter
of discipline rather than of structure.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Scanning cap. Every check below is O(rows) at least, and several are O(rows
# log rows); on a very large upload the answer from a large sample is the same
# answer, and the difference between "instant" and "twelve seconds" decides
# whether anyone reads this screen. Sampling is always disclosed.
MAX_SCAN_ROWS = 200_000

SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_NOTICE = "notice"

# How much of the score each kind of problem can cost at its very worst -- i.e.
# when it affects the entire dataset. Real penalties scale down from these by
# the fraction actually affected, so these are ceilings and not typical values.
#
# The ordering encodes a judgement about what actually ruins an analysis:
# duplicated rows silently double every total you compute, so they cost the
# most; a column that never varies is untidy rather than dangerous, so it costs
# almost nothing.
PENALTY_CEILING = {
    "duplicate_rows": 22.0,
    "missing_values": 20.0,
    "empty_column": 14.0,
    "numeric_as_text": 12.0,
    "impossible_values": 12.0,
    "mixed_types": 10.0,
    "outliers": 9.0,
    "category_variants": 9.0,
    "duplicate_columns": 8.0,
    "whitespace": 6.0,
    "constant_column": 5.0,
}

# Thresholds. Named rather than inlined so that the one place to argue with this
# module's opinions is the top of this file.
HIGH_NULL_PCT = 20.0
SOME_NULL_PCT = 2.0
OUTLIER_FENCE = 3.0          # multiples of IQR; 1.5 is the textbook value and
                             # flags far too much on real business data
MIN_OUTLIER_ROWS = 12        # below this a quartile is not a quartile
MAX_OUTLIER_REPORT = 12
NUMERIC_AS_TEXT_THRESHOLD = 0.9   # share of non-null values that parse as numbers
MIXED_TYPE_MINORITY = 0.02        # a minority type has to be more than noise
MAX_CATEGORY_SCAN = 400           # distinct values compared for near-duplicates

# Values that mean "missing" but arrive as text and so survive every null check.
# Deliberately conservative: "N/A" is unambiguous, "-" is not, and a check that
# wrongly declares a legitimate value missing is worse than one that misses some.
NULL_SENTINELS = {
    "na", "n/a", "n.a.", "nan", "null", "none", "nil", "missing",
    "unknown", "undefined", "?", "--", "#n/a", "not available",
}

GRADES = (
    (90, "Excellent", "This data is in good shape. Analyse it with confidence."),
    (75, "Good", "A few things to be aware of, none of them serious."),
    (60, "Fair", "Usable, but some findings will be affected by the issues below."),
    (40, "Poor", "Fix the flagged issues before trusting any conclusion from this."),
    (0, "Critical", "This file has problems serious enough to invalidate an analysis."),
)

ID_PATTERN = re.compile(r"(^id$|_id$|^id_|^index$|_key$|_no$|number$|^unnamed)", re.I)


def _pct(part: float, whole: float) -> float:
    """Percentage, with the zero-row case answered rather than raised."""
    return round(100.0 * part / whole, 2) if whole else 0.0


def _fmt(value: Any) -> str:
    """Format a number for a sentence a person reads."""
    if isinstance(value, (bool, np.bool_)):
        return str(value)
    if isinstance(value, (int, np.integer)):
        return f"{int(value):,}"
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not np.isfinite(number):
            return "n/a"
        if abs(number) >= 1000:
            return f"{number:,.0f}"
        if abs(number) >= 1:
            return f"{number:,.2f}".rstrip("0").rstrip(".")
        return f"{number:,.4g}"
    return str(value)


def _scan(df: pd.DataFrame) -> Tuple[pd.DataFrame, bool]:
    """The frame to check, and whether it is a sample of a larger one."""
    if len(df) > MAX_SCAN_ROWS:
        return df.sample(MAX_SCAN_ROWS, random_state=0), True
    return df, False


def _is_text(series: pd.Series) -> bool:
    """Does this column hold text?

    Asked negatively -- not numeric, not a date, not a boolean -- rather than
    by testing for a text dtype, because there is no single text dtype to test
    for. pandas 3 gives a clean column of strings the `str` dtype and a column
    of strings mixed with anything else the `object` dtype, and
    `is_string_dtype` is True for the first and False for the second. A check
    written against either one alone silently skips half the columns it exists
    to examine, which is exactly the bug this helper was extracted to fix: every
    text check in this module passed on a file full of untrimmed, misspelled
    categories, and reported the file as clean.
    """
    return not (
        pd.api.types.is_numeric_dtype(series)
        or pd.api.types.is_datetime64_any_dtype(series)
        or pd.api.types.is_bool_dtype(series)
    )


def _issue(
    kind: str,
    severity: str,
    title: str,
    detail: str,
    why: str,
    *,
    columns: Optional[List[str]] = None,
    n_affected: int = 0,
    pct_affected: float = 0.0,
    fix: Optional[Dict[str, Any]] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One finding, in the shape the Health screen renders.

    `id` is derived from the kind and the columns rather than from a counter,
    so that the id of "the whitespace problem in `city`" is the same across two
    requests. The cleaner's approval flow sends ids back, and an id that
    reshuffled between the page rendering and the user pressing Apply would
    apply the wrong fix.
    """
    return {
        "id": f"{kind}:{'+'.join(columns or [])}",
        "kind": kind,
        "severity": severity,
        "title": title,
        "detail": detail,
        "why": why,
        "columns": columns or [],
        "n_affected": int(n_affected),
        "pct_affected": round(float(pct_affected), 2),
        "fix": fix,
        "evidence": evidence or {},
    }


def _fix(action: str, label: str, description: str, **params: Any) -> Dict[str, Any]:
    """A proposed repair: what core.cleaner would run, and what to call it."""
    return {
        "action": action,
        "label": label,
        "description": description,
        "params": params,
    }


# ------------------------------------------------------------------ checks --
def _check_duplicate_rows(df: pd.DataFrame, n_rows: int) -> List[Dict[str, Any]]:
    """Rows identical across every column.

    The count reported is the number a user would delete -- copies after the
    first -- not the size of the duplicated group, because that is the number
    that matches what the fix does.
    """
    try:
        n_dupes = int(df.duplicated(keep="first").sum())
    except TypeError:
        # Unhashable cell contents. CSV cannot produce them, but a future
        # loader might, and this is not a data problem worth reporting.
        return []
    if not n_dupes:
        return []

    pct = _pct(n_dupes, n_rows)
    return [
        _issue(
            "duplicate_rows",
            SEVERITY_CRITICAL if pct >= 5 else SEVERITY_WARNING,
            f"{_fmt(n_dupes)} duplicate rows",
            f"{_fmt(n_dupes)} rows ({pct}%) are exact copies of a row that "
            f"appears earlier in the file.",
            "Every total, average and count in your analysis is inflated by "
            "these. A sum over this data is currently wrong.",
            n_affected=n_dupes,
            pct_affected=pct,
            fix=_fix(
                "drop_duplicates",
                f"Remove {_fmt(n_dupes)} duplicate rows",
                "Keeps the first occurrence of each row and removes the copies.",
            ),
            evidence={"n_duplicates": n_dupes},
        )
    ]


def _check_duplicate_columns(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Two columns holding identical values under different names.

    Common in exported joins, where the join key survives twice. Worth flagging
    because a correlation matrix reports a perfect 1.0 between them and a
    reader thinks they have found something.
    """
    issues: List[Dict[str, Any]] = []
    seen: Dict[str, str] = {}

    for name in df.columns:
        try:
            fingerprint = int(pd.util.hash_pandas_object(df[name], index=False).sum())
        except TypeError:
            continue
        token = f"{df[name].dtype}:{fingerprint}"
        first = seen.get(token)
        if first is None:
            seen[token] = str(name)
            continue
        # The hash is a filter, not the answer: confirm before accusing.
        if not df[first].equals(df[name]):
            continue
        issues.append(
            _issue(
                "duplicate_columns",
                SEVERITY_WARNING,
                f"`{name}` duplicates `{first}`",
                f"Every value in `{name}` is identical to `{first}`.",
                "Two copies of one measurement will look like a perfect "
                "correlation between two different things.",
                columns=[str(name)],
                n_affected=len(df),
                pct_affected=100.0,
                fix=_fix(
                    "drop_column",
                    f"Remove `{name}`",
                    f"`{first}` already carries these values.",
                    column=str(name),
                ),
                evidence={"duplicate_of": str(first)},
            )
        )
    return issues


def _check_missing(df: pd.DataFrame, n_rows: int) -> List[Dict[str, Any]]:
    """Blanks, per column, plus text that means blank without being blank."""
    issues: List[Dict[str, Any]] = []

    for name in df.columns:
        series = df[name]
        n_null = int(series.isna().sum())

        # Text sentinels count as missing even though pandas sees a value.
        n_sentinel = 0
        if _is_text(series):
            lowered = series.dropna().astype(str).str.strip().str.lower()
            n_sentinel = int(lowered.isin(NULL_SENTINELS).sum())

        total = n_null + n_sentinel
        if not total:
            continue

        pct = _pct(total, n_rows)
        column = str(name)

        if pct >= 99.5:
            issues.append(
                _issue(
                    "empty_column",
                    SEVERITY_CRITICAL,
                    f"`{column}` is empty",
                    f"{pct}% of `{column}` has no value. There is effectively "
                    f"nothing in this column.",
                    "An empty column cannot contribute to any analysis and will "
                    "silently drop rows from anything that uses it.",
                    columns=[column],
                    n_affected=total,
                    pct_affected=pct,
                    fix=_fix(
                        "drop_column",
                        f"Remove `{column}`",
                        "The column holds no usable values.",
                        column=column,
                    ),
                )
            )
            continue

        sentinel_note = ""
        if n_sentinel:
            sentinel_note = (
                f" {_fmt(n_sentinel)} of them are written as text like "
                f'"N/A" or "unknown" rather than left blank, so most tools '
                f"will not notice they are missing."
            )

        # The proposed repair depends on what the column is. Filling a category
        # with its most common value invents membership; filling a measure with
        # its median is standard and does not move the centre. Neither is right
        # for every case, which is exactly why this is a proposal to approve.
        if pd.api.types.is_numeric_dtype(series):
            fix = _fix(
                "fill_missing",
                f"Fill the {_fmt(total)} gaps with the median",
                f"Uses the middle value of `{column}`, which does not move the "
                f"average the way filling with zero would.",
                column=column,
                strategy="median",
            )
        else:
            fix = _fix(
                "fill_missing",
                f'Label the {_fmt(total)} gaps "Unknown"',
                "Marks them explicitly rather than leaving them blank, so they "
                "stay visible in counts instead of vanishing.",
                column=column,
                strategy="label",
                value="Unknown",
            )

        issues.append(
            _issue(
                "missing_values",
                SEVERITY_CRITICAL if pct >= HIGH_NULL_PCT
                else SEVERITY_WARNING if pct >= SOME_NULL_PCT
                else SEVERITY_NOTICE,
                f"`{column}` is {pct}% empty",
                f"{_fmt(total)} of {_fmt(n_rows)} rows have no value for "
                f"`{column}`.{sentinel_note}",
                "Rows with a gap here are dropped from any calculation that "
                "uses this column, which quietly shrinks the data behind a "
                "number without saying so.",
                columns=[column],
                n_affected=total,
                pct_affected=pct,
                fix=fix,
                evidence={"n_blank": n_null, "n_text_sentinel": n_sentinel},
            )
        )

    return issues


# The longest run of LETTERS that may be treated as a unit or currency marker
# rather than as part of the value. See strip_numeric_decoration for why this is
# three and not a larger, friendlier number.
MAX_UNIT_MARKER = 3


def _shared_marker(values: pd.Series, *, at_start: bool) -> str:
    """The longest unit-like prefix or suffix that EVERY value carries.

    Returns "" when there is none, which is the common case and the safe one.
    The marker must contain no digits (a digit is data, not a unit) and at most
    MAX_UNIT_MARKER letters, though it may carry punctuation and spaces around
    them -- "Rs. " is two letters plus punctuation and is a currency marker.
    """
    if values.empty:
        return ""

    first = str(values.iloc[0])
    matches = values.str.startswith if at_start else values.str.endswith

    for length in range(min(len(first), 6), 0, -1):
        candidate = first[:length] if at_start else first[-length:]
        if any(char.isdigit() for char in candidate):
            continue
        if sum(char.isalpha() for char in candidate) > MAX_UNIT_MARKER:
            continue
        if bool(matches(candidate).all()):
            return candidate
    return ""


def strip_numeric_decoration(series: pd.Series) -> Tuple[pd.Series, pd.Series]:
    """Remove the punctuation that stops a number parsing, and parse it.

    Returns (text_as_given, parsed_numbers) so a caller can tell which values
    were present but unreadable -- the difference between "this column is
    convertible" and "this column is convertible and you will lose nine rows".

    PUBLIC, AND SHARED WITH core.cleaner ON PURPOSE. The health check counts how
    many values would convert and the cleaner converts them; if those two used
    separate implementations, the app would offer to fix 312 values and then
    change a different number of them. That is not a hypothetical -- it is the
    class of bug where a user approves one thing and gets another.

    WHAT IS STRIPPED, AND WHY IT IS CONSERVATIVE:

      * commas and spaces, anywhere -- thousands separators
      * a trailing percent sign
      * a leading non-alphanumeric run -- $, EUR-sign, currency symbols
      * a COMMON prefix or suffix shared by every value in the column

    That last rule is what makes "Rs 1,200.50" and "1,200 NPR" work, and it is
    deliberately restricted to a prefix the WHOLE COLUMN shares. Stripping any
    leading letters would turn a column of "Item 5", "Item 12" into numbers and
    claim a product code was a measurement. A marker every single value carries
    is a unit; a marker some of them carry is part of the data.
    """
    text = series.dropna().astype("string").str.strip()
    if text.empty:
        return text, text.astype("Float64")

    working = text

    # A shared marker: a prefix ("Rs ", "USD ", "$") or a suffix (" NPR", " kg").
    #
    # Capped at MAX_UNIT_MARKER letters, and that cap is doing real work rather
    # than being a round number. Every currency code and unit abbreviation that
    # matters here is three characters or fewer -- Rs, USD, NPR, EUR, kg, km, ms
    # -- while the thing this must NOT strip is a label word: a column of
    # "Item 5", "Item 12" shares the prefix "Item" and would otherwise be
    # converted into the numbers 5 and 12, silently destroying a set of product
    # codes. Four letters is where units stop and words start.
    prefix = _shared_marker(working, at_start=True)
    if prefix:
        working = working.str.slice(len(prefix))

    suffix = _shared_marker(working, at_start=False)
    if suffix:
        working = working.str.slice(0, -len(suffix))

    cleaned = (
        working.str.replace(r"[,\s]", "", regex=True)
        .str.replace(r"^[^\w.\-+]+", "", regex=True)
        .str.replace(r"%$", "", regex=True)
    )
    return text, pd.to_numeric(cleaned, errors="coerce")


def _check_numeric_as_text(df: pd.DataFrame, n_rows: int) -> List[Dict[str, Any]]:
    """Columns of digits stored as strings -- the most common CSV fault there is.

    Caused by currency symbols, thousands separators and stray spaces. The
    symptom is that the column cannot be averaged, summed or plotted, and the
    app reports it as a category with two thousand distinct values.
    """
    issues: List[Dict[str, Any]] = []

    for name in df.columns:
        series = df[name]
        if not _is_text(series):
            continue
        # An identifier that happens to be digits is not a measurement, and
        # converting one would turn "00123" into 123 and lose the leading zeros
        # that made it an identifier.
        if ID_PATTERN.search(str(name)):
            continue

        values, parsed = strip_numeric_decoration(series)
        if values.empty:
            continue

        share = float(parsed.notna().mean())
        if share < NUMERIC_AS_TEXT_THRESHOLD:
            continue
        # A column pandas could already have typed numerically is not this
        # problem -- it would have done so on read. Something must have needed
        # stripping for this to be a real finding, which is what comparing the
        # parsed result against the original text establishes.
        if values.equals(parsed.astype("string")):
            continue

        column = str(name)
        n_convertible = int(parsed.notna().sum())
        example = str(values.iloc[0])
        issues.append(
            _issue(
                "numeric_as_text",
                SEVERITY_CRITICAL,
                f"`{column}` holds numbers stored as text",
                f"{_pct(n_convertible, len(values))}% of `{column}` is a number "
                f'wearing punctuation -- for example "{example}". Stored this '
                f"way it cannot be summed, averaged or charted.",
                "This is why a column you know is a number shows up as a "
                "category. Converting it unlocks every calculation on it.",
                columns=[column],
                n_affected=n_convertible,
                pct_affected=_pct(n_convertible, n_rows),
                fix=_fix(
                    "to_numeric",
                    f"Convert `{column}` to a number",
                    "Removes currency symbols, separators and spaces, then "
                    "reads the result as a number.",
                    column=column,
                ),
                evidence={"example": example, "parse_rate": round(share, 3)},
            )
        )

    return issues


def _check_mixed_types(df: pd.DataFrame, n_rows: int) -> List[Dict[str, Any]]:
    """One column holding two kinds of thing -- numbers and words together.

    Distinct from numeric-as-text: there the whole column is numbers with
    decoration, here the column genuinely contains both, which usually means a
    footer row, a "TOTAL" line, or two sources concatenated.
    """
    issues: List[Dict[str, Any]] = []

    for name in df.columns:
        series = df[name]
        if not _is_text(series):
            continue
        values = series.dropna().astype(str).str.strip()
        if len(values) < 10:
            continue

        numeric_mask = pd.to_numeric(
            values.str.replace(r"[,\s]", "", regex=True), errors="coerce"
        ).notna()
        share_numeric = float(numeric_mask.mean())

        # Interesting only when neither kind is a rounding error, and when the
        # numeric-as-text check above has not already claimed the column.
        if not MIXED_TYPE_MINORITY < share_numeric < NUMERIC_AS_TEXT_THRESHOLD:
            continue

        column = str(name)
        minority_is_numeric = share_numeric < 0.5
        odd = values[numeric_mask if minority_is_numeric else ~numeric_mask]
        n_minority = int(len(odd))
        examples = [str(v) for v in odd.head(3).tolist()]

        issues.append(
            _issue(
                "mixed_types",
                SEVERITY_WARNING,
                f"`{column}` mixes numbers and text",
                f"{round(share_numeric * 100, 1)}% of `{column}` reads as a "
                f"number and the rest does not. The odd ones out look like: "
                f"{', '.join(repr(e) for e in examples)}.",
                "A column has to mean one thing to be analysed. Mixed content "
                "usually means a total row, a header repeated mid-file, or two "
                "different exports stacked together.",
                columns=[column],
                n_affected=n_minority,
                pct_affected=_pct(n_minority, n_rows),
                # Deliberately no fix: which side of the mixture is the mistake
                # is a question about the user's data that this app cannot
                # answer, and guessing would destroy the minority either way.
                fix=None,
                evidence={"examples": examples, "share_numeric": round(share_numeric, 3)},
            )
        )

    return issues


def _check_whitespace(df: pd.DataFrame, n_rows: int) -> List[Dict[str, Any]]:
    """Leading or trailing spaces, which split one category into two silently."""
    issues: List[Dict[str, Any]] = []

    for name in df.columns:
        series = df[name]
        if not _is_text(series):
            continue
        values = series.dropna().astype(str)
        if values.empty:
            continue
        n_untidy = int((values != values.str.strip()).sum())
        if not n_untidy:
            continue

        column = str(name)
        issues.append(
            _issue(
                "whitespace",
                SEVERITY_WARNING,
                f"`{column}` has {_fmt(n_untidy)} values with stray spaces",
                f"{_fmt(n_untidy)} values in `{column}` start or end with a "
                f'space -- so "Kathmandu" and "Kathmandu " are being counted '
                f"as two different things.",
                "Invisible on screen, and it splits one group into several in "
                "every count, chart and grouping you make.",
                columns=[column],
                n_affected=n_untidy,
                pct_affected=_pct(n_untidy, n_rows),
                fix=_fix(
                    "trim_whitespace",
                    f"Trim the spaces in `{column}`",
                    "Removes leading and trailing spaces. Nothing inside a "
                    "value is changed.",
                    column=column,
                ),
            )
        )

    return issues


def _check_category_variants(df: pd.DataFrame, n_rows: int) -> List[Dict[str, Any]]:
    """The same category written several ways: KTM / ktm / Ktm.

    Only case and punctuation variants are claimed. Fuzzy matching on edit
    distance would also catch "Kathmandu"/"Kathmandhu" -- and would confidently
    merge "Region 1" with "Region 2". A cleaner that merges two genuinely
    different categories destroys data, so this stays conservative.
    """
    issues: List[Dict[str, Any]] = []

    for name in df.columns:
        series = df[name]
        if not _is_text(series):
            continue
        values = series.dropna().astype(str).str.strip()
        uniques = values.unique()
        if not 1 < len(uniques) <= MAX_CATEGORY_SCAN:
            continue

        groups: Dict[str, List[str]] = {}
        for value in uniques:
            key = re.sub(r"[^a-z0-9]", "", str(value).lower())
            if key:
                groups.setdefault(key, []).append(str(value))

        collisions = {k: v for k, v in groups.items() if len(v) > 1}
        if not collisions:
            continue

        column = str(name)
        counts = values.value_counts()
        # The canonical spelling is the most frequent one, not the first seen:
        # merging a thousand rows of "Kathmandu" into three rows of "kathmandu"
        # would technically be a merge and obviously the wrong direction.
        mapping: Dict[str, str] = {}
        n_affected = 0
        for variants in collisions.values():
            canonical = max(variants, key=lambda v: int(counts.get(v, 0)))
            for variant in variants:
                if variant != canonical:
                    mapping[variant] = canonical
                    n_affected += int(counts.get(variant, 0))

        sample = next(iter(collisions.values()))[:3]
        issues.append(
            _issue(
                "category_variants",
                SEVERITY_WARNING,
                f"`{column}` spells {len(collisions)} value(s) more than one way",
                f"Values that mean the same thing are written differently -- "
                f"for example {', '.join(repr(s) for s in sample)}. "
                f"{_fmt(n_affected)} rows use a non-standard spelling.",
                "Each spelling becomes its own bar in a chart and its own row "
                "in a count, so one real category looks like several small ones.",
                columns=[column],
                n_affected=n_affected,
                pct_affected=_pct(n_affected, n_rows),
                fix=_fix(
                    "merge_categories",
                    f"Merge the spellings in `{column}`",
                    f"Rewrites {len(mapping)} spelling(s) to the most common "
                    f"version of each. Only differences in capitalisation and "
                    f"punctuation are merged.",
                    column=column,
                    mapping=mapping,
                ),
                evidence={"groups": dict(list(collisions.items())[:5])},
            )
        )

    return issues


def _check_constant(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Columns that never change, which carry no information at all."""
    issues: List[Dict[str, Any]] = []

    for name in df.columns:
        series = df[name].dropna()
        if series.empty:
            continue
        try:
            if int(series.nunique()) > 1:
                continue
        except TypeError:
            continue

        column = str(name)
        issues.append(
            _issue(
                "constant_column",
                SEVERITY_NOTICE,
                f"`{column}` is always the same",
                f"Every row has `{column}` = {_fmt(series.iloc[0])}.",
                "A column that never varies cannot explain anything that does. "
                "It is not wrong, just not useful.",
                columns=[column],
                n_affected=len(df),
                pct_affected=100.0,
                fix=_fix(
                    "drop_column",
                    f"Remove `{column}`",
                    "It holds one repeated value and cannot affect any result.",
                    column=column,
                ),
                evidence={"value": _fmt(series.iloc[0])},
            )
        )
    return issues


# Rules for "impossible" values. Only claims that are safe from the column NAME
# plus the values, because a checker that guesses at semantics will eventually
# tell a physicist their negative temperature is a mistake. Each entry is a name
# pattern, a lower bound, an upper bound, and what the name says the column is.
IMPOSSIBLE_RULES = (
    (r"(^|_)age($|_)", 0.0, 130.0, "an age"),
    (r"(pct|percent|percentage|_rate)($|_)", -100.0, 100.0, "a percentage"),
    (r"(^|_)(qty|quantity|count|units|stock)($|_)", 0.0, None, "a quantity"),
    (r"(price|amount|revenue|sales|cost|salary|income)($|_)", 0.0, None, "money"),
)


def _check_impossible(df: pd.DataFrame, n_rows: int) -> List[Dict[str, Any]]:
    """Values that cannot be what the column's own name claims they are."""
    issues: List[Dict[str, Any]] = []

    for name in df.columns:
        series = df[name]
        if not pd.api.types.is_numeric_dtype(series):
            continue
        lowered = str(name).lower()

        for pattern, low, high, what in IMPOSSIBLE_RULES:
            if not re.search(pattern, lowered):
                continue

            values = series.dropna()
            if values.empty:
                break
            bad = pd.Series(False, index=values.index)
            if low is not None:
                bad |= values < low
            if high is not None:
                bad |= values > high
            n_bad = int(bad.sum())
            if not n_bad:
                break

            bounds = (
                f"below {_fmt(low)}" if high is None
                else f"outside {_fmt(low)} to {_fmt(high)}"
            )
            column = str(name)
            issues.append(
                _issue(
                    "impossible_values",
                    SEVERITY_CRITICAL,
                    f"`{column}` has {_fmt(n_bad)} impossible value(s)",
                    f"`{column}` looks like {what}, but {_fmt(n_bad)} rows are "
                    f"{bounds} -- for example {_fmt(values[bad].iloc[0])}.",
                    "These are almost certainly data entry or export errors. "
                    "They will distort every average and every chart axis.",
                    columns=[column],
                    n_affected=n_bad,
                    pct_affected=_pct(n_bad, n_rows),
                    fix=_fix(
                        "drop_invalid",
                        f"Remove the {_fmt(n_bad)} impossible row(s)",
                        f"Drops rows where `{column}` is {bounds}.",
                        column=column,
                        low=low,
                        high=high,
                    ),
                    evidence={"min_allowed": low, "max_allowed": high},
                )
            )
            # One rule per column: the first name match is the claim, and a
            # second would be describing the same values twice.
            break

    return issues


def outlier_bounds(values: pd.Series) -> Optional[Tuple[float, float]]:
    """The IQR fence for a numeric series, or None if it has no usable spread.

    Public because core.cleaner needs the identical fence to apply a cap that
    matches the one the health report proposed -- two implementations of this
    would eventually disagree, and the user would approve one number and get
    another.
    """
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if len(clean) < MIN_OUTLIER_ROWS:
        return None
    q1, q3 = float(clean.quantile(0.25)), float(clean.quantile(0.75))
    iqr = q3 - q1
    if iqr <= 0:
        return None
    return q1 - OUTLIER_FENCE * iqr, q3 + OUTLIER_FENCE * iqr


def _check_outliers(
    df: pd.DataFrame, profile: Dict[str, Any], n_rows: int
) -> List[Dict[str, Any]]:
    """Values far outside the normal range, with the actual rows named.

    Named rows are the point. "3 outliers detected" is a statistic; "row 18,291
    is 14x the typical value" is something a person can go and check, and it is
    what the Investigate action opens.
    """
    issues: List[Dict[str, Any]] = []

    for column_info in profile.get("columns", []):
        name = column_info.get("name")
        if column_info.get("semantic_type") != "numeric":
            continue
        if name not in df.columns or ID_PATTERN.search(str(name)):
            continue

        values = pd.to_numeric(df[name], errors="coerce")
        bounds = outlier_bounds(values)
        if bounds is None:
            continue
        low, high = bounds
        mask = (values < low) | (values > high)
        n_out = int(mask.sum())
        if not n_out:
            continue

        median = float(values.median())
        # Ranked by distance from the fence rather than by absolute magnitude,
        # so a large negative outlier is not sorted below a small positive one.
        distance = pd.concat([low - values[mask], values[mask] - high], axis=1).max(axis=1)
        rows: List[Dict[str, Any]] = []
        for label in distance.sort_values(ascending=False).head(MAX_OUTLIER_REPORT).index:
            actual = float(values.loc[label])
            rows.append(
                {
                    "row": int(df.index.get_loc(label)),
                    "value": actual,
                    "display": _fmt(actual),
                    # "times the typical value" is the comparison a
                    # non-technical reader can act on. Guarded against a zero
                    # median, where the ratio is meaningless rather than large.
                    "ratio": round(actual / median, 2) if median else None,
                    "direction": "above" if actual > high else "below",
                }
            )

        column = str(name)
        detail = (
            f"{_fmt(n_out)} rows have a `{column}` far outside the usual range "
            f"of {_fmt(low)} to {_fmt(high)}."
        )
        worst = rows[0] if rows else None
        if worst and worst["ratio"]:
            detail += (
                f" The most extreme is row {worst['row']:,} at {worst['display']} "
                f"-- {_fmt(abs(worst['ratio']))}x the typical value of {_fmt(median)}."
            )

        issues.append(
            _issue(
                "outliers",
                SEVERITY_WARNING if _pct(n_out, n_rows) > 1 else SEVERITY_NOTICE,
                f"{_fmt(n_out)} unusual value(s) in `{column}`",
                detail,
                "An outlier is not automatically an error -- it may be your most "
                "important customer. But it moves averages a long way, so it is "
                "worth knowing which rows they are.",
                columns=[column],
                n_affected=n_out,
                pct_affected=_pct(n_out, n_rows),
                fix=_fix(
                    "cap_outliers",
                    f"Cap the extremes in `{column}`",
                    f"Pulls values beyond {_fmt(low)} / {_fmt(high)} back to "
                    f"those limits, keeping the rows but limiting their pull on "
                    f"averages.",
                    column=column,
                    low=low,
                    high=high,
                ),
                evidence={
                    "low": low,
                    "high": high,
                    "median": median,
                    "rows": rows,
                    "column": column,
                },
            )
        )

    return issues


# ------------------------------------------------------------------ scoring --
def _score(issues: List[Dict[str, Any]], n_cols: int) -> float:
    """Turn the issue list into a number, attaching each penalty to its issue.

    Penalties scale with reach: an issue touching 2% of the data costs roughly
    a fifth of what one touching 50% costs, not the same. Column-scoped issues
    are additionally divided by the column count, because one bad column out of
    forty is not the same event as one out of two.
    """
    total = 0.0
    for issue in issues:
        ceiling = PENALTY_CEILING.get(issue["kind"], 5.0)
        reach = issue["pct_affected"] / 100.0

        if issue["columns"]:
            reach *= len(issue["columns"]) / max(n_cols, 1)

        # sqrt rather than linear: the step from 0% to 5% affected matters far
        # more than the step from 60% to 65%, and a linear scale renders
        # small-but-real problems as noise.
        penalty = ceiling * min(1.0, float(np.sqrt(max(reach, 0.0))))

        # A critical issue always costs something meaningful even when it
        # touches few rows -- eleven impossible ages in a million rows still
        # means the export is broken.
        if issue["severity"] == SEVERITY_CRITICAL:
            penalty = max(penalty, ceiling * 0.25)

        penalty = round(min(penalty, ceiling), 2)
        issue["penalty"] = penalty
        total += penalty

    return max(0.0, 100.0 - total)


def _grade(score: float) -> Tuple[str, str]:
    """The word and the sentence that go with a score."""
    for threshold, label, verdict in GRADES:
        if score >= threshold:
            return label, verdict
    return GRADES[-1][1], GRADES[-1][2]


# Each pass, with what to say when it finds nothing. The "clean" sentence is
# not filler: a health screen that only ever shows problems teaches people that
# a short list means the checker is broken, so passing checks are reported too.
PASSES = (
    ("duplicate rows", "No duplicate rows", "Every row in this file is distinct."),
    ("duplicate columns", "No repeated columns", "No two columns hold the same values."),
    ("missing values", "No missing values", "Every row has a value in every column."),
    ("numbers stored as text", "Number columns are usable",
     "Every numeric column can be summed and charted."),
    ("mixed types", "Columns are consistent",
     "Each column holds one kind of value throughout."),
    ("whitespace", "Text is tidy", "No values carry stray leading or trailing spaces."),
    ("category spellings", "Categories are consistent", "Each category is spelled one way."),
    ("constant columns", "Every column varies",
     "No column holds the same value in every row."),
    ("impossible values", "Values are plausible",
     "Nothing is outside the range its column name implies."),
    ("outliers", "No extreme outliers",
     "Every value sits within the normal range for its column."),
)


def assess(df: pd.DataFrame, profile: Dict[str, Any]) -> Dict[str, Any]:
    """Run every check and return the dataset's health report.

    Args:
        df: the session's DataFrame, unmodified. Nothing here writes to it.
        profile: core.profiler.profile_dataframe output, used for semantic
            types so this module does not re-derive them differently.

    Returns:
        {"score": float, "grade": str, "verdict": str, "headline": str,
         "issues": [issue, ...], "counts": {severity: n}, "n_fixable": int,
         "checks_run": int, "sampled": bool, "n_rows": int, "n_cols": int,
         "clean": [{"title", "detail"}, ...]}

    Never raises for a data condition. A check that fails is logged and skipped,
    so one pathological column cannot cost the user the whole report.
    """
    frame, sampled = _scan(df)
    n_rows = int(len(frame))
    n_cols = int(len(frame.columns))

    if n_rows == 0:
        return {
            "score": 0.0,
            "grade": "Critical",
            "verdict": "There are no rows in this file.",
            "headline": "This file has no data in it.",
            "issues": [],
            "counts": {SEVERITY_CRITICAL: 0, SEVERITY_WARNING: 0, SEVERITY_NOTICE: 0},
            "n_fixable": 0,
            "checks_run": 0,
            "sampled": False,
            "n_rows": 0,
            "n_cols": n_cols,
            "clean": [],
        }

    checks = (
        lambda: _check_duplicate_rows(frame, n_rows),
        lambda: _check_duplicate_columns(frame),
        lambda: _check_missing(frame, n_rows),
        lambda: _check_numeric_as_text(frame, n_rows),
        lambda: _check_mixed_types(frame, n_rows),
        lambda: _check_whitespace(frame, n_rows),
        lambda: _check_category_variants(frame, n_rows),
        lambda: _check_constant(frame),
        lambda: _check_impossible(frame, n_rows),
        lambda: _check_outliers(frame, profile, n_rows),
    )

    issues: List[Dict[str, Any]] = []
    clean: List[Dict[str, Any]] = []
    checks_run = 0

    for check, (label, ok_title, ok_detail) in zip(checks, PASSES):
        try:
            found = check()
        except (ValueError, TypeError, KeyError, ArithmeticError, AttributeError):
            logger.exception("Health check %r failed", label)
            continue
        checks_run += 1
        if found:
            issues.extend(found)
        else:
            clean.append({"title": ok_title, "detail": ok_detail})

    # Ordering: severity first, then reach. Someone scanning this list top-down
    # should be reading it in the order they ought to act on it.
    rank = {SEVERITY_CRITICAL: 0, SEVERITY_WARNING: 1, SEVERITY_NOTICE: 2}
    issues.sort(key=lambda i: (rank.get(i["severity"], 3), -i["pct_affected"]))

    score = round(_score(issues, n_cols), 1)
    grade, verdict = _grade(score)

    counts = {
        severity: sum(1 for i in issues if i["severity"] == severity)
        for severity in (SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_NOTICE)
    }
    n_fixable = sum(1 for i in issues if i.get("fix"))

    if not issues:
        headline = (
            f"All {checks_run} checks passed. This is a clean dataset -- nothing "
            f"needs fixing before you analyse it."
        )
    else:
        parts = []
        if counts[SEVERITY_CRITICAL]:
            parts.append(f"{counts[SEVERITY_CRITICAL]} serious")
        if counts[SEVERITY_WARNING]:
            parts.append(f"{counts[SEVERITY_WARNING]} worth attention")
        if counts[SEVERITY_NOTICE]:
            parts.append(f"{counts[SEVERITY_NOTICE]} minor")
        headline = (
            f"{len(issues)} issue{'s' if len(issues) != 1 else ''} found across "
            f"{checks_run} checks: {', '.join(parts)}."
        )
        if n_fixable:
            headline += f" {n_fixable} can be fixed automatically."

    return {
        "score": score,
        "grade": grade,
        "verdict": verdict,
        "headline": headline,
        "issues": issues,
        "counts": counts,
        "n_fixable": n_fixable,
        "checks_run": checks_run,
        "sampled": sampled,
        "n_rows": int(len(df)),
        "n_cols": n_cols,
        "clean": clean,
    }
