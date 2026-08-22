"""Chat endpoint: pass the session's cached summaries to core.chat and return its answer.

This router is deliberately almost empty. Everything that decides what the
assistant is allowed to know lives in core/chat.py, so the guarantee ("the model
never sees a row") is enforced by a function signature that has no parameter for
one -- not by this file remembering to filter something out.

Note what is read off the session: profile, routing, last_world_stats,
last_forecast. `session.df` is in scope here and is deliberately never touched.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from backend.models import ChatRequest, ChatResponse
from backend.routers._common import require_session
from core.chat import answer as answer_question

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


@router.post("/chat/{sid}", response_model=ChatResponse)
def chat(sid: str, request: ChatRequest) -> ChatResponse:
    """Answer a question about the session's dataset from computed summaries only."""
    session = require_session(sid)

    result = answer_question(
        message=request.message,
        profile=session.profile,
        routing=session.routing,
        history=[turn.model_dump() for turn in request.history],
        world_stats=session.last_world_stats,
        world_archetype=session.last_world_archetype,
        world_warnings=session.last_world_warnings,
        forecast=session.last_forecast,
    )

    # core.chat.answer is contractually non-raising, so there is no try/except
    # here: adding one would only catch bugs in this file, and those should
    # reach main.py's handler and be logged with a traceback rather than being
    # swallowed into a friendly message.
    return ChatResponse(
        reply=result["reply"],
        grounded_on=result["grounded_on"],
        available=result["available"],
    )
