"""Profile the three sample CSVs and assert the semantic types are correct.

Assertions rather than eyeballing: the point of this script is to be re-runnable
evidence that the heuristics still hold after a change to profiler.py.

Part 2 covers the small-file categorical case with synthetic frames. It is
synthetic on purpose: the sample CSVs are all >=300 rows, so they cannot
exercise the row-count gate at all, and the bug being guarded against is
specifically one of sample size.
"""

from __future__ import annotations

import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.profiler import profile_column, profile_dataframe  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")

# path -> {column: expected semantic_type}
EXPECTATIONS = {
    "sales_timeseries.csv": {
        "order_date": "datetime",
        "revenue": "numeric",
        "units": "numeric",
        "region": "categorical",
        "channel": "categorical",
    },
    "air_quality_geo.csv": {
        "station_id": "text",
        "latitude": "geo_lat",
        "longitude": "geo_lon",
        "reading_ts": "datetime",
        "pm25": "numeric",
        "latency": "numeric",  # decoy must NOT become geo_lat
        "sensor_type": "categorical",
    },
    "employees_tabular.csv": {
        "employee_id": "numeric",
        "department": "categorical",
        "salary": "numeric",
        "years_experience": "numeric",
        "satisfaction": "categorical",  # numeric-coded category
        "notes": "text",
    },
}

EXPECTED_FLAGS = {
    "sales_timeseries.csv": {"has_datetime": True, "has_geo": False},
    "air_quality_geo.csv": {"has_datetime": True, "has_geo": True},
    "employees_tabular.csv": {"has_datetime": False, "has_geo": False},
}


def part1_samples() -> int:
    failures = 0
    for filename, expected in EXPECTATIONS.items():
        path = os.path.join(SAMPLES, filename)
        df = pd.read_csv(path)
        profile = profile_dataframe(df)

        print("=" * 70)
        print(f"{filename}  ({profile['n_rows']} rows x {profile['n_cols']} cols)")
        print(
            f"  has_datetime={profile['has_datetime']}  "
            f"has_geo={profile['has_geo']}  n_numeric={profile['n_numeric']}"
        )
        print("-" * 70)

        for col in profile["columns"]:
            name, got = col["name"], col["semantic_type"]
            want = expected.get(name)
            ok = "OK " if got == want else "FAIL"
            if got != want:
                failures += 1
            extra = {k: v for k, v in col.items() if k not in ("name", "semantic_type", "dtype")}
            print(f"  [{ok}] {name:<18} {got:<12} (want {want})")
            print(f"         {json.dumps(extra, default=str)[:110]}")

        for flag, want in EXPECTED_FLAGS[filename].items():
            if profile[flag] != want:
                failures += 1
                print(f"  [FAIL] flag {flag}: got {profile[flag]}, want {want}")

    return failures


def part2_small_files() -> int:
    """Prove the row-count gate on the ratio rule, in both directions.

    The regression: with the ratio applied unconditionally, a 100-row file
    allowed at most 4 distinct values (0.05 * 100), so an ordinary 6-region
    column came back as "text" and every entity-split chart silently vanished.
    The gate must fix that WITHOUT reopening the hole the ratio exists to
    close -- so a small file's unique-per-row ID must still be rejected, and a
    large file must still have the ratio applied.
    """
    print("=" * 70)
    print("PART 2: small-file categorical detection")
    print("-" * 70)

    failures = 0

    def check(label: str, series: pd.Series, want: str) -> None:
        nonlocal failures
        n_rows = len(series)
        got = profile_column(series, series.name, n_rows)["semantic_type"]
        ok = got == want
        if not ok:
            failures += 1
        print(f"  [{'OK ' if ok else 'FAIL'}] {str(series.name):<22} "
              f"n_rows={n_rows:<5} n_unique={series.nunique():<5} "
              f"got={got:<12} (want {want})")

    # THE FIX: 100 rows, 6 regions. Ratio would be 6/100 = 0.06, over the 0.05
    # threshold, so the old rule called this text. It is obviously a category.
    check("small file, 6 regions",
          pd.Series(["North", "South", "East", "West", "Mid", "NW"] * 17,
                    name="region").head(100),
          "categorical")

    # The absolute cap must still bite below 200 rows: 100 unique IDs in 100
    # rows is a key, not a category.
    check("small file, unique ids",
          pd.Series([f"CUST{i:04d}" for i in range(100)], name="customer_code"),
          "text")

    # 21 distinct values in a 100-row file exceeds CATEGORICAL_MAX_UNIQUE, so
    # the cap rejects it even though the gate skipped the ratio.
    check("small file, 21 values",
          pd.Series([f"v{i % 21}" for i in range(100)], name="too_many"),
          "text")

    # Above the gate the ratio is back in force: 20 distinct values in 300 rows
    # is 0.067, over threshold, so this is NOT a category despite passing the
    # absolute cap. This is the assertion that proves the gate is a gate and
    # not a removal of the ratio rule.
    check("large file, ratio applies",
          pd.Series([f"v{i % 20}" for i in range(300)], name="above_gate"),
          "text")

    # And the same vocabulary in a genuinely large file repeats often enough to
    # pass both tests.
    check("large file, ratio passes",
          pd.Series([f"v{i % 20}" for i in range(1000)], name="well_repeated"),
          "categorical")

    return failures


def main() -> int:
    failures = part1_samples() + part2_small_files()
    print("=" * 70)
    print("ALL PASS" if failures == 0 else f"{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
