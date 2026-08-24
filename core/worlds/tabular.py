"""Tabular world: the fallback archetype -- distribution, comparison, correlation.

This is where a dataset lands when it has no time axis and no coordinates, which
in practice is most datasets. It is therefore the world that has to degrade the
most gracefully: entity_col is genuinely often None (see the profiler's
categorical rules), and a dataset with one numeric column is common.

The rule followed here is that a figure is either meaningful or absent. Nothing
is rendered as an empty placeholder or a 1x1 grid to keep the layout symmetrical
-- a chart that shows nothing still reads as a finding to someone skimming.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from core.worlds import _glassbox

# Bars beyond this are unreadable on a normal screen and the tail is almost
# always long-tail noise. 15 is roughly what fits vertically without the labels
# colliding.
MAX_BARS = 15

# A correlation matrix needs at least two columns to correlate. One numeric
# column produces a 1x1 grid whose single cell is 1.0 by definition -- a
# tautology rendered as a finding.
MIN_NUMERIC_FOR_CORRELATION = 2

# Histogram bins. WHY fixed rather than Freedman-Diaconis or Sturges: an
# automatic rule changes bin width with the data, so two runs of the app on
# related files produce charts that cannot be compared by eye. 30 is a
# conventional default that shows shape without turning into a rug plot.
HISTOGRAM_BINS = 30


def _fail(message: str, warnings: List[str]) -> Dict[str, Any]:
    """Shorthand for the 'cannot build this world' return."""
    return _glassbox.result(status="insufficient_data", message=message, warnings=warnings)


DISTRIBUTION_TEMPLATE = """
import pandas as pd
import plotly.express as px

values = pd.to_numeric(df[$target_col], errors='coerce').dropna()

fig = px.histogram(
    values, x=$target_col, nbins=$bins,
    title=$title,
)
# The mean line is what turns a shape into a reading: it shows at a glance
# whether the distribution is skewed, and where the bulk sits relative to the
# number most people would quote as "the average".
fig.add_vline(
    x=float(values.mean()),
    line_dash='dash', line_color='#71717d',
    annotation_text=f'mean = {values.mean():,.2f}',
    annotation_position='top right',
)
fig.update_layout(xaxis_title=$target_col, yaxis_title='count', bargap=0.05)
"""

ENTITY_TEMPLATE = """
import pandas as pd
import plotly.express as px

data = df[[$entity_col, $target_col]].copy()
data[$target_col] = pd.to_numeric(data[$target_col], errors='coerce')
data = data.dropna(subset=[$entity_col, $target_col])

# mean() rather than sum(): a sum conflates "this category has large values"
# with "this category has many rows", and the second is a fact about sampling,
# not about the thing being measured. The row count is kept as hover context so
# a mean drawn from three rows is not read with the same confidence as one drawn
# from three hundred.
summary = (
    data.groupby($entity_col)[$target_col]
    .agg(['mean', 'count'])
    .sort_values('mean', ascending=False)
    .head($max_bars)
    .reset_index()
)

fig = px.bar(
    summary, x=$entity_col, y='mean',
    hover_data={'count': True},
    title=$title,
)
fig.update_layout(
    xaxis_title=$entity_col,
    yaxis_title=$y_title,
    xaxis={'categoryorder': 'total descending'},
)
"""

CORRELATION_TEMPLATE = """
import plotly.express as px

# Only the numeric columns; pandas would otherwise silently drop the rest and
# leave the reader wondering why a column they can see is missing from the grid.
numeric = df[$numeric_cols]
matrix = numeric.corr(numeric_only=True)

fig = px.imshow(
    matrix,
    text_auto='.2f',
    aspect='auto',
    # A diverging scale centred on zero, because the sign of a correlation is
    # the first thing to read. A sequential scale would make -0.9 and +0.1 look
    # like neighbours.
    color_continuous_scale='RdBu_r',
    zmin=-1, zmax=1,
    title=$title,
)
fig.update_layout(margin={'l': 0, 'r': 0, 't': 50, 'b': 0})
"""


def build(df: pd.DataFrame, routing: Dict[str, Any]) -> Dict[str, Any]:
    """Build the tabular world for a routed DataFrame.

    Args:
        df: the uploaded data, unmodified.
        routing: output of core.router.route -- target_col is required,
            entity_col optional and frequently absent.

    Returns:
        The shared world dict (figures/stats/code/warnings/status/message).
        Figures present depend on what the data supports: "distribution" always,
        "by_entity" only with a categorical column, "correlation" only with at
        least two numeric columns.
    """
    target_col = routing.get("target_col")
    entity_col = routing.get("entity_col")
    warnings: List[str] = []

    if not target_col or target_col not in df.columns:
        return _fail("No target column to describe, so there is nothing to plot.", warnings)

    values = pd.to_numeric(df[target_col], errors="coerce").dropna()
    if values.empty:
        return _fail(
            f"{target_col!r} holds no numeric values, so it has no distribution "
            f"to show.",
            warnings,
        )

    n_dropped = int(len(df) - len(values))
    if n_dropped:
        warnings.append(
            f"{n_dropped} of {len(df)} rows had a missing or non-numeric "
            f"{target_col!r} and are excluded from the distribution."
        )

    figures: Dict[str, Any] = {}
    code: Dict[str, str] = {}

    distribution_code = _glassbox.render(
        DISTRIBUTION_TEMPLATE,
        target_col=target_col,
        bins=HISTOGRAM_BINS,
        title=f"Distribution of {target_col}",
    )
    figures["distribution"] = _glassbox.execute(distribution_code, df)
    code["distribution"] = distribution_code

    # entity_col being None is an ordinary outcome, not an error: a dataset can
    # legitimately have no column with a small repeated vocabulary. The world
    # loses one figure and says so, rather than inventing a grouping.
    if entity_col and entity_col in df.columns:
        entity_code = _glassbox.render(
            ENTITY_TEMPLATE,
            entity_col=entity_col,
            target_col=target_col,
            max_bars=MAX_BARS,
            y_title=f"mean {target_col}",
            title=f"Mean {target_col} by {entity_col} (top {MAX_BARS})",
        )
        figures["by_entity"] = _glassbox.execute(entity_code, df)
        code["by_entity"] = entity_code

        n_categories = int(df[entity_col].nunique(dropna=True))
        if n_categories > MAX_BARS:
            warnings.append(
                f"{entity_col!r} has {n_categories} categories; the bar chart "
                f"shows the {MAX_BARS} with the highest mean."
            )
    else:
        warnings.append(
            "No categorical column was identified, so there is no grouped "
            "comparison. Distribution and correlation are unaffected."
        )

    # select_dtypes rather than the profile's semantic types on purpose: the
    # profile calls a low-cardinality integer column "categorical", which is the
    # right call for grouping but the wrong one here -- a 1-5 satisfaction score
    # correlates perfectly meaningfully with salary.
    numeric_cols = list(df.select_dtypes(include="number").columns)
    if len(numeric_cols) >= MIN_NUMERIC_FOR_CORRELATION:
        correlation_code = _glassbox.render(
            CORRELATION_TEMPLATE,
            numeric_cols=numeric_cols,
            title=f"Correlation across {len(numeric_cols)} numeric columns",
        )
        figures["correlation"] = _glassbox.execute(correlation_code, df)
        code["correlation"] = correlation_code
    else:
        warnings.append(
            f"Only {len(numeric_cols)} numeric column(s), so no correlation "
            f"heatmap -- a 1x1 grid would only restate that a column correlates "
            f"with itself."
        )

    described = values.describe()
    stats: Dict[str, Any] = {
        "target_col": target_col,
        # describe()'s own keys, kept verbatim so the numbers can be checked
        # against a one-line pandas call rather than trusted.
        "target_summary": {
            key: round(float(val), 4) for key, val in described.items()
        },
        "n_values": int(len(values)),
        "n_excluded": n_dropped,
        "n_numeric_columns": len(numeric_cols),
    }

    if entity_col and entity_col in df.columns:
        counts = df[entity_col].value_counts()
        stats["entity_col"] = entity_col
        stats["n_categories"] = int(counts.shape[0])
        stats["category_counts"] = {
            str(name): int(count) for name, count in counts.head(MAX_BARS).items()
        }
    else:
        stats["entity_col"] = None
        stats["n_categories"] = 0
        stats["category_counts"] = {}

    return _glassbox.result(figures=figures, stats=stats, code=code, warnings=warnings)
