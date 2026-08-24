"""Grounded question answering over a dataset's COMPUTED SUMMARIES, never its rows.

WHY THIS MODULE IS BUILT THE WAY IT IS
--------------------------------------
The whole project argues one thing: a tool that shows you its working can be
trusted, and one that does not cannot. Every other module earns that -- the
profiler is conservative, the router validates the model's answer against the
profile, the world builders execute the code they display, the forecast is
scored against a baseline it is allowed to lose to.

A chatbot is the single fastest way to throw all of it away. One invented
correlation, one plausible-sounding mean that is not the mean, and the user has
a specific false belief with the app's authority behind it. Worse, they have no
way to tell that answer apart from the true ones, so every previous answer
becomes suspect too.

The defence is structural, not a matter of asking nicely:

 1. THE MODEL NEVER SEES THE DATA. It receives the profile, the routing, the
    world's computed stats and the forecast metrics -- dicts of numbers that
    pandas and scikit-learn already calculated. It never receives a DataFrame,
    a row, or a column of values. build_context() is the only thing that
    assembles what is sent, and it takes dicts, not a frame: there is no
    parameter through which rows COULD reach it. That is a stronger guarantee
    than a filter, because a filter can be got past and a missing parameter
    cannot.

 2. THE MODEL NEVER COMPUTES. It is told, in the system prompt, that every
    number in its answer must be copied from the context. It has no tools, no
    code execution, and nothing to compute from -- see (1).

 3. NOT KNOWING IS A CORRECT ANSWER. The prompt makes "I only have the summary,
    not the rows" an explicitly successful outcome rather than a failure the
    model should try to avoid. Models guess when the prompt implies that an
    answer is expected; the fix is to say clearly that it is not.

 4. THE ANSWER DECLARES ITS SOURCES, AND WE CHECK THEM. The model returns which
    context blocks it used, and that list is intersected with the blocks
    actually supplied before it reaches the caller -- the same trust-but-verify
    pattern core.router uses on a proposed column name. A model claiming to have
    used "forecast_metrics" when no forecast has been run is exactly the kind of
    confident nonsense the UI must not repeat.

 5. FAILURE IS SILENCE, NOT INVENTION. If the API is unreachable, nothing
    fabricates prose in its place. What CAN still happen without a model is a
    calculation -- see THE CALCULATOR below -- because a computed number is not
    a guess at what was asked, it is an answer to a question that was
    recognised. What never happens is an explanation assembled around numbers
    nobody computed.

THE CALCULATOR (added after the rules above, and consistent with all of them)
----------------------------------------------------------------------------
Rules 1 and 2 make the assistant trustworthy and also make it unable to answer
"which region sells most?" -- a question whose answer is a real number that is
not in any summary. The fix is NOT to relax them. It is to give the model a
calculator it can point at but cannot reach into:

    question -> the model PICKS A TOOL from a fixed menu (core.tools)
             -> the CALLER runs that tool against the DataFrame
             -> real numbers come back
             -> the model writes the sentence around them

Three things about that flow matter. First, the model still never sees a row: it
sees column names and types when planning, and computed results afterwards.
Second, this module still cannot reach the data -- the caller passes in a
`compute` function, so there is no DataFrame in scope here, and the guarantee
remains a property of the signature rather than of anyone's discipline. Third,
the numbers in the answer were produced by pandas, not by the model, which is
exactly the division of labour rule 2 was protecting.

When no model is available, the caller's `plan_locally` reads the question with
keyword rules instead. A recognised question then gets the *same* computed
answer with templated wording; an unrecognised one gets an honest "I could not
work out what to calculate". Chat degrades in fluency, not in truthfulness.

WHAT IS DISCLOSED, STATED HONESTLY: the profile carries per-column min/max/mean
and up to ten example values for each categorical column. Those examples are
real cell contents. They are a bounded, low-cardinality vocabulary that the UI
already displays on screen, and core.router already sends three of them per
column, so this is a known and accepted disclosure rather than an oversight. A
tool result may also contain values the calculation produced -- the names of the
top five regions, the row numbers of five outliers -- which is the same class of
disclosure and is the answer the user asked for. No column of raw cells is ever
sent.

Provider: whichever one core.llm is configured for. This module names no
vendor and imports no SDK. It asks core.llm for a completion and handles the
one exception type core.llm raises, so an assistant that keeps working when
the provider changes is a property of the architecture rather than of a
future edit remembering to update two files.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core import llm

logger = logging.getLogger(__name__)

# Larger than the router's 1000 because this produces prose rather than a
# classification, but still a cap: an answer longer than a few paragraphs about
# a summary dict is padding, and padding is where invention lives.
MAX_TOKENS = 1200

# Not 0.0. The router classifies and must be repeatable; this writes a sentence
# for a person to read, and a fully greedy decode produces stilted, repetitive
# phrasing. 0.2 is low enough that the FACTS cannot wander -- they are copied
# from the context either way -- while leaving enough freedom for the wording to
# be readable.
TEMPERATURE = 0.2

# Turns from the conversation to replay. Enough for "and what about the other
# one?" to resolve; short enough that the context stays small and an old answer
# cannot become the de facto source for a new one.
MAX_HISTORY_TURNS = 8

# A wide dataset would otherwise send thousands of tokens of column metadata.
# The cap is stated to the model so it knows the list is truncated rather than
# concluding that the missing columns do not exist.
MAX_CONTEXT_COLUMNS = 60

# ASCII only, deliberately: this string is printed by scripts/test_chat.py to a
# Windows console, where a cp1252 code page mangles an em dash into a
# replacement character and makes a passing test look broken.
UNAVAILABLE_MESSAGE = (
    "The assistant is unavailable right now, so I cannot answer that. "
    "Everything else on this page - the profile, the routing, the charts, the "
    "code and the forecast - is computed locally and is unaffected."
)

SYSTEM_PROMPT = """You answer questions about a dataset a user has uploaded to a \
data-visualisation tool.

You are given a JSON CONTEXT containing only COMPUTED SUMMARIES of that dataset:
a column profile, the routing decision, the statistics of the chart that was
built, and forecast metrics if a forecast was run. You are NEVER given the rows
themselves, and you cannot run code.

ABSOLUTE RULES — these override every other consideration:

1. Every number, column name, date and category you state must be copied from
   the CONTEXT. Do not calculate, do not estimate, do not extrapolate, do not
   round beyond what is given, and do not infer a value from other values.

2. If the answer is not in the CONTEXT, say so plainly and briefly, name what
   you would have needed, and suggest what the user could do to find out — for
   example: "I only have the summary, not the individual rows, so I cannot tell
   you the value on a specific date. The chart above is interactive; hovering
   that point will show it." Saying you do not know IS a correct and complete
   answer. It is never a failure.

3. Never invent a correlation, a trend, a cause or a comparison that the CONTEXT
   does not contain. Two numbers appearing in the CONTEXT does not license you
   to compute a third from them.

4. Do not speculate about what the data "probably" means, what caused a pattern,
   or what the user should do about it, beyond what the reasoning field and the
   statistics actually say.

STYLE: answer in plain language, two or three sentences unless more is genuinely
needed. Quote the numbers you used. Do not restate the whole context. Do not
apologise repeatedly. No markdown headings; short paragraphs only.

Respond with raw JSON only, no code fences, exactly this shape:
{"answer": "...", "used": ["<context block names you actually used>"]}

"used" must contain only names of blocks present in the CONTEXT you were given.
If you could not answer from the context, return an empty "used" list."""


PLANNER_PROMPT = """You decide what a data app should CALCULATE in order to \
answer a user's question. You do not answer the question yourself.

You are given the list of TOOLS the app can run, and the COLUMNS of the dataset
(names and kinds only — never any values).

Pick the single tool that would produce the number the user is asking for, and
fill in its arguments using column names EXACTLY as they appear in COLUMNS.

RULES:
1. Only ever name a column that is in COLUMNS. Never invent one, never guess at
   one that "should" exist.
2. Only ever name a tool that is in TOOLS.
3. If no tool would answer the question — the user is asking something the data
   cannot address, or is making conversation — return {"tool": null}. That is a
   correct answer and is expected regularly.
4. Prefer the most specific tool. "Which region is best?" is `rank`, not
   `overview`.
5. Do not attempt to answer, explain or calculate. Your entire output is the
   choice.

Respond with raw JSON only, no code fences, exactly this shape:
{"tool": "<tool name or null>", "args": {...}, "why": "<one short clause>"}"""


EXPLAIN_PROMPT = """You explain a calculation to someone with no background in \
data or statistics.

The app has already run a calculation over the user's dataset. You are given the
QUESTION they asked, the RESULT the calculation produced, and background CONTEXT
about the dataset.

ABSOLUTE RULES — these override every other consideration:

1. Every number you state must be copied from RESULT or CONTEXT. You must not
   calculate anything, including percentages, differences, ratios or totals that
   are not already there. If a number would be useful and is not present, leave
   it out.
2. Answer the question that was asked, using the result. Lead with the answer,
   not with a description of the method.
3. If RESULT does not actually answer the question, say so plainly and say what
   it does show. That is a correct outcome.
4. No jargon. Not "correlation coefficient" — "they move together". Not
   "aggregation" — "total". Not "outlier" — "unusual". The reader does not know
   these words and should not have to.

STYLE: two or three sentences. Plain language, specific numbers, no headings, no
bullet lists, no markdown. Do not repeat the whole result back.

Respond with raw JSON only, no code fences, exactly this shape:
{"answer": "..."}"""


def _compact_columns(profile: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int]:
    """Reduce the profile's column list to what a question could need.

    Everything kept here is metadata computed by the profiler. `examples` are
    the categorical top values -- see the module docstring for why that
    disclosure is accepted.
    """
    columns = profile.get("columns", []) or []
    kept: List[Dict[str, Any]] = []

    for column in columns[:MAX_CONTEXT_COLUMNS]:
        entry: Dict[str, Any] = {
            "name": column.get("name"),
            "type": column.get("semantic_type"),
            "dtype": column.get("dtype"),
            "n_unique": column.get("n_unique"),
            "null_pct": column.get("null_pct"),
        }
        for key in ("min", "max", "mean", "min_date", "max_date"):
            if column.get(key) is not None:
                entry[key] = column[key]
        if column.get("top_values"):
            entry["examples"] = [v["value"] for v in column["top_values"][:5]]
        kept.append(entry)

    return kept, len(columns)


def build_context(
    profile: Dict[str, Any],
    routing: Dict[str, Any],
    world_stats: Optional[Dict[str, Any]] = None,
    world_archetype: Optional[str] = None,
    world_warnings: Optional[Sequence[str]] = None,
    forecast: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Assemble everything the model is allowed to see, plus the block names.

    Note the signature: there is no DataFrame parameter and no rows parameter.
    A caller cannot pass raw data to the assistant even by mistake, which is the
    guarantee the module docstring rests on.

    Args:
        profile: core.profiler.profile_dataframe output.
        routing: core.router.route output.
        world_stats: the "stats" dict from a core.worlds builder, if one has run.
        world_archetype: which builder produced world_stats; used to name the
            block, so the UI's "grounded on" line says timeseries_stats rather
            than a generic label.
        world_warnings: the builder's warnings. Included because they describe
            what the data lost on the way to the chart, which is frequently the
            honest answer to "why does this look wrong".
        forecast: metrics/verdict/importances from core.ml.forecast, if run.

    Returns:
        (context, block_names). block_names is the definitive list of what was
        supplied, and is what any claimed source is later validated against.
    """
    columns, total_columns = _compact_columns(profile)

    context: Dict[str, Any] = {
        "profile": {
            "n_rows": profile.get("n_rows"),
            "n_cols": profile.get("n_cols"),
            "n_numeric": profile.get("n_numeric"),
            "has_datetime": profile.get("has_datetime"),
            "has_geo": profile.get("has_geo"),
            "columns": columns,
            "columns_truncated": total_columns > len(columns),
        },
        "routing": {
            "archetype": routing.get("archetype"),
            "time_col": routing.get("time_col"),
            "entity_col": routing.get("entity_col"),
            "target_col": routing.get("target_col"),
            "lat_col": routing.get("lat_col"),
            "lon_col": routing.get("lon_col"),
            "reasoning": routing.get("reasoning"),
            # The user is entitled to know whether the AI or the fallback rules
            # chose, and so is the assistant: "why was this archetype chosen" has
            # a different true answer in each case.
            "decided_by": (
                "the language model"
                if routing.get("source") == "llm"
                else "the built-in rules, because the language model was unavailable"
            ),
        },
    }
    blocks = ["profile", "routing"]

    if world_stats:
        name = f"{world_archetype or 'world'}_stats"
        context[name] = dict(world_stats)
        if world_warnings:
            context[name]["_warnings_about_this_chart"] = list(world_warnings)
        blocks.append(name)

    if forecast:
        context["forecast_metrics"] = {
            "metrics": forecast.get("metrics"),
            "beats_baseline": forecast.get("beats_baseline"),
            "verdict": forecast.get("verdict"),
            "feature_importances": forecast.get("feature_importances"),
            "horizon_days": forecast.get("horizon_days"),
            "caveats": forecast.get("warnings"),
        }
        blocks.append("forecast_metrics")

    return context, blocks


def _trim_history(history: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    """Keep the last few well-formed turns, dropping anything malformed."""
    clean: List[Dict[str, str]] = []
    for turn in history or []:
        role = turn.get("role")
        content = str(turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            clean.append({"role": role, "content": content})
    return clean[-MAX_HISTORY_TURNS:]


def _strip_code_fences(text: str) -> str:
    """Remove markdown fences the model may add despite being told not to."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned[3:]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    return cleaned.strip()


def _validate_used(claimed: Any, supplied: Sequence[str]) -> List[str]:
    """Intersect the model's claimed sources with what it was actually given.

    WHY this cannot be taken on trust: the "grounded on" line is displayed to
    the user as evidence, so it has to BE evidence. A model that answers a
    forecast question when no forecast has been run and lists
    "forecast_metrics" as its source would be presenting an invention with a
    citation attached, which is worse than presenting it bare.

    Order follows `supplied`, not the model's ordering, so the UI shows the
    blocks in a stable sequence between answers.
    """
    if not isinstance(claimed, list):
        return []
    named = {str(item) for item in claimed}
    return [block for block in supplied if block in named]


def _call_model(
    payload: str,
    api_key: Optional[str] = None,
    system_prompt: str = SYSTEM_PROMPT,
    max_tokens: int = MAX_TOKENS,
) -> str:
    """Send a payload under a given system prompt and return the raw text.

    Kept as a named function even though it now forwards to core.llm: it is the
    seam scripts/test_chat.py replaces, and it is where this module's request
    settings live. The system prompt is a parameter because this module makes
    three different kinds of request -- plan, explain, answer-from-summaries --
    and they differ in nothing else.

    JSON mode throughout. All three prompts end by specifying an exact object
    shape, and every caller parses and validates what comes back, so a provider
    honouring the flag is a convenience rather than a load-bearing assumption.
    """
    return llm.complete(
        payload,
        system_prompt,
        max_tokens=max_tokens,
        temperature=TEMPERATURE,
        json_mode=True,
        api_key_override=api_key,
    )


def _parse_json_reply(raw: str) -> Dict[str, Any]:
    """Parse a model reply that is contractually a JSON object, or raise."""
    parsed = json.loads(_strip_code_fences(raw))
    if not isinstance(parsed, dict):
        raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
    return parsed


def plan_with_model(
    question: str,
    catalogue: Dict[str, Any],
    history: Sequence[Dict[str, str]],
    api_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Ask the model which calculation would answer the question.

    Args:
        question: the user's question.
        catalogue: core.tools.catalogue output -- the tool menu and the column
            names. No values.
        history: recent turns, so "and the worst one?" can resolve.
        api_key: the provider key.

    Returns:
        {"tool": str, "args": dict} or None when no tool fits, the model said so,
        or anything at all went wrong. None is the safe outcome: it falls through
        to answering from summaries, which is the pre-existing behaviour.

    The returned plan is NOT trusted. core.tools validates every column name and
    every argument against the frame before running anything, and refuses what it
    cannot resolve -- the same trust-but-verify pattern core.router applies to a
    proposed archetype.
    """
    payload = json.dumps(
        {
            "TOOLS": catalogue.get("tools", {}),
            "COLUMNS": catalogue.get("columns", []),
            "N_ROWS": catalogue.get("n_rows"),
            "CONVERSATION_SO_FAR": _trim_history(history or []),
            "QUESTION": question,
        },
        default=str,
    )

    try:
        parsed = _parse_json_reply(
            _call_model(payload, api_key, system_prompt=PLANNER_PROMPT, max_tokens=400)
        )
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as exc:
        logger.warning("Could not parse plan: %s", exc)
        return None
    except llm.LLMError as exc:
        logger.warning("Planning call failed: %s", exc)
        return None

    tool = parsed.get("tool")
    if not tool or not isinstance(tool, str):
        return None
    args = parsed.get("args")
    return {"tool": tool, "args": args if isinstance(args, dict) else {}}


def _explain_result(
    question: str,
    tool_result: Dict[str, Any],
    context: Dict[str, Any],
    history: Sequence[Dict[str, str]],
    api_key: str,
) -> Optional[str]:
    """Have the model write the sentence around numbers it did not produce.

    Returns None on any failure, and the caller then uses the tool's own
    templated summary. That fallback is the reason this step is allowed to be a
    network call at all: the answer already exists before the model is asked,
    so the model is an improvement to the wording and never a dependency for
    the fact.
    """
    payload = json.dumps(
        {
            "QUESTION": question,
            "RESULT": {
                "calculation": tool_result.get("tool"),
                "numbers": tool_result.get("result"),
                "plain_summary": tool_result.get("summary"),
            },
            "CONTEXT": context,
            "CONVERSATION_SO_FAR": _trim_history(history or []),
        },
        default=str,
    )

    try:
        parsed = _parse_json_reply(
            _call_model(payload, api_key, system_prompt=EXPLAIN_PROMPT)
        )
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as exc:
        logger.warning("Could not parse explanation: %s", exc)
        return None
    except llm.LLMError as exc:
        logger.warning("Explanation call failed: %s", exc)
        return None

    reply = str(parsed.get("answer") or "").strip()
    return reply or None



def _reply(
    text: str,
    grounded_on: Optional[Sequence[str]] = None,
    available: bool = True,
    answered_by: str = "summaries",
    tool: Optional[str] = None,
    action: Optional[Dict[str, Any]] = None,
    table: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One response shape for every path out of answer().

    Written as a constructor rather than repeated dict literals because there
    are now seven ways out of answer(), and a field missing from one of them
    would surface in React as `undefined` on a rare branch -- the kind of bug
    that only ever appears in front of an audience.

    answered_by is the honest label the UI shows next to the reply:
      "computed"    -- the numbers came from pandas, the wording is templated
      "model"       -- the numbers came from pandas, the wording from the model
      "summaries"   -- answered from cached statistics, no fresh calculation
      "unavailable" -- no answer was produced
    """
    return {
        "reply": text,
        "grounded_on": list(grounded_on or []),
        "available": available,
        "answered_by": answered_by,
        "tool": tool,
        "action": action,
        "table": table,
        "data": data,
    }


def answer(
    message: str,
    profile: Dict[str, Any],
    routing: Dict[str, Any],
    history: Optional[Sequence[Dict[str, str]]] = None,
    world_stats: Optional[Dict[str, Any]] = None,
    world_archetype: Optional[str] = None,
    world_warnings: Optional[Sequence[str]] = None,
    forecast: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
    compute: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
    plan_locally: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
    catalogue: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Answer a question about a dataset, computing the number where one is needed.

    Args:
        message: the user's question.
        profile: core.profiler output. Required -- without it there is no
            context and nothing honest to say.
        routing: core.router output.
        history: prior turns as [{"role": "user"|"assistant", "content": str}].
        world_stats / world_archetype / world_warnings: the built chart's stats,
            if the user has one on screen.
        forecast: forecast metrics, if one has been run.
        api_key: overrides the provider key in the environment. For tests and
            for a future server holding one key per request.
        compute: ``(tool_name, args) -> core.tools.run(...) result``. Supplied by
            the caller, which holds the DataFrame. Note what this parameter is
            NOT: it is not the frame, and not a way to reach one. This module can
            ask for a calculation and read the answer; it cannot read a row.
        plan_locally: ``(question) -> {"tool", "args"} | None``. The keyword
            planner, bound by the caller to the same frame. Used when there is no
            model, and when the model declines or names a column that does not
            resolve.
        catalogue: core.tools.catalogue output -- the tool menu and the column
            names, for the model's planning step.

    Returns:
        See _reply() for the shape. Every field is always present.

    Like core.router.route, this function is contractually non-raising: chat is
    an accessory to the page, and an outage must not take the page down.
    """
    question = str(message or "").strip()
    if not question:
        return _reply(
            "Ask me anything about this dataset — what is in it, what is going "
            "up, which group is doing best, or what looks unusual."
        )

    context, blocks = build_context(
        profile=profile,
        routing=routing,
        world_stats=world_stats,
        world_archetype=world_archetype,
        world_warnings=world_warnings,
        forecast=forecast,
    )

    # One question, asked once: is a model reachable at all? core.llm knows
    # which provider is configured, whether its client library imported and
    # whether a key is set. This module used to answer that itself by naming a
    # vendor -- which is how AI_PROVIDER=deepseek turned the assistant off.
    key = api_key
    have_model = llm.available(key)

    # ---------------------------------------------------------- 1. plan ----
    # The model plans when there is one, because it resolves phrasings rules
    # cannot ("which part of the business is doing worst"). The keyword planner
    # is the fallback in BOTH directions: no model at all, and a model that
    # declined to pick anything.
    plan: Optional[Dict[str, Any]] = None
    local_plan: Optional[Dict[str, Any]] = None
    if plan_locally is not None:
        try:
            local_plan = plan_locally(question)
        except (ValueError, TypeError, KeyError) as exc:
            logger.warning("Keyword planner failed: %s", exc)

    # Rules first WHEN THEY ARE SURE. A question that names its own subject
    # ("which region has the highest revenue") is one the rules read correctly,
    # and spending a network round trip to have a model agree costs latency and
    # -- on a rate-limited free tier -- an entire request from the budget. Where
    # the rules had to guess at the subject, the model earns its round trip.
    if local_plan and local_plan.get("confident"):
        plan = local_plan
    elif have_model and catalogue and compute is not None:
        plan = plan_with_model(question, catalogue, history or [], key) or local_plan
    else:
        plan = local_plan

    # ------------------------------------------------------- 2. compute ----
    tool_result: Optional[Dict[str, Any]] = None
    if plan and compute is not None:
        tool_result = compute(plan.get("tool"), plan.get("args") or {})
        if not tool_result.get("ok") and plan_locally is not None:
            # A refused plan is not a dead end. The model may have named a
            # column that does not resolve, while the keyword planner still
            # recognises the question -- so try that before giving up on
            # computing anything at all.
            logger.info(
                "Plan refused (%s): %s", plan.get("tool"), tool_result.get("error")
            )
            second = plan_locally(question)
            if second and second != plan:
                retry = compute(second.get("tool"), second.get("args") or {})
                if retry.get("ok"):
                    tool_result = retry

    # ------------------------------------------------------- 3. explain ----
    if tool_result is not None and tool_result.get("ok"):
        grounded = [f"computed_{tool_result['tool']}"]

        if have_model:
            phrased = _explain_result(question, tool_result, context, history or [], key)
            if phrased:
                return _reply(
                    phrased,
                    grounded_on=grounded,
                    answered_by="model",
                    tool=tool_result["tool"],
                    action=tool_result.get("action"),
                    table=tool_result.get("table"),
                    data=tool_result.get("result"),
                )

        # No model, or the model failed. The tool has already written a sentence
        # that is true; using it is not a degraded answer, only a plainer one.
        return _reply(
            tool_result["summary"],
            grounded_on=grounded,
            answered_by="computed",
            tool=tool_result["tool"],
            action=tool_result.get("action"),
            table=tool_result.get("table"),
            data=tool_result.get("result"),
        )

    # ------------------------------ 4. nothing computed; fall back ---------
    if not have_model:
        # No model to write prose from the summaries, and no calculation
        # applied. Two things are worth saying, and both of them are:
        #
        #   * WHY. "The assistant is unavailable" without a cause is the kind of
        #     message that sends someone hunting through logs for a bug that is
        #     really an unset variable.
        #   * WHAT CAN STILL BE ASKED. Calculations do not need the model, so
        #     the door is not closed -- but a user who does not know the
        #     vocabulary cannot rephrase into it unaided, so it is shown.
        # core.llm.status() already phrases the cause -- unimplemented
        # provider, missing client library, absent key -- so there is one
        # sentence to maintain rather than a branch per failure mode.
        cause = (
            f"I cannot answer in my own words right now. {llm.status()['reason']} "
        )

        refusal = tool_result.get("error") if tool_result else None
        if refusal:
            cause += f"{refusal} "

        return _reply(
            cause
            + "I can still calculate things directly from your data — try naming "
            + "a column, for example “which region has the highest revenue”, "
            + "“is revenue going up”, “find unusual rows”, or “summarise this "
            + "dataset”. Everything else on this page is computed locally and "
            + "works without a key.",
            available=False,
            answered_by="unavailable",
        )

    # A model is available and no calculation applied. Answer from the cached
    # summaries -- this module's original behaviour, unchanged.
    payload = json.dumps(
        {
            "CONTEXT": context,
            "AVAILABLE_CONTEXT_BLOCKS": blocks,
            "CONVERSATION_SO_FAR": _trim_history(history or []),
            "QUESTION": question,
        },
        default=str,  # a stray non-JSON scalar must not fail the whole request
    )

    try:
        parsed = _parse_json_reply(_call_model(payload, key))
        reply = str(parsed.get("answer") or "").strip()
        if not reply:
            raise ValueError("model returned an empty answer")
        return _reply(
            reply,
            grounded_on=_validate_used(parsed.get("used"), blocks),
            answered_by="summaries",
        )

    except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as exc:
        # The model replied but not to the contract. Note that this is NOT
        # rescued by returning the raw text as the answer: unparseable output is
        # output that skipped the instructions, and the grounding rules are in
        # those instructions.
        logger.warning("Could not parse chat response: %s", exc)
        return _reply(
            "I got a reply I could not read, so I am not going to guess at what "
            "it said. Please ask again.",
            available=False,
            answered_by="unavailable",
        )
    except llm.LLMError as exc:
        logger.warning("Chat model call failed: %s", exc)
        return _reply(UNAVAILABLE_MESSAGE, available=False, answered_by="unavailable")
