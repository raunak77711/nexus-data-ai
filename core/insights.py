"""Automatic findings, written for someone who has never heard of a p-value.

WHAT THIS IS
------------
Given a DataFrame and its profile, this module looks for the handful of things
a person actually wants to know about a spreadsheet they just opened:

  * is anything going up or down over time, and by how much
  * which columns move together
  * which rows are strange
  * which category is winning
  * what is broken about the data itself
  * whether a forecast is even worth attempting

Each finding comes back as a card with a headline, a plain-language detail, a
"why it matters" line, the numbers it was derived from, and -- where the finding
can be seen -- a chart spec the UI can hand straight to core.charts.

TWO RULES IT KEEPS
------------------
1. NO LLM. Every number here is computed by pandas on the user's own rows. A
   language model is a good writer and a bad calculator, and an insight is the
   worst possible place to be approximately right. The phrasing is templated,
   which is a small stylistic price for a large correctness guarantee.

2. NO JARGON ON THE SURFACE. "Pearson r = 0.82" is true and useless to most
   people; "when advertising goes up, revenue usually goes up too -- they move
   together about 82% of the time you would expect if they were locked" is the
   same fact in a form that can be acted on. The raw statistic is still carried
   in `evidence`, so a technical user can check the claim and the UI can show it
   behind a "see the numbers" disclosure. Nothing is hidden; it is just not the
   first thing you read.

COST
----
Everything is bounded before it runs: at most MAX_NUMERIC_COLUMNS numeric
columns are considered, correlations are computed on one matrix rather than
pairwise loops, and anomaly scanning samples very large frames. A dataset that
would take a noticeable amount of time to analyse gets a slightly less thorough
analysis rather than a slow one.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import pandas as pd

from core import charts
from core.router import ID_PATTERN

logger = logging.getLogger(__name__)

# Columns beyond this are ignored for correlation and anomaly work. Twelve
# columns is 66 pairs, which is already more relationships than anyone reads;
# the cap keeps a 400-column upload from turning into 80,000 comparisons.
MAX_NUMERIC_COLUMNS = 12

# Above this row count the anomaly and correlation passes work on a sample. The
# sample is disclosed on the card that uses it.
MAX_SCAN_ROWS = 50_000

# Correlation strength bands. 0.5 is the floor for "worth mentioning" -- below
# it, a relationship is real often enough to be mentioned and weak enough to
# mislead, which is the worst combination for a non-technical reader.
STRONG_CORRELATION = 0.75
MODERATE_CORRELATION = 0.5

# An outlier here is far outside the middle of the data, not merely at the edge:
# the usual 1.5x fence flags roughly 1 row in 150 of a normal distribution, so
# on a 12,000-row upload it would report 80 "unusual" rows and mean nothing.
# 3.0x reports the genuinely odd ones.
IQR_FENCE = 3.0

# Below this, a percentage change over time is noise dressed as a trend.
MIN_TREND_PCT = 5.0
MIN_TREND_PERIODS = 6

# A column missing more than this share of its values cannot be relied on.
HIGH_NULL_PCT = 20.0

# Enough daily observations that a forecast can be trained AND scored. Mirrors
# the floor core.ml enforces, so this card never promises what /forecast refuses.
MIN_FORECAST_PERIODS = 30

# Names that look like identifiers. A trend in "order_id" is arithmetic, not a
# finding, and its correlation with everything else is an artefact of sort order.
# core.router already maintains this list for the same reason -- picking a chart
# target -- so it is imported rather than copied. EXTRA_ID_SUFFIXES adds the one
# case that matters here and not there: a "_code" column is a fine thing to
# group by, which is why the router keeps it, and a meaningless thing to report
# a trend in.
EXTRA_ID_SUFFIXES = ("_code",)

MAX_CARDS = 12


# ------------------------------------------------------------------ helpers --
def _fmt(value: Any) -> str:
    """Format a number the way a person writes one.

    Big numbers get thousands separators and no decimals -- nobody needs to see
    that revenue was 482,193.7742. Small numbers keep enough decimals to stay
    distinguishable from zero.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number != number:  # NaN
        return "-"
    magnitude = abs(number)
    if magnitude >= 1000:
        return f"{number:,.0f}"
    if magnitude >= 10:
        return f"{number:,.1f}"
    if magnitude >= 1:
        return f"{number:,.2f}"
    return f"{number:,.3f}".rstrip("0").rstrip(".") or "0"


def _pct(value: float) -> str:
    return f"{abs(value):.0f}%" if abs(value) >= 10 else f"{abs(value):.1f}%"


def _friendly(name: str) -> str:
    """Turn a column name into something readable in a sentence.

    'total_revenue_usd' reads badly mid-sentence and 'Total Revenue Usd' reads
    like a spreadsheet header. Underscores become spaces and the rest is left
    alone -- the user named these columns and will recognise their own words.
    """
    return str(name).replace("_", " ").strip()


def _is_id_like(name: str) -> bool:
    text = str(name)
    return bool(ID_PATTERN.search(text)) or text.lower().endswith(EXTRA_ID_SUFFIXES)


def _numeric_columns(df: pd.DataFrame, profile: Dict[str, Any]) -> List[str]:
    """Numeric columns worth analysing, most-varied first.

    Sorted by how much they vary (coefficient of variation) so that when the cap
    bites, what survives is the columns with something to say. A column of
    identical values is technically numeric and has no finding in it.
    """
    semantic = {c["name"]: c["semantic_type"] for c in profile.get("columns", [])}
    candidates = []
    for name in df.columns:
        if semantic.get(name) not in ("numeric", "categorical"):
            continue
        if _is_id_like(name):
            continue
        values = pd.to_numeric(df[name], errors="coerce").dropna()
        if len(values) < 3 or values.nunique() < 3:
            continue
        mean = float(values.mean())
        spread = float(values.std()) / abs(mean) if mean else float(values.std())
        candidates.append((abs(spread), str(name)))

    candidates.sort(reverse=True)
    return [name for _, name in candidates[:MAX_NUMERIC_COLUMNS]]


def _categorical_columns(df: pd.DataFrame, profile: Dict[str, Any]) -> List[str]:
    """Categorical columns with a vocabulary small enough to compare across."""
    out = []
    for column in profile.get("columns", []):
        name = column.get("name")
        if column.get("semantic_type") != "categorical" or name not in df.columns:
            continue
        if _is_id_like(name):
            continue
        if 2 <= int(column.get("n_unique") or 0) <= 20:
            out.append(str(name))
    return out


def _datetime_column(profile: Dict[str, Any], routing: Dict[str, Any]) -> Optional[str]:
    """The routed date column, or the first one the profile found."""
    if routing.get("time_col"):
        return routing["time_col"]
    for column in profile.get("columns", []):
        if column.get("semantic_type") == "datetime":
            return str(column["name"])
    return None


def _scan_frame(df: pd.DataFrame) -> pd.DataFrame:
    """The frame the expensive passes run over: the whole thing, or a sample."""
    if len(df) <= MAX_SCAN_ROWS:
        return df
    return df.sample(MAX_SCAN_ROWS, random_state=0)


def _card(
    kind: str,
    headline: str,
    detail: str,
    why: str,
    evidence: Dict[str, Any],
    score: float,
    tone: str = "neutral",
    action: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One finding, in the shape the UI renders.

    `score` never reaches the client. It exists so that findings from six
    independent passes can be ranked against each other before the list is
    truncated -- otherwise the ordering would be "whichever pass ran first",
    and the most interesting thing about the dataset could fall off the end.
    """
    return {
        "id": f"{kind}-{abs(hash((kind, headline))) % 10**8}",
        "kind": kind,
        "tone": tone,
        "headline": headline,
        "detail": detail,
        "why": why,
        "evidence": evidence,
        "action": action,
        "_score": score,
    }


# -------------------------------------------------------------------- trend --
def _trend_cards(
    df: pd.DataFrame, time_col: str, numeric_cols: List[str]
) -> List[Dict[str, Any]]:
    """How each measure changed from the start of the data to the end.

    The comparison is between the first and last thirds of the series rather
    than the first and last points, because a single unusual day at either end
    would otherwise decide the answer. Thirds are also what a person eyeballing
    a chart actually compares.
    """
    cards: List[Dict[str, Any]] = []
    stamps = pd.to_datetime(df[time_col], errors="coerce", format="mixed")
    if stamps.notna().sum() < MIN_TREND_PERIODS:
        return cards

    span_days = int((stamps.max() - stamps.min()).days)
    freq = "D" if span_days <= 90 else ("W" if span_days <= 800 else "ME")
    freq_word = {"D": "day", "W": "week", "ME": "month"}[freq]

    for name in numeric_cols:
        values = pd.to_numeric(df[name], errors="coerce")
        frame = pd.DataFrame({"t": stamps, "v": values}).dropna()
        if len(frame) < MIN_TREND_PERIODS:
            continue

        series = frame.set_index("t")["v"].resample(freq).mean().dropna()
        if len(series) < MIN_TREND_PERIODS:
            continue

        third = max(1, len(series) // 3)
        start = float(series.iloc[:third].mean())
        end = float(series.iloc[-third:].mean())
        if start == 0:
            continue
        change = 100.0 * (end - start) / abs(start)
        if abs(change) < MIN_TREND_PCT:
            continue

        rising = change > 0
        # "rose"/"fell" rather than "is up"/"is down": a column called "units"
        # makes "Units is up" ungrammatical, and there is no way to know from a
        # header whether a name is singular. A past-tense verb agrees with both.
        direction = "rose" if rising else "fell"
        peak_at = series.idxmax()
        low_at = series.idxmin()

        cards.append(
            _card(
                kind="trend",
                # Neutral, deliberately. Whether a rise is good news depends on
                # what rose, and this module has no way to know: colouring a
                # climbing PM2.5 reading green would be the app cheering at
                # pollution.
                tone="neutral",
                headline=(
                    f"{_friendly(name).capitalize()} {direction} {_pct(change)} "
                    f"across this period"
                ),
                detail=(
                    f"Early on, {_friendly(name)} averaged {_fmt(start)} per "
                    f"{freq_word}. By the end of the data it averaged {_fmt(end)} — "
                    f"a change of {_pct(change)}."
                ),
                why=(
                    f"The highest {freq_word} was {peak_at.date()} at "
                    f"{_fmt(series.max())}; the lowest was {low_at.date()} at "
                    f"{_fmt(series.min())}. "
                    + (
                        "The rise is spread across the period rather than caused by "
                        "one spike."
                        if abs(float(series.max()) - end) > abs(end - start)
                        else "Worth checking whether one unusual period is driving this."
                    )
                ),
                evidence={
                    "column": name,
                    "time_column": time_col,
                    "start_average": round(start, 4),
                    "end_average": round(end, 4),
                    "change_pct": round(change, 2),
                    "periods": int(len(series)),
                    "grouped_by": freq_word,
                    "peak": {"when": str(peak_at.date()), "value": round(float(series.max()), 4)},
                    "low": {"when": str(low_at.date()), "value": round(float(series.min()), 4)},
                },
                score=min(abs(change), 200.0),
                action={"chart": "line", "x": time_col, "y": name},
            )
        )

    return cards


# ------------------------------------------------------------- relationships --
def _relationship_cards(
    df: pd.DataFrame, numeric_cols: List[str]
) -> tuple[List[Dict[str, Any]], int]:
    """Pairs of columns that move together, and how many such pairs there are.

    Returns (cards, total_pairs_found) -- the count is reported on the overview
    even when only the top few pairs get a card, because "7 relationships" is a
    truthful summary of the dataset and three cards is a readable page.
    """
    if len(numeric_cols) < 2:
        return [], 0

    frame = _scan_frame(df)[numeric_cols].apply(pd.to_numeric, errors="coerce")
    # min_periods guards against a "correlation" computed from four overlapping
    # rows in two mostly-empty columns, which is noise with a decimal point.
    matrix = frame.corr(min_periods=20)

    found: List[tuple] = []
    for i, a in enumerate(numeric_cols):
        for b in numeric_cols[i + 1 :]:
            r = matrix.loc[a, b] if a in matrix.index and b in matrix.columns else None
            if r is None or pd.isna(r):
                continue
            if abs(float(r)) >= MODERATE_CORRELATION:
                found.append((abs(float(r)), float(r), a, b))

    found.sort(reverse=True)
    cards: List[Dict[str, Any]] = []

    for strength, r, a, b in found[:3]:
        together = r > 0
        band = "very close" if strength >= STRONG_CORRELATION else "clear"
        cards.append(
            _card(
                kind="relationship",
                tone="neutral",
                headline=(
                    f"{_friendly(a).capitalize()} and {_friendly(b)} move "
                    + ("together" if together else "in opposite directions")
                ),
                detail=(
                    f"There is a {band} link between them: when {_friendly(a)} goes up, "
                    f"{_friendly(b)} usually goes "
                    + ("up as well." if together else "down.")
                ),
                why=(
                    "Columns that move together often share a cause. This is a "
                    "pattern in the numbers, not proof that one causes the other — "
                    "but it is the first place to look."
                ),
                evidence={
                    "column_a": a,
                    "column_b": b,
                    "correlation": round(r, 3),
                    "strength": "very strong" if strength >= STRONG_CORRELATION else "strong",
                    "direction": "same direction" if together else "opposite directions",
                    "rows_compared": int(frame[[a, b]].dropna().shape[0]),
                },
                score=60.0 * strength,
                action={"chart": "scatter", "x": a, "y": b},
            )
        )

    return cards, len(found)


# ----------------------------------------------------------------- anomalies --
def _anomaly_cards(
    df: pd.DataFrame, numeric_cols: List[str]
) -> tuple[List[Dict[str, Any]], int]:
    """Rows that sit far outside the normal range of at least one measure."""
    if not numeric_cols:
        return [], 0

    scan = _scan_frame(df)
    flagged = pd.Series(False, index=scan.index)
    worst: Optional[Dict[str, Any]] = None

    for name in numeric_cols:
        values = pd.to_numeric(scan[name], errors="coerce")
        clean = values.dropna()
        if len(clean) < 20:
            continue
        q1, q3 = float(clean.quantile(0.25)), float(clean.quantile(0.75))
        iqr = q3 - q1
        if iqr <= 0:
            continue
        low, high = q1 - IQR_FENCE * iqr, q3 + IQR_FENCE * iqr
        outside = (values < low) | (values > high)
        n_outside = int(outside.sum())
        if not n_outside:
            continue
        flagged = flagged | outside.fillna(False)

        usual_low = float(clean.quantile(0.10))
        usual_high = float(clean.quantile(0.90))
        extreme_at = (values - clean.median()).abs().idxmax()
        distance = abs(float(values.loc[extreme_at]) - float(clean.median()))
        if worst is None or distance > worst["distance"]:
            worst = {
                "column": name,
                "distance": distance,
                "value": float(values.loc[extreme_at]),
                "row": int(scan.index.get_loc(extreme_at)) + 1,
                "typical": float(clean.median()),
                # Where most values sit, which is what the card says out loud.
                # The IQR fence above decided the flag but describes an interval
                # that can fall outside the data entirely, and quoting it to a
                # reader as the "normal range" is arithmetic leaking into English.
                "normal_low": usual_low,
                "normal_high": usual_high,
                "count": n_outside,
            }

    total = int(flagged.sum())
    if not total or worst is None:
        return [], 0

    share = 100.0 * total / max(1, len(scan))
    cards = [
        _card(
            kind="anomaly",
            tone="warning",
            headline=(
                f"{total:,} record{'s' if total != 1 else ''} look unusual"
                if total > 1
                else "One record looks unusual"
            ),
            detail=(
                f"These rows sit far outside the normal range for at least one "
                f"measure — {_pct(share)} of the data. The most extreme is row "
                f"{worst['row']:,}, where {_friendly(worst['column'])} is "
                f"{_fmt(worst['value'])} against a typical {_fmt(worst['typical'])}."
            ),
            why=(
                f"Most {_friendly(worst['column'])} values fall between "
                f"{_fmt(worst['normal_low'])} and {_fmt(worst['normal_high'])}. "
                f"Values outside that are either genuinely interesting or a data "
                f"entry mistake, and it is usually worth knowing which."
            ),
            evidence={
                "unusual_rows": total,
                "share_pct": round(share, 2),
                "rows_scanned": int(len(scan)),
                "most_extreme": {
                    "row": worst["row"],
                    "column": worst["column"],
                    "value": round(worst["value"], 4),
                    "typical_value": round(worst["typical"], 4),
                    "most_values_between": [
                        round(worst["normal_low"], 4),
                        round(worst["normal_high"], 4),
                    ],
                },
                "method": (
                    "A value counts as unusual when it is more than three "
                    "interquartile ranges outside the middle half of the data."
                ),
            },
            score=40.0 + min(share, 20.0),
            action={"chart": "histogram", "x": worst["column"]},
        )
    ]
    return cards, total


# ------------------------------------------------------------------ segments --
def _segment_cards(
    df: pd.DataFrame,
    cat_cols: List[str],
    numeric_cols: List[str],
    target_col: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Which category leads on the headline measure, and by how much.

    The measure is the routed target when there is one. That column was chosen
    -- by the LLM or by the rules -- as the thing this dataset is *about*, so a
    comparison across it is the comparison the user came for. Falling back to
    the most-varied numeric column is a last resort: it produces a true
    statement about a column nobody asked about.
    """
    if not cat_cols or not numeric_cols:
        return []

    target = target_col if target_col in numeric_cols else numeric_cols[0]
    values = pd.to_numeric(df[target], errors="coerce")
    overall = float(values.mean())
    if not overall:
        return []

    cards: List[Dict[str, Any]] = []
    for name in cat_cols[:2]:
        grouped = values.groupby(df[name]).agg(["mean", "count"])
        grouped = grouped[grouped["count"] >= 3]
        if len(grouped) < 2:
            continue

        best = grouped["mean"].idxmax()
        worst = grouped["mean"].idxmin()
        best_value = float(grouped.loc[best, "mean"])
        worst_value = float(grouped.loc[worst, "mean"])
        gap = 100.0 * (best_value - overall) / abs(overall)
        if abs(gap) < 3.0:
            continue

        cards.append(
            _card(
                kind="segment",
                tone="neutral",
                headline=(
                    f"{str(best)} leads on {_friendly(target)} — {_pct(gap)} above average"
                ),
                detail=(
                    f"Grouped by {_friendly(name)}, {str(best)} averages "
                    f"{_fmt(best_value)} against {_fmt(overall)} across everything. "
                    f"{str(worst)} is at the other end with {_fmt(worst_value)}."
                ),
                why=(
                    f"A gap of {_fmt(best_value - worst_value)} between the best and "
                    f"worst {_friendly(name)} usually means something is different "
                    f"about how they operate — and that difference is worth copying "
                    f"or fixing."
                ),
                evidence={
                    "grouped_by": name,
                    "measure": target,
                    "best": {"name": str(best), "average": round(best_value, 4),
                             "rows": int(grouped.loc[best, "count"])},
                    "worst": {"name": str(worst), "average": round(worst_value, 4),
                              "rows": int(grouped.loc[worst, "count"])},
                    "overall_average": round(overall, 4),
                    "n_groups": int(len(grouped)),
                },
                score=30.0 + min(abs(gap), 30.0),
                action={"chart": "bar", "x": name, "y": target, "agg": "mean"},
            )
        )

    return cards


# ------------------------------------------------------------------- quality --
def _quality_cards(df: pd.DataFrame, profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Problems with the data itself, said out loud rather than worked around.

    These score low so they sit below the findings, but they are never dropped
    silently: a chart drawn from a column that is 40% empty is a chart the user
    should know is drawn from a column that is 40% empty.
    """
    cards: List[Dict[str, Any]] = []

    gappy = [
        c for c in profile.get("columns", [])
        if float(c.get("null_pct") or 0) >= HIGH_NULL_PCT
    ]
    if gappy:
        worst = max(gappy, key=lambda c: float(c["null_pct"]))
        names = ", ".join(_friendly(c["name"]) for c in gappy[:4])
        cards.append(
            _card(
                kind="quality",
                tone="warning",
                headline=(
                    f"{len(gappy)} column{'s have' if len(gappy) != 1 else ' has'} "
                    f"a lot of blanks"
                ),
                detail=(
                    f"{_friendly(worst['name']).capitalize()} is empty in "
                    f"{worst['null_pct']:.0f}% of rows"
                    + (f". Also affected: {names}." if len(gappy) > 1 else ".")
                ),
                why=(
                    "Anything calculated from these columns is calculated from the "
                    "rows that do have a value, so treat those figures as describing "
                    "part of the data rather than all of it."
                ),
                evidence={
                    "columns": [
                        {"name": c["name"], "empty_pct": c["null_pct"]} for c in gappy[:8]
                    ]
                },
                score=12.0,
                action=None,
            )
        )

    duplicated = int(df.duplicated().sum())
    if duplicated:
        cards.append(
            _card(
                kind="quality",
                tone="warning",
                headline=f"{duplicated:,} row{'s are' if duplicated != 1 else ' is'} an exact duplicate",
                detail=(
                    f"{duplicated:,} of {len(df):,} rows repeat another row in every "
                    f"column. They are counted once each in everything shown here."
                ),
                why=(
                    "Duplicates usually come from a file being exported or merged "
                    "twice. They quietly inflate totals and counts."
                ),
                evidence={"duplicate_rows": duplicated, "total_rows": int(len(df))},
                score=10.0,
                action=None,
            )
        )

    return cards


# ------------------------------------------------------------------ forecast --
def _forecast_card(
    df: pd.DataFrame, time_col: Optional[str], target_col: Optional[str]
) -> tuple[List[Dict[str, Any]], int]:
    """Whether this dataset can support a forecast, stated either way.

    The negative case is a card too. "Prediction isn't recommended for this
    dataset" is a useful thing to be told up front, and much better than a
    Predict tab that looks broken.
    """
    if not time_col or not target_col or time_col not in df.columns:
        return [], 0
    if target_col not in df.columns:
        return [], 0

    stamps = pd.to_datetime(df[time_col], errors="coerce", format="mixed")
    values = pd.to_numeric(df[target_col], errors="coerce")
    frame = pd.DataFrame({"t": stamps, "v": values}).dropna()
    if frame.empty:
        return [], 0

    daily = frame.set_index("t")["v"].resample("D").mean()
    observed = int(daily.notna().sum())

    if observed < MIN_FORECAST_PERIODS:
        return [
            _card(
                kind="forecast",
                tone="neutral",
                headline="Not enough history to predict what comes next",
                detail=(
                    f"There are {observed} day(s) with a {_friendly(target_col)} "
                    f"reading. A forecast that can be checked against a fair "
                    f"comparison needs at least {MIN_FORECAST_PERIODS}."
                ),
                why=(
                    "Predicting from a short series produces a number that looks "
                    "confident and cannot be tested. Better to say so."
                ),
                evidence={"days_observed": observed, "days_needed": MIN_FORECAST_PERIODS},
                score=8.0,
                action=None,
            )
        ], 0

    span = f"{daily.index.min().date()} to {daily.index.max().date()}"
    return [
        _card(
            kind="forecast",
            tone="neutral",
            headline=f"{_friendly(target_col).capitalize()} can be predicted forward",
            detail=(
                f"There are {observed:,} days of {_friendly(target_col)} covering "
                f"{span} — enough history to project the next few weeks and to check "
                f"that projection against a simple benchmark."
            ),
            why=(
                "NEXUS only forecasts when it can also test itself. Open Predict to "
                "see the projection and whether it actually beat the benchmark."
            ),
            evidence={
                "time_column": time_col,
                "measure": target_col,
                "days_observed": observed,
                "covers": span,
            },
            score=45.0,
            action={"chart": "line", "x": time_col, "y": target_col},
        )
    ], 1


# --------------------------------------------------------------------- main --
def generate(
    df: pd.DataFrame,
    profile: Dict[str, Any],
    routing: Dict[str, Any],
) -> Dict[str, Any]:
    """Analyse a dataset and return everything worth telling the user about it.

    Args:
        df: the session's DataFrame, unmodified.
        profile: core.profiler.profile_dataframe output.
        routing: core.router.route output -- used only to prefer the columns the
            router already identified as the interesting ones.

    Returns:
        {"insights": [card, ...], "counts": {...}, "summary": str,
         "shape": {...}}

        `counts` is what the overview screen reads ("NEXUS found 4 trends,
        7 relationships..."). It counts everything found, not everything shown,
        so it stays honest when the card list is truncated for readability.

    This function does not raise for data conditions. A dataset with nothing to
    say produces an empty list and a summary that says so -- which is a finding
    in itself, and a far better outcome than an exception in a panel.
    """
    numeric_cols = _numeric_columns(df, profile)
    cat_cols = _categorical_columns(df, profile)
    time_col = _datetime_column(profile, routing)
    target_col = routing.get("target_col") or (numeric_cols[0] if numeric_cols else None)

    cards: List[Dict[str, Any]] = []
    # Every kind of finding is counted, not just the four headline ones. The
    # overview reads these to say what was found; a pass whose results were not
    # counted would produce a screen saying "nothing stood out" directly above a
    # card describing something that did.
    counts = {
        "trends": 0,
        "relationships": 0,
        "anomalies": 0,
        "predictions": 0,
        "standouts": 0,
        "data_issues": 0,
    }

    if time_col:
        try:
            trend_cards = _trend_cards(df, time_col, numeric_cols[:6])
            counts["trends"] = len(trend_cards)
            cards.extend(trend_cards)
        except (ValueError, TypeError, KeyError, ArithmeticError):
            logger.exception("Trend pass failed")

    try:
        relationship_cards, n_pairs = _relationship_cards(df, numeric_cols)
        counts["relationships"] = n_pairs
        cards.extend(relationship_cards)
    except (ValueError, TypeError, KeyError, ArithmeticError):
        logger.exception("Relationship pass failed")

    try:
        anomaly_cards, n_anomalies = _anomaly_cards(df, numeric_cols)
        counts["anomalies"] = n_anomalies
        cards.extend(anomaly_cards)
    except (ValueError, TypeError, KeyError, ArithmeticError):
        logger.exception("Anomaly pass failed")

    try:
        segment_cards = _segment_cards(df, cat_cols, numeric_cols, target_col)
        counts["standouts"] = len(segment_cards)
        cards.extend(segment_cards)
    except (ValueError, TypeError, KeyError, ArithmeticError):
        logger.exception("Segment pass failed")

    try:
        forecast_cards, n_forecast = _forecast_card(df, time_col, target_col)
        counts["predictions"] = n_forecast
        cards.extend(forecast_cards)
    except (ValueError, TypeError, KeyError, ArithmeticError):
        logger.exception("Forecast readiness pass failed")

    try:
        quality_cards = _quality_cards(df, profile)
        counts["data_issues"] = len(quality_cards)
        cards.extend(quality_cards)
    except (ValueError, TypeError, KeyError, ArithmeticError):
        logger.exception("Quality pass failed")

    # Drop any action that would not actually render, then rank and truncate.
    for card in cards:
        if card.get("action") and not charts.spec_is_supported(card["action"], df):
            card["action"] = None

    cards.sort(key=lambda c: c["_score"], reverse=True)
    cards = cards[:MAX_CARDS]
    for card in cards:
        card.pop("_score", None)

    return {
        "insights": cards,
        "counts": counts,
        "summary": _summarise(counts, len(cards)),
        "shape": _shape(profile),
    }


def _summarise(counts: Dict[str, int], n_cards: int) -> str:
    """One sentence for the top of the insights screen."""
    if not n_cards:
        return (
            "Nothing stood out in this dataset — no strong trends, relationships or "
            "unusual records. That is a finding, not a failure."
        )
    parts = []
    if counts["trends"]:
        parts.append(f"{counts['trends']} trend{'s' if counts['trends'] != 1 else ''}")
    if counts["relationships"]:
        parts.append(
            f"{counts['relationships']} relationship"
            f"{'s' if counts['relationships'] != 1 else ''}"
        )
    if counts["anomalies"]:
        parts.append(f"{counts['anomalies']:,} unusual records")
    if counts["predictions"]:
        parts.append("1 thing worth predicting")
    if counts.get("standouts"):
        parts.append(
            f"{counts['standouts']} standout group"
            f"{'s' if counts['standouts'] != 1 else ''}"
        )
    if counts.get("data_issues"):
        parts.append(
            f"{counts['data_issues']} thing"
            f"{'s' if counts['data_issues'] != 1 else ''} to know about the data"
        )
    if not parts:
        return (
            f"NEXUS found {n_cards} thing{'s' if n_cards != 1 else ''} worth "
            f"knowing about this data."
        )
    if len(parts) == 1:
        return f"NEXUS found {parts[0]}."
    return f"NEXUS found {', '.join(parts[:-1])} and {parts[-1]}."


def _shape(profile: Dict[str, Any]) -> Dict[str, Any]:
    """The plain counts the overview leads with: rows, columns, kinds of column."""
    types: Dict[str, int] = {}
    for column in profile.get("columns", []):
        kind = str(column.get("semantic_type"))
        types[kind] = types.get(kind, 0) + 1

    return {
        "n_rows": int(profile.get("n_rows") or 0),
        "n_cols": int(profile.get("n_cols") or 0),
        "n_datetime": types.get("datetime", 0),
        "n_numeric": types.get("numeric", 0),
        "n_categorical": types.get("categorical", 0),
        "n_geo": types.get("geo_lat", 0) + types.get("geo_lon", 0),
        "n_text": types.get("text", 0),
    }
