"""Profile the three sample CSVs and assert the semantic types are correct.

Assertions rather than eyeballing: the point of this script is to be re-runnable
evidence that the heuristics still hold after a change to profiler.py.
"""

from __future__ import annotations

import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.profiler import profile_dataframe  # noqa: E402

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


def main() -> int:
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

    print("=" * 70)
    print("ALL PASS" if failures == 0 else f"{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
