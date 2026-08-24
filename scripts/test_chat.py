"""Prove the chat assistant cannot fabricate, and that it declines what it cannot answer.

Three parts, in increasing order of what they can guarantee:

PART 1 -- STRUCTURAL. The strongest guarantee available, and it needs no network.
  A sentinel value is planted in the DataFrame and the context is then searched
  for it. If a row-level value cannot reach the context, the model cannot repeat
  one, regardless of what any prompt says. This is the claim the module rests on
  and it is checked mechanically rather than argued.

PART 2 -- PLUMBING, with a stubbed model. Proves the parts that only misbehave
  in production and therefore cannot be tested against the live API: a claimed
  source that was never supplied is stripped, an API exception degrades to
  "unavailable" rather than to a guess, and unparseable output is NOT rescued by
  returning the raw text.

PART 3 -- LIVE REFUSAL. Asks the real model a question the context genuinely
  cannot answer ("what was the value on 3 March") and asserts the reply admits
  it. Skipped with a loud notice when there is no usable API key, because a
  skipped test that looks like a pass is worse than no test.

Run:  python scripts/test_chat.py
"""

from __future__ import annotations

import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import chat  # noqa: E402
from core import llm  # noqa: E402
from core.profiler import profile_dataframe  # noqa: E402
from core.router import rule_based_route  # noqa: E402

FAILURES = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global FAILURES
    if not condition:
        FAILURES += 1
    print(f"  [{'OK ' if condition else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")


def fixture():
    """A small frame carrying deliberately unmistakable row-level values.

    The sentinels are chosen so that a substring search cannot produce a false
    negative through coincidence, and so that each covers a different column
    kind: a numeric measure, a free-text cell and a date.
    """
    frame = pd.DataFrame(
        {
            "order_date": pd.date_range("2024-03-01", periods=40, freq="D"),
            "revenue": [100.0 + i for i in range(40)],
            "region": (["North", "South", "East", "West"] * 10),
            "note": [f"note-{i}" for i in range(40)],
        }
    )
    # A numeric value no aggregate could plausibly equal, in a row in the middle.
    frame.loc[17, "revenue"] = 987654.321
    # A text cell. `note` is free text (40 unique values), so it is never a
    # categorical and its values are never sampled into top_values.
    frame.loc[17, "note"] = "SENTINEL-ROW-TEXT-QX7"
    return frame


def part1_structural() -> None:
    print("\n" + "=" * 72)
    print("PART 1: the context provably contains no row-level data")
    print("=" * 72)

    frame = fixture()
    profile = profile_dataframe(frame)
    routing = rule_based_route(profile, why="test")

    world_stats = {"mean": 122.5, "min": 100.0, "max": 987654.321, "trend_direction": "rising"}
    forecast = {
        "metrics": {"test_mae": 1.2, "baseline_mae": 1.0},
        "beats_baseline": False,
        "verdict": "The model does NOT beat the naive baseline.",
    }

    context, blocks = chat.build_context(
        profile=profile,
        routing=routing,
        world_stats=world_stats,
        world_archetype="timeseries",
        forecast=forecast,
    )
    serialised = json.dumps(context, default=str)

    check(
        "the free-text sentinel never reaches the context",
        "SENTINEL-ROW-TEXT-QX7" not in serialised,
        "a row-level text value escaped into the LLM payload",
    )
    check(
        "no individual 'note' value reaches the context",
        not any(f"note-{i}" in serialised for i in range(40)),
    )
    check(
        "build_context has no DataFrame parameter",
        "df" not in chat.build_context.__code__.co_varnames,
        f"params: {chat.build_context.__code__.co_varnames[:chat.build_context.__code__.co_argcount]}",
    )
    check(
        "answer() has no DataFrame parameter either",
        "df" not in chat.answer.__code__.co_varnames,
    )
    check(
        "the categorical vocabulary IS present (a documented, bounded disclosure)",
        "North" in serialised,
    )
    check("block names are exactly what was supplied",
          blocks == ["profile", "routing", "timeseries_stats", "forecast_metrics"], str(blocks))

    # Without a world or forecast, those blocks must not be claimable at all.
    _, minimal = chat.build_context(profile=profile, routing=routing)
    check("no world/forecast -> only profile and routing", minimal == ["profile", "routing"],
          str(minimal))


def part2_plumbing() -> None:
    print("\n" + "=" * 72)
    print("PART 2: grounding validation and failure handling (stubbed model)")
    print("=" * 72)

    frame = fixture()
    profile = profile_dataframe(frame)
    routing = rule_based_route(profile, why="test")
    original = chat._call_model

    def restore():
        chat._call_model = original

    # --- a claimed source that was never supplied must be stripped -----------
    chat._call_model = lambda payload, key: json.dumps(
        {
            "answer": "The forecast beat the baseline by 12%.",
            "used": ["profile", "forecast_metrics", "some_block_that_does_not_exist"],
        }
    )
    result = chat.answer("did the forecast win?", profile, routing, api_key="test-key")
    check(
        "an unsupplied block is removed from grounded_on",
        result["grounded_on"] == ["profile"],
        str(result["grounded_on"]),
    )
    check("the reply itself is still returned", bool(result["reply"]))
    check("available is True", result["available"] is True)

    # --- grounded_on ordering follows the supplied order, not the model's ----
    chat._call_model = lambda payload, key: json.dumps(
        {"answer": "ok", "used": ["routing", "profile"]}
    )
    result = chat.answer("what is this?", profile, routing, api_key="test-key")
    check(
        "grounded_on order is stable (supplied order)",
        result["grounded_on"] == ["profile", "routing"],
        str(result["grounded_on"]),
    )

    # --- an empty used list survives as an empty list ------------------------
    chat._call_model = lambda payload, key: json.dumps(
        {"answer": "I only have the summary, not the rows.", "used": []}
    )
    result = chat.answer("what was row 12?", profile, routing, api_key="test-key")
    check("a declined answer reports no sources", result["grounded_on"] == [])
    check("a declined answer is still available=True", result["available"] is True)

    # --- markdown fences are stripped ---------------------------------------
    chat._call_model = lambda payload, key: (
        '```json\n{"answer": "Fenced but fine.", "used": ["profile"]}\n```'
    )
    result = chat.answer("hi", profile, routing, api_key="test-key")
    check("markdown fences are tolerated", result["reply"] == "Fenced but fine.", result["reply"])

    # --- unparseable output must NOT be passed off as an answer -------------
    chat._call_model = lambda payload, key: "Sure! The mean revenue is about 300."
    result = chat.answer("what is the mean?", profile, routing, api_key="test-key")
    check(
        "non-JSON output is not returned as the answer",
        "300" not in result["reply"],
        result["reply"],
    )
    check("non-JSON output marks chat unavailable", result["available"] is False)

    # --- an empty answer field is a failure, not an empty reply -------------
    chat._call_model = lambda payload, key: json.dumps({"answer": "  ", "used": ["profile"]})
    result = chat.answer("hello", profile, routing, api_key="test-key")
    check("an empty answer is treated as a failure", result["available"] is False)
    check("an empty answer reports no sources", result["grounded_on"] == [])

    # --- an API exception degrades to unavailable, never to a guess ---------
    # Raised as core.llm.LLMError because that is now the ONE type every
    # provider failure arrives as. The old version of this test constructed a
    # google-genai exception class, which meant the test could only prove the
    # app survived a Gemini outage -- and would have gone green while a
    # DeepSeek outage crashed the request.
    def boom(payload, key):
        raise llm.LLMError("simulated outage")

    chat._call_model = boom
    try:
        result = chat.answer("anything", profile, routing, api_key="test-key")
    except Exception as exc:  # noqa: BLE001 - the point is that this cannot happen
        check("an API error does not propagate", False, f"{type(exc).__name__}: {exc}")
        result = {"available": None, "grounded_on": None, "reply": ""}
    check("an API error is caught", result["available"] is False)
    check("an API error yields no sources", result["grounded_on"] == [])
    check("the unavailable message says so", "unavailable" in result["reply"].lower())

    restore()

    # --- no key at all -------------------------------------------------------
    # Which variable to unset depends on the configured provider, so it is
    # asked for rather than hard-coded. The previous version popped
    # GOOGLE_API_KEY unconditionally, which silently stopped testing anything
    # the moment the app was pointed at a different provider: the key was still
    # set, a model still answered, and the assertion that no key produces a
    # refusal was being made against a run that had one.
    key_var = {"deepseek": "DEEPSEEK_API_KEY", "gemini": "GOOGLE_API_KEY"}.get(
        llm.PROVIDER, "GOOGLE_API_KEY"
    )
    saved = os.environ.pop(key_var, None)
    try:
        result = chat.answer("anything", profile, routing)
        check("no API key -> unavailable, not a guess", result["available"] is False)
        check("no API key -> no sources claimed", result["grounded_on"] == [])
        check(
            "no API key -> the message names the cause",
            key_var in result["reply"],
            result["reply"],
        )
    finally:
        if saved is not None:
            os.environ[key_var] = saved

    # --- an empty question is answered locally, without a call --------------
    def must_not_be_called(payload, key):
        raise AssertionError("the model was called for an empty question")

    chat._call_model = must_not_be_called
    result = chat.answer("   ", profile, routing, api_key="test-key")
    check("an empty question does not reach the model", result["available"] is True)
    restore()


def part3_live_refusal() -> None:
    print("\n" + "=" * 72)
    print("PART 3: LIVE -- the model declines a question the context cannot answer")
    print("=" * 72)

    if not os.getenv("GOOGLE_API_KEY"):
        print("  [SKIP] no GOOGLE_API_KEY set. This is the test that proves the")
        print("         refusal behaviour end to end; it MUST be run with a key")
        print("         before the work is considered verified.")
        return

    frame = fixture()
    profile = profile_dataframe(frame)
    routing = rule_based_route(profile, why="live refusal test")
    world_stats = {
        "mean": 122.5, "min": 100.0, "max": 987654.321, "std": 3.2,
        "first_date": "2024-03-01T00:00:00", "last_date": "2024-04-09T00:00:00",
        "n_periods": 40, "trend_direction": "rising", "trend_slope_per_period": 1.0,
    }

    # The question is unanswerable BY CONSTRUCTION: a specific row's value is
    # not in any summary the assistant receives.
    result = chat.answer(
        "What exactly was the revenue on 3 March 2024? Give me the number.",
        profile,
        routing,
        world_stats=world_stats,
        world_archetype="timeseries",
    )

    if not result["available"]:
        print(f"  [SKIP] the API was unreachable, so the refusal could not be")
        print(f"         exercised: {result['reply']}")
        print("         Re-run when the API is available.")
        return

    reply = result["reply"]
    print(f"\n  Question: What exactly was the revenue on 3 March 2024?")
    print(f"  Reply:    {reply}\n")

    lowered = reply.lower()
    admits = any(
        phrase in lowered
        for phrase in (
            "only have", "do not have", "don't have", "cannot", "can't", "not able",
            "no access", "summary", "not in", "unable", "individual row", "row-level",
            "specific date", "does not include", "doesn't include", "not provided",
        )
    )
    check("the reply admits it cannot answer", admits, reply)

    # The exact figure for 3 March is 102.0 (100 + index 2). If the model states
    # it, it has computed a value from the series description -- which is the
    # single behaviour this module exists to prevent.
    fabricated = any(token in reply for token in ("102.0", "102 ", "£102", "$102"))
    check("the reply does not state a fabricated row value", not fabricated, reply)

    check(
        "a refusal claims no sources, or only the ones it was given",
        set(result["grounded_on"]) <= {"profile", "routing", "timeseries_stats"},
        str(result["grounded_on"]),
    )

    # A question the context CAN answer must still get a real answer, or the
    # refusal above proves only that the assistant is uselessly cautious.
    answerable = chat.answer(
        "How many rows and columns does this dataset have?",
        profile,
        routing,
        world_stats=world_stats,
        world_archetype="timeseries",
    )
    if answerable["available"]:
        print(f"  Control:  How many rows and columns?")
        print(f"  Reply:    {answerable['reply']}\n")
        check(
            "an answerable question gets the right number of rows",
            "40" in answerable["reply"],
            answerable["reply"],
        )
        check(
            "an answerable question names its sources",
            len(answerable["grounded_on"]) > 0,
            str(answerable["grounded_on"]),
        )
    else:
        print("  [SKIP] control question could not be run (API unavailable).")


def main() -> int:
    print("=" * 72)
    print("Chat assistant test suite -- core/chat.py")
    print("=" * 72)

    part1_structural()
    part2_plumbing()
    part3_live_refusal()

    print("\n" + "=" * 72)
    print(f"{FAILURES} check(s) FAILED" if FAILURES else "All checks passed")
    print("=" * 72)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
