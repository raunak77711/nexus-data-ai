"""What-if endpoint: move a number, report what the data says would follow.

Two routes rather than one. GET /simulate/{sid}/options tells the UI what it may
offer -- which columns can be moved, which one to default to -- so the panel can
render its controls without running a projection nobody asked for. POST runs one.

core.simulate returns "unsupported" for a dataset that cannot carry a
projection, and that is a 200 rather than a 4xx: "these two columns do not move
together closely enough to predict one from the other" is an answer about the
data, not a complaint about the request. The frontend renders `message` either
way, so there is one path to write.
"""

from __future__ import annotations

import logging

import pandas as pd
from fastapi import APIRouter, HTTPException, status

from backend.models import SimulateOptions, SimulateRequest, SimulateResponse
from backend.routers._common import require_session
from core.simulate import options as simulate_options
from core.simulate import simulate as run_simulation

logger = logging.getLogger(__name__)

router = APIRouter(tags=["simulate"])


@router.get("/simulate/{sid}/options", response_model=SimulateOptions)
def get_options(sid: str) -> SimulateOptions:
    """What this dataset allows a what-if to move, and what to start from."""
    session = require_session(sid)
    return SimulateOptions(
        **simulate_options(session.df, session.profile, session.routing)
    )


@router.post("/simulate/{sid}", response_model=SimulateResponse)
def simulate(sid: str, request: SimulateRequest) -> SimulateResponse:
    """Project the effect of moving one measure by a percentage."""
    session = require_session(sid)

    try:
        result = run_simulation(
            session.df,
            session.profile,
            session.routing,
            pct_change=request.pct_change,
            target=request.target,
            driver=request.driver,
        )
    except (KeyError, IndexError, TypeError, ValueError, ArithmeticError,
            pd.errors.DataError) as exc:
        logger.exception("Simulation failed for session %s", sid)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="That projection could not be calculated. The error has been logged.",
        ) from exc

    return SimulateResponse(**result)
