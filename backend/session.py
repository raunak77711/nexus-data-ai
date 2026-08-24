"""What the server remembers: the datasets, their analysis, and what it did when.

WHAT CHANGED HERE, AND WHY
--------------------------
This module used to be an in-memory dict with a TTL. That was the right shape
for a product where a session was one upload you looked at once, and the wrong
shape the moment the product grew a "My datasets" screen: a list of your
datasets that empties itself every time the server restarts is not a list of
your datasets, it is a cache pretending to be one.

So there are now two layers, and the split is the whole design:

    MEMORY   parsed DataFrames and computed analysis. Expensive to produce,
             expensive to hold, bounded, evictable, never authoritative.
    DISK     the uploaded bytes and a metadata record. Cheap, small, durable,
             and the only thing that decides whether a dataset exists.

A dataset that has been evicted from memory has not been lost. The next request
for it re-reads the bytes from disk and re-parses them -- a second of work, once
-- and the user sees a dataset that is simply still there. This is what makes
the eviction policy safe to be aggressive about: nothing it drops is
irreplaceable.

WHY NOT A DATABASE. Because the durable part of what is stored here is a file
the user already gave us plus a small JSON record, and the expensive part is a
live Python object no database would help with. Postgres would add a dependency
and a schema migration to a problem that is `open()`. The interface below is
still narrow enough that swapping in Redis and object storage is a change to
this file, which was the previous version's stated reason for keeping it narrow
and remains true.

WHAT IS DELIBERATELY NOT PERSISTED
----------------------------------
The analysis: profile, routing, insights, health, dashboard, briefing. All of
it is a deterministic function of the bytes, so persisting it would be caching
a pure function on disk in exchange for an invalidation problem -- and for the
one non-deterministic input, the model's wording, a stale cached briefing is
worse than a recomputed one. It is cached in memory for the lifetime of the
process and recomputed after a restart.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Where the durable half lives. Overridable so a test can point it at a
# temporary directory and so a container can mount a volume; defaults to a
# gitignored directory beside the code, which is the behaviour somebody running
# this locally expects without configuring anything.
STORE_DIR = os.environ.get("NEXUS_STORE_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".nexus_store"
)

# How many parsed frames to hold in memory at once. Small, because a DataFrame
# is the expensive thing here and because eviction is cheap now that it is
# recoverable -- see the module docstring.
MAX_LIVE_FRAMES = 8

# How many datasets to keep on disk. Past this the least recently opened is
# deleted, bytes and all. A cap is necessary because nothing else ever removes
# an upload, and "my datasets" filling a disk is a worse failure than "my
# oldest dataset is gone".
MAX_STORED_DATASETS = 40

INDEX_FILENAME = "index.json"


def _now() -> float:
    return time.time()


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


# --------------------------------------------------------------- the record --
@dataclass
class Session:
    """One dataset, its analysis, and the history of what was done to it.

    Still called Session because every router refers to it by that name and a
    rename would be a large diff carrying no meaning. What it actually models
    now is a dataset that persists across visits.

    THE TWO FRAMES. `original` is exactly what was uploaded and is never
    written to. `df` is what every analysis reads, and starts as the same
    object. Applying a clean replaces `df` and leaves `original` alone, which
    is how the product's promise -- "your original file is preserved" -- is
    kept structurally rather than by remembering to be careful.

    THE ANALYSIS CACHE. Every field below `routing` is a deterministic function
    of `df` and is computed on demand, once. `invalidate()` clears all of them
    together, which is the only correct granularity: a clean changes the rows,
    and every one of these was computed from the rows.
    """

    id: str
    filename: str
    df: pd.DataFrame
    profile: Dict[str, Any]
    routing: Dict[str, Any]
    created_at: float
    last_seen: float

    # The untouched upload. Held separately so a clean is reversible.
    original: Optional[pd.DataFrame] = None

    # Analysis, cached per process. None means "not computed yet", which is
    # distinct from an empty result meaning "computed, found nothing".
    insights: Optional[Dict[str, Any]] = None
    health: Optional[Dict[str, Any]] = None
    dashboard: Optional[Dict[str, Any]] = None
    briefing: Optional[Dict[str, Any]] = None
    recommendations: Optional[Dict[str, Any]] = None
    suggested_questions: Optional[Dict[str, Any]] = None

    # State from the older flow, still read by the chat assistant.
    last_world_stats: Optional[Dict[str, Any]] = None
    last_world_archetype: Optional[str] = None
    last_world_warnings: List[str] = field(default_factory=list)
    last_forecast: Optional[Dict[str, Any]] = None

    # Cleaning
    is_cleaned: bool = False
    clean_receipt: Optional[Dict[str, Any]] = None

    # The activity log shown as the analysis timeline.
    events: List[Dict[str, Any]] = field(default_factory=list)

    def record(self, stage: str, message: str, **detail: Any) -> Dict[str, Any]:
        """Append one event to this dataset's timeline.

        Events are recorded where the work happens rather than assembled for
        display afterwards, so the timeline is a log of what the server
        actually did and its timestamps are real. A timeline generated at
        render time from the final state would be a reconstruction, and would
        show the same four steps at the same four intervals for every dataset.
        """
        event = {
            "stage": stage,
            "message": message,
            "at": _iso(_now()),
            "detail": detail or {},
        }
        self.events.append(event)
        # A pathological session could otherwise accumulate events without
        # bound. The earliest are dropped rather than the latest, since the
        # recent ones are what a user is looking at.
        if len(self.events) > 200:
            del self.events[:-200]
        return event

    def invalidate(self) -> None:
        """Drop every cached analysis. Called when `df` changes.

        All of them, together. A clean that removed 300 rows invalidates the
        insights, the health score, the dashboard and the briefing at once, and
        clearing only some would leave a page where the health score refers to
        a file the charts no longer show.
        """
        self.insights = None
        self.health = None
        self.dashboard = None
        self.briefing = None
        self.recommendations = None
        self.suggested_questions = None
        self.last_world_stats = None
        self.last_forecast = None

    def summary(self) -> Dict[str, Any]:
        """The card shown on the My Datasets screen."""
        return {
            "id": self.id,
            "filename": self.filename,
            "n_rows": int(len(self.df)),
            "n_cols": int(len(self.df.columns)),
            "created_at": _iso(self.created_at),
            "last_seen": _iso(self.last_seen),
            "health_score": (self.health or {}).get("score"),
            "health_grade": (self.health or {}).get("grade"),
            "archetype": self.routing.get("archetype"),
            "is_cleaned": self.is_cleaned,
            "analysed": self.insights is not None,
            "n_events": len(self.events),
        }


# ---------------------------------------------------------------- the store --
class SessionStore:
    """Datasets: durable on disk, parsed in memory, bounded in both.

    The lock guards both layers together. uvicorn runs sync endpoints in a
    thread pool, so two requests genuinely can create datasets concurrently,
    and the index write is a read-modify-write that is not atomic under the GIL.
    """

    def __init__(
        self,
        store_dir: str = STORE_DIR,
        max_live: int = MAX_LIVE_FRAMES,
        max_stored: int = MAX_STORED_DATASETS,
    ) -> None:
        self._live: Dict[str, Session] = {}
        self._index: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._dir = store_dir
        self._max_live = max_live
        self._max_stored = max_stored
        self._load_index()

    # -- disk ---------------------------------------------------------------
    @property
    def _index_path(self) -> str:
        return os.path.join(self._dir, INDEX_FILENAME)

    def _dataset_dir(self, dataset_id: str) -> str:
        return os.path.join(self._dir, dataset_id)

    def _load_index(self) -> None:
        """Read the on-disk index at startup.

        A corrupt or unreadable index is treated as an empty one rather than as
        a fatal error. The failure mode that matters is a server that will not
        start because a JSON file got truncated by a hard shutdown -- losing the
        dataset list is recoverable, refusing to boot is not.
        """
        try:
            os.makedirs(self._dir, exist_ok=True)
        except OSError:
            logger.exception("Could not create the dataset store at %s", self._dir)
            return

        if not os.path.exists(self._index_path):
            return
        try:
            with open(self._index_path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                self._index = {
                    key: value
                    for key, value in loaded.items()
                    if isinstance(value, dict) and os.path.exists(
                        os.path.join(self._dataset_dir(key), "data.csv")
                    )
                }
                logger.info("Loaded %d stored dataset(s)", len(self._index))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            logger.exception("Dataset index unreadable; starting with an empty one")
            self._index = {}

    def _write_index(self) -> None:
        """Persist the index. The caller must already hold the lock.

        Written to a temporary file and moved into place, so a crash midway
        through leaves the previous index intact rather than a half-written one
        that `_load_index` would discard entirely.
        """
        temporary = f"{self._index_path}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(self._index, handle, indent=2, default=str)
            os.replace(temporary, self._index_path)
        except (OSError, TypeError, ValueError):
            logger.exception("Could not write the dataset index")

    def _persist_bytes(self, dataset_id: str, content: bytes) -> None:
        """Save the uploaded file so the dataset survives a restart."""
        directory = self._dataset_dir(dataset_id)
        try:
            os.makedirs(directory, exist_ok=True)
            with open(os.path.join(directory, "data.csv"), "wb") as handle:
                handle.write(content)
        except OSError:
            # A dataset that cannot be persisted still works for this process.
            # Degrading to in-memory-only is much better than refusing an upload
            # because a disk is full or read-only.
            logger.exception("Could not persist dataset %s; it is memory-only", dataset_id)

    def _forget_files(self, dataset_id: str) -> None:
        try:
            shutil.rmtree(self._dataset_dir(dataset_id), ignore_errors=True)
        except OSError:
            logger.exception("Could not remove files for dataset %s", dataset_id)

    # -- eviction -----------------------------------------------------------
    def _evict_frames(self) -> None:
        """Drop the least recently used parsed frames. Caller holds the lock.

        Only the in-memory half. The dataset stays in the index and on disk, so
        the next request for it re-parses rather than 404s -- which is why this
        can be aggressive without the user ever noticing.
        """
        while len(self._live) > self._max_live:
            oldest = min(self._live.values(), key=lambda s: s.last_seen)
            del self._live[oldest.id]
            logger.info("Evicted parsed frame for %s (still on disk)", oldest.id)

    def _evict_stored(self) -> None:
        """Delete the least recently opened datasets past the cap."""
        while len(self._index) > self._max_stored:
            oldest_id = min(
                self._index, key=lambda key: self._index[key].get("last_seen", 0)
            )
            self._index.pop(oldest_id, None)
            self._live.pop(oldest_id, None)
            self._forget_files(oldest_id)
            logger.warning("Dataset cap reached; deleted %s", oldest_id)

    # -- api ----------------------------------------------------------------
    def create(
        self,
        filename: str,
        df: pd.DataFrame,
        profile: Dict[str, Any],
        routing: Dict[str, Any],
        content: Optional[bytes] = None,
    ) -> Session:
        """Register a parsed upload and return its session.

        Args:
            content: the raw uploaded bytes. Optional only so that a caller
                constructing a frame directly (a test, a generated sample) is
                not forced to serialise it first -- but a dataset created
                without bytes cannot be rehydrated, so callers that have them
                should always pass them.

        The id is a uuid4 rather than a counter because it is the only thing
        separating one upload from another: with no authentication in front of
        this service, a sequential id would let anyone read anyone else's data
        by incrementing a number.
        """
        now = _now()
        session = Session(
            id=str(uuid.uuid4()),
            filename=filename,
            df=df,
            original=df,
            profile=profile,
            routing=routing,
            created_at=now,
            last_seen=now,
        )
        session.record(
            "uploaded",
            f"Read {len(df):,} rows and {len(df.columns)} columns from {filename}.",
            n_rows=int(len(df)),
            n_cols=int(len(df.columns)),
        )

        with self._lock:
            if content is not None:
                self._persist_bytes(session.id, content)
            self._index[session.id] = {
                "id": session.id,
                "filename": filename,
                "created_at": now,
                "last_seen": now,
                "n_rows": int(len(df)),
                "n_cols": int(len(df.columns)),
                "persisted": content is not None,
            }
            self._live[session.id] = session
            self._evict_frames()
            self._evict_stored()
            self._write_index()

        return session

    def _rehydrate(self, dataset_id: str) -> Optional[Session]:
        """Re-parse a dataset from disk. The caller must already hold the lock.

        Imported locally rather than at module scope because backend.routers.
        upload imports this module, and importing it back at the top would be a
        cycle. The parsing rules genuinely belong to the upload path -- a
        dataset read back from disk must be parsed exactly as it was when it
        arrived, or the same file would profile differently after a restart.
        """
        record = self._index.get(dataset_id)
        if not record:
            return None

        path = os.path.join(self._dataset_dir(dataset_id), "data.csv")
        if not os.path.exists(path):
            self._index.pop(dataset_id, None)
            self._write_index()
            return None

        try:
            from backend.routers.upload import parse_csv
            from core import router as routing_module
            from core.profiler import profile_dataframe

            with open(path, "rb") as handle:
                content = handle.read()
            df = parse_csv(content, record.get("filename", "dataset.csv"))
            profile = profile_dataframe(df)
            # Rule-based, not the model: rehydration happens inside another
            # request's latency budget, and a network round trip to re-derive a
            # decision that is already cheap to compute locally would make
            # reopening an old dataset feel slower than uploading a new one.
            routing = routing_module.rule_based_route(
                profile, "Recovered from the stored copy of this dataset."
            )
        except (OSError, ValueError, TypeError, KeyError):
            logger.exception("Could not rehydrate dataset %s", dataset_id)
            return None

        now = _now()
        session = Session(
            id=dataset_id,
            filename=record.get("filename", "dataset.csv"),
            df=df,
            original=df,
            profile=profile,
            routing=routing,
            created_at=record.get("created_at", now),
            last_seen=now,
        )
        session.record(
            "reopened",
            f"Reopened {record.get('filename')} from your saved datasets.",
        )
        self._live[dataset_id] = session
        self._evict_frames()
        logger.info("Rehydrated dataset %s from disk", dataset_id)
        return session

    def get(self, session_id: str) -> Optional[Session]:
        """Return a dataset, re-parsing it from disk if it is not in memory.

        Returning None rather than raising keeps this module free of HTTP
        concepts; deciding that None means 404 is the router's job.
        """
        if not session_id:
            return None
        with self._lock:
            session = self._live.get(session_id)
            if session is None:
                session = self._rehydrate(session_id)
            if session is None:
                return None

            now = _now()
            session.last_seen = now
            if session_id in self._index:
                self._index[session_id]["last_seen"] = now
            return session

    def touch_index(self, session: Session) -> None:
        """Refresh a dataset's index record after its state changed.

        Called after a clean, so that the My Datasets card shows the new row
        count rather than the uploaded one.
        """
        with self._lock:
            record = self._index.get(session.id)
            if record is None:
                return
            record.update(
                {
                    "n_rows": int(len(session.df)),
                    "n_cols": int(len(session.df.columns)),
                    "last_seen": session.last_seen,
                    "is_cleaned": session.is_cleaned,
                    # The health score and archetype are persisted even though
                    # they are derived, breaking this module's own rule about
                    # not storing analysis -- deliberately, and only these two.
                    # They are what the My Datasets card shows, and a card that
                    # displays a score for the dataset you opened last and a
                    # blank for every other one looks broken rather than lazy.
                    # Recomputing them would mean parsing every stored file to
                    # render a list.
                    "health_score": (session.health or {}).get("score"),
                    "health_grade": (session.health or {}).get("grade"),
                    "archetype": session.routing.get("archetype"),
                }
            )
            self._write_index()

    def list(self) -> List[Dict[str, Any]]:
        """Every stored dataset, most recently opened first.

        Built from the index rather than from the live frames, so a dataset
        that has been evicted from memory still appears -- which is the whole
        point of the split. Live sessions contribute their richer summary where
        one exists.
        """
        with self._lock:
            rows: List[Dict[str, Any]] = []
            for dataset_id, record in self._index.items():
                live = self._live.get(dataset_id)
                if live is not None:
                    rows.append({**live.summary(), "loaded": True})
                    continue
                rows.append(
                    {
                        "id": dataset_id,
                        "filename": record.get("filename", "dataset.csv"),
                        "n_rows": record.get("n_rows", 0),
                        "n_cols": record.get("n_cols", 0),
                        "created_at": _iso(record.get("created_at", 0)),
                        "last_seen": _iso(record.get("last_seen", 0)),
                        "health_score": record.get("health_score"),
                        "health_grade": record.get("health_grade"),
                        "archetype": record.get("archetype"),
                        "is_cleaned": record.get("is_cleaned", False),
                        "analysed": False,
                        "n_events": 0,
                        "loaded": False,
                    }
                )
            rows.sort(key=lambda row: row["last_seen"], reverse=True)
            return rows

    def delete(self, session_id: str) -> bool:
        """Forget a dataset entirely, including its stored bytes."""
        with self._lock:
            existed = session_id in self._index or session_id in self._live
            self._live.pop(session_id, None)
            self._index.pop(session_id, None)
            self._forget_files(session_id)
            if existed:
                self._write_index()
            return existed

    def count(self) -> int:
        """Number of stored datasets."""
        with self._lock:
            return len(self._index)

    def clear(self) -> None:
        """Drop everything, memory and disk. Exists for tests."""
        with self._lock:
            for dataset_id in list(self._index):
                self._forget_files(dataset_id)
            self._live.clear()
            self._index.clear()
            self._write_index()


# The single process-wide store. Imported by the routers rather than injected
# through FastAPI's dependency system, which would only add indirection around a
# value that is genuinely global to the process -- and tests can call .clear().
store = SessionStore()
