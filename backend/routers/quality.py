"""Data health, the cleaning workflow, and exporting the result.

THE SHAPE OF THE CLEANING FLOW, AND WHY IT HAS THREE STEPS
-----------------------------------------------------------
    GET  /health/{sid}        here is what is wrong
    POST /clean/{sid}/plan    here is exactly what I would change
    POST /clean/{sid}         change it
    POST /clean/{sid}/revert  put it back

The plan step exists because "I found 342 issues -- fix them?" is not informed
consent. A user approving a clean is agreeing to a specific set of operations
against a specific set of columns, and they cannot agree to it without seeing
it. So the plan endpoint returns the operations in the order they will run,
each with the sentence that describes it, and changes nothing.

Revert exists because half of these operations have no inverse. You cannot
un-cap a value or un-drop a row. The original frame is therefore kept intact on
the session for the whole of its life -- see backend.session.Session -- and
reverting is dropping a reference rather than computing an undo. That is the
only implementation of "your original file is preserved" that is actually true
under every code path.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException, Response, status

from backend.models import (
    CleanPlanResponse,
    CleanRequest,
    CleanResponse,
    HealthResponseBody,
)
from backend.routers import _analysis
from backend.routers._common import require_session
from backend.serialisation import jsonable
from backend.session import store
from core import cleaner, health, report
from core.profiler import profile_dataframe

logger = logging.getLogger(__name__)

router = APIRouter(tags=["quality"])


@router.get("/health-report/{sid}", response_model=HealthResponseBody)
def get_health_report(sid: str) -> HealthResponseBody:
    """Score this dataset's quality and list everything wrong with it.

    Named `health-report` rather than `health` because /api/health already
    means "is the server up" -- a much older route that the frontend polls to
    decide whether to show its offline banner. Two routes whose names differ
    only by a path parameter is exactly the kind of collision that produces an
    outage banner in front of an audience.
    """
    session = require_session(sid)
    return HealthResponseBody(**_analysis.get_health(session))


@router.post("/clean/{sid}/plan", response_model=CleanPlanResponse)
def plan_clean(sid: str, request: CleanRequest) -> CleanPlanResponse:
    """Say exactly what would be changed, and change nothing.

    Note that `issue_ids: null` and `issue_ids: []` mean different things here
    and both are legitimate requests -- everything, and nothing. core.cleaner.plan
    makes the same distinction, so the two agree by construction rather than by
    both remembering to.
    """
    session = require_session(sid)
    assessment = _analysis.get_health(session)

    steps = cleaner.plan(assessment, request.issue_ids)

    if not steps:
        note = (
            "Nothing to do. Either no issues were selected, or none of the "
            "issues found can be repaired automatically."
        )
    else:
        note = (
            f"{len(steps)} change(s) would be applied, in the order shown -- "
            f"text is tidied before categories are merged, and rows are removed "
            f"before gaps are filled, so each step sees the result of the last. "
            f"Your original file is kept either way."
        )

    return CleanPlanResponse(steps=jsonable(steps), n_steps=len(steps), note=note)


@router.post("/clean/{sid}", response_model=CleanResponse)
def apply_clean(sid: str, request: CleanRequest) -> CleanResponse:
    """Apply the approved repairs, producing a cleaned copy of the dataset.

    The original stays on the session untouched. What changes is which frame
    the rest of the app reads -- so every subsequent chart, insight and answer
    is computed from the cleaned data, and the user can switch back at any time
    without having lost anything.
    """
    session = require_session(sid)
    assessment = _analysis.get_health(session)
    steps = cleaner.plan(assessment, request.issue_ids)

    if not steps:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "None of the selected issues can be repaired automatically, so "
                "there is nothing to apply."
            ),
        )

    try:
        cleaned, receipt = cleaner.apply(session.df, steps)
    except cleaner.CleanError as exc:
        # CleanError carries a sentence written for a user, so it is passed
        # through verbatim rather than replaced with a generic message.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        logger.exception("Cleaning failed for %s", sid)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "The dataset could not be cleaned. Your original data is "
                "unchanged. The error has been logged."
            ),
        ) from exc

    # The frame changed, so every cached analysis computed from it is now about
    # a dataset that no longer exists. All of them go together.
    session.df = cleaned
    session.profile = profile_dataframe(cleaned)
    session.is_cleaned = True
    session.clean_receipt = jsonable(receipt)
    session.invalidate()

    session.record(
        "cleaned",
        receipt["summary"].split(" Your original")[0],
        n_fixes=len(receipt["log"]),
        rows_removed=receipt["rows_before"] - receipt["rows_after"],
        cells_changed=receipt["cells_changed"],
    )
    store.touch_index(session)

    # Recomputed immediately rather than lazily, so the response carries the new
    # score. A user who just approved eleven fixes wants to see the number move
    # in the same interaction, not after a navigation.
    new_health = _analysis.get_health(session)

    return CleanResponse(
        summary=receipt["summary"],
        log=jsonable(receipt["log"]),
        applied=receipt["applied"],
        rows_before=receipt["rows_before"],
        rows_after=receipt["rows_after"],
        cols_before=receipt["cols_before"],
        cols_after=receipt["cols_after"],
        cells_changed=receipt["cells_changed"],
        health=new_health,
        is_cleaned=True,
    )


@router.post("/clean/{sid}/revert", response_model=CleanResponse)
def revert_clean(sid: str) -> CleanResponse:
    """Go back to the file as it was uploaded.

    Implemented as a reassignment rather than an undo, which is why it always
    works: `session.original` has been sitting there untouched since the upload,
    so there is no sequence of cleans that can leave a dataset unrevertable.
    """
    session = require_session(sid)

    if not session.is_cleaned or session.original is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This dataset has not been cleaned, so there is nothing to undo.",
        )

    rows_before, cols_before = len(session.df), len(session.df.columns)

    session.df = session.original
    session.profile = profile_dataframe(session.original)
    session.is_cleaned = False
    session.clean_receipt = None
    session.invalidate()

    session.record(
        "reverted",
        f"Restored the original file: {len(session.df):,} rows, "
        f"{len(session.df.columns)} columns.",
    )
    store.touch_index(session)
    new_health = _analysis.get_health(session)

    return CleanResponse(
        summary=(
            f"Reverted to your original file -- {len(session.df):,} rows and "
            f"{len(session.df.columns)} columns. Every chart and finding on "
            f"this dataset now comes from the data exactly as you uploaded it."
        ),
        log=[],
        applied=[],
        rows_before=rows_before,
        rows_after=len(session.df),
        cols_before=cols_before,
        cols_after=len(session.df.columns),
        cells_changed=0,
        health=new_health,
        is_cleaned=False,
    )


def _safe_filename(name: str, suffix: str) -> str:
    """A download filename that cannot smuggle anything into the header.

    The uploaded name reaches a Content-Disposition header, which is a place
    user-controlled text does not belong: a newline in it splits the header, and
    a quote breaks out of the filename parameter. Everything outside a
    conservative whitelist is replaced rather than escaped, because escaping
    rules for this header differ between browsers and a stripped-down name is
    always safe.
    """
    stem = re.sub(r"\.csv$", "", str(name or "dataset"), flags=re.IGNORECASE)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._") or "dataset"
    return f"{stem[:60]}{suffix}.csv"


@router.get("/export/{sid}")
def export_csv(sid: str, original: bool = False) -> Response:
    """Download the dataset as CSV -- cleaned by default, original on request.

    Returned as a raw Response rather than through a response_model because the
    body is a CSV document, not JSON. FastAPI would otherwise wrap the string in
    quotes and escape every newline in it, producing a file that is technically
    a valid JSON string and useless as a spreadsheet.
    """
    session = require_session(sid)

    if original:
        frame = session.original if session.original is not None else session.df
        suffix = "-original"
    else:
        frame = session.df
        suffix = "-cleaned" if session.is_cleaned else ""

    body = report.to_csv(frame)
    filename = _safe_filename(session.filename, suffix)

    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
