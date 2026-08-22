"""Turn core/'s Python objects into things json.dumps() will actually accept.

This module exists because the boundary between pandas and JSON is where a
FastAPI port of a pandas app silently breaks, and it breaks in a way that is
easy to miss in a demo:

  * numpy scalars are not JSON-serialisable. ``np.int64(5)`` is not an ``int``
    as far as the stdlib encoder is concerned, and pandas returns numpy scalars
    from a great many operations -- ``.sum()``, ``.nunique()``, ``.value_counts()``
    items, ``.describe()`` values. core/ is careful to cast, but core/ produces
    nested dicts whose leaves come from several different code paths, and one
    uncast leaf anywhere in the tree fails the whole response.
  * ``float('nan')`` and ``float('inf')`` ARE accepted by ``json.dumps`` by
    default, which is worse than being rejected: it emits the bare tokens
    ``NaN`` and ``Infinity``, which are not valid JSON and which
    ``JSON.parse`` in the browser rejects with a syntax error pointing at a
    character offset in a 200KB payload. They are mapped to null here.
  * a plotly ``Figure`` is not data at all; it has to be handed over as the JSON
    string ``fig.to_json()`` produces, because that is the exact format
    plotly.js consumes on the other side.
  * a DataFrame has no natural JSON form, and the interesting part of core.ml's
    forecast frames is the *index* (the dates), which every generic converter
    throws away.

Everything here is deliberately defensive rather than clever: it is cheaper to
walk a small result dict once than to debug a 500 in front of an examiner.
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Dict, List, Mapping, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go


def jsonable(value: Any) -> Any:
    """Recursively convert a value into JSON-safe plain Python.

    The order of the checks matters. numpy bool_ is tested before the numpy
    integer branch because ``np.bool_`` satisfies neither ``bool`` nor
    ``np.integer`` reliably across versions, and Python ``bool`` is tested
    before ``int`` because ``isinstance(True, int)`` is True and turning a flag
    into ``1`` would quietly change the frontend's rendering.

    Non-finite floats become ``None``: see the module docstring for why letting
    them through is the more dangerous option.
    """
    # Scalars that are already fine.
    if value is None or isinstance(value, (str, bool)):
        return value

    # numpy scalar types, before their Python lookalikes.
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return jsonable(float(value))

    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value

    # Missing values in all their pandas guises. pd.isna on a scalar is the one
    # call that handles None, nan, NaT and pd.NA uniformly.
    if value is pd.NaT or value is pd.NA:
        return None

    # Timestamps -> ISO 8601 strings, which is the one datetime format every
    # JavaScript Date parser agrees on.
    if isinstance(value, (pd.Timestamp, _dt.datetime, _dt.date)):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, pd.Timedelta):
        return value.isoformat()

    if isinstance(value, np.ndarray):
        return [jsonable(v) for v in value.tolist()]

    if isinstance(value, pd.Series):
        return [jsonable(v) for v in value.tolist()]

    if isinstance(value, pd.DataFrame):
        return frame_to_records(value)

    if isinstance(value, go.Figure):
        # A Figure has no place inside a data dict -- it belongs in
        # figures_json. Reaching here means a world builder put one somewhere
        # unexpected, and failing loudly beats emitting a giant nested blob.
        raise TypeError("plotly Figure must be serialised via figures_to_json, not jsonable")

    if isinstance(value, Mapping):
        # Keys are coerced to str because JSON object keys must be strings and
        # pandas hands back numpy scalars as dict keys from value_counts().
        return {str(k): jsonable(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in value]

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [jsonable(v) for v in value]

    # Anything left is something core/ was not expected to produce. Stringify
    # rather than raise: a slightly ugly value in one field is a better outcome
    # for the user than a 500 that loses the entire world.
    return str(value)


def frame_to_records(
    df: pd.DataFrame,
    index_name: str = "date",
) -> List[Dict[str, Any]]:
    """Flatten a DataFrame into row dicts, keeping the index as a named field.

    WHY the index is promoted to a column rather than dropped: core.ml.forecast
    returns ``predictions`` and ``future`` indexed by date, and the dates are
    the x axis of the chart the frontend has to draw. ``df.to_dict('records')``
    on its own throws them away and produces a chart plotted against row number.

    A DatetimeIndex is rendered as an ISO string; any other index is rendered
    through ``jsonable``, so an integer index survives as an integer.
    """
    if df is None or df.empty:
        return []

    records: List[Dict[str, Any]] = []
    is_datetime_index = isinstance(df.index, pd.DatetimeIndex)

    for idx, row in zip(df.index, df.to_dict("records")):
        record: Dict[str, Any] = {
            index_name: idx.isoformat() if is_datetime_index else jsonable(idx)
        }
        for key, val in row.items():
            record[str(key)] = jsonable(val)
        records.append(record)
    return records


def figures_to_json(figures: Mapping[str, go.Figure]) -> Dict[str, str]:
    """Convert ``{name: Figure}`` into ``{name: json_string}``.

    ``fig.to_json()`` and not ``fig.to_dict()``: plotly's own encoder knows how
    to render numpy arrays, datetime axes and colour scales in the exact shape
    plotly.js expects, and re-implementing that through a generic dict walk is a
    guaranteed source of subtly broken charts. The frontend does one
    ``JSON.parse`` and spreads ``data`` and ``layout`` straight into
    ``<Plot />``.

    The value is a *string*, not a nested object. That is intentional: it keeps
    the figure opaque to the response model (no attempt to validate plotly's
    schema in pydantic) and it keeps the round trip lossless.
    """
    return {str(name): fig.to_json() for name, fig in figures.items()}


def world_to_payload(world: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a core.worlds ``build()`` result into a JSON-safe response body.

    The shared world contract (figures/stats/code/warnings/status/message) is
    the same for all three archetypes, so this one function serves all of them --
    which is the payoff for core/ having agreed on a single return shape.
    """
    return {
        "figures_json": figures_to_json(world.get("figures") or {}),
        "stats": jsonable(world.get("stats") or {}),
        "code": {str(k): str(v) for k, v in (world.get("code") or {}).items()},
        "warnings": [str(w) for w in (world.get("warnings") or [])],
        "status": str(world.get("status", "ok")),
        "message": str(world.get("message", "")),
    }


def forecast_to_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a core.ml.forecast result into a JSON-safe response body.

    The two DataFrames are handled explicitly rather than by the generic walker
    so that the field names in the emitted records are the ones the frontend
    charts against: ``date``/``actual``/``predicted`` for the scored window, and
    ``date``/``predicted`` for the projection.
    """
    status = str(result.get("status", "ok"))
    payload: Dict[str, Any] = {
        "status": status,
        "message": str(result.get("message", "")),
        "warnings": [str(w) for w in (result.get("warnings") or [])],
        "metrics": jsonable(result.get("metrics") or {}),
        "beats_baseline": bool(result.get("beats_baseline", False)),
        "verdict": str(result.get("verdict", "")),
        "predictions": frame_to_records(result.get("predictions")),
        "future": frame_to_records(result.get("future")),
        "feature_importances": jsonable(result.get("feature_importances") or {}),
        "code": str(result.get("code", "")),
    }
    return payload
