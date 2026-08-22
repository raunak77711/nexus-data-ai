"""Geo world: where things are, and how big the measure is there.

Same figures/stats/code contract as the other worlds. The map uses plotly's
scatter_map (MapLibre) with the open-street-map raster style, which needs no
Mapbox token -- a deliberate constraint: the app has to run for a marker who
clones the repo and has no third-party account to sign up for. The older
scatter_mapbox is avoided because plotly has deprecated the whole mapbox family
in favour of these map_* traces.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from core.worlds import _glassbox

# Used when the bounding box has no extent -- one point, or many points at the
# same coordinate. See _fit_view for why that case cannot be computed.
DEFAULT_ZOOM = 10.0

# Web-mercator tile zoom is bounded in practice; past ~18 OSM has no tiles and
# below 0 the world repeats. Clamping keeps a pathological bounding box from
# producing a map that renders as grey.
MIN_ZOOM = 0.0
MAX_ZOOM = 16.0

# Leave the extreme points off the edge of the viewport rather than exactly on
# it. One zoom level is a factor of two, so 0.4 is a modest visual margin.
ZOOM_PADDING = 0.4

# Grid size for the densest-cluster stat, in degrees. 0.1 deg is roughly 11 km
# of latitude -- city-scale, which is the resolution at which "where is the
# cluster" is a useful answer rather than either one point or one continent.
CLUSTER_GRID_DEG = 0.1

# Marker radius bounds in pixels. Below ~5 a point is hard to see on a busy
# basemap; above ~26 large values swamp their neighbours entirely.
MIN_MARKER_PX = 5
MAX_MARKER_PX = 26


def _fail(message: str, warnings: List[str]) -> Dict[str, Any]:
    """Shorthand for the 'cannot build this world' return."""
    return _glassbox.result(status="insufficient_data", message=message, warnings=warnings)


def _fit_view(lats: pd.Series, lons: pd.Series) -> Tuple[Dict[str, float], float]:
    """Derive map centre and zoom from the coordinate bounds.

    WHY computed rather than hardcoded: a hardcoded centre is right for exactly
    one dataset. Air-quality sensors in Scotland and delivery drops in Singapore
    are the same archetype, and a fixed view would open one of them on an empty
    ocean.

    The zoom formula inverts web mercator's tile scheme: at zoom z the visible
    world spans 360/2^z degrees of longitude, so the zoom that just fits a span
    s is log2(360/s). The same is done for latitude against 180 degrees and the
    smaller (further out) of the two is taken, because the view must contain
    both extents -- fitting longitude alone would crop a tall, narrow dataset.

    WHY a special case for zero extent: with one point, or many points at an
    identical coordinate, the span is 0 and log2(360/0) is infinite. There is no
    correct answer -- a single point carries no information about how much
    context to show -- so DEFAULT_ZOOM picks a sensible city-level view instead
    of crashing or handing plotly a NaN.
    """
    lat_span = float(lats.max() - lats.min())
    lon_span = float(lons.max() - lons.min())
    centre = {"lat": float(lats.mean()), "lon": float(lons.mean())}

    if lat_span <= 0 and lon_span <= 0:
        return centre, DEFAULT_ZOOM

    candidates = []
    if lon_span > 0:
        candidates.append(math.log2(360.0 / lon_span))
    if lat_span > 0:
        candidates.append(math.log2(180.0 / lat_span))

    zoom = min(candidates) - ZOOM_PADDING
    return centre, round(max(MIN_ZOOM, min(MAX_ZOOM, zoom)), 2)


def _densest_cluster(lats: pd.Series, lons: pd.Series) -> Optional[Dict[str, Any]]:
    """Find the busiest ~11km grid cell, or None if nothing repeats.

    WHY a rounding grid rather than DBSCAN or k-means: this is a supporting
    statistic, not the point of the world. Rounding to CLUSTER_GRID_DEG and
    taking the modal cell is a single groupby -- O(n), no parameters to tune,
    no distance matrix -- and answers the question a user actually asks ("where
    are most of them?") well enough. A real clustering algorithm would be more
    accurate about cluster shape and would also need a tuned epsilon, which is
    exactly the sort of hidden knob that makes a result hard to defend.

    Returns None when no cell holds more than one point, because "the densest
    cluster has one point in it" is noise dressed as a finding.
    """
    cells = pd.DataFrame({
        "lat_cell": (lats / CLUSTER_GRID_DEG).round() * CLUSTER_GRID_DEG,
        "lon_cell": (lons / CLUSTER_GRID_DEG).round() * CLUSTER_GRID_DEG,
    })
    counts = cells.value_counts()
    if counts.empty or int(counts.iloc[0]) < 2:
        return None

    (lat_cell, lon_cell) = counts.index[0]
    return {
        "lat": round(float(lat_cell), 4),
        "lon": round(float(lon_cell), 4),
        "n_points": int(counts.iloc[0]),
        "grid_degrees": CLUSTER_GRID_DEG,
    }


MAP_TEMPLATE = """
import pandas as pd
import plotly.express as px

data = df[$columns].copy()
data[$lat_col] = pd.to_numeric(data[$lat_col], errors='coerce')
data[$lon_col] = pd.to_numeric(data[$lon_col], errors='coerce')
data[$target_col] = pd.to_numeric(data[$target_col], errors='coerce')

# A point with no coordinate cannot be placed at all, so those rows are dropped.
# A point with a coordinate but no measure could still be drawn, but it would be
# an unsized, uncoloured marker sitting among sized ones -- visually it would
# read as "small value" rather than "no value", so it is dropped too.
data = data.dropna(subset=[$lat_col, $lon_col, $target_col])
$time_filter_block
# Marker area encodes the measure, but plotly needs a non-negative size column
# and a raw target can be negative (a temperature anomaly, a net change). Rescale
# into a fixed pixel band instead: this keeps every point visible and makes the
# size scale comparable across datasets. A flat target (span 0) gets a constant
# mid-size, because scaling a constant is a division by zero.
span = data[$target_col].max() - data[$target_col].min()
if span > 0:
    normalised = (data[$target_col] - data[$target_col].min()) / span
    data['marker_size'] = $min_px + ($max_px - $min_px) * normalised
else:
    data['marker_size'] = ($min_px + $max_px) / 2

fig = px.scatter_map(
    data,
    lat=$lat_col,
    lon=$lon_col,
    color=$target_col,
    size='marker_size',
    size_max=$max_px,
    hover_name=$hover_name,
    hover_data=$hover_data,
    color_continuous_scale='Viridis',
    # Centre and zoom are derived from this data's own bounding box, not
    # hardcoded -- see core/worlds/geo.py::_fit_view for the mercator maths.
    center={'lat': $center_lat, 'lon': $center_lon},
    zoom=$zoom,
    # open-street-map raster tiles need no access token, so the app runs for
    # anyone who clones the repo.
    map_style='open-street-map',
    title=$title,
)
fig.update_layout(margin={'l': 0, 'r': 0, 't': 40, 'b': 0})
"""

# Applied inside MAP_TEMPLATE when a time filter is active. Kept as its own
# fragment so the snippet a user sees contains the filter only when one really
# ran -- dead code in a glass box is as misleading as missing code.
TIME_FILTER_BLOCK = """
# Restrict to the selected window before plotting.
data[$time_col] = pd.to_datetime(data[$time_col], errors='coerce', format='mixed')
data = data.dropna(subset=[$time_col])
data = data[(data[$time_col] >= pd.Timestamp($start)) & (data[$time_col] <= pd.Timestamp($end))]
"""


def build(
    df: pd.DataFrame,
    routing: Dict[str, Any],
    time_filter: Optional[Tuple[Any, Any]] = None,
) -> Dict[str, Any]:
    """Build the geo world for a routed DataFrame.

    Args:
        df: the uploaded data, unmodified.
        routing: output of core.router.route -- lat_col, lon_col and target_col
            are required; entity_col and time_col are optional.
        time_filter: (start, end) inclusive, applied only when routing carries a
            time_col. Anything pd.Timestamp accepts will do.

    Returns:
        The shared world dict (figures/stats/code/warnings/status/message).

    Raises:
        ValueError: if time_filter is given but is not a 2-tuple. Like the
            timeseries frequency, this value comes from the app's own controls,
            so a malformed one is a caller bug worth surfacing loudly.
    """
    if time_filter is not None and len(tuple(time_filter)) != 2:
        raise ValueError(f"time_filter must be a (start, end) pair, got {time_filter!r}")

    lat_col = routing.get("lat_col")
    lon_col = routing.get("lon_col")
    target_col = routing.get("target_col")
    entity_col = routing.get("entity_col")
    time_col = routing.get("time_col")
    warnings: List[str] = []

    for label, col in (("latitude", lat_col), ("longitude", lon_col)):
        if not col or col not in df.columns:
            return _fail(f"No {label} column, so there is nothing to put on a map.", warnings)
    if not target_col or target_col not in df.columns:
        return _fail("No numeric column to colour and size the points by.", warnings)

    # Reproduce the snippet's cleaning here so the stats describe exactly the
    # points the figure shows. Doing this twice is the price of the code string
    # being self-contained enough to paste into a notebook; the alternative --
    # a snippet that calls back into this package -- would not be runnable
    # anywhere but inside this repo, which defeats the purpose.
    data = df.copy()
    for col in (lat_col, lon_col, target_col):
        data[col] = pd.to_numeric(data[col], errors="coerce")

    n_before = len(data)
    missing_coords = int(data[[lat_col, lon_col]].isna().any(axis=1).sum())
    data = data.dropna(subset=[lat_col, lon_col, target_col])
    if missing_coords:
        warnings.append(
            f"{missing_coords} of {n_before} rows had a missing or non-numeric "
            f"coordinate and could not be placed on the map."
        )

    filter_active = bool(time_filter and time_col and time_col in df.columns)
    if time_filter and not filter_active:
        warnings.append("A time filter was supplied but this dataset has no date column.")

    if filter_active:
        stamps = pd.to_datetime(data[time_col], errors="coerce", format="mixed")
        start, end = pd.Timestamp(time_filter[0]), pd.Timestamp(time_filter[1])
        n_pre_filter = len(data)
        data = data[stamps.notna() & (stamps >= start) & (stamps <= end)]
        warnings.append(
            f"Time filter {start.date()} to {end.date()} kept {len(data)} of "
            f"{n_pre_filter} placeable points."
        )

    if data.empty:
        return _fail(
            "No rows have a usable coordinate and measure"
            + (" inside the selected time window." if filter_active else "."),
            warnings,
        )

    lats, lons = data[lat_col], data[lon_col]
    centre, zoom = _fit_view(lats, lons)
    if zoom == DEFAULT_ZOOM and float(lats.max() - lats.min()) <= 0 and float(
        lons.max() - lons.min()
    ) <= 0:
        warnings.append(
            "Every point shares one coordinate, so the map is opened at a default "
            "zoom rather than fitted to a bounding box with no extent."
        )

    # hover_name is the label at the top of the tooltip. The entity is the more
    # human-readable identity ("Camden", "Sensor B") so it takes that slot when
    # one exists; without it the coordinate itself is the only identity there is.
    hover_name = entity_col if entity_col and entity_col in df.columns else lat_col
    hover_data = [target_col]
    if time_col and time_col in df.columns:
        hover_data.append(time_col)

    extra_columns = sorted({hover_name, *hover_data} - {lat_col, lon_col, target_col})
    if filter_active and time_col not in extra_columns:
        extra_columns.append(time_col)

    time_filter_block = ""
    if filter_active:
        time_filter_block = _glassbox.render(
            TIME_FILTER_BLOCK,
            time_col=time_col,
            start=str(pd.Timestamp(time_filter[0])),
            end=str(pd.Timestamp(time_filter[1])),
        )

    code = _glassbox.render(
        MAP_TEMPLATE,
        lat_col=lat_col,
        lon_col=lon_col,
        target_col=target_col,
        columns=[lat_col, lon_col, target_col] + extra_columns,
        time_filter_block=_glassbox.Raw(
            f"\n{time_filter_block}\n" if time_filter_block else ""
        ),
        min_px=MIN_MARKER_PX,
        max_px=MAX_MARKER_PX,
        hover_name=hover_name,
        hover_data=hover_data,
        center_lat=round(centre["lat"], 6),
        center_lon=round(centre["lon"], 6),
        zoom=zoom,
        title=f"{target_col} by location",
    )
    figure = _glassbox.execute(code, df)

    stats: Dict[str, Any] = {
        "n_points": int(len(data)),
        "n_rows_dropped": int(n_before - len(data)),
        "bounds": {
            "lat_min": round(float(lats.min()), 6),
            "lat_max": round(float(lats.max()), 6),
            "lon_min": round(float(lons.min()), 6),
            "lon_max": round(float(lons.max()), 6),
        },
        "center": {"lat": round(centre["lat"], 6), "lon": round(centre["lon"], 6)},
        "zoom": zoom,
        "target_col": target_col,
        "target_min": round(float(data[target_col].min()), 4),
        "target_max": round(float(data[target_col].max()), 4),
        "target_mean": round(float(data[target_col].mean()), 4),
        "densest_cluster": _densest_cluster(lats, lons),
        "time_filter_applied": filter_active,
    }

    return _glassbox.result(
        figures={"map": figure}, stats=stats, code={"map": code}, warnings=warnings
    )
