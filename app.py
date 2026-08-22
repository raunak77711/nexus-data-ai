"""Streamlit shell for AI Data Worlds.

This file renders; it does not decide. Every judgement -- what a column means,
which world to build, what to plot, whether a forecast is trustworthy -- is made
in core/ and arrives here as plain data. The only functions defined below turn
core's dicts into Streamlit calls.

WHY the separation is enforced rather than merely intended: core/ must stay
importable from a FastAPI process that has never heard of Streamlit. If any
decision leaked into this file it would have to be rewritten for the planned
React front end, and the two would drift. The test for whether something belongs
here is simple -- would it still be true if the UI were a REST endpoint? If yes,
it belongs in core/.
"""

from __future__ import annotations

import hashlib
import io
from typing import Any, Dict

import pandas as pd
import streamlit as st

from core import ml, router
from core.profiler import profile_dataframe
from core.worlds import geo, tabular, timeseries

st.set_page_config(
    page_title="AI Data Worlds",
    page_icon=":material/travel_explore:",
    layout="wide",
)

WORLD_LABELS = {
    "timeseries": "Timeseries",
    "geo": "Geo",
    "tabular": "Tabular",
}

FIGURE_LABELS = {
    "main": "Measure over time",
    "by_entity": "Split by category",
    "map": "Locations",
    "distribution": "Distribution",
    "correlation": "Correlation",
}

FREQ_LABELS = {"D": "Daily", "W": "Weekly", "M": "Monthly"}

# Session keys are initialised in one place so it is obvious what state this app
# carries between reruns. Streamlit reruns the whole script on every widget
# interaction, so anything expensive or non-deterministic -- notably the Gemini
# call -- must be held rather than recomputed.
st.session_state.setdefault("file_hash", None)
st.session_state.setdefault("forecasts", {})


@st.cache_data(max_entries=8, show_spinner=False)
def load_csv(file_bytes: bytes) -> pd.DataFrame:
    """Parse an uploaded CSV, keyed on its exact bytes."""
    return pd.read_csv(io.BytesIO(file_bytes))


@st.cache_data(max_entries=8, show_spinner="Profiling columns...")
def cached_profile(file_hash: str, _df: pd.DataFrame) -> Dict[str, Any]:
    """Profile the dataset, cached on the file's content hash.

    The leading underscore on _df tells Streamlit not to hash that argument --
    file_hash already identifies the data exactly, and hashing a large DataFrame
    on every rerun would cost more than the profiling it is meant to avoid.
    """
    return profile_dataframe(_df)


@st.cache_data(max_entries=8, show_spinner="Asking the model which world to build...")
def cached_routing(file_hash: str, _profile: Dict[str, Any]) -> Dict[str, Any]:
    """Route the dataset, cached on the file's content hash.

    This is the only function in the app that costs money and network time. It
    is cached rather than merely fast because Streamlit reruns this script from
    the top on every slider drag -- without the cache, changing the resampling
    frequency would issue a fresh Gemini request each time.
    """
    return router.route(_profile)


def profile_table(profile: Dict[str, Any]) -> pd.DataFrame:
    """Flatten the profile's column list into something st.dataframe can show.

    Purely presentational: the semantic type is the column a user most needs to
    check, so it sits immediately after the name rather than at the end of a row
    they would have to scroll to reach.
    """
    return pd.DataFrame([
        {
            "column": col["name"],
            "semantic type": col["semantic_type"],
            "pandas dtype": col["dtype"],
            "unique": col["n_unique"],
            "null %": col["null_pct"],
        }
        for col in profile["columns"]
    ])


def show_warnings(warnings: list) -> None:
    """Surface what the builder had to do to the data to make it plottable.

    Rendered next to the charts rather than hidden in a log, because a user who
    does not know that 40% of their rows were dropped will read the chart as the
    whole truth.
    """
    if warnings:
        st.warning("\n".join(f"- {item}" for item in warnings), icon=":material/info:")


def show_figure(name: str, world: Dict[str, Any]) -> None:
    """Render one figure with its code underneath.

    The expander is the product's whole point: the code inside it is the code
    that produced the figure above it, not a description of it, because core
    executes the string it returns.
    """
    st.subheader(FIGURE_LABELS.get(name, name), divider="gray")
    st.plotly_chart(world["figures"][name], key=f"chart_{name}")
    with st.expander("Show the code", icon=":material/code:"):
        st.code(world["code"][name], language="python")


def show_world(world: Dict[str, Any]) -> None:
    """Render a world dict, or explain why it could not be built."""
    if world["status"] != "ok":
        st.error(world["message"], icon=":material/error:")
        show_warnings(world["warnings"])
        return

    show_warnings(world["warnings"])
    for name in world["figures"]:
        show_figure(name, world)

    with st.expander("Summary statistics", icon=":material/functions:"):
        st.json(world["stats"])


# ----------------------------------------------------------------- the page --

st.title("AI data worlds")
st.markdown(
    "Upload a CSV. The app profiles the columns, asks a model which kind of "
    "world the data describes, and builds it -- **and shows you the code behind "
    "every chart it draws.**"
)

uploaded = st.file_uploader(
    "Upload a CSV file", type="csv", help="Try the files in the samples/ folder."
)

if uploaded is None:
    st.info(
        "No file yet. `samples/` contains one dataset per archetype: "
        "`sales_timeseries.csv`, `air_quality_geo.csv`, `employees_tabular.csv`.",
        icon=":material/upload_file:",
    )
    st.stop()

file_bytes = uploaded.getvalue()
file_hash = hashlib.sha256(file_bytes).hexdigest()

# A new file invalidates anything held from the previous one. Forecasts are
# keyed by hash anyway, but clearing keeps the session from growing without
# bound across a long exploratory session.
if st.session_state["file_hash"] != file_hash:
    st.session_state["file_hash"] = file_hash
    st.session_state["forecasts"] = {}

df = load_csv(file_bytes)
profile = cached_profile(file_hash, df)
routing = cached_routing(file_hash, profile)

# ------------------------------------------------------------------ profile --

st.header("What is in this file", divider="rainbow")

with st.container(horizontal=True):
    st.metric("Rows", f"{profile['n_rows']:,}", border=True)
    st.metric("Columns", profile["n_cols"], border=True)
    st.metric("Numeric columns", profile["n_numeric"], border=True)
    st.metric(
        "Has coordinates",
        "Yes" if profile["has_geo"] else "No",
        border=True,
    )

st.dataframe(profile_table(profile), hide_index=True, key="profile_table")
st.caption(
    "Semantic type is this app's reading of what a column *means*, which is not "
    "the same as its pandas dtype -- a low-cardinality integer is a category, "
    "not a measure."
)

# ------------------------------------------------------------------ routing --

st.header("Which world was chosen", divider="rainbow")

with st.container(border=True):
    # The badge is not decoration. A user comparing two sessions needs to know
    # whether they are looking at a model's judgement or a deterministic rule,
    # because only one of those will give the same answer twice.
    if routing["source"] == "llm":
        st.badge("AI routed", icon=":material/smart_toy:", color="green")
    else:
        st.badge("Rule-based fallback", icon=":material/rule:", color="orange")

    st.markdown(f"**Archetype:** {WORLD_LABELS.get(routing['archetype'])}")
    st.markdown(f"_{routing['reasoning']}_")

    chosen_columns = {
        key: routing[key]
        for key in ("time_col", "entity_col", "target_col", "lat_col", "lon_col")
        if routing[key]
    }
    st.caption(
        "Columns chosen: "
        + ", ".join(f"`{value}` as {key}" for key, value in chosen_columns.items())
    )

archetypes = list(WORLD_LABELS)
archetype = st.selectbox(
    "Build a different world instead",
    options=archetypes,
    index=archetypes.index(routing["archetype"]),
    format_func=lambda key: WORLD_LABELS[key],
    help=(
        "The routed archetype is the default. Overriding it is allowed and may "
        "not work -- forcing a map onto a dataset with no coordinates will say "
        "so rather than guess."
    ),
    key="archetype_override",
)

if archetype != routing["archetype"]:
    st.info(
        f"Showing the {WORLD_LABELS[archetype].lower()} world instead of the "
        f"routed {WORLD_LABELS[routing['archetype']].lower()} one.",
        icon=":material/edit:",
    )

# -------------------------------------------------------------------- world --

st.header(f"{WORLD_LABELS[archetype]} world", divider="rainbow")

if archetype == "timeseries":
    with st.container(horizontal=True):
        freq = st.segmented_control(
            "Resample by",
            options=list(FREQ_LABELS),
            default="D",
            format_func=lambda key: FREQ_LABELS[key],
            key="ts_freq",
        )
        rolling_window = st.slider(
            "Rolling mean window (periods)", 2, 30, 7, key="ts_window"
        )

    world = timeseries.build(df, routing, freq=freq or "D", rolling_window=rolling_window)
    show_world(world)

elif archetype == "geo":
    time_filter = None
    time_col = routing.get("time_col")

    if time_col and time_col in df.columns:
        stamps = pd.to_datetime(df[time_col], errors="coerce", format="mixed").dropna()
        # A slider needs two distinct endpoints. A dataset whose timestamps are
        # all identical is rare but real (a single export), and Streamlit raises
        # on a zero-width range rather than degrading, so check before rendering.
        if len(stamps) and stamps.min() < stamps.max():
            low, high = stamps.min().to_pydatetime(), stamps.max().to_pydatetime()
            time_filter = st.slider(
                f"Filter by {time_col}",
                min_value=low,
                max_value=high,
                value=(low, high),
                key="geo_time",
            )
        else:
            st.caption(f"`{time_col}` has no range to filter on.")

    world = geo.build(df, routing, time_filter=time_filter)
    show_world(world)

else:
    world = tabular.build(df, routing)
    show_world(world)

# ----------------------------------------------------------------- forecast --

if archetype == "timeseries":
    st.header("Forecast", divider="rainbow")
    st.caption(
        "A random forest over lag and calendar features, scored against the "
        "naive 'tomorrow looks like today' baseline."
    )

    horizon = st.slider("Days to forecast ahead", 1, 30, 7, key="forecast_horizon")
    forecast_key = f"{file_hash}:{routing['time_col']}:{routing['target_col']}:{horizon}"

    if st.button("Run forecast", icon=":material/model_training:", type="primary"):
        with st.spinner("Fitting..."):
            st.session_state["forecasts"][forecast_key] = ml.forecast(
                df, routing["time_col"], routing["target_col"], horizon=horizon
            )

    # Read from session state rather than the button's return value: the button
    # is True for exactly one rerun, so without this the results would vanish
    # the moment the user touched any other control on the page.
    result = st.session_state["forecasts"].get(forecast_key)

    if result is None:
        st.info("Not run yet.", icon=":material/play_circle:")
    elif result["status"] != "ok":
        st.error(result["message"], icon=":material/error:")
    else:
        metrics = result["metrics"]
        with st.container(horizontal=True):
            st.metric("Model MAE", f"{metrics['test_mae']:,.3f}", border=True)
            st.metric("Naive baseline MAE", f"{metrics['baseline_mae']:,.3f}", border=True)
            st.metric(
                "Improvement",
                f"{metrics['improvement_pct']:,.1f}%",
                delta=f"{metrics['improvement_pct']:,.1f}%",
                border=True,
            )
            st.metric("Train / test rows", f"{metrics['n_train']} / {metrics['n_test']}",
                      border=True)

        if result["beats_baseline"]:
            st.success(result["verdict"], icon=":material/check_circle:")
        else:
            st.error(result["verdict"], icon=":material/report:")

        show_warnings(result["warnings"])

        st.subheader("Predictions against actuals", divider="gray")
        st.caption("The held-out final 20% of the series, which the model never saw.")
        st.line_chart(result["predictions"], x_label="date", y_label=routing["target_col"])

        st.subheader(f"Next {horizon} day(s)", divider="gray")
        st.caption(
            "Recursive: each predicted day feeds the next one's lag features, so "
            "error compounds with distance."
        )
        st.line_chart(result["future"], x_label="date", y_label=routing["target_col"])

        st.subheader("What the model used", divider="gray")
        st.bar_chart(
            pd.Series(result["feature_importances"], name="importance"),
            horizontal=True,
            x_label="relative importance",
            y_label="feature",
        )

        with st.expander("Show the code", icon=":material/code:"):
            st.code(result["code"], language="python")
