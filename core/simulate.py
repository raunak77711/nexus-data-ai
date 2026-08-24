"""What-if: move one number and say what happens to another, without pretending.

WHY THIS IS SMALL ON PURPOSE
----------------------------
"What if sales go up 20%?" is the question every dashboard demo wants to answer
and almost none can answer honestly. A real answer needs a causal model, and a
causal model needs an experiment nobody ran. What is available here is a
historical relationship between two columns, which is a different and weaker
thing.

So this module does exactly two things, and says which one it did:

  DIRECT      -- the measure is changed by hand. "Revenue is 71,975 today; 20%
                 more is 86,370." That is arithmetic, and it is labelled as
                 arithmetic. Its value is not insight, it is a calculator that
                 knows your column totals.

  RELATIONSHIP -- one column is moved and another is projected from the
                 straight line that best fits their history. That is a real
                 estimate, and it comes with the strength of the fit attached,
                 because a projection through a weak relationship is a number
                 with no information in it.

And it refuses a third thing: projecting through a relationship too weak to
carry one. Below MIN_CORRELATION the answer is "these two do not move together
closely enough to predict one from the other", which is more useful than a
confidently-drawn line through a cloud of noise.

Every returned figure carries the caveats that apply to it. The UI shows them
next to the number rather than behind a tooltip -- a projection whose
assumptions are hidden is a projection being passed off as a measurement.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from core.router import ID_PATTERN

logger = logging.getLogger(__name__)

# Below this, one column tells you almost nothing about the other, and a
# straight line fitted between them is a decoration.
MIN_CORRELATION = 0.3

# Rows both columns must share before a fit is worth reporting.
MIN_ROWS = 20

# The slider's range. Wider than this and the projection is being extrapolated
# far outside the data it was fitted on, where a straight line is least
# trustworthy.
MIN_PCT = -90.0
MAX_PCT = 200.0


def _fmt(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if abs(value) >= 10:
        return f"{value:,.1f}"
    return f"{value:,.2f}"


def _friendly(name: str) -> str:
    return str(name).replace("_", " ").strip()


def _numeric_columns(df: pd.DataFrame, profile: Dict[str, Any]) -> List[str]:
    """Columns a slider could sensibly move: real measures, not codes or keys."""
    out = []
    for column in profile.get("columns", []):
        name = column.get("name")
        if column.get("semantic_type") != "numeric" or name not in df.columns:
            continue
        # An id is numeric and has no business on a what-if slider: "what if
        # every employee_id went up 20%" is not a question about anything.
        if ID_PATTERN.search(str(name)):
            continue
        values = pd.to_numeric(df[name], errors="coerce").dropna()
        if len(values) >= MIN_ROWS and values.nunique() > 5:
            out.append(str(name))
    return out


def options(df: pd.DataFrame, profile: Dict[str, Any], routing: Dict[str, Any]) -> Dict[str, Any]:
    """What the UI may offer: which columns can be moved, and what to move first.

    Returned as its own call so the panel can render its controls before the
    user has chosen anything, without running a projection nobody asked for.
    """
    numeric = _numeric_columns(df, profile)
    target = routing.get("target_col") if routing.get("target_col") in numeric else None
    if target is None and numeric:
        target = numeric[0]

    return {
        "available": bool(numeric),
        "columns": numeric,
        "default_target": target,
        # A driver worth suggesting is one that actually moves with the target.
        "suggested_driver": _best_driver(df, numeric, target) if target else None,
        "min_pct": MIN_PCT,
        "max_pct": MAX_PCT,
    }


def _best_driver(df: pd.DataFrame, numeric: List[str], target: str) -> Optional[str]:
    """The column most strongly linked to the target, if any is linked at all."""
    best, best_strength = None, MIN_CORRELATION
    target_values = pd.to_numeric(df[target], errors="coerce")
    for name in numeric:
        if name == target:
            continue
        frame = pd.DataFrame(
            {"a": pd.to_numeric(df[name], errors="coerce"), "b": target_values}
        ).dropna()
        if len(frame) < MIN_ROWS:
            continue
        r = frame["a"].corr(frame["b"])
        if pd.notna(r) and abs(float(r)) > best_strength:
            best, best_strength = name, abs(float(r))
    return best


def simulate(
    df: pd.DataFrame,
    profile: Dict[str, Any],
    routing: Dict[str, Any],
    pct_change: float,
    target: Optional[str] = None,
    driver: Optional[str] = None,
) -> Dict[str, Any]:
    """Project the effect of changing one column by a percentage.

    Args:
        df: the session's DataFrame.
        profile: core.profiler output.
        routing: core.router output -- supplies the default target.
        pct_change: how much to move the driver, in percent. Clamped to
            [MIN_PCT, MAX_PCT] rather than rejected, because the slider is the
            only thing that produces this value and clamping is what a slider
            means.
        target: the column to project. Defaults to the routed measure.
        driver: the column to move. Defaults to the target itself, which is the
            direct case.

    Returns:
        {"status": "ok"|"unsupported", "message": str, ...} -- see the module
        docstring for the two modes. "unsupported" is a normal outcome, not an
        error: a dataset with one numeric column has nothing to simulate, and
        saying so is the right answer.

    Never raises for a data condition. Bad column names produce "unsupported"
    with a sentence naming the column, because this is reached from a UI control
    whose state can be one dataset behind.
    """
    numeric = _numeric_columns(df, profile)
    if not numeric:
        return {
            "status": "unsupported",
            "message": (
                "This dataset has no numeric measure that could be moved up or "
                "down, so there is nothing to simulate."
            ),
            "caveats": [],
        }

    target = target or routing.get("target_col") or numeric[0]
    if target not in numeric:
        return {
            "status": "unsupported",
            "message": (
                f"{target!r} is not a numeric measure in this dataset, so it "
                f"cannot be projected."
            ),
            "caveats": [],
        }

    driver = driver or target
    if driver not in numeric:
        return {
            "status": "unsupported",
            "message": f"{driver!r} is not a numeric measure that can be moved.",
            "caveats": [],
        }

    pct = float(max(MIN_PCT, min(MAX_PCT, float(pct_change))))
    factor = 1.0 + pct / 100.0

    target_values = pd.to_numeric(df[target], errors="coerce").dropna()
    base_total = float(target_values.sum())
    base_mean = float(target_values.mean())

    # ------------------------------------------------------------- direct --
    if driver == target:
        caveats = [
            f"This is a straight {abs(pct):.0f}% "
            f"{'increase' if pct >= 0 else 'decrease'} applied to every "
            f"{_friendly(target)} value. It assumes nothing else in the data "
            f"changes as a result.",
        ]
        return {
            "status": "ok",
            "basis": "direct",
            "target": target,
            "driver": driver,
            "pct_change": round(pct, 2),
            "baseline": {"total": round(base_total, 2), "average": round(base_mean, 2)},
            "projected": {
                "total": round(base_total * factor, 2),
                "average": round(base_mean * factor, 2),
            },
            "delta": {
                "total": round(base_total * factor - base_total, 2),
                "average": round(base_mean * factor - base_mean, 2),
                "pct": round(pct, 2),
            },
            "rows_used": int(len(target_values)),
            "confidence": None,
            "message": (
                f"If every {_friendly(target)} value moved by {pct:+.0f}%, the "
                f"total would go from {_fmt(base_total)} to "
                f"{_fmt(base_total * factor)}."
            ),
            "caveats": caveats,
        }

    # ------------------------------------------------------- relationship --
    frame = pd.DataFrame(
        {
            "driver": pd.to_numeric(df[driver], errors="coerce"),
            "target": pd.to_numeric(df[target], errors="coerce"),
        }
    ).dropna()

    if len(frame) < MIN_ROWS:
        return {
            "status": "unsupported",
            "message": (
                f"Only {len(frame)} row(s) have both {_friendly(driver)} and "
                f"{_friendly(target)}, which is too few to estimate how one "
                f"affects the other."
            ),
            "caveats": [],
        }

    r = float(frame["driver"].corr(frame["target"]))
    if not np.isfinite(r) or abs(r) < MIN_CORRELATION:
        return {
            "status": "unsupported",
            "message": (
                f"{_friendly(driver).capitalize()} and {_friendly(target)} do not "
                f"move together closely enough to predict one from the other. "
                f"Changing {_friendly(driver)} would tell us nothing reliable "
                f"about {_friendly(target)}."
            ),
            "caveats": [
                "NEXUS will not draw a projection through a relationship this "
                "weak, because the resulting number would look precise and mean "
                "nothing."
            ],
        }

    # The straight line that best fits the history, and the shift along it that
    # the requested change in the driver implies. Only the SLOPE is used --
    # applying the intercept would re-predict the target from scratch and throw
    # away what it actually is today.
    slope, _intercept = np.polyfit(frame["driver"], frame["target"], 1)
    driver_mean = float(frame["driver"].mean())
    driver_shift = driver_mean * (factor - 1.0)
    target_shift_per_row = float(slope) * driver_shift

    projected_mean = base_mean + target_shift_per_row
    projected_total = projected_mean * len(target_values)
    change_pct = (
        100.0 * (projected_mean - base_mean) / abs(base_mean) if base_mean else 0.0
    )

    strength = "very close" if abs(r) >= 0.75 else ("clear" if abs(r) >= 0.5 else "weak")
    caveats = [
        f"This projection assumes {_friendly(target)} keeps responding to "
        f"{_friendly(driver)} the way it has historically.",
        f"The link between them is {strength} — they explain about "
        f"{100 * r * r:.0f}% of each other's movement across "
        f"{len(frame):,} rows.",
        "A relationship in past data is not proof that one causes the other.",
    ]
    if abs(r) < 0.5:
        caveats.append(
            "Because the link is weak, treat this as the direction of travel "
            "rather than a figure to plan against."
        )

    return {
        "status": "ok",
        "basis": "relationship",
        "target": target,
        "driver": driver,
        "pct_change": round(pct, 2),
        "baseline": {"total": round(base_total, 2), "average": round(base_mean, 2)},
        "projected": {
            "total": round(projected_total, 2),
            "average": round(projected_mean, 2),
        },
        "delta": {
            "total": round(projected_total - base_total, 2),
            "average": round(projected_mean - base_mean, 2),
            "pct": round(change_pct, 2),
        },
        "rows_used": int(len(frame)),
        "confidence": {
            "correlation": round(r, 3),
            "explains_pct": round(100 * r * r, 1),
            "strength": strength,
            "rows": int(len(frame)),
        },
        "message": (
            f"If {_friendly(driver)} moved {pct:+.0f}%, {_friendly(target)} would be "
            f"expected to move {change_pct:+.1f}% — a total of about "
            f"{_fmt(projected_total)} against {_fmt(base_total)} today."
        ),
        "caveats": caveats,
    }
