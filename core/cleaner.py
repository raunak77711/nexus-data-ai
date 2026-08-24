"""Applies the repairs core.health proposed -- and only the ones a user approved.

THE ONE RULE
------------
Nothing in this module runs unless it was named in a request. There is no
"clean my data" function that decides for itself what to do, because the
difference between a tool people trust with their only copy of something and a
tool people use once is whether it ever surprised them. core.health proposes;
the user approves; this applies. Three steps, three places, and the approval
step cannot be skipped by any code path.

WHAT COMES BACK
---------------
`apply` returns a NEW frame and never mutates its argument. The session keeps
the original alongside the cleaned copy, so "revert" is dropping a reference
rather than an inverse operation -- which matters because half the operations
here (dropping a row, capping a value) have no inverse once applied.

Every operation also returns a log entry saying what it actually did, in
numbers: rows before, rows after, cells changed. That log is shown to the user
after the fact and is the honest counterpart to the estimate they approved --
an estimate is made from a scan, and a scan of a sample can be wrong. If a fix
that promised to remove 342 rows removed 341, the log says 341.

FAILURE
-------
An operation whose column has vanished, or whose parameters do not fit the
data, raises CleanError with a sentence fit to show a user. It never half-
applies: the caller runs operations in sequence against a working copy and
either gets the whole result or the exception, so a failed sixth fix cannot
leave the dataset in a state that is neither cleaned nor original.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core import health

logger = logging.getLogger(__name__)


class CleanError(ValueError):
    """An operation that cannot be applied, carrying a sentence for a user.

    A ValueError subclass so routers that already map ValueError to 400 -- "the
    request was wrong, not the server" -- need no new except clause.
    """


# Fill strategies for a numeric column. Whitelisted rather than passed through
# to pandas, because the strategy name reaches a method lookup and an
# unvalidated one is the one place a request could name an arbitrary attribute.
NUMERIC_STRATEGIES = ("median", "mean", "zero", "forward", "drop")

MAX_LOG_EXAMPLES = 5


def _require_column(df: pd.DataFrame, name: Any, action: str) -> str:
    """Resolve a column name, raising something a user can act on.

    Names are matched case-insensitively as a fallback because a fix proposed
    against one snapshot may be applied after an earlier fix in the same batch
    renamed nothing but changed the frame -- and because a user hand-editing a
    request should not be defeated by capitalisation.
    """
    if name is None:
        raise CleanError(f"The {action} fix did not say which column to work on.")
    text = str(name)
    if text in df.columns:
        return text
    lowered = {str(c).lower(): str(c) for c in df.columns}
    if text.lower() in lowered:
        return lowered[text.lower()]
    raise CleanError(
        f"There is no column called `{text}` any more, so the {action} fix "
        f"cannot run. It may have been removed by an earlier fix in this batch."
    )


def _log(
    action: str,
    summary: str,
    *,
    rows_before: int,
    rows_after: int,
    cells_changed: int = 0,
    column: Optional[str] = None,
    examples: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """One line of the receipt shown after a clean."""
    return {
        "action": action,
        "column": column,
        "summary": summary,
        "rows_before": int(rows_before),
        "rows_after": int(rows_after),
        "rows_removed": int(rows_before - rows_after),
        "cells_changed": int(cells_changed),
        "examples": (examples or [])[:MAX_LOG_EXAMPLES],
    }


# ------------------------------------------------------------- operations --
# Every operation has the same signature -- (df, params) -> (df, log) -- so the
# dispatcher below is a dict lookup rather than a chain of if-statements, and
# adding one is adding a function and a dict entry.


def _op_drop_duplicates(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Remove rows that are exact copies of an earlier row."""
    before = len(df)
    cleaned = df.drop_duplicates(keep="first")
    removed = before - len(cleaned)
    return cleaned, _log(
        "drop_duplicates",
        f"Removed {removed:,} duplicate row(s), keeping the first copy of each."
        if removed
        else "No duplicate rows were left to remove.",
        rows_before=before,
        rows_after=len(cleaned),
    )


def _op_drop_column(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Remove one column entirely."""
    column = _require_column(df, params.get("column"), "remove column")
    if len(df.columns) <= 1:
        raise CleanError(
            f"`{column}` is the only column left. Removing it would leave "
            f"nothing to analyse."
        )
    return df.drop(columns=[column]), _log(
        "drop_column",
        f"Removed the `{column}` column.",
        rows_before=len(df),
        rows_after=len(df),
        cells_changed=len(df),
        column=column,
    )


def _op_fill_missing(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Give the blanks in one column a value -- or drop the rows that have one.

    Text sentinels ("N/A", "unknown") are converted to real blanks first, so
    that a fill actually reaches them. Without that step the column would end up
    holding both the fill value and the string "N/A" meaning the same thing,
    which is a worse state than the one it started in.
    """
    column = _require_column(df, params.get("column"), "fill missing")
    strategy = str(params.get("strategy") or "").strip().lower()
    series = df[column]
    cleaned = df.copy()

    if health._is_text(series):
        as_text = series.astype("string")
        sentinel_mask = as_text.str.strip().str.lower().isin(health.NULL_SENTINELS)
        working = as_text.mask(sentinel_mask.fillna(False))
    else:
        working = series

    missing_mask = working.isna()
    n_missing = int(missing_mask.sum())

    if not n_missing:
        return df, _log(
            "fill_missing",
            f"`{column}` had no gaps left to fill.",
            rows_before=len(df),
            rows_after=len(df),
            column=column,
        )

    if strategy == "drop":
        cleaned = cleaned.loc[~missing_mask]
        return cleaned, _log(
            "fill_missing",
            f"Removed {n_missing:,} row(s) that had no value for `{column}`.",
            rows_before=len(df),
            rows_after=len(cleaned),
            column=column,
        )

    if strategy == "label":
        label = str(params.get("value") or "Unknown")
        cleaned[column] = working.fillna(label).astype("string")
        return cleaned, _log(
            "fill_missing",
            f'Labelled {n_missing:,} blank value(s) in `{column}` as "{label}".',
            rows_before=len(df),
            rows_after=len(df),
            cells_changed=n_missing,
            column=column,
            examples=[label],
        )

    numbers = pd.to_numeric(working, errors="coerce")
    if numbers.notna().sum() == 0:
        raise CleanError(
            f"`{column}` has no numbers in it, so it cannot be filled with a "
            f"{strategy}. Label the gaps instead."
        )

    if strategy in ("median", "mean"):
        value = float(numbers.median() if strategy == "median" else numbers.mean())
        cleaned[column] = numbers.fillna(value)
        what = f"the {strategy}, {health._fmt(value)}"
    elif strategy == "zero":
        cleaned[column] = numbers.fillna(0)
        what = "zero"
    elif strategy == "forward":
        # ffill then bfill, so a gap at the very start of the column is filled
        # too. ffill alone leaves leading blanks blank, which looks like the fix
        # silently did not run.
        cleaned[column] = numbers.ffill().bfill()
        what = "the previous row's value"
    else:
        raise CleanError(
            f"{strategy!r} is not a way of filling gaps this app knows. "
            f"Available: {', '.join(NUMERIC_STRATEGIES)}, or label."
        )

    return cleaned, _log(
        "fill_missing",
        f"Filled {n_missing:,} gap(s) in `{column}` with {what}.",
        rows_before=len(df),
        rows_after=len(df),
        cells_changed=n_missing,
        column=column,
    )


def _op_to_numeric(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Turn a text column of decorated numbers into a real numeric column.

    The stripping here must match core.health._check_numeric_as_text exactly,
    or the app would offer a fix for a column and then convert a different set
    of values than the one it counted.
    """
    column = _require_column(df, params.get("column"), "convert to number")
    series = df[column]

    if pd.api.types.is_numeric_dtype(series):
        return df, _log(
            "to_numeric",
            f"`{column}` is already a number column.",
            rows_before=len(df),
            rows_after=len(df),
            column=column,
        )

    # The SAME stripper the health check counted with. Two implementations here
    # would mean offering to convert 312 values and converting a different
    # number of them -- the user approving one thing and getting another.
    text, numbers = health.strip_numeric_decoration(series)
    n_converted = int(numbers.notna().sum())
    if not n_converted:
        raise CleanError(
            f"Nothing in `{column}` reads as a number once the symbols are "
            f"removed, so converting it would empty the column."
        )

    # Values that were present and did not parse become blanks. That is a real
    # loss and is reported as one rather than described as a conversion.
    n_lost = int((text.notna() & numbers.isna()).sum())
    examples = [str(v) for v in text[text.notna() & numbers.isna()].head(3).tolist()]

    cleaned = df.copy()
    cleaned[column] = numbers
    summary = f"Converted {n_converted:,} value(s) in `{column}` to numbers."
    if n_lost:
        summary += (
            f" {n_lost:,} value(s) could not be read as a number and are now "
            f"blank (for example {', '.join(repr(e) for e in examples)})."
        )

    return cleaned, _log(
        "to_numeric",
        summary,
        rows_before=len(df),
        rows_after=len(df),
        cells_changed=n_converted,
        column=column,
        examples=examples,
    )


def _op_trim_whitespace(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Strip leading and trailing spaces from one text column."""
    column = _require_column(df, params.get("column"), "trim whitespace")
    series = df[column]
    if not health._is_text(series):
        raise CleanError(f"`{column}` is not a text column, so it has no spaces to trim.")

    text = series.astype("string")
    trimmed = text.str.strip()
    changed_mask = (text != trimmed) & text.notna()
    n_changed = int(changed_mask.sum())

    cleaned = df.copy()
    cleaned[column] = trimmed
    return cleaned, _log(
        "trim_whitespace",
        f"Trimmed spaces from {n_changed:,} value(s) in `{column}`."
        if n_changed
        else f"`{column}` had no stray spaces left.",
        rows_before=len(df),
        rows_after=len(df),
        cells_changed=n_changed,
        column=column,
        examples=[repr(v) for v in text[changed_mask].head(3).tolist()],
    )


def _op_merge_categories(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Rewrite spelling variants of a category to one agreed spelling.

    The mapping arrives from the health report rather than being recomputed, so
    the merge that happens is exactly the merge the user read and approved. A
    recomputed mapping could differ -- an earlier fix in the same batch may have
    changed which spelling is most common -- and silently merging into a
    different canonical value than the one shown is precisely the surprise this
    module exists to avoid.
    """
    column = _require_column(df, params.get("column"), "merge categories")
    raw_mapping = params.get("mapping") or {}
    if not isinstance(raw_mapping, dict) or not raw_mapping:
        raise CleanError(
            f"The merge fix for `{column}` did not carry a list of spellings to "
            f"merge, so there is nothing to apply."
        )

    mapping = {str(k): str(v) for k, v in raw_mapping.items()}
    text = df[column].astype("string")
    # Match against the stripped form so this still works when trim_whitespace
    # has not been applied -- the two fixes are independent and either order
    # must produce the same result.
    stripped = text.str.strip()
    changed_mask = stripped.isin(list(mapping)) & stripped.notna()
    n_changed = int(changed_mask.sum())

    cleaned = df.copy()
    cleaned[column] = stripped.replace(mapping)

    examples = [f"{k} -> {v}" for k, v in list(mapping.items())[:MAX_LOG_EXAMPLES]]
    return cleaned, _log(
        "merge_categories",
        f"Merged {len(mapping)} spelling(s) in `{column}`, changing "
        f"{n_changed:,} row(s)."
        if n_changed
        else f"`{column}` already used one spelling for each value.",
        rows_before=len(df),
        rows_after=len(df),
        cells_changed=n_changed,
        column=column,
        examples=examples,
    )


def _op_drop_invalid(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Remove rows whose value in one column is outside a stated range."""
    column = _require_column(df, params.get("column"), "remove invalid rows")
    low = params.get("low", params.get("min"))
    high = params.get("high", params.get("max"))
    if low is None and high is None:
        raise CleanError(
            f"The fix for `{column}` did not say what counts as invalid, so no "
            f"rows were removed."
        )

    values = pd.to_numeric(df[column], errors="coerce")
    bad = pd.Series(False, index=df.index)
    if low is not None:
        bad |= values < float(low)
    if high is not None:
        bad |= values > float(high)

    before = len(df)
    cleaned = df.loc[~bad]
    removed = before - len(cleaned)

    bounds = []
    if low is not None:
        bounds.append(f"below {health._fmt(float(low))}")
    if high is not None:
        bounds.append(f"above {health._fmt(float(high))}")

    return cleaned, _log(
        "drop_invalid",
        f"Removed {removed:,} row(s) where `{column}` was {' or '.join(bounds)}."
        if removed
        else f"No rows in `{column}` were outside the valid range.",
        rows_before=before,
        rows_after=len(cleaned),
        column=column,
    )


def _op_cap_outliers(df: pd.DataFrame, params: Dict[str, Any]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Pull extreme values back to a limit instead of deleting their rows.

    Capping rather than dropping is the default this app proposes because an
    outlier is usually a real observation -- the biggest customer, the busiest
    day -- and deleting it removes a fact. Capping keeps the row, and everything
    else on it, while stopping one value from deciding an average.
    """
    column = _require_column(df, params.get("column"), "cap outliers")
    values = pd.to_numeric(df[column], errors="coerce")

    low = params.get("low")
    high = params.get("high")
    if low is None or high is None:
        # Recomputing the fence is safe here in a way that recomputing a
        # category mapping is not: the fence is a property of the column's
        # distribution and is stated in the log either way.
        bounds = health.outlier_bounds(values)
        if bounds is None:
            raise CleanError(
                f"`{column}` does not have enough spread to work out what counts "
                f"as an extreme value."
            )
        low, high = bounds

    low, high = float(low), float(high)
    n_capped = int(((values < low) | (values > high)).sum())

    cleaned = df.copy()
    cleaned[column] = values.clip(lower=low, upper=high)

    return cleaned, _log(
        "cap_outliers",
        f"Capped {n_capped:,} extreme value(s) in `{column}` to the range "
        f"{health._fmt(low)} to {health._fmt(high)}."
        if n_capped
        else f"`{column}` had no values outside its normal range.",
        rows_before=len(df),
        rows_after=len(df),
        cells_changed=n_capped,
        column=column,
    )


Operation = Callable[[pd.DataFrame, Dict[str, Any]], Tuple[pd.DataFrame, Dict[str, Any]]]

OPERATIONS: Dict[str, Operation] = {
    "drop_duplicates": _op_drop_duplicates,
    "drop_column": _op_drop_column,
    "fill_missing": _op_fill_missing,
    "to_numeric": _op_to_numeric,
    "trim_whitespace": _op_trim_whitespace,
    "merge_categories": _op_merge_categories,
    "drop_invalid": _op_drop_invalid,
    "cap_outliers": _op_cap_outliers,
}

# The order fixes are applied in, regardless of the order they arrive in.
#
# This is not cosmetic. Converting a text column to numbers must happen before
# anything tries to fill its gaps with a median, or the median is computed over
# nothing. Trimming whitespace must happen before merging categories, or the
# merge matches fewer rows than it promised. Dropping duplicate rows should
# happen AFTER the text normalisations, because two rows that differ only by a
# trailing space are duplicates the moment that space is gone -- and a user who
# approved both fixes expects both to have had their full effect.
#
# Sorting here rather than asking the caller to send them in order means the UI
# can present fixes in whatever order reads best.
APPLY_ORDER = (
    "trim_whitespace",
    "merge_categories",
    "to_numeric",
    "drop_column",
    "drop_invalid",
    "cap_outliers",
    "drop_duplicates",
    "fill_missing",
)


def _rank(action: str) -> int:
    try:
        return APPLY_ORDER.index(action)
    except ValueError:
        return len(APPLY_ORDER)


def plan(assessment: Dict[str, Any], issue_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Turn a health report into the list of operations to run.

    Args:
        assessment: core.health.assess output.
        issue_ids: which issues the user approved. None means every issue that
            carries a fix -- the "fix everything" button -- and an empty list
            means none, which is not the same thing and must not be conflated.

    Returns:
        A list of {"issue_id", "action", "params", "label", "description"},
        sorted into the order they must be applied in.
    """
    approved = None if issue_ids is None else set(issue_ids)
    steps: List[Dict[str, Any]] = []

    for issue in assessment.get("issues", []):
        fix = issue.get("fix")
        if not fix:
            continue
        if approved is not None and issue["id"] not in approved:
            continue
        steps.append(
            {
                "issue_id": issue["id"],
                "action": fix["action"],
                "params": dict(fix.get("params") or {}),
                "label": fix["label"],
                "description": fix["description"],
                "severity": issue["severity"],
            }
        )

    steps.sort(key=lambda step: _rank(step["action"]))
    return steps


def apply(df: pd.DataFrame, steps: List[Dict[str, Any]]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Run a list of approved operations against a copy of the frame.

    Args:
        df: the original DataFrame. Not modified -- every operation returns a
            new frame, and the original reference the caller holds is still the
            original data afterwards.
        steps: plan() output, or any list of {"action", "params"}.

    Returns:
        (cleaned_df, receipt) where receipt is
        {"log": [...], "rows_before", "rows_after", "cols_before", "cols_after",
         "cells_changed", "summary", "applied": [issue_id, ...]}

    Raises:
        CleanError: for an unknown action or one that cannot run. Nothing is
            returned in that case, so the caller keeps the original frame and
            the dataset is never left half-cleaned.
    """
    working = df
    log: List[Dict[str, Any]] = []
    applied: List[str] = []

    rows_before, cols_before = len(df), len(df.columns)

    for step in sorted(steps, key=lambda s: _rank(str(s.get("action")))):
        action = str(step.get("action") or "")
        operation = OPERATIONS.get(action)
        if operation is None:
            raise CleanError(
                f"{action!r} is not a repair this app can make. Available: "
                f"{', '.join(sorted(OPERATIONS))}."
            )
        working, entry = operation(working, dict(step.get("params") or {}))
        entry["label"] = step.get("label", entry["summary"])
        entry["issue_id"] = step.get("issue_id")
        log.append(entry)
        if step.get("issue_id"):
            applied.append(str(step["issue_id"]))

    rows_after, cols_after = len(working), len(working.columns)
    cells_changed = sum(entry["cells_changed"] for entry in log)
    rows_removed = rows_before - rows_after
    cols_removed = cols_before - cols_after

    parts = []
    if rows_removed:
        parts.append(f"removed {rows_removed:,} row(s)")
    if cols_removed:
        parts.append(f"removed {cols_removed} column(s)")
    if cells_changed:
        parts.append(f"changed {cells_changed:,} value(s)")

    summary = (
        f"Applied {len(log)} fix(es): {', '.join(parts)}."
        if parts
        else f"Applied {len(log)} fix(es). Nothing needed changing."
    )
    summary += (
        f" Your original file is untouched -- {rows_before:,} rows, "
        f"{cols_before} columns -- and you can switch back to it at any time."
    )

    return working, {
        "log": log,
        "applied": applied,
        "rows_before": rows_before,
        "rows_after": rows_after,
        "cols_before": cols_before,
        "cols_after": cols_after,
        "cells_changed": cells_changed,
        "summary": summary,
    }
