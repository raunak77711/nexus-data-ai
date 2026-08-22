"""World building: dispatch to a core.worlds builder and serialise what it returns.

The archetype comes from the *request*, not from the session's routing, so the
UI's manual override works without a second endpoint. The routed archetype is
still the default the frontend sends; overriding it is a deliberate user action
and the worlds are built to cope -- forcing "timeseries" onto a dataset with no
date column returns status "insufficient_data" with an explanation, which is a
better answer than refusing the request.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import pandas as pd
from fastapi import APIRouter, HTTPException, status

from backend.models import WorldRequest, WorldResponse
from backend.routers._common import require_session
from backend.serialisation import world_to_payload
from core.worlds import geo, tabular, timeseries

logger = logging.getLogger(__name__)

router = APIRouter(tags=["world"])

# Defaults live here rather than in the pydantic model so that "the client sent
# no freq" and "the client sent freq=D" stay distinguishable in the request, and
# so the defaults match core/'s own signatures in one obvious place.
DEFAULT_FREQ = "D"
DEFAULT_ROLLING_WINDOW = 7


def _build(
    archetype: str,
    df: pd.DataFrame,
    routing: Dict[str, Any],
    params: Any,
) -> Dict[str, Any]:
    """Call the right builder with only the parameters that builder understands.

    Filtering parameters per archetype rather than passing **params to every
    builder means an irrelevant control left over in the UI state (a rolling
    window still set from a previous timeseries view) cannot reach the geo
    builder and raise a TypeError about an unexpected keyword.
    """
    if archetype == "timeseries":
        return timeseries.build(
            df,
            routing,
            freq=params.freq or DEFAULT_FREQ,
            rolling_window=(
                params.rolling_window
                if params.rolling_window is not None
                else DEFAULT_ROLLING_WINDOW
            ),
        )

    if archetype == "geo":
        time_filter = None
        if params.time_filter:
            try:
                start, end = (pd.Timestamp(v) for v in params.time_filter)
            except (ValueError, TypeError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"time_filter values must be parseable dates: {exc}",
                ) from exc
            if start > end:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="time_filter start must not be after end.",
                )
            time_filter = (start, end)
        return geo.build(df, routing, time_filter=time_filter)

    return tabular.build(df, routing)


@router.post("/world/{sid}", response_model=WorldResponse)
def build_world(sid: str, request: WorldRequest) -> WorldResponse:
    """Build one world for a session and return its figures, stats and code."""
    session = require_session(sid)

    # A shallow copy so an override never mutates the cached routing -- the
    # banner must keep showing what the router actually decided, even while the
    # user is looking at a world they forced by hand.
    routing = dict(session.routing)
    routing["archetype"] = request.archetype

    try:
        world = _build(request.archetype, session.df, routing, request.params)
    except HTTPException:
        raise
    except ValueError as exc:
        # core/'s builders raise ValueError for an out-of-range control value.
        # The pydantic model catches the ranges it knows about; this covers a
        # constraint that lives in core/ and is therefore the client's fault.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except (KeyError, IndexError, TypeError, RuntimeError, ArithmeticError,
            pd.errors.DataError, pd.errors.IndexingError) as exc:
        # A template or data condition core/ did not anticipate. Logged with the
        # traceback server-side; the client gets one sentence and no internals.
        logger.exception("World build failed for session %s (%s)", sid, request.archetype)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"The {request.archetype} world could not be built from this "
                f"dataset. The error has been logged."
            ),
        ) from exc

    payload = world_to_payload(world)

    # Cached for the chat assistant, which is grounded on computed context and
    # must never recompute anything itself. Only a successful build is stored:
    # grounding an answer on the stats of a world that failed would be worse
    # than having no stats at all.
    if payload["status"] == "ok":
        session.last_world_stats = payload["stats"]
        session.last_world_archetype = request.archetype
        session.last_world_warnings = payload["warnings"]

    return WorldResponse(archetype=request.archetype, **payload)
