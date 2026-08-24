"""Upload: parse a CSV, profile it, route it, and open a session.

Profiling and routing both happen here, at upload time, rather than lazily on
first request. WHY: routing may cost a network round trip to Gemini, and doing
it inside /route would mean the user's first click after uploading sits on a
spinner for a second or two with nothing on screen. Doing it during the upload
-- when the user already expects to wait, and a progress state is already on
screen -- moves the latency to the one moment it is invisible. Both results are
cached on the session, so /route is a dict lookup.
"""

from __future__ import annotations

import io
import logging
from typing import Tuple

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile, status

from backend.models import UploadResponse
from backend.session import Session, store
from core.profiler import profile_dataframe
from core.router import route as route_profile

logger = logging.getLogger(__name__)

router = APIRouter(tags=["upload"])

# 50MB. Chosen because the whole file is held in memory as a DataFrame for the
# session's lifetime, and pandas' in-memory footprint for a CSV is typically
# 2-5x the file size -- so the real ceiling this sets is closer to 250MB of RSS
# per session, which is the number that actually matters.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Read the stream in 1MB bites so an oversized upload is rejected after ~51MB
# rather than after the client has finished sending a gigabyte.
CHUNK_BYTES = 1024 * 1024


def _read_capped(upload: UploadFile) -> bytes:
    """Read an UploadFile into memory, refusing anything over the cap.

    WHY not trust the Content-Length header: it is client-supplied and a
    truncated or lying header is the trivial way past a size check. Counting
    bytes as they arrive is the only measurement that cannot be forged.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = upload.file.read(CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"That file is larger than the "
                    f"{MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit. Sessions are held "
                    f"in memory, so the cap protects the server for everyone."
                ),
            )
        chunks.append(chunk)
    return b"".join(chunks)


def parse_csv(content: bytes, filename: str) -> pd.DataFrame:
    """Decode and parse CSV bytes, or raise a 400 the user can act on.

    UTF-8 is tried first and latin-1 second. WHY a fallback at all: exported
    spreadsheets from Windows are routinely cp1252, and latin-1 decodes any byte
    sequence without raising, so it is a guaranteed-terminating last resort. The
    risk is mojibake in a text column rather than a failed upload, which is the
    better trade for a tool whose job is to show you your data.
    """
    for encoding in ("utf-8", "latin-1"):
        try:
            frame = pd.read_csv(io.BytesIO(content), encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
        except pd.errors.EmptyDataError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="That file is empty -- there are no columns to read.",
            ) from exc
        except pd.errors.ParserError as exc:
            # The parser's own message names the offending line, which is far
            # more useful than "invalid CSV", and it contains no server paths.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"That file could not be parsed as CSV: {exc}",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"That file could not be read as CSV: {exc}",
            ) from exc
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That file's text encoding could not be decoded.",
        )

    if frame.empty or frame.shape[1] == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{filename!r} parsed but contains no rows. A header alone is not "
                f"enough to build a world from."
            ),
        )
    return frame


def ingest(content: bytes, filename: str) -> Tuple[Session, pd.DataFrame]:
    """Parse, profile, route and register one file. Shared with the samples router.

    Returns the session and the frame so callers do not have to reach back into
    the session object for something they just created.
    """
    frame = parse_csv(content, filename)

    try:
        profile = profile_dataframe(frame)
    except (TypeError, ValueError) as exc:
        # profile_dataframe raises TypeError only for a non-DataFrame, which
        # cannot happen here; a ValueError would mean a column pandas produced
        # that the profiler cannot describe. Either way it is our bug, not the
        # user's, so it is logged in full and reported in one clean line.
        logger.exception("Profiling failed for %s", filename)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That file was read but could not be profiled.",
        ) from exc

    # route() is contractually non-raising: an API outage degrades to the
    # rule-based path rather than failing the upload. No try/except here would
    # add anything except the illusion of care.
    routing = route_profile(profile)

    # The bytes are handed over so the dataset can be re-read after a restart or
    # an eviction. Without them the dataset would exist only for as long as this
    # process holds its frame, and the My Datasets screen would list entries
    # that vanish when opened.
    session = store.create(
        filename=filename,
        df=frame,
        profile=profile,
        routing=routing,
        content=content,
    )
    session.record(
        "routed",
        f"Worked out that this is {routing['archetype']} data"
        f"{' using AI' if routing['source'] == 'llm' else ' from its column types'}.",
        archetype=routing["archetype"],
        source=routing["source"],
    )
    logger.info(
        "Session %s: %s (%d rows x %d cols) routed to %s via %s",
        session.id, filename, profile["n_rows"], profile["n_cols"],
        routing["archetype"], routing["source"],
    )
    return session, frame


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_csv(file: UploadFile = File(...)) -> UploadResponse:
    """Accept a multipart CSV, profile and route it, and open a session."""
    filename = (file.filename or "upload.csv").strip()

    # Extension and declared content type are both weak signals, so this is a
    # courtesy check rather than a security control -- the real gate is whether
    # pandas can parse the bytes. It exists because "this is not a CSV" is a
    # much more useful message than a parser error about line 1.
    if not filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{filename!r} is not a .csv file. This tool reads CSV only.",
        )

    content = _read_capped(file)
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That upload contained no data.",
        )

    session, frame = ingest(content, filename)
    return UploadResponse(
        session_id=session.id,
        filename=session.filename,
        n_rows=int(len(frame)),
        n_cols=int(frame.shape[1]),
        profile=session.profile,
    )
