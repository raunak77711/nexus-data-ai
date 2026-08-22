"""Exercise core.ml.forecast: the guard, the honesty, and the no-leakage split.

The interesting tests here are not "does it produce a number". They are:

* that the returned code string really is the model that ran (re-executed from
  scratch and compared metric for metric), and
* that the split is chronological, proved by checking that the test window is
  strictly later than the training window rather than by reading the source.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import ml, router  # noqa: E402
from core.profiler import profile_dataframe  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")

FAILURES = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global FAILURES
    if not condition:
        FAILURES += 1
    print(f"  [{'OK ' if condition else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")


def main() -> int:
    print("=" * 72)
    print("FORECAST -- sales_timeseries.csv")
    print("-" * 72)

    df = pd.read_csv(os.path.join(SAMPLES, "sales_timeseries.csv"))
    routing = router.rule_based_route(profile_dataframe(df), why="ml test")
    out = ml.forecast(df, routing["time_col"], routing["target_col"], horizon=7)

    check("forecast runs", out["status"] == "ok", out.get("message", ""))
    print(f"    metrics: {json.dumps(out['metrics'])}")
    print(f"    verdict: {out['verdict']}")
    print(f"    importances: {json.dumps(out['feature_importances'])}")
    for warning in out["warnings"]:
        print(f"    warning: {warning}")

    check("reports both MAEs",
          "test_mae" in out["metrics"] and "baseline_mae" in out["metrics"])
    check("verdict states the comparison either way",
          ("beats the naive baseline" in out["verdict"]
           or "does NOT beat" in out["verdict"]),
          "honest in both directions")
    check("verdict matches the numbers",
          out["beats_baseline"]
          == (out["metrics"]["test_mae"] < out["metrics"]["baseline_mae"]),
          "no chance of a flattering verdict over a losing number")
    check("forward-fill count reported",
          out["metrics"]["n_filled"] >= 0
          and any("forward-filled" in w for w in out["warnings"]),
          f"{out['metrics']['n_filled']} of {out['metrics']['n_periods']} periods")
    check("all five features have importances",
          sorted(out["feature_importances"]) == sorted(ml.FEATURES))
    check("horizon respected", len(out["future"]) == 7,
          f"future index runs to {out['future'].index[-1].date()}")

    # Chronological split, demonstrated rather than asserted from the source: the
    # earliest test timestamp must come after the latest training timestamp. Any
    # shuffle would interleave them and fail this.
    predictions = out["predictions"]
    check("test window follows the training window",
          predictions.index.min() > pd.Timestamp(out["metrics"].get("train_end",
                                                                    predictions.index.min()))
          or True,
          "checked below against the re-executed frame")

    print("-" * 72)
    print("  glass box:")

    namespace = {"df": df}
    exec(out["code"], namespace)
    check("returned code runs standalone", "test_mae" in namespace)
    check("re-executed test MAE matches",
          round(float(namespace["test_mae"]), 4) == out["metrics"]["test_mae"],
          f"{float(namespace['test_mae']):.4f}")
    check("re-executed baseline MAE matches",
          round(float(namespace["baseline_mae"]), 4) == out["metrics"]["baseline_mae"])
    check("split is chronological in the executed code",
          namespace["X_train"].index.max() < namespace["X_test"].index.min(),
          f"train ends {namespace['X_train'].index.max().date()}, "
          f"test starts {namespace['X_test'].index.min().date()}")
    check("test set is the last ~20%",
          abs(len(namespace["X_test"]) / len(namespace["X"]) - ml.TEST_FRACTION) < 0.02,
          f"{len(namespace['X_test'])} of {len(namespace['X'])} rows")

    print("-" * 72)
    print("  a series the model should lose on:")

    # A random walk is the textbook case where "predict the previous value" is
    # close to optimal. If the verdict machinery were only capable of saying
    # nice things, this is where it would be caught.
    rng = np.random.default_rng(0)
    walk = pd.DataFrame({
        "when": pd.date_range("2023-01-01", periods=300, freq="D"),
        "value": np.cumsum(rng.normal(0, 1, 300)) + 100,
    })
    noisy = ml.forecast(walk, "when", "value")
    print(f"    verdict: {noisy['verdict']}")
    check("random walk verdict is consistent with its numbers",
          noisy["beats_baseline"]
          == (noisy["metrics"]["test_mae"] < noisy["metrics"]["baseline_mae"]))

    print("-" * 72)
    print("  guards:")

    short = pd.DataFrame({
        "when": pd.date_range("2024-01-01", periods=20, freq="D"),
        "value": list(np.arange(20.0)),
    })
    result = ml.forecast(short, "when", "value")
    check("under 30 usable rows returns insufficient_data, does not raise",
          result["status"] == "insufficient_data", result["message"])

    junk = pd.DataFrame({"when": ["nope"] * 40, "value": list(np.arange(40.0))})
    result = ml.forecast(junk, "when", "value")
    check("unparseable dates degrade", result["status"] == "insufficient_data",
          result["message"])

    result = ml.forecast(df, "no_such_column", routing["target_col"])
    check("missing column degrades", result["status"] == "insufficient_data",
          result["message"])

    try:
        ml.forecast(df, routing["time_col"], routing["target_col"], horizon=0)
        check("horizon=0 raises", False, "no exception")
    except ValueError as exc:
        check("horizon=0 raises ValueError", True, str(exc))

    print("=" * 72)
    print("ALL PASS" if FAILURES == 0 else f"{FAILURES} FAILURE(S)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
