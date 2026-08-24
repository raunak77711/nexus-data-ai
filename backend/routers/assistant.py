"""The chat bubble's endpoint: one door, two assistants behind it.

The user sees a single chat window that follows them from the home page into
their results. Behind it are two very different answerers, and this router is
what chooses between them:

    core.chat   -- questions ABOUT THE DATA. Picks a calculation, runs it over
                   the real rows with pandas, and only then lets a model write
                   the sentence around the numbers. Refuses rather than guesses.
    core.guide  -- questions ABOUT THE APP. "What is a CSV?", "what do I do
                   now?", "is my file private?". Warm, brief, and structurally
                   incapable of stating a fact about the data.

WHY NOT JUST ONE
----------------
Because the rules that make core.chat trustworthy make it useless as an
onboarding helper. Asked "what do I do next?", a grounded assistant correctly
observes that no calculation applies and says so -- which is the right answer
to the wrong question, and reads to a beginner as a broken chatbot. And the
reverse is worse: a chatty helper asked "what were total sales?" would happily
produce a plausible number nobody computed.

HOW THE CHOICE IS MADE, AND WHY IT IS NOT A MODEL CALL
------------------------------------------------------
Classifying with a model would mean an extra round trip on every message, paid
for on every question, to decide something two cheap local signals already
decide well:

  1. Does the keyword planner recognise a calculation in the question? That is
     core.tools.plan_from_keywords, which already exists, runs locally in
     microseconds and returns None for anything it does not recognise.
  2. Does the question name one of the dataset's own columns?

Either is enough to send it to the calculator. Neither, and it goes to the
guide -- which is given the file's shape anyway, so "what do I do next?" gets
an answer that knows what the user has open.

Getting the choice wrong is not costly in either direction, which is what makes
a heuristic the right tool. A data question sent to the guide comes back with
"ask me directly and NEXUS will work it out from your rows"; an app question
sent to the calculator falls through to its own summaries path. Neither
fabricates.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from backend.models import AssistantRequest, AssistantResponse
from backend.serialisation import jsonable
from backend.session import Session, store
from core.chat import answer as answer_about_data
from core.guide import answer as answer_about_app
from core.tools import catalogue as tool_catalogue
from core.tools import plan_from_keywords
from core.tools import run as run_tool

logger = logging.getLogger(__name__)

router = APIRouter(tags=["assistant"])

# Phrases that are about the APP even when they happen to contain a column
# name. "How do I upload my revenue file" mentions `revenue` and is not a
# question about revenue. Checked first, so an explicit request for help is
# never routed into the calculator.
HELP_PATTERN = re.compile(
    r"\b(how (do|can|would) i|what (do|should) i do|what is this|what can you do|"
    r"help me|get started|getting started|how does (this|it) work|what next|"
    r"now what|where do i|is (this|my data|it) (safe|private|secure)|"
    r"what (kind of |type of )?files?|csv|excel|upload|sign ?up|account|cost|free)\b",
    re.IGNORECASE,
)


def _mentions_a_column(message: str, session: Session) -> bool:
    """Does the question name one of this dataset's columns?

    Matched on word boundaries with underscores treated as spaces, so a
    question asking about "order date" finds the `order_date` column. Columns
    shorter than three characters are skipped: a column called "id" or "x"
    would otherwise match inside ordinary English and send every message to the
    calculator.
    """
    text = re.sub(r"[_\s]+", " ", message.lower())
    for column in session.df.columns:
        name = re.sub(r"[_\s]+", " ", str(column).lower()).strip()
        if len(name) < 3:
            continue
        if re.search(rf"\b{re.escape(name)}\b", text):
            return True
    return False


def _is_about_the_data(message: str, session: Session) -> bool:
    """Route this message to the calculator rather than to the guide?"""
    if HELP_PATTERN.search(message):
        return False
    if _mentions_a_column(message, session):
        return True
    # plan_from_keywords is the same planner core.chat falls back to when no
    # model is available, so agreeing with it here means the two never disagree
    # about whether a question is answerable by a calculation.
    return plan_from_keywords(message, session.df, session.profile, session.routing) is not None


def _dataset_note(session: Optional[Session]) -> Optional[Dict[str, Any]]:
    """What the guide is allowed to know about the open file.

    Shape, column NAMES, and the routing decision's own plain-language
    reasoning. No values: a name is already on the user's screen, and the
    reasoning is the app explaining a choice it made rather than a fact about
    the data. Anything drawn from the rows goes to core.chat instead.
    """
    if session is None:
        return None
    return {
        "filename": session.filename,
        "n_rows": int(len(session.df)),
        "n_cols": int(len(session.df.columns)),
        "columns": [str(c) for c in session.df.columns],
        "chart_reason": (session.routing or {}).get("reasoning"),
    }


@router.post("/assistant", response_model=AssistantResponse)
def assistant(request: AssistantRequest) -> AssistantResponse:
    """Answer one message from the chat bubble, with or without a dataset.

    Note there is no `require_session` here and no 404. This endpoint is
    reachable from the home page, where by definition there is no session, and
    an expired session must degrade to app help rather than to an error --
    somebody whose upload has just timed out is exactly the person who needs
    the helper to still work.
    """
    session = store.get(request.session_id) if request.session_id else None
    history: List[Dict[str, str]] = [turn.model_dump() for turn in request.history]

    if session is not None and _is_about_the_data(request.message, session):
        result = answer_about_data(
            message=request.message,
            profile=session.profile,
            routing=session.routing,
            history=history,
            world_stats=session.last_world_stats,
            world_archetype=session.last_world_archetype,
            world_warnings=session.last_world_warnings,
            forecast=session.last_forecast,
            compute=lambda tool, args: run_tool(
                session.df, session.profile, session.routing, tool, args
            ),
            plan_locally=lambda question: plan_from_keywords(
                question, session.df, session.profile, session.routing
            ),
            catalogue=tool_catalogue(session.df, session.profile),
        )
        return AssistantResponse(
            reply=result["reply"],
            available=result["available"],
            answered_by=result["answered_by"],
            about="data",
            action=result.get("action"),
            table=jsonable(result.get("table")) if result.get("table") else None,
        )

    result = answer_about_app(
        message=request.message,
        history=history,
        dataset=_dataset_note(session),
    )
    return AssistantResponse(
        reply=result["reply"],
        available=result["available"],
        answered_by=result["answered_by"],
        about="app",
    )
