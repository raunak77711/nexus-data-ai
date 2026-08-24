"""Chart endpoint: render one visual component from a structured spec.

This is the endpoint the insight cards and the assistant point at. What arrives
is a small dict naming a chart type and some columns -- never code, never an
expression -- and core.charts validates every field of it against the session's
frame before anything runs. See that module for why the shape of this feature is
"a whitelist the model configures" rather than "code the model writes".

The response carries the Python that produced the figure, the same way every
world does. A chart that appeared because an assistant suggested it should be no
harder to check than one the app built at upload time.
"""

from __future__ import annotations

import logging

import pandas as pd
from fastapi import APIRouter, HTTPException, status

from backend.models import ChartRequest, ChartResponse
from backend.routers._common import require_session
from backend.serialisation import jsonable
from core.charts import ChartError, build_chart

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chart"])


@router.post("/chart/{sid}", response_model=ChartResponse)
def make_chart(sid: str, request: ChartRequest) -> ChartResponse:
    """Build one figure from a validated chart spec."""
    session = require_session(sid)

    try:
        built = build_chart(session.df, request.model_dump(exclude_none=True))
    except ChartError as exc:
        # The spec named something the dataset does not have. That is a bad
        # request, and the message already says which field was wrong in words
        # the UI can render unmodified.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except (KeyError, IndexError, TypeError, RuntimeError, ArithmeticError,
            pd.errors.DataError) as exc:
        logger.exception("Chart build failed for session %s (%s)", sid, request.chart)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "That chart could not be drawn from this dataset. The error has "
                "been logged."
            ),
        ) from exc

    return ChartResponse(
        figure_json=built["figure"].to_json(),
        code=built["code"],
        title=built["title"],
        spec=jsonable(built["spec"]),
        warnings=built["warnings"],
    )
