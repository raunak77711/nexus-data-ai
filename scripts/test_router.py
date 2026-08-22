"""Exercise the router on the sample datasets, and prove the failure paths.

Part 1 calls route() for real. With GOOGLE_API_KEY set that hits Gemini; without
one it must still return a usable routing marked source="fallback".

Part 2 stubs _call_gemini to prove the parts that only misbehave in production:
fence-stripping, hallucinated-column repair, and an API exception degrading to
the rules instead of propagating. These cannot be tested against the live API,
which is exactly why they are the parts most likely to be wrong.
"""

from __future__ import annotations

import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import router  # noqa: E402
from core.profiler import profile_dataframe  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
FILES = ["sales_timeseries.csv", "air_quality_geo.csv", "employees_tabular.csv"]
EXPECTED_ARCHETYPE = {
    "sales_timeseries.csv": "timeseries",
    "air_quality_geo.csv": "geo",
    "employees_tabular.csv": "tabular",
}


def part1_live() -> int:
    key_state = "SET" if os.getenv("GOOGLE_API_KEY") else "NOT SET"
    print(f"\n{'=' * 72}\nPART 1: route() end to end   [GOOGLE_API_KEY {key_state}]\n{'=' * 72}")

    failures = 0
    for name in FILES:
        profile = profile_dataframe(pd.read_csv(os.path.join(SAMPLES, name)))
        routing = router.route(profile)
        want = EXPECTED_ARCHETYPE[name]
        ok = routing["archetype"] == want
        failures += 0 if ok else 1

        print(f"\n--- {name} ---")
        print(json.dumps(routing, indent=2))
        print(f"  archetype {'OK' if ok else 'FAIL'} (want {want}), source={routing['source']}")
    return failures


def part2_stubbed() -> int:
    print(f"\n{'=' * 72}\nPART 2: stubbed LLM responses (failure paths)\n{'=' * 72}")

    profile = profile_dataframe(pd.read_csv(os.path.join(SAMPLES, "sales_timeseries.csv")))
    original = router._call_gemini
    failures = 0

    def check(label: str, condition: bool, detail: str = "") -> None:
        nonlocal failures
        if not condition:
            failures += 1
        print(f"  [{'OK ' if condition else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")

    cases = {
        "fenced JSON is recovered": (
            '```json\n{"archetype":"timeseries","time_col":"order_date",'
            '"entity_col":"region","target_col":"revenue","lat_col":null,'
            '"lon_col":null,"reasoning":"Revenue over time."}\n```'
        ),
        "hallucinated column is repaired": (
            '{"archetype":"timeseries","time_col":"invented_date_col",'
            '"entity_col":"region","target_col":"revenue","lat_col":null,'
            '"lon_col":null,"reasoning":"Uses a column that does not exist."}'
        ),
        "unknown archetype falls back": (
            '{"archetype":"network","time_col":null,"entity_col":null,'
            '"target_col":null,"lat_col":null,"lon_col":null,"reasoning":"bad"}'
        ),
        "non-JSON prose falls back": "Sure! I think this is a timeseries dataset.",
    }

    try:
        for label, payload in cases.items():
            router._call_gemini = lambda _s, _k, _p=payload: _p
            result = router.route(profile, api_key="stub-key")
            print(f"\n{label}:")
            print(f"  -> archetype={result['archetype']} source={result['source']} "
                  f"time_col={result['time_col']} target_col={result['target_col']}")

            if label.startswith("fenced"):
                check(label, result["source"] == "llm" and result["time_col"] == "order_date")
            elif label.startswith("hallucinated"):
                check(
                    label,
                    result["source"] == "llm" and result["time_col"] == "order_date",
                    "invalid name replaced by the rule-based pick, archetype kept",
                )
            else:
                check(label, result["source"] == "fallback", "degraded, did not raise")

        # An API exception must degrade, not propagate.
        def boom(_summary: str, _key: str) -> str:
            from google.api_core import exceptions as ge

            raise ge.ResourceExhausted("quota exceeded")

        router._call_gemini = boom
        result = router.route(profile, api_key="stub-key")
        print("\nAPI raises ResourceExhausted:")
        print(f"  -> archetype={result['archetype']} source={result['source']}")
        check("API error degrades to rules", result["source"] == "fallback")
    finally:
        router._call_gemini = original

    return failures


if __name__ == "__main__":
    total = part1_live() + part2_stubbed()
    print(f"\n{'=' * 72}")
    print("ALL PASS" if total == 0 else f"{total} FAILURE(S)")
    raise SystemExit(1 if total else 0)
