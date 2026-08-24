"""Spec-driven charts: a fixed set of visual components the rest of the app configures.

WHY THIS EXISTS
---------------
Two features need to draw a chart that nobody wrote by hand: the insight cards
("show me why you think revenue is rising") and the assistant ("show me the
highest-performing products"). The tempting implementation is to let the model
emit plotting code, or React, and run it. That hands an external service the
ability to execute in the user's browser or on our server, and it makes the
output unpredictable in exactly the place the user is being asked to trust it.

The alternative used here: the model -- or an insight, or a button -- emits a
*structured spec*, a small dict naming a chart type and some columns. This
module validates every field of that spec against the DataFrame it will run
against, then renders one of a handful of authored templates. Anything the spec
asks for that is not on the whitelist is refused with a sentence, not attempted.

So the surface an LLM can reach is: six chart types, column names that already
exist, and six aggregation names. It cannot name a function, a module, or a
piece of syntax.

GLASS BOX, PRESERVED
--------------------
Every chart here is produced by core.worlds._glassbox the same way the worlds
are: the template is rendered to Python source, that exact source is executed,
and the source is returned alongside the figure. A chart the assistant conjured
up is therefore no more mysterious than one the app built at upload time -- the
user can read the few lines that made it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from core.worlds import _glassbox

logger = logging.getLogger(__name__)

# The complete vocabulary. Both tuples are whitelists, and both are consulted
# with `in` before any value from a spec is used -- including the aggregation,
# which is spliced into the template as a method name and would otherwise be
# the one place a spec could reach into code position.
CHART_TYPES = ("line", "bar", "scatter", "histogram", "box", "map", "heatmap")
AGGREGATIONS = ("sum", "mean", "median", "count", "min", "max")

FREQ_ALIASES = {"D": "D", "W": "W", "M": "ME"}
FREQ_LABELS = {"D": "daily", "W": "weekly", "M": "monthly"}

# Bars past roughly this many stop being a ranking and start being a texture.
MAX_BARS = 20
DEFAULT_BARS = 12
HISTOGRAM_BINS = 30
# A correlation grid past roughly this many columns becomes a texture rather
# than a readable matrix, and the labels stop fitting on the axes.
MAX_HEATMAP_COLUMNS = 12
MIN_HEATMAP_COLUMNS = 2
# Scatter plots of very large frames produce a solid block of ink and a payload
# to match. Sampling is disclosed in the returned warnings, never silently.
MAX_SCATTER_POINTS = 4000


class ChartError(ValueError):
    """A spec that cannot be drawn, carrying a sentence fit to show a user.

    A subclass of ValueError so callers that already treat ValueError as "the
    request was wrong, not the server" -- which is how backend/routers/world.py
    is written -- keep working without a new except clause.
    """


# --------------------------------------------------------------- templates --
# Each snippet stands alone: it carries its own imports and reads only `df`, so
# it can be copied into a notebook and run. That is the whole point of showing it.

LINE_TEMPLATE = """
import pandas as pd
import plotly.graph_objects as go

data = df[[$x, $y]].copy()
data[$x] = pd.to_datetime(data[$x], errors="coerce", format="mixed")
data[$y] = pd.to_numeric(data[$y], errors="coerce")
data = data.dropna().sort_values($x)

series = data.set_index($x)[$y].resample($freq_alias).$agg()

fig = go.Figure()
fig.add_trace(go.Scatter(x=series.index, y=series.values, mode="lines", name=$y))
fig.update_layout(title=$title, xaxis_title=$x, yaxis_title=$y_label)
"""

BAR_TEMPLATE = """
import pandas as pd
import plotly.graph_objects as go

data = df[[$x, $y]].copy()
data[$y] = pd.to_numeric(data[$y], errors="coerce")
data = data.dropna(subset=[$x, $y])

ranked = (
    data.groupby($x)[$y]
    .$agg()
    .sort_values(ascending=$ascending)
    .head($limit)
)

fig = go.Figure()
fig.add_trace(go.Bar(x=ranked.index.astype(str), y=ranked.values, name=$y))
fig.update_layout(title=$title, xaxis_title=$x, yaxis_title=$y_label)
"""

SCATTER_TEMPLATE = """
import numpy as np
import pandas as pd
import plotly.graph_objects as go

data = df[[$x, $y]].apply(pd.to_numeric, errors="coerce").dropna()
$sample_block
fig = go.Figure()
fig.add_trace(
    go.Scatter(x=data[$x], y=data[$y], mode="markers", name="observations",
               marker={"size": 6, "opacity": 0.55})
)

# A least-squares line, drawn only when there are two distinct x values to fit
# through -- polyfit on a constant column returns a meaningless slope.
if data[$x].nunique() > 1:
    slope, intercept = np.polyfit(data[$x], data[$y], 1)
    xs = np.linspace(data[$x].min(), data[$x].max(), 50)
    fig.add_trace(go.Scatter(x=xs, y=slope * xs + intercept, mode="lines",
                             name="line of best fit"))

fig.update_layout(title=$title, xaxis_title=$x, yaxis_title=$y)
"""

HISTOGRAM_TEMPLATE = """
import pandas as pd
import plotly.graph_objects as go

values = pd.to_numeric(df[$x], errors="coerce").dropna()

fig = go.Figure()
fig.add_trace(go.Histogram(x=values, nbinsx=$bins, name=$x))
fig.update_layout(title=$title, xaxis_title=$x, yaxis_title="rows")
"""

BOX_TEMPLATE = """
import pandas as pd
import plotly.graph_objects as go

data = df[[$x, $y]].copy()
data[$y] = pd.to_numeric(data[$y], errors="coerce")
data = data.dropna(subset=[$x, $y])

keep = data[$x].value_counts().head($limit).index
fig = go.Figure()
for name in keep:
    fig.add_trace(go.Box(y=data.loc[data[$x] == name, $y], name=str(name)))
fig.update_layout(title=$title, xaxis_title=$x, yaxis_title=$y, showlegend=False)
"""

MAP_TEMPLATE = """
import pandas as pd
import plotly.express as px

data = df[[$lat, $lon, $y]].apply(pd.to_numeric, errors="coerce").dropna()

fig = px.scatter_map(
    data, lat=$lat, lon=$lon, color=$y, size=$y,
    size_max=18, zoom=$zoom, map_style="carto-positron", title=$title,
)
"""


HEATMAP_TEMPLATE = """
import pandas as pd
import plotly.graph_objects as go

data = df[$columns].apply(pd.to_numeric, errors="coerce")
matrix = data.corr(numeric_only=True).round(2)

fig = go.Figure(
    go.Heatmap(
        z=matrix.values,
        x=list(matrix.columns),
        y=list(matrix.index),
        zmin=-1,
        zmax=1,
        colorscale=$colorscale,
        text=matrix.values,
        texttemplate="%{text:.2f}",
        hovertemplate="%{y} vs %{x}<br>correlation %{z:.2f}<extra></extra>",
    )
)
fig.update_layout(title=$title)
fig.update_yaxes(autorange="reversed")
"""

# A diverging scale, because a correlation matrix has a meaningful midpoint at
# zero: -0.8 and +0.8 are equally strong and opposite in direction, and a
# sequential ramp would render one of them as "nearly nothing". Neutral grey in
# the middle so that "no relationship" reads as absence rather than as a
# colour; red and blue read as opposite poles at a glance, unlike the previous
# rust/teal pairing, which read as two shades of the same murky brown-green.
HEATMAP_COLORSCALE = [
    [0.0, "#c0392b"],
    [0.5, "#f0efec"],
    [1.0, "#1c5cab"],
]


# -------------------------------------------------------------- validation --
def _column_names(df: pd.DataFrame) -> List[str]:
    return [str(c) for c in df.columns]


def _require_column(df: pd.DataFrame, name: Any, role: str) -> str:
    """Resolve a spec's column name against the frame, or refuse by name.

    Matching falls back to case-insensitive as a convenience -- an assistant
    that writes "Revenue" for a column called "revenue" has understood the
    question, and failing that request would be pedantry. Anything that does not
    resolve is refused with the name that was asked for, because the caller (an
    LLM, or a stale UI action) can then correct itself.
    """
    if name is None or str(name).strip() == "":
        raise ChartError(f"This chart needs a column for {role}, and none was given.")

    wanted = str(name).strip()
    columns = _column_names(df)
    if wanted in columns:
        return wanted

    lowered = wanted.lower()
    for column in columns:
        if column.lower() == lowered:
            return column

    raise ChartError(f"There is no column called {wanted!r} in this dataset.")


def _require_numeric(df: pd.DataFrame, column: str, role: str) -> str:
    """Refuse a column that holds nothing a chart could measure."""
    values = pd.to_numeric(df[column], errors="coerce")
    if values.notna().sum() == 0:
        raise ChartError(f"{column!r} holds no numbers, so it cannot be used as {role}.")
    return column


def _suggest_freq(df: pd.DataFrame, time_col: str) -> str:
    """Pick a time grouping from the span of the data rather than defaulting to daily.

    A three-year daily series drawn at daily resolution is a thousand points of
    noise with a trend hidden inside it; the same series by month is the trend.
    Choosing from the span means the caller does not have to know the shape of
    the data to ask for a sensible chart.
    """
    try:
        stamps = pd.to_datetime(df[time_col], errors="coerce", format="mixed").dropna()
    except (ValueError, TypeError):
        return "D"
    if stamps.empty:
        return "D"
    span_days = int((stamps.max() - stamps.min()).days)
    if span_days <= 90:
        return "D"
    if span_days <= 800:
        return "W"
    return "M"


def normalise(spec: Dict[str, Any], df: pd.DataFrame) -> Dict[str, Any]:
    """Validate and complete a chart spec against the frame it will draw from.

    Returns a spec with every field either resolved or defaulted, so build_chart
    below can read it without re-checking anything.

    Raises:
        ChartError: for an unknown chart type, a missing or unusable column, or
            an aggregation outside the whitelist. Every message names what was
            wrong in words a user could read, because these surface in the UI.
    """
    kind = str(spec.get("chart") or spec.get("type") or "").strip().lower()
    if kind not in CHART_TYPES:
        shown = kind or "that"
        raise ChartError(
            f"{shown!r} is not a chart this app can draw. "
            f"Available: {', '.join(CHART_TYPES)}."
        )

    clean: Dict[str, Any] = {"chart": kind}

    agg = str(spec.get("agg") or "").strip().lower()
    if agg and agg not in AGGREGATIONS:
        raise ChartError(
            f"{agg!r} is not an available summary. Available: {', '.join(AGGREGATIONS)}."
        )

    freq = str(spec.get("freq") or "").strip().upper()
    if freq and freq not in FREQ_ALIASES:
        raise ChartError(
            "Time grouping must be one of D (daily), W (weekly) or M (monthly)."
        )

    raw_limit = spec.get("limit")
    try:
        limit = int(raw_limit) if raw_limit is not None else DEFAULT_BARS
    except (TypeError, ValueError):
        limit = DEFAULT_BARS
    clean["limit"] = max(1, min(MAX_BARS, limit))

    clean["ascending"] = bool(spec.get("ascending", False))
    clean["title"] = str(spec.get("title") or "").strip()

    if kind == "line":
        clean["x"] = _require_column(df, spec.get("x"), "the time axis")
        clean["y"] = _require_numeric(
            df, _require_column(df, spec.get("y"), "the value axis"), "a value"
        )
        clean["agg"] = agg or "mean"
        clean["freq"] = freq or _suggest_freq(df, clean["x"])

    elif kind == "bar":
        clean["x"] = _require_column(df, spec.get("x"), "the grouping")
        clean["y"] = _require_numeric(
            df, _require_column(df, spec.get("y"), "the value axis"), "a value"
        )
        clean["agg"] = agg or "mean"

    elif kind == "scatter":
        clean["x"] = _require_numeric(
            df, _require_column(df, spec.get("x"), "the horizontal axis"), "an axis"
        )
        clean["y"] = _require_numeric(
            df, _require_column(df, spec.get("y"), "the vertical axis"), "an axis"
        )

    elif kind == "histogram":
        clean["x"] = _require_numeric(
            df,
            _require_column(df, spec.get("x") or spec.get("y"), "the value"),
            "a value",
        )

    elif kind == "box":
        clean["x"] = _require_column(df, spec.get("x"), "the grouping")
        clean["y"] = _require_numeric(
            df, _require_column(df, spec.get("y"), "the value axis"), "a value"
        )

    elif kind == "heatmap":
        # The only spec that takes a LIST of columns. Callers may omit it
        # entirely, in which case every numeric column in the frame is used --
        # "show me the correlations" is a question about the whole dataset, and
        # making the user enumerate its columns to ask it would defeat the point.
        raw = spec.get("columns")
        if isinstance(raw, str):
            raw = [raw]
        if not raw:
            candidates = [
                name
                for name in _column_names(df)
                if pd.api.types.is_numeric_dtype(df[name])
            ]
        else:
            candidates = [_require_column(df, name, "a column") for name in raw]

        # Constant columns are dropped rather than rejected: their correlation
        # with everything is undefined, and a matrix with a stripe of NaN
        # through it looks like a bug in the app rather than a fact about a
        # column that never changes.
        columns: List[str] = []
        for name in candidates:
            values = pd.to_numeric(df[name], errors="coerce")
            if values.notna().sum() >= 2 and values.std(skipna=True) > 0:
                columns.append(name)

        if len(columns) < MIN_HEATMAP_COLUMNS:
            raise ChartError(
                "A correlation grid needs at least two numeric columns that "
                "actually vary. This data does not have them."
            )
        clean["columns"] = columns[:MAX_HEATMAP_COLUMNS]

    else:  # map -- the only remaining member of CHART_TYPES
        clean["lat"] = _require_numeric(
            df, _require_column(df, spec.get("lat"), "latitude"), "latitude"
        )
        clean["lon"] = _require_numeric(
            df, _require_column(df, spec.get("lon"), "longitude"), "longitude"
        )
        clean["y"] = _require_numeric(
            df, _require_column(df, spec.get("y"), "the value"), "a value"
        )

    return clean


# ------------------------------------------------------------------ render --
def build_chart(df: pd.DataFrame, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Render one chart from a spec, returning the figure and the code that made it.

    Args:
        df: the session's DataFrame.
        spec: a chart spec -- see normalise() for the accepted fields.

    Returns:
        {"figure": go.Figure, "code": str, "spec": <normalised spec>,
         "title": str, "warnings": [str]}

    Raises:
        ChartError: for anything wrong with the spec.
    """
    clean = normalise(spec, df)
    kind = clean["chart"]
    warnings: List[str] = []

    if kind == "line":
        title = clean["title"] or f"{clean['y']} over time ({FREQ_LABELS[clean['freq']]})"
        code = _glassbox.render(
            LINE_TEMPLATE,
            x=clean["x"],
            y=clean["y"],
            freq_alias=FREQ_ALIASES[clean["freq"]],
            agg=_glassbox.Raw(clean["agg"]),
            y_label=f"{clean['agg']} of {clean['y']}",
            title=title,
        )

    elif kind == "bar":
        direction = "lowest" if clean["ascending"] else "highest"
        title = clean["title"] or (
            f"{clean['limit']} {direction} by {clean['agg']} {clean['y']}"
        )
        code = _glassbox.render(
            BAR_TEMPLATE,
            x=clean["x"],
            y=clean["y"],
            agg=_glassbox.Raw(clean["agg"]),
            ascending=clean["ascending"],
            limit=clean["limit"],
            y_label=f"{clean['agg']} of {clean['y']}",
            title=title,
        )

    elif kind == "scatter":
        n_rows = int(len(df))
        sample_block = ""
        if n_rows > MAX_SCATTER_POINTS:
            # random_state is fixed so the same question twice draws the same
            # chart. A plot that reshuffles on every ask looks like the data
            # changed.
            sample_block = (
                f"data = data.sample({MAX_SCATTER_POINTS}, random_state=0)\n"
            )
            warnings.append(
                f"This dataset has {n_rows:,} rows, so the chart shows a random "
                f"sample of {MAX_SCATTER_POINTS:,} of them. The line of best fit "
                f"is fitted to that sample."
            )
        title = clean["title"] or f"{clean['y']} against {clean['x']}"
        code = _glassbox.render(
            SCATTER_TEMPLATE,
            x=clean["x"],
            y=clean["y"],
            sample_block=_glassbox.Raw(sample_block),
            title=title,
        )

    elif kind == "histogram":
        title = clean["title"] or f"How {clean['x']} is spread"
        code = _glassbox.render(
            HISTOGRAM_TEMPLATE, x=clean["x"], bins=HISTOGRAM_BINS, title=title
        )

    elif kind == "box":
        title = clean["title"] or f"{clean['y']} by {clean['x']}"
        code = _glassbox.render(
            BOX_TEMPLATE, x=clean["x"], y=clean["y"], limit=clean["limit"], title=title
        )

    elif kind == "heatmap":
        title = clean["title"] or "How the numbers move together"
        n_dropped = len(
            [c for c in _column_names(df) if pd.api.types.is_numeric_dtype(df[c])]
        ) - len(clean["columns"])
        if n_dropped > 0:
            warnings.append(
                f"{n_dropped} numeric column(s) are not shown: a column has to "
                f"vary to correlate with anything, and these do not, or the grid "
                f"was capped at {MAX_HEATMAP_COLUMNS} columns for legibility."
            )
        code = _glassbox.render(
            HEATMAP_TEMPLATE,
            columns=clean["columns"],
            colorscale=HEATMAP_COLORSCALE,
            title=title,
        )

    else:  # map
        title = clean["title"] or f"{clean['y']} by location"
        code = _glassbox.render(
            MAP_TEMPLATE,
            lat=clean["lat"],
            lon=clean["lon"],
            y=clean["y"],
            zoom=4,
            title=title,
        )

    figure = _glassbox.execute(code, df)
    return {
        "figure": figure,
        "code": code,
        "spec": clean,
        "title": title,
        "warnings": warnings,
    }


def spec_is_supported(spec: Optional[Dict[str, Any]], df: pd.DataFrame) -> bool:
    """True if a spec would render. Used to drop actions that would only fail.

    An insight or an assistant answer may carry a "show me" action. Offering a
    button that fails when pressed is worse than offering no button, so the
    action is checked before it is attached rather than when it is clicked.
    """
    if not spec:
        return False
    try:
        normalise(spec, df)
        return True
    except ChartError:
        return False
