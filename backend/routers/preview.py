"""Preview endpoint: a window onto the actual rows, for the Explore screen.

WHY THIS EXISTS AT ALL, given the rest of the app is careful never to move rows
around: the rows here go to the person who uploaded them, in their own session,
because they asked to look at their own spreadsheet. That is a completely
different act from sending rows to a third-party model, which is what the chat
module refuses to do. Charts and statistics are the app's answer to "what is in
this file"; they are not a substitute for occasionally seeing the file.

The cap is enforced on the server, not requested by the client. The whole frame
is in memory, and serialising a million rows to JSON would take the process down
for every session it holds -- so `limit` narrows the window and can never widen
it past MAX_ROWS.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from backend.models import PreviewResponse
from backend.routers._common import require_session
from backend.serialisation import jsonable

logger = logging.getLogger(__name__)

router = APIRouter(tags=["preview"])

# 200 rows is enough to scroll, recognise the file and spot an obviously broken
# column, and small enough that the payload stays well under a megabyte for a
# realistically wide table.
MAX_ROWS = 200


@router.get("/preview/{sid}", response_model=PreviewResponse)
def preview(
    sid: str,
    limit: int = Query(default=50, ge=1, le=MAX_ROWS),
) -> PreviewResponse:
    """Return the first `limit` rows of a session's dataset."""
    session = require_session(sid)
    frame = session.df.head(limit)

    return PreviewResponse(
        columns=[str(c) for c in session.df.columns],
        # Row-major lists rather than dicts: a dict per row repeats every column
        # name once per row, which on a 40-column table is most of the payload.
        rows=[[jsonable(value) for value in row] for row in frame.itertuples(index=False)],
        n_rows_total=int(len(session.df)),
        n_rows_returned=int(len(frame)),
        truncated=bool(len(session.df) > len(frame)),
        # The profile travels with the rows. It is read off the session rather
        # than recomputed, and the session's profile is replaced whenever the
        # frame is -- see backend/routers/quality.py -- so the two always agree.
        profile=jsonable(session.profile.get("columns", [])),
    )
