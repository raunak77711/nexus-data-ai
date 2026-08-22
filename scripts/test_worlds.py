"""Exercise the world builders: happy paths, degradation paths, and the glass box.

The most important check here is check_code_is_real(). The project's claim is
that the code shown under every figure is the code that produced it. That claim
is worth nothing unless it is tested, so every returned snippet is re-executed
in a *fresh* namespace containing only `df`, and the resulting figure is compared
to the returned one as JSON. If a snippet were pseudocode, truncated, or subtly
different from the real path, this fails.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd
import plotly.graph_objects as go

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import router  # noqa: E402
from core.profiler import profile_dataframe  # noqa: E402
from core.worlds import geo, timeseries  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")

FAILURES = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global FAILURES
    if not condition:
        FAILURES += 1
    print(f"  [{'OK ' if condition else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")


def load(name: str) -> tuple:
    """Load a sample and route it with the rules, not the LLM.

    WHY rule-based here: these tests assert on specific columns, and the point
    under test is the world builder, not the router. Pinning routing keeps a
    world test from failing because the model picked a different-but-valid
    target column that week.
    """
    df = pd.read_csv(os.path.join(SAMPLES, name))
    return df, router.rule_based_route(profile_dataframe(df), why="world test")


def check_code_is_real(world_name: str, df: pd.DataFrame, out: dict) -> None:
    """Re-run every returned snippet from scratch and compare to the shipped figure.

    A fresh dict is used as the namespace so the snippet cannot lean on anything
    the builder happened to leave lying around -- exactly the position a user is
    in when they paste it into a notebook with only `df` defined.
    """
    for name, code in out["code"].items():
        namespace = {"df": df}
        try:
            exec(code, namespace)
        except Exception as exc:  # noqa: BLE001 - the whole point is to report any failure
            check(f"{world_name}.{name} snippet runs", False, f"{type(exc).__name__}: {exc}")
            continue

        replayed = namespace.get("fig")
        if not isinstance(replayed, go.Figure):
            check(f"{world_name}.{name} snippet runs", False, "did not produce a Figure")
            continue

        same = replayed.to_json() == out["figures"][name].to_json()
        check(
            f"{world_name}.{name} snippet reproduces the figure",
            same,
            "byte-identical plotly JSON" if same else "REPLAY DIFFERS FROM SHIPPED FIGURE",
        )


def test_timeseries() -> None:
    print("=" * 72)
    print("TIMESERIES")
    print("-" * 72)

    df, routing = load("sales_timeseries.csv")
    out = timeseries.build(df, routing, freq="D")

    check("builds", out["status"] == "ok")
    check("has main figure", "main" in out["figures"])
    check("has entity split", "by_entity" in out["figures"])
    check(
        "unparseable dates reported",
        any("could not be parsed" in w for w in out["warnings"]),
        out["warnings"][0] if out["warnings"] else "no warning emitted",
    )
    check("trend from slope", out["stats"]["trend_direction"] in ("rising", "falling", "flat"))
    print(f"    stats: {json.dumps(out['stats'])}")
    check_code_is_real("timeseries", df, out)

    for freq in ("D", "W", "M"):
        result = timeseries.build(df, routing, freq=freq)
        check(f"freq={freq} builds", result["status"] == "ok",
              f"{result['stats'].get('n_periods')} periods")
        check_code_is_real(f"timeseries[{freq}]", df, result)

    # A single outlier at the end must not flip the reported direction. This is
    # the concrete failure a first-vs-last comparison has and a slope does not.
    rising = pd.DataFrame({
        "when": pd.date_range("2024-01-01", periods=60, freq="D"),
        "value": list(np.arange(60, dtype=float)),
    })
    rising.loc[59, "value"] = -500.0  # one catastrophic final reading
    spiked = timeseries.build(rising, {"time_col": "when", "target_col": "value"})
    check(
        "outlier at the end does not flip the trend",
        spiked["stats"]["trend_direction"] == "rising",
        f"got {spiked['stats']['trend_direction']} "
        f"(first-vs-last would say 'falling': {rising['value'].iloc[0]} -> "
        f"{rising['value'].iloc[-1]})",
    )

    print("-" * 72)
    print("  degradation:")

    all_null = pd.DataFrame({
        "when": pd.date_range("2024-01-01", periods=10, freq="D"),
        "value": [None] * 10,
    })
    result = timeseries.build(all_null, {"time_col": "when", "target_col": "value"})
    check("all-null target degrades", result["status"] == "insufficient_data", result["message"])

    one_day = pd.DataFrame({
        "when": ["2024-01-01", "2024-01-01"],
        "value": [1.0, 2.0],
    })
    result = timeseries.build(one_day, {"time_col": "when", "target_col": "value"}, freq="M")
    check("<2 periods degrades", result["status"] == "insufficient_data", result["message"])

    junk = pd.DataFrame({"when": ["nope", "also nope"], "value": [1.0, 2.0]})
    result = timeseries.build(junk, {"time_col": "when", "target_col": "value"})
    check("no parseable dates degrades", result["status"] == "insufficient_data",
          result["message"])

    result = timeseries.build(df, {**routing, "time_col": None})
    check("missing time_col degrades", result["status"] == "insufficient_data",
          result["message"])

    no_entity = timeseries.build(df, {**routing, "entity_col": None})
    check("no entity_col still builds", no_entity["status"] == "ok"
          and "by_entity" not in no_entity["figures"], "main figure only")

    try:
        timeseries.build(df, routing, freq="Q")
        check("bad freq raises", False, "no exception")
    except ValueError as exc:
        check("bad freq raises ValueError", True, str(exc))


def test_geo() -> None:
    print("=" * 72)
    print("GEO")
    print("-" * 72)

    df, routing = load("air_quality_geo.csv")
    out = geo.build(df, routing)

    check("builds", out["status"] == "ok")
    check("has map", "map" in out["figures"])
    check("zoom is computed, not hardcoded", out["stats"]["zoom"] != geo.DEFAULT_ZOOM,
          f"zoom={out['stats']['zoom']} from bounds {out['stats']['bounds']}")
    print(f"    stats: {json.dumps(out['stats'])}")
    check_code_is_real("geo", df, out)

    # Time filter must actually reduce the point count.
    time_col = routing["time_col"]
    stamps = pd.to_datetime(df[time_col], errors="coerce", format="mixed").dropna()
    midpoint = stamps.min() + (stamps.max() - stamps.min()) / 2
    filtered = geo.build(df, routing, time_filter=(stamps.min(), midpoint))
    check(
        "time_filter reduces the points plotted",
        filtered["stats"]["n_points"] < out["stats"]["n_points"],
        f"{out['stats']['n_points']} -> {filtered['stats']['n_points']}",
    )
    check_code_is_real("geo[filtered]", df, filtered)

    print("-" * 72)
    print("  degradation:")

    nulls = df.copy()
    nulls.loc[:99, routing["lat_col"]] = None
    result = geo.build(nulls, routing)
    check("null coordinates dropped and reported",
          any("coordinate" in w for w in result["warnings"]),
          result["warnings"][0] if result["warnings"] else "no warning")

    identical = pd.DataFrame({
        "lat": [51.5] * 20, "lon": [-0.12] * 20, "pm25": list(range(20)),
    })
    result = geo.build(identical, {"lat_col": "lat", "lon_col": "lon", "target_col": "pm25"})
    check("identical points do not produce infinite zoom",
          result["status"] == "ok" and result["stats"]["zoom"] == geo.DEFAULT_ZOOM,
          f"fell back to DEFAULT_ZOOM={geo.DEFAULT_ZOOM}")
    check_code_is_real("geo[identical]", identical, result)

    empty = pd.DataFrame({"lat": [None] * 5, "lon": [None] * 5, "pm25": [1, 2, 3, 4, 5]})
    result = geo.build(empty, {"lat_col": "lat", "lon_col": "lon", "target_col": "pm25"})
    check("all-null coordinates degrade", result["status"] == "insufficient_data",
          result["message"])


if __name__ == "__main__":
    test_timeseries()
    test_geo()
    print("=" * 72)
    print("ALL PASS" if FAILURES == 0 else f"{FAILURES} FAILURE(S)")
    raise SystemExit(1 if FAILURES else 0)
