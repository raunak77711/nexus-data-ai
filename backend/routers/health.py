"""Liveness endpoint.

Reports the live session count as well as a status, because "the server is up"
and "the server still remembers my upload" are different questions and the
frontend needs an answer to the first one before it can explain the second.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend import __version__
from backend.models import HealthResponse
from backend.session import store

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report that the API is reachable, and how many sessions it holds."""
    return HealthResponse(status="ok", version=__version__, sessions=store.count())
