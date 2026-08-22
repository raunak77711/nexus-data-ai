"""Drive app.py end to end for each sample CSV, through Streamlit's own runtime.

This is not a smoke test of core/ -- scripts/test_worlds.py and scripts/test_ml.py
already cover that. This runs the actual Streamlit script with a real uploaded
file, in the same order of reruns a person clicking through the app would
produce, and asserts on what ends up on the page.

The check that matters most is the last one in each block: every code string
that reaches a "Show the code" expander is pulled back out of the rendered page
and executed against the same DataFrame. A user who copies what they see gets a
result -- and that is verified here rather than assumed.
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import plotly.graph_objects as go
from streamlit.testing.v1 import AppTest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "samples")
APP = os.path.join(ROOT, "app.py")

EXPECTED = {
    "sales_timeseries.csv": "timeseries",
    "air_quality_geo.csv": "geo",
    "employees_tabular.csv": "tabular",
}

FAILURES = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global FAILURES
    if not condition:
        FAILURES += 1
    print(f"  [{'OK ' if condition else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")


def upload(filename: str) -> AppTest:
    """Start the app and upload one sample, returning the run app."""
    with open(os.path.join(SAMPLES, filename), "rb") as handle:
        content = handle.read()

    app = AppTest.from_file(APP, default_timeout=120)
    app.run()
    app.file_uploader[0].set_value((filename, content, "text/csv"))
    app.run()
    return app


def check_expander_code(app: AppTest, df: pd.DataFrame, label: str) -> None:
    """Execute every code block on the page against the uploaded DataFrame.

    Each snippet gets a fresh namespace holding only `df`, which is exactly the
    position of a user who pastes it into a notebook. Snippets that build a
    figure must produce one; the forecast snippet produces metrics instead, so
    it is checked for those.
    """
    blocks = [element.value for element in app.code]
    check(f"{label}: code is shown", len(blocks) > 0, f"{len(blocks)} block(s)")

    for index, code in enumerate(blocks):
        namespace = {"df": df}
        try:
            exec(code, namespace)
        except Exception as exc:  # noqa: BLE001 - reporting any failure is the point
            check(f"{label}: code block {index} runs", False,
                  f"{type(exc).__name__}: {exc}")
            continue

        produced_figure = isinstance(namespace.get("fig"), go.Figure)
        produced_metrics = "test_mae" in namespace
        check(
            f"{label}: code block {index} runs and produces output",
            produced_figure or produced_metrics,
            "figure" if produced_figure else "model metrics",
        )


def run_sample(filename: str) -> None:
    print("=" * 72)
    print(filename)
    print("-" * 72)

    df = pd.read_csv(os.path.join(SAMPLES, filename))
    app = upload(filename)

    check("app runs without exception", not app.exception,
          str(app.exception[0].value) if app.exception else "")
    check("profile is rendered", len(app.dataframe) >= 1)
    check("row count is shown",
          any(m.value == f"{len(df):,}" for m in app.metric),
          f"{len(df):,} rows")

    routed = app.selectbox[0].value
    check("routed archetype is correct", routed == EXPECTED[filename],
          f"routed to {routed}, expected {EXPECTED[filename]}")

    # The routing badge is the user's only signal about which path ran. It is
    # rendered as markdown, so assert on the page text rather than trust it.
    page_text = " ".join(element.value for element in app.markdown)
    has_badge = "AI routed" in page_text or "Rule-based fallback" in page_text
    check("routing badge is present", has_badge,
          "AI routed" if "AI routed" in page_text else "Rule-based fallback")

    check("a chart was drawn", len(app.subheader) > 0,
          f"{len(app.subheader)} figure section(s)")
    check("no error boxes on the page", len(app.error) == 0,
          "; ".join(e.value for e in app.error) if app.error else "clean")

    check_expander_code(app, df, "world")

    if EXPECTED[filename] == "timeseries":
        print("  forecast:")
        forecast_button = [b for b in app.button if "forecast" in b.label.lower()]
        check("run forecast button exists", len(forecast_button) == 1)
        forecast_button[0].click()
        app.run()

        check("forecast runs without exception", not app.exception,
              str(app.exception[0].value) if app.exception else "")

        labels = [m.label for m in app.metric]
        check("both MAEs are shown side by side",
              "Model MAE" in labels and "Naive baseline MAE" in labels,
              ", ".join(labels[-4:]))

        # The verdict is rendered as success when the model wins and error when
        # it loses. Exactly one must be present, or the app is either silent
        # about a bad model or celebrating one.
        verdicts = [s.value for s in app.success] + [e.value for e in app.error]
        stated = [v for v in verdicts if "naive baseline" in v]
        check("verdict is stated", len(stated) == 1,
              stated[0][:100] + "..." if stated else "no verdict on the page")

        check_expander_code(app, df, "forecast")

        # Frequency control must survive a rerun and rebuild the world.
        app.segmented_control[0].set_value("W")
        app.run()
        check("frequency change rebuilds without error", not app.exception,
              "resampled weekly")
        check("forecast survives the rerun",
              any(m.label == "Model MAE" for m in app.metric),
              "results held in session_state, not lost on rerun")

    # Overriding the archetype must never crash, even where it makes no sense.
    # A world that cannot be built must say so in an error box; that is the
    # designed outcome, not a failure -- so the two are distinguished here.
    # The forecast verdict also renders as an error box when the model loses,
    # which is why it is excluded rather than counted as a refusal.
    for override in ("timeseries", "geo", "tabular"):
        app.selectbox[0].set_value(override)
        app.run()
        refusals = [
            element.value for element in app.error
            if "naive baseline" not in element.value
        ]
        check(f"override to {override} does not crash", not app.exception,
              str(app.exception[0].value) if app.exception
              else ("declined cleanly: " + refusals[0][:60] if refusals else "built"))


if __name__ == "__main__":
    for name in EXPECTED:
        run_sample(name)
    print("=" * 72)
    print("ALL PASS" if FAILURES == 0 else f"{FAILURES} FAILURE(S)")
    raise SystemExit(1 if FAILURES else 0)
