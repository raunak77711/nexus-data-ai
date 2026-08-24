"""The friendly assistant on the home page: help with the APP, not with the data.

WHY THIS IS A SEPARATE MODULE FROM core.chat
--------------------------------------------
core.chat answers "which region sells most?" It is built to be paranoid: it
never sees a row, it copies every number from a computed summary, and it
refuses rather than guesses. Those rules are what make its answers worth
believing, and they are exactly the wrong rules for "what is a CSV?" or "I
uploaded my file, now what?" -- questions where there is no dataset to ground
against and refusing to answer is simply unhelpful.

So there are two assistants behind one chat bubble, and the router in
backend/routers/assistant.py decides which one a message goes to:

    "which region sells most?"   -> core.chat    (calculates, cites, refuses)
    "what do I do next?"         -> core.guide   (explains the app, warmly)

Splitting them means neither has to be a compromise. core.chat keeps its
absolute prohibition on inventing a number. This module is free to be
conversational, because the only thing it is allowed to talk about is how the
app works -- which is knowledge that lives in its prompt, not in the user's
file.

THE ONE RULE THIS MODULE SHARES
-------------------------------
It must not state a fact about the user's data. It is given the shape of the
loaded file (name, row count, column count, column names) so it can say
"your file has 1,200 rows, try asking which month was busiest" -- but the
prompt forbids it from answering with a value, a total or an average, and
tells it to hand those questions back to the calculator instead. That keeps
the project's central promise intact: every number the user is shown was
computed by pandas, never written by a model.

WHEN THERE IS NO MODEL
----------------------
The bubble still opens and still answers. FALLBACK_ANSWERS below is a small
keyword-matched FAQ covering the questions this screen actually gets, so an
app with no API key is a slightly less fluent app rather than one with a dead
chat window. A chat that says "unavailable" to a beginner asking "how do I
start" is worse than no chat at all.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from core import llm

logger = logging.getLogger(__name__)

# Short. This assistant is read by someone who is mid-task and slightly lost,
# and a five-paragraph answer to "what now?" is another thing to get lost in.
MAX_TOKENS = 400

# Warmer than core.chat's 0.2. Nothing here is a fact about the user's data --
# the facts are in the prompt -- so the freedom buys readable, un-robotic
# phrasing at no cost to correctness.
TEMPERATURE = 0.5

MAX_HISTORY_TURNS = 8

SYSTEM_PROMPT = """You are the helper inside NEXUS, a website that lets someone \
upload a spreadsheet and get answers about it without knowing anything about \
data, statistics, AI or programming.

WHO YOU ARE TALKING TO
Assume the person has never used a data tool before. They may not know what a
CSV is. They may not be sure whether their file will work. They are not stupid;
they are simply here for an answer, not for a lesson.

HOW THE APP WORKS -- this is what you are here to explain:

1. UPLOAD. On the home page they drop a spreadsheet file onto the box, or click
   it to pick a file. It must be a CSV file (a spreadsheet saved as "CSV" --
   in Excel or Google Sheets: File > Save As / Download > CSV). Nothing else is
   needed: no account, no setup, no settings to choose.
2. NEXUS READS IT. This takes a few seconds. It looks at every column and works
   out what each one holds -- dates, numbers, categories, places.
3. THEY GET RESULTS. A summary of the file, a chart of the most interesting
   thing in it, and a few plain-English findings.
4. THEY CAN ASK QUESTIONS. In this same chat window. Questions about their own
   data are answered by actually calculating the answer from their rows.

They can also click one of the example files on the home page to see how it all
works without uploading anything of their own. Their file stays on the server
for one hour and is then forgotten; it is not shared with anyone.

HOW TO ANSWER

* Be brief. Two to four short sentences. This is a chat bubble, not a manual.
* Use ordinary words. Never say: dataset, archetype, profile, schema, routing,
  model, API, endpoint, parse, aggregate, correlation, anomaly. Say: your file,
  your spreadsheet, your columns, what kind of information it holds, things
  that look unusual, things that move together.
* Be warm and encouraging, never gushing. No exclamation marks stacked up, no
  "Great question!".
* When they are stuck, give them ONE next thing to do, not a list of five.
* If they ask something you genuinely do not know about the app, say so plainly
  and suggest what they could try.

THE RULE YOU MUST NOT BREAK
You are never told the contents of anyone's file. If they ask what is IN their
data -- a total, an average, which category is biggest, what happened in March
-- you must NOT answer with a number or a name, because you do not have one and
anything you produced would be invented. Instead tell them to ask that question
directly ("ask me: which region sold the most") and explain that NEXUS will work
it out from their actual rows. If a file is loaded you are told its name and its
column names, and you may use those to suggest a good question.

Reply as plain conversational text. No markdown, no headings, no bullet
characters, no code blocks. Just sentences."""


def _dataset_note(dataset: Optional[Dict[str, Any]]) -> str:
    """One line telling the model what the user currently has open.

    Column NAMES are included and column VALUES are not. A name is already on
    screen in front of the user and is what makes "try asking which region
    sold the most" possible instead of a generic suggestion; a value would be
    a fact about the data, which this module is not allowed to state.
    """
    if not dataset:
        return (
            "The person has NOT uploaded anything yet. They are on the home page "
            "looking at the upload box."
        )

    columns = [str(c) for c in (dataset.get("columns") or [])][:25]
    note = (
        "The person has a file open. Its name is "
        f"{dataset.get('filename', 'their file')!r}. It has "
        f"{dataset.get('n_rows', 'some')} rows and {dataset.get('n_cols', 'some')} "
        f"columns. The columns are called: {', '.join(columns) or 'unknown'}. "
        "You know NOTHING about the values inside it."
    )

    # The routing reasoning, when there is one. This is the app explaining a
    # decision IT made, not a fact about the data, so it is safe here in a way
    # a value never would be -- and it is already written in plain language for
    # exactly this audience.
    #
    # It is included because "why this chart?" is a question this assistant gets
    # and could otherwise only answer by improvising something plausible. An
    # invented reason is the one failure mode a helper standing next to a
    # trustworthy calculator cannot afford.
    why = str(dataset.get("chart_reason") or "").strip()
    if why:
        note += (
            " NEXUS chose the chart currently on their screen for this stated "
            f"reason: {why!r}. If they ask why that chart, say this in your own "
            "words. Do not offer any other reason."
        )
    return note


def _trim(history: Optional[Sequence[Dict[str, str]]]) -> List[Dict[str, str]]:
    """The last few turns, in the provider-neutral shape core.llm accepts."""
    kept: List[Dict[str, str]] = []
    for turn in list(history or [])[-MAX_HISTORY_TURNS:]:
        role = turn.get("role")
        content = str(turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            kept.append({"role": role, "content": content})
    return kept


# --------------------------------------------------------------- no-model path

# Ordered most specific first: the first pattern that matches wins, so
# "what file types" is checked before the broader "how do I upload".
FALLBACK_ANSWERS: List[tuple] = [
    (
        r"\b(csv|file type|format|excel|xlsx|spreadsheet type|what kind of file)\b",
        "NEXUS reads CSV files. If your data is in Excel or Google Sheets, open "
        "it and choose File then Save As (or Download) and pick CSV. Then drop "
        "that file onto the upload box.",
    ),
    (
        r"\b(private|safe|secure|share|delete|store|keep my)\b",
        "Your file is held on the server just long enough to answer questions "
        "about it, and is forgotten after an hour. It is not shared with anyone "
        "and it is not used to train anything.",
    ),
    (
        r"\b(how do i (start|begin|upload)|get started|what do i do|where do i start|first step)\b",
        "Drop a CSV file onto the big box on the home page, or click it to choose "
        "one from your computer. If you would rather just see how it works, click "
        "one of the example files underneath.",
    ),
    (
        r"\b(next|now what|after upload|what should i do)\b",
        "Have a look at the chart and the findings NEXUS put together, then ask me "
        "a question about your file in this box — for example which category is "
        "biggest, or whether something is going up or down.",
    ),
    (
        r"\b(what (is|does) (this|nexus)|what can (you|it) do|purpose|about)\b",
        "NEXUS takes a spreadsheet and tells you what is in it, in plain English. "
        "You upload a file, it reads every column, and then you can ask it "
        "questions and get answers worked out from your actual rows.",
    ),
    (
        r"\b(error|fail|not work|broken|wrong|stuck|problem)\b",
        "Sorry that went wrong. The most common cause is a file that is not a CSV, "
        "or one with no header row at the top. Try saving it again as CSV with the "
        "column names in the first row, then upload it once more.",
    ),
    (
        r"\b(example|sample|demo|try it)\b",
        "There are example files on the home page, underneath the upload box. Click "
        "any one of them and NEXUS will open it straight away, so you can see what "
        "you get before using your own data.",
    ),
]

DEFAULT_FALLBACK = (
    "I can help you get started. Drop a CSV file onto the box on the home page, "
    "or click one of the examples to see how it works. Once a file is open you "
    "can ask me questions about it right here."
)


def fallback_answer(message: str) -> str:
    """Answer from the built-in FAQ, for when there is no model configured.

    Deliberately keyword-matched rather than clever. The value here is not that
    it handles every question -- it cannot -- but that the chat window always
    responds with something a beginner can act on, instead of an apology.
    """
    text = (message or "").lower()
    for pattern, reply in FALLBACK_ANSWERS:
        if re.search(pattern, text):
            return reply
    return DEFAULT_FALLBACK


# ------------------------------------------------------------------ the answer


def answer(
    message: str,
    history: Optional[Sequence[Dict[str, str]]] = None,
    dataset: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Answer a question about how to use the app.

    Args:
        message: what the user typed.
        history: prior turns as [{"role", "content"}].
        dataset: {filename, n_rows, n_cols, columns, chart_reason} for the open
            file, or None when nothing has been uploaded. Names and the app's
            own routing explanation only -- never a value from the data.
        api_key: overrides the provider key in the environment.

    Returns:
        {"reply": str, "available": bool, "answered_by": "guide"|"guide_offline"}

    Non-raising, for the same reason core.chat.answer is: this powers a chat
    bubble that sits on every screen, and a helper that can take the page down
    is worse than no helper.
    """
    question = str(message or "").strip()
    if not question:
        return {
            "reply": "How can I help you today?",
            "available": True,
            "answered_by": "guide",
        }

    if not llm.available(api_key):
        logger.info("Guide answering from the built-in FAQ: %s", llm.status()["reason"])
        return {
            "reply": fallback_answer(question),
            "available": True,
            "answered_by": "guide_offline",
        }

    payload = json.dumps(
        {
            "SITUATION": _dataset_note(dataset),
            "CONVERSATION_SO_FAR": _trim(history),
            "THEY_ASKED": question,
        },
        default=str,
    )

    try:
        # json_mode=False: the reply goes straight to a person, so asking the
        # provider to wrap it in an object would mean parsing a document just
        # to unwrap one string -- and would add a failure mode (unparseable
        # JSON) to a request that has no other way to fail.
        reply = llm.complete(
            payload,
            SYSTEM_PROMPT,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            json_mode=False,
            history=_trim(history),
            api_key_override=api_key,
        ).strip()
    except llm.LLMError as exc:
        # Degrade to the FAQ rather than to an error. The user asked a question
        # about the app, and the app's own documentation is sitting right there
        # in FALLBACK_ANSWERS.
        logger.warning("Guide model call failed, using the FAQ: %s", exc)
        return {
            "reply": fallback_answer(question),
            "available": True,
            "answered_by": "guide_offline",
        }

    if not reply:
        return {
            "reply": fallback_answer(question),
            "available": True,
            "answered_by": "guide_offline",
        }

    return {"reply": reply, "available": True, "answered_by": "guide"}
