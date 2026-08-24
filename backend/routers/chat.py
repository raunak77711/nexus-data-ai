"""Chat endpoint: give core.chat a calculator, and pass its answer back.

This router stays deliberately thin. Everything that decides what the assistant
is allowed to know lives in core/chat.py; everything it is allowed to CALCULATE
lives in core/tools.py. What this file contributes is the binding between them:
two closures over the session's DataFrame, handed to core.chat as functions.

That binding is the whole point. core.chat has no DataFrame parameter and never
will -- it can ask for a calculation and read the result, and it cannot read a
row. The frame is in scope HERE, and reaches the assistant only as numbers that
pandas has already reduced.

Note what is read off the session directly: profile, routing, last_world_stats,
last_forecast. `session.df` is used solely to build the two closures below.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter

from backend.models import ChatRequest, ChatResponse
from backend.routers._common import require_session
from backend.serialisation import jsonable
from core import followup
from core.chat import answer as answer_question
from core.tools import catalogue as tool_catalogue
from core.tools import plan_from_keywords
from core.tools import run as run_tool

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


@router.post("/chat/{sid}", response_model=ChatResponse)
def chat(sid: str, request: ChatRequest) -> ChatResponse:
    """Answer a question about the session's dataset, computing where needed."""
    session = require_session(sid)

    def compute(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Run one calculation against this session's data.

        Returns core.tools.run's shape unchanged, including its failure shape --
        core.chat is written to read `ok` and to recover from a refusal, so
        swallowing one here would only hide information it needs.
        """
        return run_tool(session.df, session.profile, session.routing, tool, args)

    def plan_locally(question: str) -> Optional[Dict[str, Any]]:
        return plan_from_keywords(question, session.df, session.profile, session.routing)

    result = answer_question(
        message=request.message,
        profile=session.profile,
        routing=session.routing,
        history=[turn.model_dump() for turn in request.history],
        world_stats=session.last_world_stats,
        world_archetype=session.last_world_archetype,
        world_warnings=session.last_world_warnings,
        forecast=session.last_forecast,
        compute=compute,
        plan_locally=plan_locally,
        catalogue=tool_catalogue(session.df, session.profile),
    )

    # What to ask next. Computed after the answer rather than alongside it, and
    # wrapped, because a follow-up is a garnish: the user has already been given
    # a correct answer at this point, and no failure in suggesting a next
    # question may cost them that answer. core.followup is itself non-raising,
    # so this guard is for bugs in the binding rather than for its failures.
    try:
        suggestions = followup.suggest(
            request.message,
            result["reply"],
            session.profile,
            session.routing,
            tool=result.get("tool"),
        )
    except (ValueError, TypeError, KeyError):
        logger.exception("Follow-up suggestions failed for %s", sid)
        suggestions = []

    # core.chat.answer is contractually non-raising, so there is no try/except
    # here: adding one would only catch bugs in this file, and those should
    # reach main.py's handler and be logged with a traceback rather than being
    # swallowed into a friendly message.
    #
    # jsonable() on the computed payloads because they come straight out of
    # pandas and a numpy scalar anywhere in that tree would fail the response.
    return ChatResponse(
        reply=result["reply"],
        grounded_on=result["grounded_on"],
        available=result["available"],
        answered_by=result["answered_by"],
        tool=result.get("tool"),
        action=result.get("action"),
        table=jsonable(result.get("table")) if result.get("table") else None,
        data=jsonable(result.get("data")) if result.get("data") else None,
        followups=suggestions,
    )
