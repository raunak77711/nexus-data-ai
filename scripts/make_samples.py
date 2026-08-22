"""Generate three sample CSVs, one per archetype, into samples/.

Kept as a script rather than committed CSVs so the repo stays small and the
data generating process itself is inspectable -- a reviewer can see exactly
what the profiler was tested against, including the deliberately dirty rows.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
rng = np.random.default_rng(42)


def timeseries_csv(path: str) -> None:
    """Daily sales with trend + weekly seasonality, mixed date formats, dirty rows."""
    n = 400
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    trend = np.linspace(100, 260, n)
    weekly = 25 * np.sin(np.arange(n) * 2 * np.pi / 7)
    noise = rng.normal(0, 12, n)

    # Mixed formats + a few unparseable cells, to exercise the 80% threshold.
    date_strings = [d.strftime("%Y-%m-%d") if i % 3 else d.strftime("%d/%m/%Y") for i, d in enumerate(dates)]
    for i in (10, 50, 123):
        date_strings[i] = "N/A"

    pd.DataFrame(
        {
            "order_date": date_strings,
            "revenue": np.round(trend + weekly + noise, 2),
            "units": rng.integers(1, 40, n),
            "region": rng.choice(["North", "South", "East", "West"], n),
            "channel": rng.choice(["online", "retail"], n),
        }
    ).to_csv(path, index=False)


def geo_csv(path: str) -> None:
    """Sensor readings with coordinates, plus 'latency' as a name-only decoy."""
    n = 300
    pd.DataFrame(
        {
            "station_id": [f"ST{i:04d}" for i in range(n)],
            "latitude": np.round(rng.uniform(50.0, 58.5, n), 5),
            "longitude": np.round(rng.uniform(-6.0, 1.7, n), 5),
            "reading_ts": pd.date_range("2024-01-01", periods=n, freq="h").astype(str),
            "pm25": np.round(rng.gamma(2.0, 6.0, n), 2),
            "latency": np.round(rng.uniform(5, 80, n), 1),  # decoy: name-ish, out of range
            "sensor_type": rng.choice(["A", "B", "C"], n),
        }
    ).to_csv(path, index=False)


def tabular_csv(path: str) -> None:
    """Purely cross-sectional: no dates, no coordinates, one numeric-coded category."""
    n = 600
    pd.DataFrame(
        {
            "employee_id": np.arange(1000, 1000 + n),
            "department": rng.choice(["Eng", "Sales", "HR", "Ops", "Finance"], n),
            "salary": np.round(rng.normal(52000, 14000, n), 0),
            "years_experience": np.round(rng.uniform(0, 30, n), 1),
            "satisfaction": rng.integers(1, 6, n),  # numeric-coded category, 5 values
            "notes": [f"Review note number {i} for the annual cycle" for i in range(n)],
        }
    ).to_csv(path, index=False)


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    timeseries_csv(os.path.join(OUT_DIR, "sales_timeseries.csv"))
    geo_csv(os.path.join(OUT_DIR, "air_quality_geo.csv"))
    tabular_csv(os.path.join(OUT_DIR, "employees_tabular.csv"))
    print(f"Wrote 3 sample CSVs to {OUT_DIR}")
