"""Dataset profiling: turn a raw DataFrame into a compact, JSON-safe description.

The profile is the single source of truth every later stage consumes -- the
router sends a summary of it to the LLM, and the world builders read it to pick
sensible defaults. It therefore has to be (a) cheap to compute, (b) free of
numpy/pandas scalar types so it can be serialised straight to JSON, and
(c) conservative: a wrong semantic type silently produces a wrong world, which
is worse than an honest "text".
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

# Semantic types this profiler can assign.
DATETIME = "datetime"
NUMERIC = "numeric"
CATEGORICAL = "categorical"
GEO_LAT = "geo_lat"
GEO_LON = "geo_lon"
TEXT = "text"

# Column names that plausibly denote coordinates. Kept deliberately small:
# every extra alias widens the false-positive surface, and the range check is
# only a second line of defence, not a substitute for a sane name list.
LAT_NAMES = {"lat", "latitude", "lat_deg", "y_lat"}
LON_NAMES = {"lon", "lng", "long", "longitude", "lon_deg", "x_lon"}

# Tunables, named so they can be cited in the write-up rather than buried.
DATETIME_SAMPLE_SIZE = 500
DATETIME_PARSE_THRESHOLD = 0.80
# Plausibility window for a parsed date. pandas' underlying parser is extremely
# permissive -- it reads the ID string "ST0004" as 4 AD -- so a parse rate alone
# is not sufficient evidence. No business dataset contains dates outside this
# window, and anything that claims to is far more likely to be an ID or a code.
MIN_PLAUSIBLE_YEAR = 1900
MAX_PLAUSIBLE_YEAR = 2100
CATEGORICAL_MAX_UNIQUE = 20
CATEGORICAL_MAX_RATIO = 0.05
# Below this row count the ratio test is skipped entirely -- see _is_categorical.
CATEGORICAL_RATIO_MIN_ROWS = 200
TOP_VALUES_LIMIT = 10


def _normalise_name(name: Any) -> str:
    """Lower-case and unify separators so 'Lat_Deg' and 'lat deg' compare equal."""
    return str(name).strip().lower().replace(" ", "_").replace("-", "_")


def _looks_like_datetime(series: pd.Series) -> bool:
    """True if >=80% of a 500-row non-null sample parses as a *plausible* date.

    WHY a sample and a threshold rather than all-or-nothing parsing: real
    uploads contain dirty rows ("N/A", "????", a header repeated mid-file).
    Requiring 100% would reject an obviously temporal column because of three
    bad cells; accepting any single parse would flag free text, since pandas
    will happily read a date out of a sentence containing "May" or "2020".
    80% tolerates dirt while still requiring the column to be *mostly* dates.

    WHY only 500 rows: parsing is the most expensive step in profiling and
    accuracy plateaus quickly. 500 rows separates a date column from a text
    column on any realistic file while keeping a million-row upload responsive.

    WHY the year window: the parse rate alone is not enough. Testing against a
    sample file showed an ID column of the form "ST0004" parsing at 100% --
    the underlying dateutil parser reads it as the year 4 AD. Requiring the
    result to land between 1900 and 2100 removes that whole class of false
    positive at no cost to genuine date columns.
    """
    sample = series.dropna().head(DATETIME_SAMPLE_SIZE)
    if sample.empty:
        return False

    try:
        parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    except (ValueError, TypeError):
        # format='mixed' can still reject genuinely unparseable cell types
        # (lists, dicts in object columns). That is a "not a datetime" answer,
        # not an error worth propagating to the caller.
        return False

    # A value counts as a date only if it both parsed AND is plausible, so the
    # single 80% threshold covers both failure modes.
    years = parsed.dt.year
    plausible = parsed.notna() & years.between(MIN_PLAUSIBLE_YEAR, MAX_PLAUSIBLE_YEAR)
    return (plausible.sum() / len(sample)) >= DATETIME_PARSE_THRESHOLD


def _in_range(series: pd.Series, low: float, high: float) -> bool:
    """True if every non-null value sits inside [low, high]."""
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return False
    return bool(clean.min() >= low and clean.max() <= high)


def _is_categorical(n_unique: int, n_rows: int) -> bool:
    """Low absolute cardinality, plus a ratio test that only applies to real files.

    WHY two conditions at all: the absolute cap alone would call a 20-row
    table's primary key a category; the ratio alone would call a 10,000-value
    ID column in a 10-million-row table a category. Together they describe what
    a human means by "a category" -- a small fixed vocabulary repeated many
    times.

    WHY the ratio is gated on row count: n_unique/n_rows < 0.05 is a statement
    about repetition, and repetition is only measurable once there are enough
    rows for a value to repeat. On a 100-row file the rule permits at most 4
    distinct values, so a perfectly ordinary 6-region column is classified as
    text and the entity-split charts silently disappear. That is a false
    negative caused by sample size, not by the data.

    Below CATEGORICAL_RATIO_MIN_ROWS the absolute cap carries the decision
    alone. 200 rows is where the ratio first admits the full 20-value cap
    (20/200 = 0.10 still fails, but the gap has closed enough that the cap is
    the binding constraint for realistic vocabularies) and it is comfortably
    above the size at which a handful of repeats is coincidence. The cost of
    dropping the ratio on small files is bounded: with fewer than 200 rows, a
    column with <=20 distinct values is at worst a slightly odd grouping, never
    the million-value ID column the ratio exists to reject.

    Applied to numeric columns too, deliberately. A column holding 8 distinct
    integers across 5,000 rows is a category code (region_id, star rating), and
    taking its mean would be meaningless.
    """
    if n_rows == 0 or n_unique == 0:
        return False
    if n_unique > CATEGORICAL_MAX_UNIQUE:
        return False
    if n_rows < CATEGORICAL_RATIO_MIN_ROWS:
        return True
    return (n_unique / n_rows) < CATEGORICAL_MAX_RATIO


def _classify(series: pd.Series, name: str, n_rows: int, n_unique: int) -> str:
    """Assign exactly one semantic type, in a fixed precedence order.

    Precedence: datetime -> geo -> categorical -> numeric -> text.
    The order encodes strength of evidence. A successful date parse, or a
    name-and-range coordinate match, is hard evidence about what a column
    *means*; cardinality is only a statistical hint; numeric/text are what is
    left when nothing more specific fits.
    """
    is_numeric = pd.api.types.is_numeric_dtype(series)

    # 1. datetime -- native dtype first, then a parse test on non-numeric columns.
    if pd.api.types.is_datetime64_any_dtype(series):
        return DATETIME
    if not is_numeric and _looks_like_datetime(series):
        return DATETIME
    # WHY numeric columns are skipped entirely: pd.to_datetime turns the integer
    # 2020 into 1970-01-01T00:00:00.000002020 and a price of 45.5 into an epoch
    # offset. Every numeric column would parse at ~100% and be mislabelled.

    # 2. geo -- requires BOTH a recognised name AND a plausible coordinate range.
    # Name alone false-positives on "latency" and "long_description"; range
    # alone flags every small number in the file (percentages, ratings, deltas).
    normalised = _normalise_name(name)
    if is_numeric:
        if normalised in LAT_NAMES and _in_range(series, -90, 90):
            return GEO_LAT
        if normalised in LON_NAMES and _in_range(series, -180, 180):
            return GEO_LON

    # 3. categorical -- a small repeated vocabulary, numeric or not.
    if _is_categorical(n_unique, n_rows):
        return CATEGORICAL

    # 4/5. fallback.
    return NUMERIC if is_numeric else TEXT


def _numeric_stats(series: pd.Series) -> Dict[str, Any]:
    """min/max/mean as plain floats, or None for an all-null column."""
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return {"min": None, "max": None, "mean": None}
    return {
        "min": float(clean.min()),
        "max": float(clean.max()),
        "mean": float(clean.mean()),
    }


def _datetime_stats(series: pd.Series) -> Dict[str, Any]:
    """First/last timestamp as ISO strings, keeping the profile JSON-safe."""
    try:
        parsed = pd.to_datetime(series, errors="coerce", format="mixed")
    except (ValueError, TypeError):
        return {"min_date": None, "max_date": None}

    clean = parsed.dropna()
    if clean.empty:
        return {"min_date": None, "max_date": None}
    return {
        "min_date": clean.min().isoformat(),
        "max_date": clean.max().isoformat(),
    }


def _top_values(series: pd.Series) -> List[Dict[str, Any]]:
    """Ten most frequent values with counts, for display and for LLM context."""
    counts = series.dropna().value_counts().head(TOP_VALUES_LIMIT)
    return [{"value": str(idx), "count": int(cnt)} for idx, cnt in counts.items()]


def profile_column(series: pd.Series, name: str, n_rows: int) -> Dict[str, Any]:
    """Profile a single column into a JSON-safe dict.

    Split out from profile_dataframe so the classification rules can be tested
    against a bare Series without constructing a whole DataFrame.
    """
    n_unique = int(series.nunique(dropna=True))
    null_count = int(series.isna().sum())
    null_pct = round(100.0 * null_count / n_rows, 2) if n_rows else 0.0

    semantic_type = _classify(series, name, n_rows, n_unique)

    column: Dict[str, Any] = {
        "name": str(name),
        "dtype": str(series.dtype),
        "semantic_type": semantic_type,
        "null_pct": null_pct,
        "n_unique": n_unique,
    }

    if semantic_type in (NUMERIC, GEO_LAT, GEO_LON):
        column.update(_numeric_stats(series))
    elif semantic_type == DATETIME:
        column.update(_datetime_stats(series))
    elif semantic_type == CATEGORICAL:
        column["top_values"] = _top_values(series)

    return column


def profile_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    """Profile every column and summarise the dataset.

    Returns n_rows, n_cols, a per-column list, and the three roll-up flags the
    rule-based router needs (has_datetime, has_geo, n_numeric). Those flags are
    computed here rather than in the router so the fallback path never has to
    re-scan the DataFrame.

    Raises:
        TypeError: if df is not a DataFrame. Failing loudly here beats emitting
            a nonsense profile that only breaks three stages later.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"profile_dataframe expects a DataFrame, got {type(df).__name__}")

    n_rows = int(len(df))
    columns = [profile_column(df[col], col, n_rows) for col in df.columns]

    types = [c["semantic_type"] for c in columns]
    # A lone latitude cannot be plotted, so has_geo requires a matched pair.
    has_geo = GEO_LAT in types and GEO_LON in types

    return {
        "n_rows": n_rows,
        "n_cols": int(len(df.columns)),
        "columns": columns,
        "has_datetime": DATETIME in types,
        "has_geo": has_geo,
        "n_numeric": sum(1 for t in types if t == NUMERIC),
    }
