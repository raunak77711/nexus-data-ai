"""Builds a dashboard shaped like the dataset, instead of pouring the dataset
into a dashboard.

THE DECISION THIS MODULE MAKES
------------------------------
Given a frame, which handful of charts are worth drawing? Not "all of them" --
a page with fourteen figures on it is a place where nothing gets looked at --
and not a fixed template either, because a template is a set of questions
chosen before anyone saw the data. Six panels, chosen from the columns that
exist, ranked by how much they are likely to tell someone.

The candidate rules are deliberately boring and deterministic:

    a date + a measure          -> how it changed over time
    a category + a measure      -> which groups are biggest
    two correlated measures     -> the relationship, with a fit line
    three or more measures      -> the correlation grid
    a measure                   -> how it is spread
    a category + a measure      -> how the spread differs by group
    coordinates + a measure     -> the map

Each candidate carries a SCORE, and the score is what makes this adaptive
rather than merely conditional: a time series in a file with a strong trend
outranks a histogram in the same file, and the same histogram outranks a
scatter plot of two variables that have nothing to do with each other. So a
sales export gets a line chart first and a survey export gets a distribution
first, from one rule set.

WHY NOT ASK THE MODEL WHICH CHARTS TO DRAW. Because the answer would be
non-deterministic, slow, and no better: choosing between seven chart types
given a column profile is a decision with a right answer that a rule can
compute exactly. The model's judgement is spent where it is actually worth
something -- on the words around the charts, in core.story. What this module
sends upward is the reasoning too, so the interface can say WHY a chart is on
the page, which is the part users actually find surprising.

Every panel is built through core.charts, so every one of them arrives with the
runnable pandas that produced it. The glass box is not suspended just because
the app chose the chart rather than the user.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core import charts

logger = logging.getLogger(__name__)

# Six is the number of things a person will actually look at on one screen.
# Past that the page becomes a gallery, and a gallery is browsed rather than
# read.
MAX_PANELS = 6

# Correlation strong enough that a scatter plot shows something rather than a
# cloud. Lower than the "strong relationship" bar in core.insights on purpose:
# a chart can be worth drawing at a correlation that is not worth announcing.
SCATTER_MIN_CORRELATION = 0.35
HEATMAP_MIN_COLUMNS = 3

# Sampling cap for the scoring pass. Scoring reads correlations and variances
# over every candidate column pair; on a large frame that is the slowest thing
# in the request, and the ranking it produces from 20k rows is the same ranking.
MAX_SCORE_ROWS = 20_000

# A category with more distinct values than this is an identifier wearing a
# category's clothes, and ranking it produces a bar chart with one bar per row.
MAX_CATEGORY_CARDINALITY = 50

ID_PATTERN = re.compile(r"(^id$|_id$|^id_|^index$|_key$|_no$|number$|^unnamed)", re.I)


def _friendly(name: str) -> str:
    """A column name as prose: order_total -> 'order total'."""
    return str(name).replace("_", " ").replace("-", " ").strip()


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
        if abs(number) >= 1_000_000:
            return f"{number / 1_000_000:,.2f}M".replace(".00M", "M")
        if abs(number) >= 1000:
            return f"{number:,.0f}"
        if abs(number) >= 1:
            return f"{number:,.2f}".rstrip("0").rstrip(".")
        return f"{number:,.4g}"
    return str(value)


# Measures whose name says they accumulate. Summing one of these answers a real
# question ("total revenue"); summing anything else produces a number with no
# meaning -- a "total salary" across a company is a payroll figure nobody asked
# for, and a "total temperature" is not a quantity at all. The name is the only
# signal available for telling the two apart, so it is used, carefully, in one
# place rather than guessed at separately by each rule that needs it.
ACCUMULATING_NAME = re.compile(
    r"(revenue|sales|amount|total|count|qty|quantity|units|spend|cost|profit|"
    r"income|volume|orders|clicks|views|visits)",
    re.I,
)


def _accumulates(column: str) -> bool:
    """Is summing this measure a meaningful thing to do?"""
    return bool(ACCUMULATING_NAME.search(str(column)))


def _default_agg(column: str) -> str:
    """The aggregation to use when grouping this measure."""
    return "sum" if _accumulates(column) else "mean"


def _columns_by_type(profile: Dict[str, Any]) -> Dict[str, List[str]]:
    """Group the profile's columns by semantic type, dropping identifiers.

    Identifiers are removed here, once, rather than in each rule below. A
    customer id is numeric and a customer id is not a measure, and every rule
    that forgot the distinction would produce a chart of a meaningless average.
    """
    grouped: Dict[str, List[str]] = {
        "numeric": [], "categorical": [], "datetime": [], "geo_lat": [],
        "geo_lon": [], "text": [],
    }
    for column in profile.get("columns", []):
        name = str(column.get("name"))
        kind = str(column.get("semantic_type"))
        if kind not in grouped:
            continue
        if kind == "numeric" and ID_PATTERN.search(name):
            continue
        if kind == "categorical" and int(column.get("n_unique") or 0) > MAX_CATEGORY_CARDINALITY:
            continue
        grouped[kind].append(name)
    return grouped


def _scoring_frame(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) > MAX_SCORE_ROWS:
        return df.sample(MAX_SCORE_ROWS, random_state=0)
    return df


def _numeric(df: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(df[column], errors="coerce")


def _variation(df: pd.DataFrame, column: str) -> float:
    """Coefficient of variation: how much a measure actually moves.

    Used to rank measures against each other. A column that barely varies makes
    a flat line and a featureless histogram, and putting it on the dashboard
    ahead of one that swings is the single most common way an auto-generated
    dashboard ends up boring.
    """
    values = _numeric(df, column).dropna()
    if len(values) < 3:
        return 0.0
    mean = float(values.mean())
    std = float(values.std())
    if not np.isfinite(std) or std <= 0:
        return 0.0
    # Absolute mean in the denominator, so a measure centred near zero does not
    # report an infinite coefficient and win every ranking.
    return float(std / abs(mean)) if abs(mean) > 1e-9 else 1.0


def _rank_measures(df: pd.DataFrame, numeric: List[str], target: Optional[str]) -> List[str]:
    """Order the measures by how interesting they are likely to be.

    The router's chosen target goes first when there is one -- it was picked by
    looking at the whole profile and is a better guess than any single statistic
    here -- and the rest sort by how much they vary.
    """
    scored = sorted(numeric, key=lambda c: _variation(df, c), reverse=True)
    if target and target in scored:
        scored.remove(target)
        scored.insert(0, target)
    return scored


def _best_pair(df: pd.DataFrame, numeric: List[str]) -> Optional[Tuple[str, str, float]]:
    """The two measures most worth plotting against each other.

    Correlation is computed on the sample once for the whole matrix rather than
    pairwise in a loop, because the loop is O(n^2) requests into pandas and the
    matrix is one.
    """
    usable = [c for c in numeric if _numeric(df, c).notna().sum() >= 10][:12]
    if len(usable) < 2:
        return None
    matrix = df[usable].apply(pd.to_numeric, errors="coerce").corr(numeric_only=True)
    best: Optional[Tuple[str, str, float]] = None
    for i, left in enumerate(usable):
        for right in usable[i + 1:]:
            try:
                value = float(matrix.loc[left, right])
            except (KeyError, TypeError, ValueError):
                continue
            if not np.isfinite(value):
                continue
            # Near-perfect correlation is almost always the same column twice
            # under two names, or a value and its own running total. Plotting it
            # produces a straight line and teaches nobody anything.
            if abs(value) > 0.995:
                continue
            if best is None or abs(value) > abs(best[2]):
                best = (left, right, value)
    return best


def _best_category(df: pd.DataFrame, categorical: List[str], measure: str) -> Optional[str]:
    """The category that splits a measure most unevenly.

    Unevenness is the point: a grouping where every group averages the same
    thing makes a flat bar chart, which looks like a broken chart rather than a
    finding. The spread of group means, relative to the overall mean, is what
    ranks them.
    """
    best: Optional[Tuple[str, float]] = None
    values = _numeric(df, measure)
    overall = float(values.mean()) if values.notna().any() else 0.0
    if not overall:
        return categorical[0] if categorical else None

    for column in categorical[:8]:
        try:
            grouped = values.groupby(df[column], observed=True).mean().dropna()
        except (TypeError, ValueError, KeyError):
            continue
        if len(grouped) < 2:
            continue
        spread = float(grouped.std() / abs(overall))
        if not np.isfinite(spread):
            continue
        if best is None or spread > best[1]:
            best = (column, spread)

    if best:
        return best[0]
    return categorical[0] if categorical else None


def _panel(
    df: pd.DataFrame,
    spec: Dict[str, Any],
    *,
    kind: str,
    score: float,
    why: str,
    question: str,
) -> Optional[Dict[str, Any]]:
    """Build one panel, or return None if the chart will not draw.

    Returning None rather than raising is the whole error policy of this module:
    a dashboard is a best-effort collection, and one candidate that cannot be
    rendered should cost that panel and nothing else. The user gets five charts
    instead of six and is never shown a broken frame.
    """
    try:
        built = charts.build_chart(df, spec)
    except (charts.ChartError, ValueError, TypeError, KeyError, ArithmeticError):
        logger.exception("Dashboard panel %r could not be built", kind)
        return None

    return {
        "id": f"{kind}-{abs(hash((kind, built['title']))) % 10**8}",
        "kind": kind,
        "title": built["title"],
        # `question` is the panel's headline in the UI: a chart titled "How
        # revenue is spread" tells you what it plots, and one titled "Is revenue
        # concentrated in a few large orders?" tells you why you would look.
        "question": question,
        "why": why,
        "figure": built["figure"],
        "code": built["code"],
        "spec": built["spec"],
        "warnings": built["warnings"],
        "score": round(float(score), 3),
    }


# --------------------------------------------------------------------- KPIs --
def _kpis(
    df: pd.DataFrame,
    profile: Dict[str, Any],
    grouped: Dict[str, List[str]],
    measures: List[str],
    time_col: Optional[str],
) -> List[Dict[str, Any]]:
    """The numbers across the top: what this file is, plus what it measures.

    Shape first (rows, columns) because that is what a person checks to confirm
    the right file uploaded, then up to three facts drawn from the data itself.
    """
    cards: List[Dict[str, Any]] = [
        {
            "label": "Rows",
            "value": _fmt(len(df)),
            "note": "records in this file",
            "kind": "shape",
        },
        {
            "label": "Columns",
            "value": _fmt(len(df.columns)),
            "note": (
                f"{len(grouped['numeric'])} measure(s), "
                f"{len(grouped['categorical'])} category/ies"
            ),
            "kind": "shape",
        },
    ]

    if time_col:
        stamps = pd.to_datetime(df[time_col], errors="coerce", format="mixed").dropna()
        if len(stamps) > 1:
            span_days = int((stamps.max() - stamps.min()).days)
            span = (
                f"{span_days:,} days" if span_days < 730
                else f"{span_days / 365.25:,.1f} years"
            )
            cards.append(
                {
                    "label": "Covers",
                    "value": span,
                    "note": (
                        f"{stamps.min():%d %b %Y} to {stamps.max():%d %b %Y}"
                    ),
                    "kind": "time",
                }
            )

    for measure in measures[:2]:
        values = _numeric(df, measure).dropna()
        if values.empty:
            continue
        accumulates = _accumulates(measure)
        cards.append(
            {
                "label": f"{'Total' if accumulates else 'Average'} {_friendly(measure)}",
                "value": _fmt(float(values.sum() if accumulates else values.mean())),
                "note": (
                    f"across {len(values):,} rows" if accumulates
                    else f"ranges {_fmt(float(values.min()))} to {_fmt(float(values.max()))}"
                ),
                "kind": "measure",
                "column": measure,
            }
        )

    if len(cards) < 4 and grouped["categorical"]:
        column = grouped["categorical"][0]
        n_unique = int(df[column].nunique())
        top = df[column].value_counts()
        cards.append(
            {
                "label": f"Distinct {_friendly(column)}",
                "value": _fmt(n_unique),
                "note": (
                    f"most common: {top.index[0]} ({_fmt(int(top.iloc[0]))} rows)"
                    if len(top) else ""
                ),
                "kind": "category",
                "column": column,
            }
        )

    return cards[:5]


# --------------------------------------------------------------- candidates --
def _candidates(
    df: pd.DataFrame,
    grouped: Dict[str, List[str]],
    measures: List[str],
    time_col: Optional[str],
) -> List[Dict[str, Any]]:
    """Every chart worth considering, each with a score and a reason.

    Nothing is built here -- these are proposals. Building is expensive
    (plotly figures are large) and most candidates lose, so the frame is only
    touched for the winners.
    """
    proposals: List[Dict[str, Any]] = []
    primary = measures[0] if measures else None

    # --- how it changed over time -------------------------------------------
    # Ranked highest when it applies, because "is this going up or down" is the
    # first question anyone asks of anything with a date on it.
    if time_col and primary:
        stamps = pd.to_datetime(df[time_col], errors="coerce", format="mixed").dropna()
        n_periods = int(stamps.dt.normalize().nunique()) if len(stamps) else 0
        if n_periods >= 3:
            proposals.append(
                {
                    "kind": "trend",
                    "spec": {
                        "chart": "line", "x": time_col, "y": primary,
                        "agg": _default_agg(primary),
                    },
                    "score": 10.0 + min(n_periods / 100.0, 1.0),
                    "why": (
                        f"`{time_col}` is a date and `{primary}` is a measure, so the "
                        f"first thing worth seeing is which way it has been moving."
                    ),
                    "question": f"How has {_friendly(primary)} changed over time?",
                }
            )

    # --- which groups are biggest -------------------------------------------
    if primary and grouped["categorical"]:
        category = _best_category(df, grouped["categorical"], primary)
        if category:
            agg = _default_agg(primary)
            proposals.append(
                {
                    "kind": "ranking",
                    "spec": {
                        "chart": "bar", "x": category, "y": primary,
                        "agg": agg, "limit": 12,
                    },
                    "score": 9.0,
                    "why": (
                        f"`{category}` splits `{primary}` more unevenly than any other "
                        f"grouping in this file, which is where the differences are. "
                        f"Groups are compared by {'total' if agg == 'sum' else 'average'} "
                        f"because that is what `{primary}` means when you add it up."
                    ),
                    "question": (
                        f"Which {_friendly(category)} has the "
                        f"{'most' if agg == 'sum' else 'highest average'} "
                        f"{_friendly(primary)}?"
                    ),
                }
            )

    # --- the map -------------------------------------------------------------
    if grouped["geo_lat"] and grouped["geo_lon"] and primary:
        proposals.append(
            {
                "kind": "map",
                "spec": {
                    "chart": "map",
                    "lat": grouped["geo_lat"][0],
                    "lon": grouped["geo_lon"][0],
                    "y": primary,
                },
                "score": 8.5,
                "why": (
                    "This file carries coordinates, so where the values are is a "
                    "question it can answer and most files cannot."
                ),
                "question": f"Where is {_friendly(primary)} concentrated?",
            }
        )

    # --- the relationship ----------------------------------------------------
    pair = _best_pair(df, measures)
    if pair:
        left, right, correlation = pair
        if abs(correlation) >= SCATTER_MIN_CORRELATION:
            direction = "together" if correlation > 0 else "in opposite directions"
            proposals.append(
                {
                    "kind": "relationship",
                    "spec": {"chart": "scatter", "x": left, "y": right},
                    # Scored by the strength of the correlation, so a strong
                    # relationship beats a ranking and a weak one loses to a
                    # histogram. This is the rule that makes the page adapt.
                    "score": 6.0 + 4.0 * abs(correlation),
                    "why": (
                        f"`{left}` and `{right}` move {direction} "
                        f"(correlation {correlation:+.2f}), which is the strongest "
                        f"relationship between two measures in this file."
                    ),
                    "question": (
                        f"Does {_friendly(right)} depend on {_friendly(left)}?"
                    ),
                }
            )

    # --- the correlation grid ------------------------------------------------
    if len(measures) >= HEATMAP_MIN_COLUMNS:
        proposals.append(
            {
                "kind": "correlations",
                "spec": {"chart": "heatmap", "columns": measures[:12]},
                "score": 5.5 + min(len(measures) / 20.0, 0.5),
                "why": (
                    f"With {len(measures)} measures there are "
                    f"{len(measures) * (len(measures) - 1) // 2} possible pairs. "
                    f"The grid shows all of them at once."
                ),
                "question": "Which measures move together?",
            }
        )

    # --- how it is spread ----------------------------------------------------
    if primary:
        variation = _variation(df, primary)
        proposals.append(
            {
                "kind": "distribution",
                "spec": {"chart": "histogram", "x": primary},
                # A measure that varies a lot has a shape worth seeing; one that
                # does not produces a single bar.
                "score": 4.0 + min(variation, 2.0),
                "why": (
                    f"An average hides its own shape. This is every value of "
                    f"`{primary}` in the file, so you can see whether the typical "
                    f"row is really typical."
                ),
                "question": f"How is {_friendly(primary)} spread out?",
            }
        )

    # --- how the spread differs by group -------------------------------------
    if primary and grouped["categorical"]:
        category = _best_category(df, grouped["categorical"], primary)
        if category:
            proposals.append(
                {
                    "kind": "spread_by_group",
                    "spec": {
                        "chart": "box", "x": category, "y": primary, "limit": 8,
                    },
                    "score": 3.5,
                    "why": (
                        f"A bar chart compares the averages of each "
                        f"`{category}`. This compares their whole ranges, which is "
                        f"where consistency and outliers show up."
                    ),
                    "question": (
                        f"Is {_friendly(primary)} more consistent in some "
                        f"{_friendly(category)} than others?"
                    ),
                }
            )

    # --- a second measure over time ------------------------------------------
    # Only when there is a genuinely different second measure to show; a
    # dashboard of one column plotted six ways is not a dashboard.
    if time_col and len(measures) > 1:
        second = measures[1]
        proposals.append(
            {
                "kind": "trend_secondary",
                "spec": {
                    "chart": "line", "x": time_col, "y": second,
                    "agg": _default_agg(second),
                },
                "score": 3.0 + min(_variation(df, second), 1.5),
                "why": (
                    f"`{second}` is the other measure in this file that moves most, "
                    f"so it is worth seeing whether it follows the same shape."
                ),
                "question": f"How has {_friendly(second)} changed over time?",
            }
        )

    return proposals


def compose(
    df: pd.DataFrame,
    profile: Dict[str, Any],
    routing: Dict[str, Any],
    *,
    max_panels: int = MAX_PANELS,
) -> Dict[str, Any]:
    """Choose and build the dashboard for one dataset.

    Args:
        df: the session's DataFrame, unmodified.
        profile: core.profiler.profile_dataframe output.
        routing: core.router.route output. Only its column choices are used --
            the archetype is not consulted, because the panel rules read the
            columns directly and a dataset can deserve a map and a trend at once.
        max_panels: how many charts to build. Lowered by the report builder,
            which wants fewer and larger.

    Returns:
        {"kpis": [...], "panels": [...], "note": str, "n_considered": int}

        `note` explains the selection in one sentence, so the page can say why
        it looks the way it does rather than presenting itself as inevitable.

    Never raises for a data condition. A file with nothing chartable in it
    returns empty lists and a note saying so.
    """
    grouped = _columns_by_type(profile)
    scoring = _scoring_frame(df)

    time_col = routing.get("time_col") or (
        grouped["datetime"][0] if grouped["datetime"] else None
    )
    if time_col and time_col not in df.columns:
        time_col = None

    measures = _rank_measures(scoring, grouped["numeric"], routing.get("target_col"))

    try:
        proposals = _candidates(scoring, grouped, measures, time_col)
    except (ValueError, TypeError, KeyError, ArithmeticError):
        logger.exception("Dashboard candidate selection failed")
        proposals = []

    proposals.sort(key=lambda p: p["score"], reverse=True)

    panels: List[Dict[str, Any]] = []
    seen_kinds: set = set()
    for proposal in proposals:
        if len(panels) >= max_panels:
            break
        # One panel per kind. Two histograms of two columns is the shape a
        # naive generator produces and it reads as padding; the variety is what
        # makes the page feel considered.
        if proposal["kind"] in seen_kinds:
            continue
        panel = _panel(
            df,
            proposal["spec"],
            kind=proposal["kind"],
            score=proposal["score"],
            why=proposal["why"],
            question=proposal["question"],
        )
        if panel is None:
            continue
        seen_kinds.add(proposal["kind"])
        panels.append(panel)

    kpis = _kpis(df, profile, grouped, measures, time_col)

    if not panels:
        note = (
            "There is nothing in this file that can be charted -- charts need at "
            "least one column of numbers, and this one appears to be all text."
        )
    else:
        note = (
            f"{len(panels)} chart(s) chosen from {len(proposals)} the data could "
            f"support, ranked by how much each is likely to tell you. "
            f"Every one of them is built from your columns, not from a template."
        )

    return {
        "kpis": kpis,
        "panels": panels,
        "note": note,
        "n_considered": len(proposals),
        "time_col": time_col,
        "measures": measures[:12],
    }
