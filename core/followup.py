"""What to ask next.

WHY A CONVERSATION NEEDS THIS
-----------------------------
A person who does not know their data does not know what to ask about it
either. They ask one question, get a good answer, and stop -- not because they
are satisfied but because the next question has not occurred to them. The
difference between a tool that answers questions and one that feels like an
analyst is almost entirely in whether it says "and here is what I would look at
next".

WHAT MAKES A GOOD FOLLOW-UP
---------------------------
It has to be a genuinely different question. "Show me the trend" after
answering a trend question is padding, and three follow-ups that are the same
question reworded make the assistant look like it was not listening. So the
suggestions are built from a MOVE -- a direction to travel from where the
conversation is now -- and each move can appear once:

    narrow    a level down: which part of that group, which product
    widen     a level up: how does that compare to everything else
    time      the same question, over time
    cause     what else moves with the thing just discussed
    verify    is this unusual, or is it normal for this data
    act       what should be done about it

Which moves are available depends on what the dataset actually has. There is no
"over time" follow-up for a file with no dates, because offering a question the
assistant will then refuse to answer is worse than offering nothing.

GROUNDING. A follow-up naming a column that does not exist is the specific
failure this module must not have: the user clicks it, the assistant says it
cannot find that column, and the product looks broken at the exact moment it
was being helpful. Every model-written suggestion is checked against the real
column list before it is offered.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Set

from core import grounding, llm
from core.llm import LLMError

logger = logging.getLogger(__name__)

MAX_FOLLOWUPS = 4
MAX_TOKENS = 400

# Warmer than the analytical paths. These are conversational prompts and a
# greedy decode makes four suggestions that all start with "What is the".
TEMPERATURE = 0.65

# Longer than this stops looking like something a person would type and starts
# looking like a report title.
MAX_QUESTION_CHARS = 90

PROMPT = """You suggest the next questions someone should ask about their \
dataset, immediately after they received an answer.

You are given: the QUESTION they just asked, the ANSWER they received, the
COLUMNS of their dataset (names and kinds only, never values), and the MOVES
that are available for this dataset.

Write up to 4 follow-up questions.

RULES:
1. Only reference columns that appear in COLUMNS. Never invent one.
2. Each question must use a DIFFERENT move from the MOVES list. Do not suggest
   four versions of the same question.
3. Do not re-ask what the ANSWER already told them.
4. Write them the way a person types into a chat box: short, direct, no more
   than 12 words. No question marks stacked with clauses.
5. If the answer said the app could not determine something, do not suggest a
   question that would fail the same way.

Respond with raw JSON only, no code fences, exactly this shape:
{"followups": [{"text": "...", "move": "<one of the MOVES>"}]}"""


# The moves, with the template used when no model is available. `{measure}`,
# `{category}` and `{time}` are filled from the dataset's own columns, so even
# the fallback suggestions name real things.
MOVES: Dict[str, Dict[str, str]] = {
    "narrow": {
        "label": "Go deeper",
        "template": "Break that down by {category}",
    },
    "widen": {
        "label": "Zoom out",
        "template": "How does that compare to the overall average?",
    },
    "time": {
        "label": "Over time",
        "template": "How has {measure} changed over time?",
    },
    "cause": {
        "label": "What drives it",
        "template": "What else moves with {measure}?",
    },
    "verify": {
        "label": "Sanity check",
        "template": "Is that unusual, or normal for this data?",
    },
    "act": {
        "label": "Next step",
        "template": "What should I investigate next?",
    },
}


def _friendly(name: str) -> str:
    return str(name).replace("_", " ").replace("-", " ").strip()


def _available_moves(
    profile: Dict[str, Any], routing: Dict[str, Any], tool: Optional[str]
) -> List[str]:
    """Which directions this dataset and this answer can actually support.

    `tool` is what just ran. It is used to REMOVE a move rather than to add one:
    having just answered a trend question, "how has it changed over time" is no
    longer a next question.
    """
    kinds = {
        str(column.get("semantic_type")) for column in profile.get("columns", [])
    }
    moves: List[str] = []

    if "categorical" in kinds and tool != "rank":
        moves.append("narrow")
    if tool in ("rank", "aggregate", "count", "outliers"):
        moves.append("widen")
    if ("datetime" in kinds or routing.get("time_col")) and tool != "trend":
        moves.append("time")
    if sum(1 for k in kinds if k == "numeric") and tool != "relationship":
        moves.append("cause")
    if tool not in ("outliers",):
        moves.append("verify")
    moves.append("act")

    return moves


def _columns_for_templates(
    profile: Dict[str, Any], routing: Dict[str, Any]
) -> Dict[str, Optional[str]]:
    """The one measure, category and date the fallback templates should name."""
    by_kind: Dict[str, List[str]] = {}
    for column in profile.get("columns", []):
        by_kind.setdefault(str(column.get("semantic_type")), []).append(
            str(column.get("name"))
        )

    numeric = by_kind.get("numeric", [])
    categorical = by_kind.get("categorical", [])

    return {
        "measure": routing.get("target_col") or (numeric[0] if numeric else None),
        "category": categorical[0] if categorical else None,
        "time": routing.get("time_col") or (by_kind.get("datetime") or [None])[0],
    }


def _fallback(
    profile: Dict[str, Any],
    routing: Dict[str, Any],
    tool: Optional[str],
) -> List[Dict[str, str]]:
    """Follow-ups with no model: real questions, built from real columns.

    A template that cannot be filled is skipped rather than rendered with a
    placeholder in it. "Break that down by {category}" on screen is worse than
    one fewer suggestion.
    """
    names = _columns_for_templates(profile, routing)
    suggestions: List[Dict[str, str]] = []

    for move in _available_moves(profile, routing, tool):
        template = MOVES[move]["template"]
        needed = set(re.findall(r"\{(\w+)\}", template))
        if any(not names.get(key) for key in needed):
            continue
        text = template.format(
            **{key: _friendly(names[key] or "") for key in needed}
        )
        suggestions.append({"text": text, "move": move, "label": MOVES[move]["label"]})
        if len(suggestions) >= MAX_FOLLOWUPS:
            break

    return suggestions


def suggest(
    question: str,
    reply: str,
    profile: Dict[str, Any],
    routing: Dict[str, Any],
    *,
    tool: Optional[str] = None,
    api_key: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Propose what to ask next, after an answer has been given.

    Args:
        question: what the user just asked.
        reply: what the assistant just answered. Used so the suggestions do not
            repeat it -- never quoted back.
        profile: core.profiler output, for the real column names.
        routing: core.router output.
        tool: the core.tools tool that produced the answer, if any.
        api_key: per-request override, threaded to core.llm.

    Returns:
        [{"text", "move", "label"}, ...] -- possibly empty, which is a valid
        outcome the UI must handle by showing nothing rather than a gap.

    Never raises. Follow-ups are a garnish on an answer that has already been
    delivered, and no failure here may cost the user that answer.
    """
    moves = _available_moves(profile, routing, tool)
    fallback = _fallback(profile, routing, tool)

    if not llm.available(api_key) or not question.strip():
        return fallback

    columns = [
        {"name": str(c.get("name")), "kind": str(c.get("semantic_type"))}
        for c in profile.get("columns", [])[:40]
    ]
    payload = {
        "question": question,
        "answer": reply[:600],
        "columns": columns,
        "moves": [{"id": m, "means": MOVES[m]["label"]} for m in moves],
    }

    try:
        raw = llm.complete(
            json.dumps(payload, default=str),
            PROMPT,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            json_mode=True,
            api_key_override=api_key,
        )
    except LLMError as exc:
        logger.info("Follow-up suggestions unavailable: %s", exc)
        return fallback

    parsed = grounding.parse_json(raw)
    known: Set[str] = {str(c["name"]).lower() for c in columns}
    known |= {_friendly(c["name"]).lower() for c in columns}

    suggestions: List[Dict[str, str]] = []
    used_moves: Set[str] = set()

    for entry in parsed.get("followups", []) or []:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "").strip()
        if not text or len(text) > MAX_QUESTION_CHARS:
            continue

        # Reject anything naming a column that does not exist. Only tokens that
        # look like a column reference are checked -- backticked names and
        # snake_case words -- since checking every word would reject ordinary
        # English, "the" not being a column either.
        invented = False
        for backticked, snake_case in re.findall(r"`([^`]+)`|(\b\w+_\w+\b)", text):
            name = (backticked or snake_case).strip().lower()
            if name and name not in known:
                invented = True
                break
        if invented:
            logger.info("Discarded follow-up naming an unknown column: %r", text)
            continue

        move = str(entry.get("move") or "").strip().lower()
        if move not in MOVES or move in used_moves:
            # An unusable or repeated move still leaves a usable question; it is
            # kept and labelled generically rather than thrown away.
            move = ""
        if move:
            used_moves.add(move)

        suggestions.append(
            {
                "text": text,
                "move": move,
                "label": MOVES[move]["label"] if move else "Ask next",
            }
        )
        if len(suggestions) >= MAX_FOLLOWUPS:
            break

    return suggestions or fallback
