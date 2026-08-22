"""In-memory session store: one parsed DataFrame per upload, with a TTL sweep.

WHY AN IN-MEMORY DICT, AND WHY THAT IS NOT THE PRODUCTION ANSWER
----------------------------------------------------------------
A session here holds a *parsed pandas DataFrame*. That is the whole point: the
alternative is re-reading and re-parsing the uploaded CSV on every /world,
/forecast and /chat call, which for a large upload is hundreds of milliseconds
of pure waste per interaction, repeated every time the user nudges a slider.

Given that what is cached is a live Python object, a module-level dict is the
right choice *for this deployment shape* and the wrong one for any other:

  * Single-process only. Run uvicorn with --workers 2 and half the requests
    land on a worker that has never heard of the session id, so the user gets
    an intermittent 404 that looks like a frontend bug.
  * It dies with the process. A reload during a demo loses every session.
  * Its only memory bound is the per-upload size cap and the session cap below.

The production answer is a shared store: Redis for the session metadata, plus
object storage (or Parquet on a shared volume) for the frame itself, because a
DataFrame is not something you want to pickle in and out of Redis on every
request. That is a deliberate deferral, not an oversight -- it buys horizontal
scaling and survival across restarts, and it costs a serialisation round trip
per request plus a piece of infrastructure a single-machine submission does not
need. The interface below (create/get/delete) is kept narrow precisely so that
swapping the backing store is a change to this file alone.

TTL SWEEP
---------
Sessions expire SESSION_TTL_SECONDS after their last access. The sweep is lazy:
it runs at the top of every store operation instead of on a background timer.
WHY lazy -- a sweeper thread would need its own lifecycle bolted to the app's
startup/shutdown and would mutate the dict underneath a request thread. Inline
sweeping costs O(live sessions) on a dict holding tens of entries and has the
one property that actually matters: a request can never see an expired session.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# One hour: long enough that a user can read the page, make coffee and come back
# to their world; short enough that an abandoned upload is not held for the
# lifetime of the process.
SESSION_TTL_SECONDS = 60 * 60

# A hard cap on live sessions, so a scripted upload loop cannot exhaust memory
# before the TTL has a chance to fire. On overflow the least recently *touched*
# session is evicted -- LRU rather than FIFO, because the oldest session is not
# necessarily the least wanted, whereas the least recently used one is.
MAX_SESSIONS = 32


@dataclass
class Session:
    """Everything the server remembers about one uploaded file.

    profile and routing are computed once at upload and reused, because they are
    deterministic functions of the frame and routing in particular may have cost
    a network round trip to Gemini.

    last_world_stats and last_forecast exist for the chat assistant. Chat is
    grounded on computed context only, so that context has to be readable
    without silently recomputing a world the user is already looking at.
    """

    id: str
    filename: str
    df: pd.DataFrame
    profile: Dict[str, Any]
    routing: Dict[str, Any]
    created_at: float
    last_seen: float
    last_world_stats: Optional[Dict[str, Any]] = None
    last_world_archetype: Optional[str] = None
    last_world_warnings: List[str] = field(default_factory=list)
    last_forecast: Optional[Dict[str, Any]] = None


class SessionStore:
    """A dict with a TTL, an LRU bound, and a lock.

    The lock is not paranoia: uvicorn runs sync endpoint functions in a thread
    pool, so two requests genuinely can mutate the dict concurrently. Individual
    dict operations are atomic under the GIL, but the sweep is a read-then-delete
    sequence and eviction is a scan-then-delete, and neither of those is.
    """

    def __init__(
        self,
        ttl_seconds: int = SESSION_TTL_SECONDS,
        max_sessions: int = MAX_SESSIONS,
    ) -> None:
        self._sessions: Dict[str, Session] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._max = max_sessions

    def _sweep(self) -> None:
        """Drop expired sessions. The caller must already hold the lock."""
        cutoff = time.time() - self._ttl
        expired = [sid for sid, s in self._sessions.items() if s.last_seen < cutoff]
        for sid in expired:
            del self._sessions[sid]
        if expired:
            logger.info("Swept %d expired session(s)", len(expired))

    def _evict_if_full(self) -> None:
        """Make room for one more session. The caller must already hold the lock."""
        while len(self._sessions) >= self._max:
            oldest = min(self._sessions.values(), key=lambda s: s.last_seen)
            del self._sessions[oldest.id]
            logger.warning("Session cap reached; evicted least recently used %s", oldest.id)

    def create(
        self,
        filename: str,
        df: pd.DataFrame,
        profile: Dict[str, Any],
        routing: Dict[str, Any],
    ) -> Session:
        """Register a parsed upload and return its session.

        The id is a uuid4 rather than a counter because it is the only thing
        protecting one upload from another: with no authentication in front of
        this service, a sequential id would let anyone read anyone else's data
        by incrementing a number.
        """
        now = time.time()
        session = Session(
            id=str(uuid.uuid4()),
            filename=filename,
            df=df,
            profile=profile,
            routing=routing,
            created_at=now,
            last_seen=now,
        )
        with self._lock:
            self._sweep()
            self._evict_if_full()
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Optional[Session]:
        """Return a live session and refresh its TTL, or None if unknown/expired.

        Returning None rather than raising keeps this module free of HTTP
        concepts; deciding that None means 404 is the router's job.
        """
        with self._lock:
            self._sweep()
            session = self._sessions.get(session_id)
            if session is not None:
                session.last_seen = time.time()
            return session

    def delete(self, session_id: str) -> bool:
        """Forget a session. True if one was actually removed."""
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def count(self) -> int:
        """Number of live (unexpired) sessions."""
        with self._lock:
            self._sweep()
            return len(self._sessions)

    def clear(self) -> None:
        """Drop everything. Exists for tests, which must not leak state."""
        with self._lock:
            self._sessions.clear()


# The single process-wide store. Imported by the routers rather than injected
# through FastAPI's dependency system, which would only add indirection around a
# value that is genuinely global to the process -- and tests can call .clear().
store = SessionStore()
