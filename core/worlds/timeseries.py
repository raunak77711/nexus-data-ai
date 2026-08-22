"""Timeseries world: how a measure moved over time.

build() returns figures/stats/code plus warnings and a status, per the shared
contract in _glassbox.result(). Every figure is produced by executing the code
string returned alongside it, so the "Show the code" panel cannot drift from
what was plotted -- see _glassbox for why that inversion matters.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from core.worlds import _glassbox

# User-facing frequency vocabulary -> the alias pandas actually accepts.
# WHY a translation table rather than passing the string straight through:
# pandas 3.0 removed the bare "M" alias (it now raises "'M' is no longer
# supported") in favour of "ME" for month-end. Keeping "M" as the public option
# means the UI, the docs and the spec do not have to track pandas' internal
# renames, and a future alias change is a one-line edit here.
FREQ_ALIASES = {"D": "D", "W": "W", "M": "ME"}
FREQ_LABELS = {"D": "daily", "W": "weekly", "M": "monthly"}

# A category split beyond this is an unreadable tangle of near-identical lines;
# six is about the limit at which a qualitative colour scale stays legible.
MAX_ENTITY_LINES = 6

# Minimum resampled points needed to draw a line and fit a trend. One point is
# not a line; below this the honest answer is "not enough data" rather than a
# chart the user would reasonably read as a trend.
MIN_PERIODS = 2

# A modelled change smaller than this fraction of the series' scale is called
# flat. WHY a dead band at all: a least-squares slope is almost never exactly
# zero, so without one every series would be labelled rising or falling, and a
# 0.001% drift would be reported with the same confidence as a doubling.
FLAT_BAND = 0.05


def _fail(message: str, warnings: List[str]) -> Dict[str, Any]:
    """Shorthand for the 'cannot build this world' return."""
    return _glassbox.result(status="insufficient_data", message=message, warnings=warnings)


def _clean(df: pd.DataFrame, time_col: str, target_col: str) -> Tuple[pd.DataFrame, List[str]]:
    """Coerce the time and target columns, drop unusable rows, report the losses.

    Routing tells us which column *means* time, not that every cell in it parses.
    A column that is 95% dates still routes as datetime (by design -- see the
    profiler's 80% threshold), which leaves live bad cells to deal with here.

    errors="coerce" turns those into NaT/NaN and they are dropped, because the
    alternative -- letting to_datetime raise -- would take the whole world down
    over three malformed rows in a 50,000-row file. The count is returned rather
    than logged: a user whose upload lost 40% of its rows to unparseable dates
    needs to see that next to the chart, or they will read a badly incomplete
    series as the truth.
    """
    warnings: List[str] = []
    data = df[[time_col, target_col]].copy()
    n_before = len(data)

    data[time_col] = pd.to_datetime(data[time_col], errors="coerce", format="mixed")
    data[target_col] = pd.to_numeric(data[target_col], errors="coerce")

    bad_dates = int(data[time_col].isna().sum())
    bad_values = int(data[target_col].isna().sum())
    data = data.dropna(subset=[time_col, target_col])

    if bad_dates:
        warnings.append(
            f"{bad_dates} of {n_before} rows had a date that could not be parsed "
            f"and were dropped."
        )
    if bad_values:
        warnings.append(
            f"{bad_values} of {n_before} rows had a non-numeric or missing "
            f"value in {target_col!r} and were dropped."
        )
    return data.sort_values(time_col), warnings


def _trend(series: pd.Series) -> Dict[str, Any]:
    """Describe the trend from a least-squares slope over the whole series.

    WHY a linear fit and not first-vs-last: comparing the endpoints asks two of
    the n points to speak for all of them. One anomalous final reading -- an
    outage, a partial last month, a single huge order -- flips the reported
    direction of an otherwise obvious trend, and the user has no way to tell.
    The slope uses every point, so a single outlier moves it a little instead of
    inverting it.

    The x axis is the period index (0, 1, 2, ...) rather than the timestamp, so
    the slope reads as "units per period" -- a number that means something next
    to a chart labelled in those same periods.
    """
    clean = series.dropna()
    if len(clean) < MIN_PERIODS:
        return {"trend_direction": "unknown", "trend_slope_per_period": None}

    x = np.arange(len(clean), dtype=float)
    slope, _intercept = np.polyfit(x, clean.to_numpy(dtype=float), 1)

    # Total change the fitted line implies across the observed window, compared
    # against the series' own scale so the dead band means the same thing for
    # revenue in millions and for a fraction between 0 and 1.
    modelled_change = slope * (len(clean) - 1)
    mean = float(clean.mean())
    std = float(clean.std()) if len(clean) > 1 else 0.0
    # Fall back to std when the mean is ~0 (a centred or signed series), and to
    # 1.0 when both are ~0, which means the series is constant and any slope is
    # numerical noise.
    scale = abs(mean) if abs(mean) > 1e-12 else (std if std > 1e-12 else 1.0)

    if abs(modelled_change) < FLAT_BAND * scale:
        direction = "flat"
    else:
        direction = "rising" if modelled_change > 0 else "falling"

    return {
        "trend_direction": direction,
        "trend_slope_per_period": round(float(slope), 6),
    }


MAIN_TEMPLATE = """
import pandas as pd
import plotly.graph_objects as go

# Routing identified $time_col as the time axis and $target_col as the measure.
# Coerce both: a column can route as a date while still holding a few
# unparseable cells, and errors='coerce' turns those into NaT/NaN so they can be
# dropped instead of raising.
data = df[[$time_col, $target_col]].copy()
data[$time_col] = pd.to_datetime(data[$time_col], errors='coerce', format='mixed')
data[$target_col] = pd.to_numeric(data[$target_col], errors='coerce')
data = data.dropna(subset=[$time_col, $target_col]).sort_values($time_col)

# One point per $freq_label period. mean() rather than sum(): averaging is
# meaningful for every kind of measure, whereas summing a temperature or a
# percentage produces a number with no units. Periods with no data stay NaN,
# which plotly draws as a gap -- an honest hole beats an invented straight line.
series = data.set_index($time_col)[$target_col].resample($freq_alias).mean()

# min_periods=1 so the rolling mean starts at the first point instead of leaving
# the first $rolling_window periods blank.
rolling = series.rolling(window=$rolling_window, min_periods=1).mean()

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=series.index, y=series.values, mode='lines',
    name=$series_name, line={'width': 1.4},
))
fig.add_trace(go.Scatter(
    x=rolling.index, y=rolling.values, mode='lines',
    name=$rolling_name, line={'width': 2.6, 'dash': 'dash'},
))
fig.update_layout(
    title=$title,
    xaxis_title=$time_col,
    yaxis_title=$target_col,
    hovermode='x unified',
    legend={'orientation': 'h', 'y': -0.2},
)
"""

ENTITY_TEMPLATE = """
import pandas as pd
import plotly.express as px

data = df[[$time_col, $target_col, $entity_col]].copy()
data[$time_col] = pd.to_datetime(data[$time_col], errors='coerce', format='mixed')
data[$target_col] = pd.to_numeric(data[$target_col], errors='coerce')
data = data.dropna(subset=[$time_col, $target_col, $entity_col])

# Only the $max_lines most common categories. Past roughly six lines a
# multi-series chart stops being readable -- the colours become hard to tell
# apart and the lines occlude each other -- so this is a legibility limit, not a
# performance one. Ranking by row count keeps the categories the data actually
# has the most evidence about.
top = data[$entity_col].value_counts().head($max_lines).index
data = data[data[$entity_col].isin(top)]

# Resample within each category. pd.Grouper applies the same $freq_label buckets
# as the main chart, so the two figures line up on the x axis.
grouped = (
    data.groupby([$entity_col, pd.Grouper(key=$time_col, freq=$freq_alias)])[$target_col]
    .mean()
    .reset_index()
)

fig = px.line(
    grouped, x=$time_col, y=$target_col, color=$entity_col,
    title=$title, markers=False,
)
fig.update_layout(hovermode='x unified', legend={'title': $entity_col})
"""


def build(
    df: pd.DataFrame,
    routing: Dict[str, Any],
    freq: str = "D",
    rolling_window: int = 7,
) -> Dict[str, Any]:
    """Build the timeseries world for a routed DataFrame.

    Args:
        df: the uploaded data, unmodified.
        routing: output of core.router.route -- time_col and target_col are
            required, entity_col optional.
        freq: resampling period, one of "D", "W", "M".
        rolling_window: number of periods in the rolling-mean overlay.

    Returns:
        The shared world dict (figures/stats/code/warnings/status/message).
        status is "insufficient_data" when the data cannot support a chart, and
        the caller renders message instead of figures.

    Raises:
        ValueError: for an out-of-range freq or rolling_window. These come from
            the app's own controls, never from the uploaded file, so a bad value
            is a bug in the caller and should be loud rather than silently
            coerced to a default that hides it.
    """
    if freq not in FREQ_ALIASES:
        raise ValueError(f"freq must be one of {sorted(FREQ_ALIASES)}, got {freq!r}")
    if rolling_window < 1:
        raise ValueError(f"rolling_window must be >= 1, got {rolling_window}")

    time_col = routing.get("time_col")
    target_col = routing.get("target_col")
    entity_col = routing.get("entity_col")
    warnings: List[str] = []

    # Routing is validated against the profile, but build() may also be reached
    # through the app's manual archetype override -- a user can force
    # "timeseries" onto a dataset with no date column. Check rather than assume.
    if not time_col or time_col not in df.columns:
        return _fail("No usable date column, so there is no time axis to plot.", warnings)
    if not target_col or target_col not in df.columns:
        return _fail("No usable numeric column, so there is nothing to plot.", warnings)
    if df[target_col].isna().all():
        return _fail(f"Every value in {target_col!r} is missing.", warnings)

    data, warnings = _clean(df, time_col, target_col)
    if data.empty:
        return _fail(
            f"No rows survived cleaning: {time_col!r} and {target_col!r} never both "
            f"held a usable value in the same row.",
            warnings,
        )

    freq_alias = FREQ_ALIASES[freq]
    freq_label = FREQ_LABELS[freq]
    series = data.set_index(time_col)[target_col].resample(freq_alias).mean()
    n_observed = int(series.dropna().shape[0])

    if n_observed < MIN_PERIODS:
        return _fail(
            f"Only {n_observed} {freq_label} period(s) of data after resampling -- "
            f"at least {MIN_PERIODS} are needed to draw a trend. Try a finer "
            f"frequency.",
            warnings,
        )

    figures: Dict[str, Any] = {}
    code: Dict[str, str] = {}

    main_code = _glassbox.render(
        MAIN_TEMPLATE,
        time_col=time_col,
        target_col=target_col,
        freq_alias=freq_alias,
        freq_label=_glassbox.Raw(freq_label),
        rolling_window=rolling_window,
        series_name=f"{target_col} ({freq_label})",
        rolling_name=f"{rolling_window}-period rolling mean",
        title=f"{target_col} over time ({freq_label})",
    )
    figures["main"] = _glassbox.execute(main_code, df)
    code["main"] = main_code

    if entity_col and entity_col in df.columns:
        entity_code = _glassbox.render(
            ENTITY_TEMPLATE,
            time_col=time_col,
            target_col=target_col,
            entity_col=entity_col,
            freq_alias=freq_alias,
            freq_label=_glassbox.Raw(freq_label),
            max_lines=MAX_ENTITY_LINES,
            title=(
                f"{target_col} over time by {entity_col} "
                f"(top {MAX_ENTITY_LINES} by volume)"
            ),
        )
        figures["by_entity"] = _glassbox.execute(entity_code, df)
        code["by_entity"] = entity_code

        n_categories = int(df[entity_col].nunique(dropna=True))
        if n_categories > MAX_ENTITY_LINES:
            warnings.append(
                f"{entity_col!r} has {n_categories} categories; the split chart "
                f"shows only the {MAX_ENTITY_LINES} most common."
            )

    observed = series.dropna()
    stats: Dict[str, Any] = {
        # Computed on the resampled series, not the raw rows, because that is
        # what the chart shows. Quoting a raw-row mean next to a weekly chart
        # invites the user to check one against the other and find they differ.
        "mean": round(float(observed.mean()), 4),
        "min": round(float(observed.min()), 4),
        "max": round(float(observed.max()), 4),
        "std": round(float(observed.std()), 4) if len(observed) > 1 else 0.0,
        "first_date": series.index.min().isoformat(),
        "last_date": series.index.max().isoformat(),
        "n_periods": int(len(series)),
        "n_periods_observed": int(len(observed)),
        "freq": freq,
        "n_rows_used": int(len(data)),
    }
    stats.update(_trend(series))

    return _glassbox.result(figures=figures, stats=stats, code=code, warnings=warnings)
