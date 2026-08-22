"""Helpers shared by more than one router.

Kept in a private module rather than in main.py so that importing a router does
not drag in the application object, which would make a circular import out of
what is really just a lookup function.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from backend.session import Session, store


def require_session(session_id: str) -> Session:
    """Fetch a live session or raise a clean 404.

    WHY one message for both "never existed" and "expired": distinguishing them
    would require keeping a tombstone for every id ever issued, and the client's
    remedy is identical either way -- upload the file again. The message says
    both so the user is not left wondering whether the server lost their data.
    """
    session = store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "That session is unknown or has expired. Sessions are held in "
                "memory for one hour; please upload the file again."
            ),
        )
    return session
