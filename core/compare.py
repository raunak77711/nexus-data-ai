"""What changed between two datasets.

THE QUESTION THIS ANSWERS
-------------------------
Somebody has last year's export and this year's. They do not want two
dashboards side by side -- they can already open two tabs. They want the
difference, ranked, in words: what grew, what shrank, what appeared, what
vanished, and which of those changes is big enough to be worth their attention.

WHAT MAKES A DIFFERENCE WORTH REPORTING
---------------------------------------
Not its size. A 4% move in the measure the business runs on matters more than a
900% move in a column that was near zero in both files, and a comparison tool
that sorts by percentage change will lead with the second one every time. So
every change carries a `score` combining how large it is with how much of the
data it covers, and the report is ordered by that.

The other half of the job is refusing to compare things that are not
comparable. Two files with no columns in common are not two versions of one
dataset, and saying "revenue fell 100%" because the second file calls it
`total_revenue` would be worse than useless. Column matching is therefore
explicit, reported, and never fuzzy -- an unmatched column is listed as
appeared or disappeared, never silently paired with something that looks close.

NOTHING HERE IS WRITTEN BY A MODEL. Every number is computed by pandas; the
narrative sentences are assembled from templates. `narrate` may then hand the
computed changes to core.llm for rephrasing, under the same grounding check
every other prose path in this project uses.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

from core import grounding, llm
from core.llm import LLMError

logger = logging.getLogger(__name__)

MAX_CHANGES = 12
MAX_CATEGORY_REPORT = 8

# A change smaller than this is noise in most business data, and reporting it
# fills the list with rows nobody acts on.
MIN_REPORTABLE_PCT = 2.0

# Below this many rows a mean is not stable enough to compare against another
# mean and call the difference a change.
MIN_ROWS_FOR_COMPARISON = 5

# Share of a category's presence that must shift before it is called a shift.
MIN_CATEGORY_SHIFT_PCT = 3.0

NARRATE_TOKENS = 700
TEMPERATURE = 0.35

NARRATE_PROMPT = """You are summarising what changed between two versions of a \
dataset, for someone who has not looked at either.

You are given a JSON object with the two files' names, their shapes, and a list
of CHANGES that have already been computed and verified.

ABSOLUTE RULES:
1. Every number you write must appear in the CHANGES or the shapes you were
   given. Do not calculate anything new -- no totals, no averages of the
   changes, no combined percentages.
2. Do not invent a cause. "Revenue fell 12%" must not become "revenue fell 12%
   due to seasonality".
3. Do not describe a change that is not in the list.
4. If the changes are all small, say the two files are broadly similar. That is
   a useful finding, not a failure.

STYLE: one paragraph of 3 to 5 sentences. Lead with the single most important
change. Plain language, second person. No markdown, no lists, no headings.

Respond with raw JSON only, no code fences, exactly this shape:
{"summary": "..."}"""


def _fmt(value: Any) -> str:
    """A number as a person would write it."""
    if value is None:
        return "n/a"
    if isinstance(value, (bool, np.bool_)):
        return "Yes" if value else "No"
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


def _pct_change(before: float, after: float) -> Optional[float]:
    """Percentage change, or None where the question does not have an answer.

    A change from zero has no percentage -- every answer is either infinite or
    arbitrary -- and returning a large number instead of None is how comparison
    tools end up reporting "+999999%" for a column that went from 0 to 3.
    """
    if before is None or after is None:
        return None
    if not np.isfinite(before) or not np.isfinite(after):
        return None
    if abs(before) < 1e-12:
        return None
    return float((after - before) / abs(before) * 100.0)


def _friendly(name: str) -> str:
    return str(name).replace("_", " ").replace("-", " ").strip()


def _change(
    kind: str,
    column: Optional[str],
    headline: str,
    detail: str,
    *,
    direction: str,
    score: float,
    before: Any = None,
    after: Any = None,
    pct: Optional[float] = None,
) -> Dict[str, Any]:
    """One reported difference, in the shape the comparison screen renders."""
    return {
        "id": f"{kind}:{column or 'dataset'}",
        "kind": kind,
        "column": column,
        "headline": headline,
        "detail": detail,
        # "up" / "down" / "flat" / "added" / "removed". Kept separate from the
        # sign of `pct` because a category appearing has a direction and no
        # percentage, and the UI needs one rule for which arrow to draw.
        "direction": direction,
        "before": before,
        "after": after,
        "pct_change": round(pct, 2) if pct is not None else None,
        "score": round(float(score), 3),
    }


def _align_columns(
    profile_a: Dict[str, Any], profile_b: Dict[str, Any]
) -> Tuple[List[str], List[str], List[str], Dict[str, str]]:
    """Match the two files' columns by name, exactly and then case-insensitively.

    Returns (shared, only_in_a, only_in_b, type_conflicts).

    Case-insensitive matching is the only fuzziness permitted, because
    `Revenue` and `revenue` are the same column renamed by a spreadsheet and
    nothing else is safe to assume. `revenue` and `total_revenue` are NOT
    matched: they might be the same measure and they might be a subtotal and a
    total, and getting that wrong produces a headline change that is entirely
    fictional.
    """
    types_a = {
        str(c["name"]): str(c["semantic_type"]) for c in profile_a.get("columns", [])
    }
    types_b = {
        str(c["name"]): str(c["semantic_type"]) for c in profile_b.get("columns", [])
    }

    lookup_b = {name.lower(): name for name in types_b}
    shared: List[str] = []
    only_a: List[str] = []
    conflicts: Dict[str, str] = {}

    matched_b: Set[str] = set()
    for name in types_a:
        match = name if name in types_b else lookup_b.get(name.lower())
        if match is None:
            only_a.append(name)
            continue
        matched_b.add(match)
        shared.append(name)
        if types_a[name] != types_b[match]:
            # Reported rather than resolved. A column that was numbers and is
            # now text is itself the most important finding about that column,
            # and quietly coercing one side to match would hide it.
            conflicts[name] = (
                f"was {types_a[name]} in the first file, {types_b[match]} in the second"
            )

    only_b = [name for name in types_b if name not in matched_b]
    return shared, only_a, only_b, conflicts


def _resolve(df: pd.DataFrame, name: str) -> Optional[str]:
    """The real column in `df` matching `name`, allowing for case differences."""
    if name in df.columns:
        return name
    lookup = {str(c).lower(): str(c) for c in df.columns}
    return lookup.get(name.lower())


def _shape_changes(
    df_a: pd.DataFrame, df_b: pd.DataFrame, only_a: List[str], only_b: List[str]
) -> List[Dict[str, Any]]:
    """How the two files differ in size and structure."""
    changes: List[Dict[str, Any]] = []
    rows_a, rows_b = len(df_a), len(df_b)
    pct = _pct_change(rows_a, rows_b)

    if rows_a != rows_b:
        direction = "up" if rows_b > rows_a else "down"
        changes.append(
            _change(
                "row_count",
                None,
                f"{'More' if rows_b > rows_a else 'Fewer'} rows: "
                f"{_fmt(rows_a)} to {_fmt(rows_b)}",
                f"The second file has {_fmt(abs(rows_b - rows_a))} "
                f"{'more' if rows_b > rows_a else 'fewer'} rows"
                + (f", a change of {pct:+.1f}%." if pct is not None else "."),
                direction=direction,
                # Always near the top: a change in row count is the context for
                # every other change in the report. A measure's total falling
                # while the row count halved is not the same story as it falling
                # with the row count steady.
                score=95.0,
                before=rows_a,
                after=rows_b,
                pct=pct,
            )
        )

    if only_b:
        changes.append(
            _change(
                "columns_added",
                None,
                f"{len(only_b)} new column(s)",
                f"The second file has column(s) the first did not: "
                f"{', '.join(f'`{c}`' for c in only_b[:6])}"
                + (f" and {len(only_b) - 6} more." if len(only_b) > 6 else "."),
                direction="added",
                score=70.0,
            )
        )

    if only_a:
        changes.append(
            _change(
                "columns_removed",
                None,
                f"{len(only_a)} column(s) no longer present",
                f"The first file had column(s) the second does not: "
                f"{', '.join(f'`{c}`' for c in only_a[:6])}"
                + (f" and {len(only_a) - 6} more." if len(only_a) > 6 else "."),
                direction="removed",
                # Higher than columns added: losing a column breaks any analysis
                # that depended on it, whereas gaining one only adds options.
                score=75.0,
            )
        )

    return changes


def _numeric_changes(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    shared: List[str],
    profile_a: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """How each shared measure moved.

    Both the total and the average are computed, and which one is REPORTED
    depends on whether the row count changed. If the files are different sizes,
    a change in total is partly just a change in how many rows there are, and
    the average is the honest comparison. This is the single most common way a
    naive comparison misleads: "revenue doubled" when the export simply covers
    twice as many months.
    """
    changes: List[Dict[str, Any]] = []
    numeric = {
        str(c["name"])
        for c in profile_a.get("columns", [])
        if str(c.get("semantic_type")) == "numeric"
    }
    rows_differ = abs(len(df_a) - len(df_b)) / max(len(df_a), 1) > 0.02

    for name in shared:
        if name not in numeric:
            continue
        col_b = _resolve(df_b, name)
        if col_b is None:
            continue

        values_a = pd.to_numeric(df_a[name], errors="coerce").dropna()
        values_b = pd.to_numeric(df_b[col_b], errors="coerce").dropna()
        if len(values_a) < MIN_ROWS_FOR_COMPARISON or len(values_b) < MIN_ROWS_FOR_COMPARISON:
            continue

        mean_a, mean_b = float(values_a.mean()), float(values_b.mean())
        sum_a, sum_b = float(values_a.sum()), float(values_b.sum())

        statistic = "average" if rows_differ else "total"
        before, after = (mean_a, mean_b) if rows_differ else (sum_a, sum_b)
        pct = _pct_change(before, after)

        if pct is None or abs(pct) < MIN_REPORTABLE_PCT:
            continue

        direction = "up" if after > before else "down"
        verb = "rose" if after > before else "fell"

        detail = (
            f"The {statistic} {_friendly(name)} {verb} from {_fmt(before)} to "
            f"{_fmt(after)}, a change of {pct:+.1f}%."
        )
        if rows_differ:
            detail += (
                f" The average is compared rather than the total, because the "
                f"two files have different numbers of rows."
            )

        changes.append(
            _change(
                "measure",
                name,
                f"{_friendly(name).capitalize()} {verb} {abs(pct):.1f}%",
                detail,
                direction=direction,
                # Size of the move, damped, so a huge move in a small column
                # cannot outrank a solid move in a big one -- but with enough
                # weight that a real swing still leads.
                score=40.0 + min(abs(pct), 200.0) / 4.0,
                before=round(before, 4),
                after=round(after, 4),
                pct=pct,
            )
        )

        # A shift in spread with no shift in centre is a real and easily missed
        # change: same average, different consistency.
        std_a, std_b = float(values_a.std()), float(values_b.std())
        spread_pct = _pct_change(std_a, std_b)
        if spread_pct is not None and abs(spread_pct) >= 25.0 and abs(pct) < 10.0:
            changes.append(
                _change(
                    "spread",
                    name,
                    f"{_friendly(name).capitalize()} became "
                    f"{'more variable' if spread_pct > 0 else 'more consistent'}",
                    f"The average {_friendly(name)} barely moved, but its spread "
                    f"changed {spread_pct:+.1f}% -- values are "
                    f"{'further from' if spread_pct > 0 else 'closer to'} the "
                    f"middle than they were.",
                    direction="up" if spread_pct > 0 else "down",
                    score=35.0 + min(abs(spread_pct), 100.0) / 10.0,
                    before=round(std_a, 4),
                    after=round(std_b, 4),
                    pct=spread_pct,
                )
            )

    return changes


def _category_changes(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    shared: List[str],
    profile_a: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Categories that appeared, vanished, or changed their share of the data.

    Share rather than count, for the same reason the numeric pass prefers the
    average: in a file that grew by half, every category's count grew, and a
    report saying so twelve times tells the reader nothing.
    """
    changes: List[Dict[str, Any]] = []
    categorical = {
        str(c["name"])
        for c in profile_a.get("columns", [])
        if str(c.get("semantic_type")) == "categorical"
    }

    for name in shared:
        if name not in categorical:
            continue
        col_b = _resolve(df_b, name)
        if col_b is None:
            continue

        share_a = df_a[name].value_counts(normalize=True, dropna=True) * 100
        share_b = df_b[col_b].value_counts(normalize=True, dropna=True) * 100
        if share_a.empty or share_b.empty:
            continue

        appeared = [str(v) for v in share_b.index if v not in set(share_a.index)]
        vanished = [str(v) for v in share_a.index if v not in set(share_b.index)]

        if appeared:
            changes.append(
                _change(
                    "category_added",
                    name,
                    f"{len(appeared)} new value(s) in {_friendly(name)}",
                    f"`{name}` now contains "
                    f"{', '.join(repr(v) for v in appeared[:MAX_CATEGORY_REPORT])}"
                    + (f" and {len(appeared) - MAX_CATEGORY_REPORT} more" if len(appeared) > MAX_CATEGORY_REPORT else "")
                    + ", which did not appear in the first file.",
                    direction="added",
                    score=55.0,
                )
            )
        if vanished:
            changes.append(
                _change(
                    "category_removed",
                    name,
                    f"{len(vanished)} value(s) gone from {_friendly(name)}",
                    f"`{name}` no longer contains "
                    f"{', '.join(repr(v) for v in vanished[:MAX_CATEGORY_REPORT])}"
                    + (f" and {len(vanished) - MAX_CATEGORY_REPORT} more" if len(vanished) > MAX_CATEGORY_REPORT else "")
                    + ", which the first file had.",
                    direction="removed",
                    score=58.0,
                )
            )

        # The biggest share move among values present in both.
        common = [v for v in share_b.index if v in set(share_a.index)]
        best: Optional[Tuple[str, float, float, float]] = None
        for value in common:
            before, after = float(share_a[value]), float(share_b[value])
            delta = after - before
            if abs(delta) < MIN_CATEGORY_SHIFT_PCT:
                continue
            if best is None or abs(delta) > abs(best[3]):
                best = (str(value), before, after, delta)

        if best:
            value, before, after, delta = best
            changes.append(
                _change(
                    "category_shift",
                    name,
                    f"{value} is {'a bigger' if delta > 0 else 'a smaller'} "
                    f"share of {_friendly(name)}",
                    f"'{value}' was {before:.1f}% of `{name}` and is now "
                    f"{after:.1f}% -- a shift of {delta:+.1f} percentage points.",
                    direction="up" if delta > 0 else "down",
                    score=45.0 + min(abs(delta), 50.0) / 2.0,
                    before=round(before, 2),
                    after=round(after, 2),
                    pct=delta,
                )
            )

    return changes


def _quality_change(
    health_a: Optional[Dict[str, Any]], health_b: Optional[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Whether the data got cleaner or dirtier between the two files."""
    if not health_a or not health_b:
        return []
    score_a = float(health_a.get("score") or 0)
    score_b = float(health_b.get("score") or 0)
    delta = score_b - score_a
    if abs(delta) < 3:
        return []

    return [
        _change(
            "quality",
            None,
            f"Data quality {'improved' if delta > 0 else 'got worse'}: "
            f"{_fmt(score_a)} to {_fmt(score_b)}",
            f"The health score moved {delta:+.1f} points. "
            + (
                "The second file has fewer problems than the first."
                if delta > 0
                else "The second file has more problems than the first, so "
                     "differences below may partly reflect data errors rather "
                     "than real change."
            ),
            direction="up" if delta > 0 else "down",
            # A quality drop is scored high because it changes how every other
            # finding in this report should be read.
            score=85.0 if delta < 0 else 60.0,
            before=score_a,
            after=score_b,
            pct=delta,
        )
    ]


def compare(
    df_a: pd.DataFrame,
    profile_a: Dict[str, Any],
    df_b: pd.DataFrame,
    profile_b: Dict[str, Any],
    *,
    name_a: str = "First dataset",
    name_b: str = "Second dataset",
    health_a: Optional[Dict[str, Any]] = None,
    health_b: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compare two datasets and rank what changed.

    Args:
        df_a / df_b: the two frames. Neither is modified.
        profile_a / profile_b: their core.profiler outputs.
        name_a / name_b: display names, used only in prose.
        health_a / health_b: optional core.health.assess outputs, so the report
            can say whether the data itself got better or worse.

    Returns:
        {"comparable": bool, "changes": [...], "columns": {...},
         "shape": {...}, "summary": str, "n_changes": int, "conflicts": {...}}

        `comparable` is False when the two files share no columns. Everything
        else is still returned so the UI can explain the refusal concretely.

    Never raises for a data condition.
    """
    shared, only_a, only_b, conflicts = _align_columns(profile_a, profile_b)

    columns_block = {
        "shared": shared,
        "only_in_first": only_a,
        "only_in_second": only_b,
        "type_conflicts": conflicts,
    }
    shape_block = {
        "name_a": name_a,
        "name_b": name_b,
        "rows_a": len(df_a),
        "rows_b": len(df_b),
        "cols_a": len(df_a.columns),
        "cols_b": len(df_b.columns),
    }

    if not shared:
        return {
            "comparable": False,
            "changes": [],
            "columns": columns_block,
            "shape": shape_block,
            "n_changes": 0,
            "conflicts": conflicts,
            "summary": (
                f"These two files have no columns in common, so there is nothing "
                f"to compare. `{name_a}` has {len(df_a.columns)} column(s) and "
                f"`{name_b}` has {len(df_b.columns)}, and none of the names match. "
                f"They are probably two different datasets rather than two "
                f"versions of one."
            ),
        }

    changes: List[Dict[str, Any]] = []
    for pass_name, runner in (
        ("shape", lambda: _shape_changes(df_a, df_b, only_a, only_b)),
        ("quality", lambda: _quality_change(health_a, health_b)),
        ("measures", lambda: _numeric_changes(df_a, df_b, shared, profile_a)),
        ("categories", lambda: _category_changes(df_a, df_b, shared, profile_a)),
    ):
        try:
            changes.extend(runner())
        except (ValueError, TypeError, KeyError, ArithmeticError):
            logger.exception("Comparison pass %r failed", pass_name)

    changes.sort(key=lambda c: c["score"], reverse=True)
    changes = changes[:MAX_CHANGES]

    if not changes:
        summary = (
            f"`{name_a}` and `{name_b}` are broadly the same. They share "
            f"{len(shared)} column(s), and nothing moved by more than "
            f"{MIN_REPORTABLE_PCT}%."
        )
    else:
        summary = (
            f"{len(changes)} difference(s) between `{name_a}` and `{name_b}`, "
            f"across {len(shared)} shared column(s). "
            f"The largest is: {changes[0]['headline']}."
        )

    return {
        "comparable": True,
        "changes": changes,
        "columns": columns_block,
        "shape": shape_block,
        "n_changes": len(changes),
        "conflicts": conflicts,
        "summary": summary,
    }


def narrate(result: Dict[str, Any], *, api_key: Optional[str] = None) -> Dict[str, Any]:
    """Add a written summary of a comparison, if a model is available.

    Returns the result with `summary` replaced and `source` set. The computed
    summary stays in place on any failure, and a model-written one that quotes
    a number nobody computed is rejected outright -- same rule as everywhere
    else in this project.
    """
    changes = result.get("changes") or []
    if not llm.available(api_key) or not changes:
        return {**result, "source": "rules"}

    shape = result.get("shape", {})
    payload = {
        "first_file": shape.get("name_a"),
        "second_file": shape.get("name_b"),
        "shape": {
            "rows_first": shape.get("rows_a"),
            "rows_second": shape.get("rows_b"),
            "shared_columns": len(result.get("columns", {}).get("shared", [])),
        },
        "changes": [
            {
                "what": change["headline"],
                "detail": change["detail"],
                "direction": change["direction"],
            }
            for change in changes
        ],
    }

    allowed: Set[str] = set()
    for change in changes:
        allowed |= grounding.number_tokens(change["headline"])
        allowed |= grounding.number_tokens(change["detail"])
    allowed |= grounding.normalise(
        [
            shape.get("rows_a"),
            shape.get("rows_b"),
            len(result.get("columns", {}).get("shared", [])),
        ]
    )
    # The file names too. A dataset called "2024 sales" puts the number 2024 in
    # front of the model, and referring to the file by the name we ourselves
    # supplied is not an invented figure -- it is the most natural way to write
    # the sentence. Without this the check rejects every comparison of two files
    # whose names contain a year, which is most of them.
    allowed |= grounding.number_tokens(f"{shape.get('name_a')} {shape.get('name_b')}")

    try:
        raw = llm.complete(
            json.dumps(payload, default=str),
            NARRATE_PROMPT,
            max_tokens=NARRATE_TOKENS,
            temperature=TEMPERATURE,
            json_mode=True,
            api_key_override=api_key,
        )
    except LLMError as exc:
        logger.info("Comparison narrative unavailable: %s", exc)
        return {**result, "source": "rules"}

    parsed = grounding.parse_json(raw)
    summary = grounding.keep_if_grounded(
        str(parsed.get("summary") or ""), allowed, "comparison summary"
    )

    if not summary:
        return {**result, "source": "rules"}
    return {**result, "summary": summary, "source": "llm"}
