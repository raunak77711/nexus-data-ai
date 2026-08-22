"""Forecasting: a small, honest baseline model for a single timeseries.

The design goal is not accuracy, it is defensibility. Three things follow from
that, and each is enforced in the code below rather than left to good intentions:

1. The split is chronological. Shuffling a timeseries is the single most common
   way to produce an impressive number that means nothing.
2. Every score is reported next to a naive baseline. A MAE quoted alone is
   uninterpretable -- the reader has no idea whether it is good.
3. The verdict says out loud when the model loses to that baseline. A forecast
   the user cannot trust is only dangerous if they do not know it.

As with the world builders, the returned code string is executed to produce the
returned results, so the "Show the code" panel is the model that actually ran
rather than a description of it. See core/worlds/_glassbox.py.
"""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from core.worlds import _glassbox

# Rows in the modelling frame (after resampling and feature construction) below
# which a forecast is not worth producing. WHY 30: the features include a 7-day
# lag and a 7-day rolling mean, so the model needs several complete weekly
# cycles before it has seen each day-of-week more than once. With a 20% test
# split, 30 rows means 24 training rows and 6 test rows -- already thin, and the
# point at which the MAE itself becomes too noisy to compare against a baseline.
MIN_ROWS = 30

# Fraction of the series held back, taken from the end.
TEST_FRACTION = 0.20

# Above this share of forward-filled periods the series is mostly invention and
# the forecast should be read as such.
HEAVY_FILL_WARNING = 0.30

FEATURES = ["lag_1", "lag_7", "rolling_mean_7", "day_of_week", "month"]


FORECAST_TEMPLATE = """
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error

# ---------------------------------------------------------------- prepare ----
data = df[[$time_col, $target_col]].copy()
data[$time_col] = pd.to_datetime(data[$time_col], errors='coerce', format='mixed')
data[$target_col] = pd.to_numeric(data[$target_col], errors='coerce')
data = data.dropna(subset=[$time_col, $target_col]).sort_values($time_col)

# Resample to a regular daily grid. A model with lag features assumes the gap
# between consecutive rows is constant; feeding it irregular rows would make
# 'lag_1' mean "yesterday" on one row and "three weeks ago" on the next.
series = data.set_index($time_col)[$target_col].resample('D').mean()

# Forward-fill the resulting gaps: a day with no observation inherits the last
# known value. This is the assumption that the measure persists, which is mild
# for a stock (a price, a level) and wrong for a flow (a daily total, where no
# observation may really mean zero). $n_filled of $n_periods periods here were
# filled this way -- the more that were, the more of the "data" below is really
# an assumption.
series = series.ffill().dropna()

# ---------------------------------------------------------------- features ---
frame = pd.DataFrame({'y': series})
frame['lag_1'] = frame['y'].shift(1)
frame['lag_7'] = frame['y'].shift(7)

# shift(1) BEFORE rolling, not after. Without the shift the 7-day window would
# include today's value, so the model would be given part of the answer it is
# being asked to predict -- the resulting MAE would look excellent and would not
# survive contact with a real unseen day.
frame['rolling_mean_7'] = frame['y'].shift(1).rolling(window=7).mean()

frame['day_of_week'] = frame.index.dayofweek
frame['month'] = frame.index.month
frame = frame.dropna()

features = $features
X = frame[features]
y = frame['y']

# ------------------------------------------------------------------ split ----
# CHRONOLOGICAL split: the last $test_fraction of rows, in time order, are the
# test set. Never use train_test_split(shuffle=True) on a timeseries. Shuffling
# scatters future rows into the training set, and because neighbouring days are
# highly correlated the model can effectively look up the answer -- it learns to
# interpolate between two known points either side of a "test" day instead of
# extrapolating past the end of what it has seen. The score that produces is
# large, flattering, and completely unrelated to forecasting performance.
split = int(len(frame) * (1 - $test_fraction))
X_train, X_test = X.iloc[:split], X.iloc[split:]
y_train, y_test = y.iloc[:split], y.iloc[split:]

# ------------------------------------------------------------------ model ----
model = RandomForestRegressor(n_estimators=100, random_state=42)
model.fit(X_train, y_train)
predictions = model.predict(X_test)

# ----------------------------------------------------------------- verdict ---
test_mae = mean_absolute_error(y_test, predictions)

# The naive baseline: predict that today equals yesterday. On many real series
# this is very hard to beat, which is exactly why it is the number the model has
# to be compared against. A MAE quoted on its own tells the reader nothing.
baseline_mae = mean_absolute_error(y_test, X_test['lag_1'])

beats_baseline = bool(test_mae < baseline_mae)
importances = dict(zip(features, model.feature_importances_))

results = pd.DataFrame(
    {'actual': y_test, 'predicted': predictions}, index=y_test.index
)

# ------------------------------------------------------------------ future ---
# Refit on everything before forecasting forward -- holding data back is only
# useful for scoring, and the last $test_fraction of the series is the most
# relevant part for predicting what comes next.
model_full = RandomForestRegressor(n_estimators=100, random_state=42)
model_full.fit(X, y)

# Recursive multi-step: each predicted day becomes the lag_1 of the next. Errors
# therefore compound with the horizon -- day $horizon is a prediction built on
# $horizon predictions, and should be read with far less confidence than day 1.
history = list(y.values)
future_index = pd.date_range(
    y.index[-1] + pd.Timedelta(days=1), periods=$horizon, freq='D'
)
future_values = []
for stamp in future_index:
    row = pd.DataFrame([{
        'lag_1': history[-1],
        'lag_7': history[-7] if len(history) >= 7 else history[0],
        'rolling_mean_7': sum(history[-7:]) / len(history[-7:]),
        'day_of_week': stamp.dayofweek,
        'month': stamp.month,
    }])[features]
    predicted = float(model_full.predict(row)[0])
    future_values.append(predicted)
    history.append(predicted)

future = pd.DataFrame({'predicted': future_values}, index=future_index)
"""


def forecast(
    df: pd.DataFrame,
    time_col: str,
    target_col: str,
    horizon: int = 7,
) -> Dict[str, Any]:
    """Fit a daily forecast, score it against a naive baseline, and say which won.

    Args:
        df: the uploaded data, unmodified.
        time_col: the datetime column, as chosen by routing.
        target_col: the numeric measure to forecast.
        horizon: days to project past the end of the data.

    Returns:
        On success: status "ok" plus metrics, verdict, beats_baseline,
        predictions (a DataFrame of actual vs predicted over the test window),
        future (the horizon-day projection), feature_importances, code and
        warnings.

        On failure: {"status": "insufficient_data", "message": ...}. Returned
        rather than raised because too-short a series is an ordinary property of
        an uploaded file, not a bug -- the app needs to explain it, not crash.

    Raises:
        ValueError: if horizon is not positive. That value comes from the app's
            own control, so a bad one is a caller bug.
    """
    if horizon < 1:
        raise ValueError(f"horizon must be >= 1, got {horizon}")

    warnings: list = []

    for label, col in (("time", time_col), ("target", target_col)):
        if not col or col not in df.columns:
            return {
                "status": "insufficient_data",
                "message": f"No {label} column available to forecast from.",
                "warnings": warnings,
            }

    # Prepared twice -- once here to decide whether a forecast is possible at
    # all, once inside the snippet so that the snippet stands alone when pasted
    # into a notebook. The duplication is the cost of the code string being
    # genuinely self-contained; the alternative is a snippet that imports this
    # module, which nobody can learn anything from.
    data = df[[time_col, target_col]].copy()
    data[time_col] = pd.to_datetime(data[time_col], errors="coerce", format="mixed")
    data[target_col] = pd.to_numeric(data[target_col], errors="coerce")
    data = data.dropna(subset=[time_col, target_col]).sort_values(time_col)

    if data.empty:
        return {
            "status": "insufficient_data",
            "message": (
                f"No rows have both a usable date and a numeric {target_col!r}."
            ),
            "warnings": warnings,
        }

    series = data.set_index(time_col)[target_col].resample("D").mean()
    n_periods = int(len(series))
    n_filled = int(series.isna().sum())
    filled_fraction = (n_filled / n_periods) if n_periods else 0.0

    # 7 rows are consumed by lag_7 and the rolling window; check the frame the
    # model will actually see, not the raw count.
    n_modelling_rows = max(0, int(series.ffill().dropna().shape[0]) - 7)
    if n_modelling_rows < MIN_ROWS:
        return {
            "status": "insufficient_data",
            "message": (
                f"Only {n_modelling_rows} usable day(s) after resampling and "
                f"building lag features; at least {MIN_ROWS} are needed for a "
                f"forecast that can be scored against a baseline."
            ),
            "warnings": warnings,
        }

    if n_filled:
        warnings.append(
            f"{n_filled} of {n_periods} daily periods ({filled_fraction:.0%}) had "
            f"no observation and were forward-filled from the previous day."
        )
    if filled_fraction > HEAVY_FILL_WARNING:
        warnings.append(
            f"More than {HEAVY_FILL_WARNING:.0%} of this series is forward-filled, "
            f"so the model is largely learning from carried-forward values rather "
            f"than observations. Treat the forecast as indicative at best."
        )
        # Stated explicitly because it changes how the verdict should be read,
        # and it is not obvious. Forward-filling copies yesterday's value into
        # today, so on every filled day the naive "predict the previous value"
        # baseline is not approximately right, it is exactly right. A heavily
        # filled series therefore hands the baseline a large block of free
        # zero-error predictions that no model can match. The comparison stays
        # in the output as-is -- quietly excluding filled days would be tuning
        # the benchmark until the model wins -- but the reader is told that the
        # contest is not a fair one.
        warnings.append(
            "Note that forward-filling also flatters the baseline: on a filled "
            "day the value equals the previous day's by construction, so the "
            "naive predictor scores exactly zero error there. The baseline MAE "
            "below is correspondingly harder to beat than it would be on a "
            "fully observed series."
        )

    code = _glassbox.render(
        FORECAST_TEMPLATE,
        time_col=time_col,
        target_col=target_col,
        features=FEATURES,
        test_fraction=TEST_FRACTION,
        horizon=horizon,
        n_filled=_glassbox.Raw(str(n_filled)),
        n_periods=_glassbox.Raw(str(n_periods)),
    )
    namespace = _glassbox.run(code, df)

    test_mae = float(namespace["test_mae"])
    baseline_mae = float(namespace["baseline_mae"])
    beats_baseline = bool(namespace["beats_baseline"])

    # Expressed against the baseline, not against the target's scale: "18% better
    # than predicting yesterday's value" is a claim a reader can weigh, whereas a
    # MAE of 4.2 means nothing without knowing the series.
    if baseline_mae > 0:
        improvement_pct = round(100.0 * (baseline_mae - test_mae) / baseline_mae, 2)
    else:
        # A zero baseline MAE means the series is flat over the test window; the
        # naive predictor is exactly right and no improvement is possible.
        improvement_pct = 0.0

    if beats_baseline:
        verdict = (
            f"The model beats the naive baseline: MAE {test_mae:,.3f} versus "
            f"{baseline_mae:,.3f} for simply predicting the previous day, an "
            f"improvement of {improvement_pct:.1f}%."
        )
    else:
        verdict = (
            f"The model does NOT beat the naive baseline: MAE {test_mae:,.3f} "
            f"versus {baseline_mae:,.3f} for simply predicting the previous day. "
            f"On this series, last known value is the better forecast, and these "
            f"predictions should not be relied on."
        )

    return {
        "status": "ok",
        "metrics": {
            "test_mae": round(test_mae, 4),
            "baseline_mae": round(baseline_mae, 4),
            "improvement_pct": improvement_pct,
            "n_train": int(len(namespace["X_train"])),
            "n_test": int(len(namespace["X_test"])),
            "n_periods": n_periods,
            "n_filled": n_filled,
            "filled_pct": round(100.0 * filled_fraction, 2),
        },
        "beats_baseline": beats_baseline,
        "verdict": verdict,
        "predictions": namespace["results"],
        "future": namespace["future"],
        "feature_importances": {
            key: round(float(val), 4)
            for key, val in sorted(
                namespace["importances"].items(), key=lambda kv: -kv[1]
            )
        },
        "code": code,
        "warnings": warnings,
    }
