"""Forecast endpoint: run core.ml.forecast and flatten its DataFrames for the wire.

The forecast is deliberately a separate endpoint rather than part of /world,
even though it only applies to timeseries data. It costs a model fit -- orders
of magnitude more than drawing a chart -- and most of the time the user is
adjusting a frequency control rather than asking for a prediction. Making it
explicit means the expensive thing happens when, and only when, it was asked for.
"""

from __future__ import annotations

import logging

import pandas as pd
from fastapi import APIRouter, HTTPException, status

from backend.models import ForecastRequest, ForecastResponse
from backend.routers._common import require_session
from backend.serialisation import forecast_to_payload
from core.ml import forecast as run_forecast

logger = logging.getLogger(__name__)

router = APIRouter(tags=["forecast"])


@router.post("/forecast/{sid}", response_model=ForecastResponse)
def make_forecast(sid: str, request: ForecastRequest) -> ForecastResponse:
    """Fit a forecast for a session, scored against the naive baseline."""
    session = require_session(sid)
    time_col = session.routing.get("time_col")
    target_col = session.routing.get("target_col")

    # Missing columns are an ordinary property of an uploaded file, not a client
    # error, so this is a 200 carrying an explanation rather than a 4xx. The
    # frontend renders `message` in both cases, so there is one path to write.
    if not time_col or not target_col:
        return ForecastResponse(
            status="insufficient_data",
            message=(
                "This dataset has no date column and numeric measure pair, so "
                "there is no series to forecast."
            ),
            warnings=[],
            metrics={},
            beats_baseline=False,
            verdict="",
            predictions=[],
            future=[],
            feature_importances={},
            code="",
        )

    try:
        result = run_forecast(
            session.df, time_col=time_col, target_col=target_col, horizon=request.horizon
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except (KeyError, IndexError, TypeError, RuntimeError, ArithmeticError,
            pd.errors.DataError) as exc:
        logger.exception("Forecast failed for session %s", sid)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The forecast could not be fitted for this dataset. The error has been logged.",
        ) from exc

    payload = forecast_to_payload(result)

    # Cached for the chat assistant. Only the metrics and the verdict are kept,
    # not the prediction rows: chat is grounded on summaries by design, and
    # handing it 200 dated predictions would be handing it exactly the kind of
    # row-level detail it is built never to see.
    if payload["status"] == "ok":
        session.last_forecast = {
            "metrics": payload["metrics"],
            "beats_baseline": payload["beats_baseline"],
            "verdict": payload["verdict"],
            "feature_importances": payload["feature_importances"],
            "horizon_days": request.horizon,
            "warnings": payload["warnings"],
        }

    return ForecastResponse(**payload)
