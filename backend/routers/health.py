"""Liveness endpoint.

Reports the live session count as well as a status, because "the server is up"
and "the server still remembers my upload" are different questions and the
frontend needs an answer to the first one before it can explain the second.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend import __version__
from backend.models import AssistantStatus, HealthResponse
from backend.session import store
from core import llm

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report that the API is reachable, what it holds, and whether AI is on."""
    return HealthResponse(
        status="ok",
        version=__version__,
        sessions=store.count(),
        # A local check, not a ping: core.llm.status() reads configuration only.
        # Health is polled repeatedly by every open tab, and a probe of a paid
        # third-party API on each one would be a bill and a rate limit rather
        # than a health check.
        assistant=AssistantStatus(**llm.status()),
    )
