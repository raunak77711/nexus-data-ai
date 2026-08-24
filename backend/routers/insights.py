"""Insights endpoint: what NEXUS found in the data, in plain language.

Computed once per session and cached, for two reasons. It walks the whole frame
several times, so recomputing on every visit to the Insights screen would make
navigating between screens feel slow for no gain -- and, more importantly, it is
a deterministic function of a frame that never changes, so a second computation
could only ever produce the same answer. A finding that changed between two
views of the same dataset would be a finding nobody could trust.
"""

from __future__ import annotations

import logging

import pandas as pd
from fastapi import APIRouter, HTTPException, status

from backend.models import InsightsResponse
from backend.routers._common import require_session
from backend.serialisation import jsonable
from core.insights import generate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["insights"])


@router.get("/insights/{sid}", response_model=InsightsResponse)
def get_insights(sid: str) -> InsightsResponse:
    """Analyse a session's dataset and return everything worth telling the user."""
    session = require_session(sid)

    if session.insights is None:
        try:
            result = generate(session.df, session.profile, session.routing)
        except (KeyError, IndexError, TypeError, ValueError, ArithmeticError,
                pd.errors.DataError) as exc:
            # core.insights already contains each analysis pass in its own
            # try/except so one failing pass cannot lose the others. Reaching
            # here means something outside those passes broke, which is our bug.
            logger.exception("Insight generation failed for session %s", sid)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "The dataset could not be analysed for insights. The error "
                    "has been logged."
                ),
            ) from exc

        # jsonable because insight evidence carries numbers straight out of
        # pandas, and a numpy scalar anywhere in that tree fails the response.
        session.insights = jsonable(result)

    return InsightsResponse(**session.insights)
