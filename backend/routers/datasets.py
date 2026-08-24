"""My Datasets: the list, deleting one, and comparing two.

WHY A LIST ENDPOINT EXISTS AT ALL, given there is no login. Because the
alternative -- a dataset that exists only while the tab that uploaded it stays
open -- makes every piece of analysis disposable, and a user who cannot come
back to what they found yesterday will not treat any of it as worth finding.
The store persists uploads to disk (see backend.session), so this returns real
history rather than the contents of one browser tab.

THE SCOPE OF THAT, STATED PLAINLY: this lists every dataset on the server, not
every dataset belonging to the caller, because there is no notion of a caller.
That is correct for a single-user deployment and would be a data leak in a
shared one. Adding accounts means putting an owner on the index record and a
filter on `store.list`; the shape here does not have to change for that, but the
absence of it must not be mistaken for the presence of it.
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, HTTPException, status

from backend.models import CompareRequest, CompareResponse, DatasetSummary
from backend.routers import _analysis
from backend.routers._common import require_session
from backend.serialisation import jsonable
from backend.session import store
from core import compare as compare_module

logger = logging.getLogger(__name__)

router = APIRouter(tags=["datasets"])


@router.get("/datasets", response_model=List[DatasetSummary])
def list_datasets() -> List[DatasetSummary]:
    """Every stored dataset, most recently opened first.

    Datasets that have been evicted from memory still appear, with `loaded`
    false and their analysis fields empty -- they are on disk and will be
    re-read when opened. Hiding them would make the list look like it had lost
    things it had not.
    """
    return [DatasetSummary(**row) for row in store.list()]


@router.delete("/datasets/{sid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(sid: str) -> None:
    """Forget a dataset completely, including the bytes on disk.

    A 404 for an id that is already gone, rather than a silent success. Deleting
    something twice is usually a bug in the caller, and reporting it costs
    nothing here -- the user's data is gone either way, which is what they asked
    for.
    """
    if not store.delete(sid):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That dataset is not on the server, so there is nothing to delete.",
        )


@router.post("/compare/{sid}", response_model=CompareResponse)
def compare_datasets(sid: str, request: CompareRequest) -> CompareResponse:
    """Compare this dataset against another stored one.

    Both health reports are computed first and passed in, so the comparison can
    say whether the DATA got better or worse as well as whether the numbers
    moved. That distinction matters more than it sounds: a measure that "rose
    12%" between two files, one of which has twice the missing values of the
    other, may not have risen at all.
    """
    session = require_session(sid)
    other_id = request.other_id.strip()

    if other_id == sid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That is the same dataset. Choose a different one to compare against.",
        )

    other = store.get(other_id)
    if other is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "The dataset you asked to compare against is not on the server. "
                "It may have been deleted."
            ),
        )

    try:
        # The OTHER dataset is the baseline and the current one is the result.
        # "Compare this against that" means "what changed to arrive at what I am
        # looking at now", so the file the user is currently in must be the
        # second argument -- otherwise every direction in the report is
        # inverted, and a report that says revenue fell when it rose is worse
        # than no report.
        result = compare_module.compare(
            other.df,
            other.profile,
            session.df,
            session.profile,
            name_a=other.filename,
            name_b=session.filename,
            health_a=_analysis.get_health(other),
            health_b=_analysis.get_health(session),
        )
        result = compare_module.narrate(result)
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        logger.exception("Comparison of %s against %s failed", sid, other_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Those two datasets could not be compared. The error has been "
                "logged; neither file was changed."
            ),
        ) from exc

    session.record(
        "compared",
        f"Compared against {other.filename}: {result['n_changes']} difference(s).",
        other_id=other_id,
        n_changes=result["n_changes"],
    )

    return CompareResponse(**jsonable(result))
