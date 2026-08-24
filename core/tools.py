"""The calculator the assistant is allowed to use.

THE PROBLEM
-----------
core.chat is built on one rule: the model never sees a row and never computes a
number. That rule is what makes its answers trustworthy, and it is also what
makes it useless for the questions people actually ask -- "which product sells
best?", "how many orders came from the north?", "is advertising doing anything
for revenue?". Every one of those needs a number that is not in a summary.

Loosening the rule is not the answer. Handing the model the rows would let it
average them, and a model averaging 12,000 numbers in its head is a model
producing a plausible wrong number.

THE SHAPE OF THE FIX
--------------------
Put a calculator between them. The model does not compute; it *chooses a
question to ask of pandas*, from a fixed menu, naming columns that already
exist. This module runs that question against the DataFrame and returns real
numbers. The model then explains the result it was handed.

    question -> plan (a tool name + arguments)
             -> THIS MODULE runs pandas
             -> real numbers
             -> the model writes a sentence around them

Every number in the final answer therefore came out of pandas, and the model's
contribution is the English. That is the division of labour each side is
actually good at.

WHAT A PLAN CAN CONTAIN
-----------------------
A tool name from TOOLS, column names that resolve against the frame, an
aggregation from a whitelist, and an integer count that gets clamped. There is
no free-text field anywhere in a plan, no expression to evaluate, and no way to
name a function. A plan asking for something outside that vocabulary is refused
with a sentence -- it is not attempted, and it is not passed through.

WITHOUT AN LLM
--------------
plan_from_keywords() reads the question with rules instead. It is less clever --
it will not resolve "the thing we sell most of" to a column -- but when it does
recognise a question, the answer it produces is computed by the same pandas call
and is exactly as correct. So the assistant degrades from "understands you" to
"understands common phrasings", rather than from "works" to "unavailable".
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from core import charts

logger = logging.getLogger(__name__)

# Rows returned in a table result. Ten is what fits on screen under an answer
# without becoming the answer.
MAX_ROWS = 10
MAX_ROWS_HARD = 25

AGGREGATIONS = {
    "sum": "total",
    "mean": "average",
    "median": "middle value",
    "count": "number of rows",
    "min": "lowest",
    "max": "highest",
}


class ToolError(ValueError):
    """A plan that cannot be run, carrying a sentence fit to show a user."""


# The menu, described in the words used to explain it to a model. Keep the
# descriptions in terms of what a *user* would ask, not what pandas would do --
# the model is matching a question to a tool, not a call to an API.
TOOLS: Dict[str, Dict[str, Any]] = {
    "rank": {
        "purpose": "Which groups are highest or lowest on some measure. "
                   "Use for 'best', 'worst', 'top 5', 'which region leads'.",
        "args": {
            "group_by": "a categorical column to group by (required)",
            "measure": "a numeric column to rank on (required)",
            "agg": f"one of {', '.join(AGGREGATIONS)} (default mean)",
            "n": "how many groups to return, 1-25 (default 10)",
            "order": "'top' or 'bottom' (default top)",
        },
    },
    "aggregate": {
        "purpose": "One number summarising a whole column: total, average, "
                   "highest, lowest, how many. Use for 'what is total revenue'.",
        "args": {
            "measure": "a numeric column (required)",
            "agg": f"one of {', '.join(AGGREGATIONS)} (default mean)",
        },
    },
    "trend": {
        "purpose": "How a measure changed over time, and by how much. "
                   "Use for 'is it growing', 'why did sales fall'.",
        "args": {
            "measure": "a numeric column (required)",
            "freq": "D, W or M for daily, weekly or monthly (optional)",
        },
    },
    "relationship": {
        "purpose": "Whether two numeric columns move together. Use for "
                   "'does advertising affect revenue', 'what influences X'.",
        "args": {
            "column_a": "a numeric column (required)",
            "column_b": "a numeric column (required)",
        },
    },
    "outliers": {
        "purpose": "The most unusual rows for a measure. Use for 'find "
                   "anomalies', 'anything strange', 'unexpected values'.",
        "args": {
            "measure": "a numeric column (required)",
            "n": "how many rows to return, 1-25 (default 5)",
        },
    },
    "describe": {
        "purpose": "A summary of one column: range, typical value, how many "
                   "blanks, most common values.",
        "args": {"column": "any column (required)"},
    },
    "overview": {
        "purpose": "What this dataset is, as a whole: size, what kind of "
                   "columns it holds, what period it covers, what it measures. "
                   "Use for 'summarise this data', 'what is the most important "
                   "thing here', 'what am I looking at'.",
        "args": {},
    },
    "count": {
        "purpose": "How many rows there are, optionally only those where a "
                   "column has a particular value.",
        "args": {
            "column": "a column to filter on (optional)",
            "value": "the value to match in that column (optional)",
        },
    },
}


# ------------------------------------------------------------- arg handling --
def _resolve(df: pd.DataFrame, name: Any, role: str) -> str:
    """Resolve a column name from a plan, or refuse it by name.

    Delegates to core.charts so a plan and a chart spec agree on what counts as
    a valid column reference -- including the case-insensitive fallback. Two
    different answers to "is there a column called Revenue?" in one app would be
    a bug waiting to happen.
    """
    try:
        return charts._require_column(df, name, role)
    except charts.ChartError as exc:
        raise ToolError(str(exc)) from exc


def _numeric(df: pd.DataFrame, column: str) -> pd.Series:
    values = pd.to_numeric(df[column], errors="coerce")
    if values.notna().sum() == 0:
        raise ToolError(
            f"{column!r} does not hold numbers, so there is nothing to calculate "
            f"from it."
        )
    return values


def _agg(value: Any, default: str = "mean") -> str:
    name = str(value or default).strip().lower()
    # Common synonyms a model or a user reaches for. Mapped rather than
    # rejected: refusing "average" because pandas calls it "mean" would be the
    # app being pedantic about its own internals.
    name = {"avg": "mean", "average": "mean", "total": "sum", "largest": "max",
            "smallest": "min", "highest": "max", "lowest": "min"}.get(name, name)
    if name not in AGGREGATIONS:
        raise ToolError(
            f"{name!r} is not something this app can calculate. Available: "
            f"{', '.join(AGGREGATIONS)}."
        )
    return name


def _count(value: Any, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(1, min(MAX_ROWS_HARD, n))


def _fmt(value: Any) -> str:
    """Same number formatting as the insight cards, so the app speaks one way."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number != number:
        return "-"
    if abs(number) >= 1000:
        return f"{number:,.0f}"
    if abs(number) >= 10:
        return f"{number:,.1f}"
    return f"{number:,.2f}"


def _friendly(name: str) -> str:
    return str(name).replace("_", " ").strip()


def _rows(n: int) -> str:
    '''"1 row" / "106 rows". Writing "row(s)" is the app talking to itself.'''
    return f"{n:,} row" if n == 1 else f"{n:,} rows"


# ---------------------------------------------------------------- the tools --
def _tool_rank(df: pd.DataFrame, args: Dict[str, Any]) -> Dict[str, Any]:
    group_by = _resolve(df, args.get("group_by") or args.get("group"), "the grouping")
    measure = _resolve(df, args.get("measure") or args.get("value"), "the measure")
    agg = _agg(args.get("agg"))
    n = _count(args.get("n"), MAX_ROWS)
    ascending = str(args.get("order") or "top").lower() in ("bottom", "lowest", "worst", "asc")

    values = _numeric(df, measure)
    grouped = values.groupby(df[group_by]).agg([agg, "count"])
    grouped.columns = ["value", "rows"]
    grouped = grouped.dropna(subset=["value"]).sort_values("value", ascending=ascending)
    if grouped.empty:
        raise ToolError(
            f"No group in {group_by!r} has a usable {measure!r} value to rank on."
        )

    top = grouped.head(n)
    rows = [
        {"group": str(idx), "value": round(float(row["value"]), 4), "rows": int(row["rows"])}
        for idx, row in top.iterrows()
    ]
    leader = rows[0]
    direction = "lowest" if ascending else "highest"

    return {
        "result": {
            "rows": rows,
            "group_by": group_by,
            "measure": measure,
            "agg": agg,
            "n_groups": int(len(grouped)),
            "order": direction,
        },
        "summary": (
            f"{leader['group']} has the {direction} {AGGREGATIONS[agg]} "
            f"{_friendly(measure)} at {_fmt(leader['value'])}, from "
            f"{_rows(leader['rows'])}. "
            + (
                f"Next is {rows[1]['group']} at {_fmt(rows[1]['value'])}."
                if len(rows) > 1
                else ""
            )
        ).strip(),
        "action": {
            "chart": "bar",
            "x": group_by,
            "y": measure,
            "agg": agg,
            "limit": len(rows),
            "ascending": ascending,
        },
        "table": {"columns": [group_by, f"{agg} of {measure}", "rows"],
                  "rows": [[r["group"], r["value"], r["rows"]] for r in rows]},
    }


def _tool_aggregate(df: pd.DataFrame, args: Dict[str, Any]) -> Dict[str, Any]:
    measure = _resolve(df, args.get("measure") or args.get("column"), "the measure")
    agg = _agg(args.get("agg"))
    values = _numeric(df, measure)
    clean = values.dropna()

    computed = float(len(clean)) if agg == "count" else float(getattr(clean, agg)())
    excluded = int(len(df) - len(clean))

    return {
        "result": {
            "measure": measure,
            "agg": agg,
            "value": round(computed, 4),
            "rows_used": int(len(clean)),
            "rows_excluded": excluded,
        },
        "summary": (
            f"The {AGGREGATIONS[agg]} of {_friendly(measure)} is {_fmt(computed)}, "
            f"across {_rows(len(clean))}"
            + (
                f" ({_rows(excluded)} had no value and were left out)."
                if excluded
                else "."
            )
        ),
        "action": {"chart": "histogram", "x": measure},
        "table": None,
    }


def _tool_trend(df: pd.DataFrame, args: Dict[str, Any], time_col: Optional[str]) -> Dict[str, Any]:
    measure = _resolve(df, args.get("measure") or args.get("column"), "the measure")
    resolved_time = args.get("time_column") or time_col
    if not resolved_time:
        raise ToolError(
            "This dataset has no date column, so there is no timeline to measure "
            "change along."
        )
    resolved_time = _resolve(df, resolved_time, "the date column")

    stamps = pd.to_datetime(df[resolved_time], errors="coerce", format="mixed")
    values = _numeric(df, measure)
    frame = pd.DataFrame({"t": stamps, "v": values}).dropna()
    if len(frame) < 4:
        raise ToolError(
            f"Only {_rows(len(frame))} have both a date and a {measure!r} value — "
            f"not enough to describe a change over time."
        )

    freq = str(args.get("freq") or "").upper()
    alias = {"D": "D", "W": "W", "M": "ME"}.get(freq) or charts.FREQ_ALIASES[
        charts._suggest_freq(df, resolved_time)
    ]
    word = {"D": "day", "W": "week", "ME": "month"}[alias]

    series = frame.set_index("t")["v"].resample(alias).mean().dropna()
    if len(series) < 3:
        raise ToolError(
            f"There are only {len(series)} {word}(s) of data, which is too few to "
            f"call a trend."
        )

    third = max(1, len(series) // 3)
    start = float(series.iloc[:third].mean())
    end = float(series.iloc[-third:].mean())
    change = 100.0 * (end - start) / abs(start) if start else 0.0
    direction = "up" if change > 0 else ("down" if change < 0 else "flat")

    return {
        "result": {
            "measure": measure,
            "time_column": resolved_time,
            "grouped_by": word,
            "start_average": round(start, 4),
            "end_average": round(end, 4),
            "change_pct": round(change, 2),
            "direction": direction,
            "periods": int(len(series)),
            "peak": {"when": str(series.idxmax().date()), "value": round(float(series.max()), 4)},
            "low": {"when": str(series.idxmin().date()), "value": round(float(series.min()), 4)},
            "covers": f"{series.index.min().date()} to {series.index.max().date()}",
        },
        "summary": (
            f"{_friendly(measure).capitalize()} is {direction}"
            + (f" {abs(change):.1f}%" if direction != "flat" else "")
            + f" across the data: it averaged {_fmt(start)} per {word} early on and "
            f"{_fmt(end)} at the end. The highest {word} was "
            f"{series.idxmax().date()} at {_fmt(series.max())}."
        ),
        "action": {"chart": "line", "x": resolved_time, "y": measure,
                   "freq": {"D": "D", "W": "W", "ME": "M"}[alias]},
        "table": None,
    }


def _tool_relationship(df: pd.DataFrame, args: Dict[str, Any]) -> Dict[str, Any]:
    a = _resolve(df, args.get("column_a") or args.get("x"), "the first column")
    b = _resolve(df, args.get("column_b") or args.get("y"), "the second column")
    if a == b:
        raise ToolError("Those are the same column, so there is no relationship to measure.")

    frame = pd.DataFrame({a: _numeric(df, a), b: _numeric(df, b)}).dropna()
    if len(frame) < 10:
        raise ToolError(
            f"Only {_rows(len(frame))} have both {a!r} and {b!r}, which is too few "
            f"to say anything about how they relate."
        )

    r = float(frame[a].corr(frame[b]))
    strength = abs(r)
    if strength >= 0.75:
        wording = "a very close link"
    elif strength >= 0.5:
        wording = "a clear link"
    elif strength >= 0.3:
        wording = "a weak link"
    else:
        wording = "no meaningful link"

    together = r > 0
    return {
        "result": {
            "column_a": a,
            "column_b": b,
            "correlation": round(r, 3),
            "strength": wording,
            "direction": "same direction" if together else "opposite directions",
            "rows_compared": int(len(frame)),
        },
        "summary": (
            f"There is {wording} between {_friendly(a)} and {_friendly(b)}"
            + (
                f": when one goes up the other usually goes "
                f"{'up too' if together else 'down'}."
                if strength >= 0.3
                else ". They move more or less independently."
            )
            + f" Measured across {len(frame):,} rows that have both."
        ),
        "action": {"chart": "scatter", "x": a, "y": b},
        "table": None,
    }


def _tool_outliers(df: pd.DataFrame, args: Dict[str, Any]) -> Dict[str, Any]:
    measure = _resolve(df, args.get("measure") or args.get("column"), "the measure")
    n = _count(args.get("n"), 5)
    values = _numeric(df, measure)
    clean = values.dropna()
    if len(clean) < 10:
        raise ToolError(
            f"Only {_rows(len(clean))} have a {measure!r} value — too few to say "
            f"which of them is unusual."
        )

    median = float(clean.median())
    q1, q3 = float(clean.quantile(0.25)), float(clean.quantile(0.75))
    iqr = q3 - q1
    low, high = q1 - 3.0 * iqr, q3 + 3.0 * iqr
    unusual = int(((clean < low) | (clean > high)).sum()) if iqr > 0 else 0
    # What gets REPORTED is where most values actually sit, not the fence that
    # decided the flag. The fence is an interval on the arithmetic and can run
    # past the data entirely -- telling a user their revenue "normally falls
    # between -105 and 462" is arithmetic leaking into English.
    usual_low, usual_high = float(clean.quantile(0.10)), float(clean.quantile(0.90))

    furthest = (values - median).abs().sort_values(ascending=False).dropna().head(n)
    rows = [
        {
            "row": int(df.index.get_loc(idx)) + 1,
            "value": round(float(values.loc[idx]), 4),
            "difference": round(float(values.loc[idx]) - median, 4),
        }
        for idx in furthest.index
    ]

    return {
        "result": {
            "measure": measure,
            "typical_value": round(median, 4),
            "most_values_between": [round(usual_low, 4), round(usual_high, 4)],
            "unusual_row_count": unusual,
            "furthest_rows": rows,
        },
        "summary": (
            (
                f"{_rows(unusual)} sit far outside the normal range for "
                f"{_friendly(measure)}"
                if unusual
                else f"No {_friendly(measure)} value is far outside the normal range"
            )
            + f". The most extreme is row {rows[0]['row']:,} at "
            f"{_fmt(rows[0]['value'])}, against a typical {_fmt(median)}."
        ),
        "action": {"chart": "histogram", "x": measure},
        "table": {
            "columns": ["row", measure, f"difference from typical"],
            "rows": [[r["row"], r["value"], r["difference"]] for r in rows],
        },
    }


def _tool_describe(df: pd.DataFrame, args: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    column = _resolve(df, args.get("column") or args.get("measure"), "the column")
    meta = next(
        (c for c in profile.get("columns", []) if str(c.get("name")) == column), {}
    )
    kind = str(meta.get("semantic_type") or "text")
    series = df[column]
    n_missing = int(series.isna().sum())

    result: Dict[str, Any] = {
        "column": column,
        "kind": kind,
        "distinct_values": int(series.nunique(dropna=True)),
        "missing_rows": n_missing,
        "missing_pct": round(100.0 * n_missing / max(1, len(df)), 2),
    }

    if kind in ("numeric", "geo_lat", "geo_lon"):
        values = pd.to_numeric(series, errors="coerce").dropna()
        result.update(
            {
                "lowest": round(float(values.min()), 4),
                "highest": round(float(values.max()), 4),
                "average": round(float(values.mean()), 4),
                "typical": round(float(values.median()), 4),
            }
        )
        summary = (
            f"{_friendly(column).capitalize()} is a number ranging from "
            f"{_fmt(values.min())} to {_fmt(values.max())}, averaging "
            f"{_fmt(values.mean())}. "
            f"{_rows(n_missing)} have no value."
        )
        action: Optional[Dict[str, Any]] = {"chart": "histogram", "x": column}
    else:
        top = series.dropna().value_counts().head(5)
        result["most_common"] = [
            {"value": str(idx), "rows": int(count)} for idx, count in top.items()
        ]
        listed = ", ".join(f"{idx} ({count:,})" for idx, count in top.items())
        summary = (
            f"{_friendly(column).capitalize()} has "
            f"{result['distinct_values']:,} different "
            f"{'value' if result['distinct_values'] == 1 else 'values'}. Most common: "
            f"{listed}. {_rows(n_missing)} have no value."
        )
        action = None

    return {"result": result, "summary": summary, "action": action, "table": None}


def _tool_overview(
    df: pd.DataFrame, profile: Dict[str, Any], routing: Dict[str, Any]
) -> Dict[str, Any]:
    """What the dataset is, in one paragraph.

    Reads the profile rather than the frame wherever it can: the profile already
    knows every column's kind and date range, and recomputing that here would be
    a second answer to a question the app has already answered once.
    """
    kinds: Dict[str, int] = {}
    for column in profile.get("columns", []):
        kind = str(column.get("semantic_type"))
        kinds[kind] = kinds.get(kind, 0) + 1

    covers = None
    time_col = routing.get("time_col")
    if time_col:
        meta = next(
            (c for c in profile.get("columns", []) if str(c.get("name")) == time_col),
            {},
        )
        if meta.get("min_date") and meta.get("max_date"):
            covers = f"{str(meta['min_date'])[:10]} to {str(meta['max_date'])[:10]}"

    measure = routing.get("target_col")
    def columns_of(n: int, kind: str) -> str:
        return f"{n} {kind} column" if n == 1 else f"{n} {kind} columns"

    pieces = []
    if kinds.get("datetime"):
        pieces.append(columns_of(kinds["datetime"], "date"))
    if kinds.get("numeric"):
        pieces.append(columns_of(kinds["numeric"], "number"))
    if kinds.get("categorical"):
        pieces.append(columns_of(kinds["categorical"], "category"))
    if kinds.get("geo_lat") or kinds.get("geo_lon"):
        pieces.append("location coordinates")

    summary = (
        f"This dataset has {len(df):,} rows and {df.shape[1]} columns"
        + (f", made up of {', '.join(pieces)}" if pieces else "")
        + ". "
        + (f"It covers {covers}. " if covers else "")
        + (
            f"The main thing it measures is {_friendly(measure)}. "
            if measure
            else ""
        )
        + (
            f"Rows are grouped by {_friendly(routing['entity_col'])}."
            if routing.get("entity_col")
            else ""
        )
    ).strip()

    return {
        "result": {
            "rows": int(len(df)),
            "columns": int(df.shape[1]),
            "column_kinds": kinds,
            "covers": covers,
            "main_measure": measure,
            "grouped_by": routing.get("entity_col"),
            "shaped_as": routing.get("archetype"),
        },
        "summary": summary,
        "action": (
            {"chart": "line", "x": time_col, "y": measure}
            if time_col and measure
            else ({"chart": "histogram", "x": measure} if measure else None)
        ),
        "table": None,
    }


def _tool_count(df: pd.DataFrame, args: Dict[str, Any]) -> Dict[str, Any]:
    column = args.get("column")
    value = args.get("value")

    if not column or value is None:
        return {
            "result": {"rows": int(len(df)), "columns": int(df.shape[1])},
            "summary": (
                f"This dataset has {len(df):,} rows and {df.shape[1]} columns."
            ),
            "action": None,
            "table": None,
        }

    resolved = _resolve(df, column, "the column to filter on")
    as_text = df[resolved].astype("string").str.strip().str.lower()
    matches = int((as_text == str(value).strip().lower()).sum())
    return {
        "result": {
            "column": resolved,
            "value": str(value),
            "matching_rows": matches,
            "total_rows": int(len(df)),
            "share_pct": round(100.0 * matches / max(1, len(df)), 2),
        },
        "summary": (
            f"{matches:,} of {len(df):,} rows have {_friendly(resolved)} = "
            f"{value!r} — {100.0 * matches / max(1, len(df)):.1f}% of the data."
        ),
        "action": None,
        "table": None,
    }


# ------------------------------------------------------------------- runner --
def run(
    df: pd.DataFrame,
    profile: Dict[str, Any],
    routing: Dict[str, Any],
    tool: str,
    args: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute one plan against the data.

    Args:
        df: the session's DataFrame.
        profile: core.profiler output, used by `describe`.
        routing: core.router output, used to fill in the date column when a
            trend request does not name one.
        tool: a key of TOOLS.
        args: the plan's arguments. Unknown keys are ignored; missing required
            ones produce a ToolError naming what was missing.

    Returns:
        {"ok": bool, "tool": str, "args": {...}, "result": {...},
         "summary": str, "action": spec|None, "table": {...}|None,
         "error": str|None}

    Never raises for a bad plan. A plan is an untrusted input -- it comes from a
    model or from a URL -- and the caller's remedy for every failure is the same:
    show the sentence. Raising would only mean writing that branch twice.
    """
    args = dict(args or {})
    name = str(tool or "").strip().lower()

    if name not in TOOLS:
        return {
            "ok": False, "tool": name, "args": args, "result": {},
            "summary": "", "action": None, "table": None,
            "error": (
                f"{name!r} is not something this app can work out. It can rank, "
                f"total, describe a column, measure a trend, compare two columns, "
                f"find unusual rows and count rows."
            ),
        }

    try:
        if name == "rank":
            payload = _tool_rank(df, args)
        elif name == "aggregate":
            payload = _tool_aggregate(df, args)
        elif name == "trend":
            payload = _tool_trend(df, args, routing.get("time_col"))
        elif name == "relationship":
            payload = _tool_relationship(df, args)
        elif name == "outliers":
            payload = _tool_outliers(df, args)
        elif name == "describe":
            payload = _tool_describe(df, args, profile)
        elif name == "overview":
            payload = _tool_overview(df, profile, routing)
        else:
            payload = _tool_count(df, args)
    except ToolError as exc:
        return {
            "ok": False, "tool": name, "args": args, "result": {},
            "summary": "", "action": None, "table": None, "error": str(exc),
        }
    except (KeyError, IndexError, TypeError, ValueError, ArithmeticError) as exc:
        # A data condition the tool did not anticipate. Logged with a traceback;
        # the user gets a sentence, in keeping with the app's error policy.
        logger.exception("Tool %s failed with args %s", name, args)
        return {
            "ok": False, "tool": name, "args": args, "result": {},
            "summary": "", "action": None, "table": None,
            "error": "That calculation did not work on this dataset.",
        }

    action = payload.get("action")
    if action and not charts.spec_is_supported(action, df):
        action = None

    return {
        "ok": True,
        "tool": name,
        "args": args,
        "result": payload["result"],
        "summary": payload["summary"],
        "action": action,
        "table": payload.get("table"),
        "error": None,
    }


# ------------------------------------------------------------- rule planner --
# Word groups that signal each tool. Ordered by specificity when scanned: a
# question containing both "unusual" and "average" is asking about unusual
# values, so the outlier group is tested first.
_INTENTS: List[Tuple[str, Tuple[str, ...]]] = [
    # Listed first because its phrases are the most specific: "what is the most
    # important thing here" contains "most", and matching that as a ranking
    # question would answer "which region sells most" to somebody asking what
    # they are looking at.
    ("overview", ("summar*", "overview", "what is this", "what am i looking at",
                  "most important", "what matters", "explain this data*",
                  "tell me about this data*", "what does this data* ")),
    ("outliers", ("unusual", "anomal*", "outlier*", "strange", "odd", "weird",
                  "unexpected", "spike*", "surpris*")),
    ("relationship", ("relationship", "related", "correlat*", "linked",
                      "link between", "affect*", "influenc*", "impact*",
                      "depend*", "driven by", "connection")),
    ("trend", ("trend*", "over time", "growing", "grow", "declin*", "increas*",
               "decreas*", "rising", "falling", "fell", "dropped", "changed over",
               "trajectory", "momentum")),
    ("rank", ("top", "highest", "best", "most", "largest", "biggest", "leading",
              "leader", "rank*", "worst", "lowest", "smallest", "bottom",
              "fastest growing", "which category", "which region", "compare")),
    ("aggregate", ("average", "mean", "total", "sum", "how much", "median",
                   "maximum", "minimum")),
    ("count", ("how many rows", "row count", "how many records", "how big")),
    ("describe", ("describe", "tell me about", "what is in", "range of",
                  "distribution", "spread of", "what values")),
]


def _matches(text: str, keyword: str) -> bool:
    """Does a keyword appear in the question as a word rather than as letters?

    A plain substring test reads "mean" out of "the meaning of life" and answers
    a philosophical question with an arithmetic mean. Every keyword is therefore
    anchored to word boundaries; a trailing "*" marks a stem ("anomal*" is meant
    to catch anomaly, anomalies and anomalous), which drops the closing boundary
    and keeps the opening one.
    """
    if keyword.endswith("*"):
        return re.search(r"\b" + re.escape(keyword[:-1]), text) is not None
    return re.search(r"\b" + re.escape(keyword) + r"\b", text) is not None



def _mentioned_columns(question: str, df: pd.DataFrame) -> List[str]:
    """Columns whose names appear in the question, longest name first.

    Longest first because "sales" is a substring of "sales_region", and matching
    the shorter name would answer a question about regions with a question about
    sales. Word boundaries stop "id" matching inside "paid".
    """
    lowered = question.lower()
    found = []
    for name in sorted((str(c) for c in df.columns), key=len, reverse=True):
        spaced = name.lower().replace("_", " ")
        for candidate in {name.lower(), spaced}:
            if re.search(rf"\b{re.escape(candidate)}\b", lowered):
                found.append(name)
                break
    return found


def plan_from_keywords(
    question: str,
    df: pd.DataFrame,
    profile: Dict[str, Any],
    routing: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Guess a plan from the words in a question. Returns None if nothing fits.

    Used as the assistant's planner when no LLM is configured, and as a fallback
    when one is configured but unreachable. Returning None is a first-class
    outcome: an unrecognised question should be answered with "I could not work
    out what to calculate", never with a calculation nobody asked for.
    """
    text = str(question or "").strip().lower()
    if not text:
        return None

    intent = next(
        (name for name, words in _INTENTS if any(_matches(text, w) for w in words)),
        None,
    )
    if intent is None:
        return None

    semantic = {str(c["name"]): c["semantic_type"] for c in profile.get("columns", [])}
    mentioned = _mentioned_columns(text, df)
    numeric_mentioned = [c for c in mentioned if semantic.get(c) in ("numeric", "categorical")
                         and pd.to_numeric(df[c], errors="coerce").notna().any()]
    categorical_mentioned = [c for c in mentioned if semantic.get(c) == "categorical"]

    measure = (
        numeric_mentioned[0]
        if numeric_mentioned
        else routing.get("target_col")
    )
    group = (
        categorical_mentioned[0]
        if categorical_mentioned
        else routing.get("entity_col")
    )

    # A plan is "confident" when the question named a real column, or when the
    # intent needs no column at all. The caller uses that to decide whether to
    # spend a model call on planning: rules are free and instant, and on a
    # question that names its own subject they are also right. Where the rules
    # are guessing at the subject, the model is worth the round trip.
    confident = bool(mentioned) or intent in ("overview", "count")

    if intent == "rank":
        if not group or not measure:
            return None
        wants_bottom = any(
            _matches(text, w)
            for w in ("worst", "lowest", "smallest", "bottom", "least")
        )
        return {
            "tool": "rank",
            "confident": confident,
            "args": {
                "group_by": group,
                "measure": measure,
                "agg": (
                    "sum"
                    if any(_matches(text, w) for w in ("total", "sum", "most"))
                    else "mean"
                ),
                "order": "bottom" if wants_bottom else "top",
                "n": 10,
            },
        }

    if intent == "relationship":
        if len(numeric_mentioned) >= 2:
            a, b = numeric_mentioned[0], numeric_mentioned[1]
        elif numeric_mentioned and routing.get("target_col") not in (None, numeric_mentioned[0]):
            a, b = numeric_mentioned[0], routing["target_col"]
        else:
            return None
        return {
            "tool": "relationship",
            "confident": confident,
            "args": {"column_a": a, "column_b": b},
        }

    if intent == "trend":
        if not measure or not routing.get("time_col"):
            return None
        return {"tool": "trend", "confident": confident, "args": {"measure": measure}}

    if intent == "outliers":
        if not measure:
            return None
        return {
            "tool": "outliers",
            "confident": confident,
            "args": {"measure": measure, "n": 5},
        }

    if intent == "aggregate":
        if not measure:
            return None
        if _matches(text, "total") or _matches(text, "sum"):
            agg = "sum"
        elif _matches(text, "median"):
            agg = "median"
        elif _matches(text, "maximum") or _matches(text, "highest"):
            agg = "max"
        elif _matches(text, "minimum") or _matches(text, "lowest"):
            agg = "min"
        else:
            agg = "mean"
        return {
            "tool": "aggregate",
            "confident": confident,
            "args": {"measure": measure, "agg": agg},
        }

    if intent == "overview":
        return {"tool": "overview", "confident": True, "args": {}}

    if intent == "count":
        return {"tool": "count", "confident": True, "args": {}}

    if intent == "describe":
        column = mentioned[0] if mentioned else measure
        if not column:
            return None
        return {"tool": "describe", "confident": confident, "args": {"column": column}}

    return None


def catalogue(df: pd.DataFrame, profile: Dict[str, Any]) -> Dict[str, Any]:
    """What a planner needs to know: the tool menu and the columns it may name.

    Sent to the LLM instead of the data. Note that it carries column names and
    types only -- no values -- so the planning step discloses strictly less than
    the answering step already does.
    """
    columns = []
    for column in profile.get("columns", [])[:60]:
        columns.append(
            {
                "name": column.get("name"),
                "kind": column.get("semantic_type"),
                "distinct_values": column.get("n_unique"),
            }
        )
    return {
        "tools": {name: spec for name, spec in TOOLS.items()},
        "columns": columns,
        "n_rows": int(len(df)),
    }
