"""Routing endpoint: report the archetype decision made at upload time.

This is a read of cached state, not a recomputation. Routing is deterministic
given the profile and may have cost an LLM call, so calling route() again here
would spend money and latency to produce -- at best -- the same answer, and at
worst a *different* one, which would leave the banner disagreeing with the world
that was already built.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.models import RouteResponse
from backend.routers._common import require_session

router = APIRouter(tags=["route"])


@router.get("/route/{sid}", response_model=RouteResponse)
def get_route(sid: str) -> RouteResponse:
    """Return the full routing dict for a session, including which path decided it."""
    session = require_session(sid)
    return RouteResponse(**session.routing)
