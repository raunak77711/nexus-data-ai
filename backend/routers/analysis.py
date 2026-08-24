"""The endpoints behind the autonomous analysis: briefing, dashboard, timeline.

These are the routes the app calls WITHOUT being asked to. A user who uploads a
file does not request a briefing; the briefing is what happens to them. So the
frontend fires these immediately after an upload completes, and the shape of
this module follows from that: every endpoint is a GET with no body, cached on
the server, and safe to call repeatedly while a page mounts and remounts.

WHY THERE IS NO SINGLE /analysis ENDPOINT RETURNING EVERYTHING. It was the
obvious design and it is worse. The briefing needs a model round trip and the
dashboard needs to build six plotly figures; bundling them means the user waits
for the slowest one before seeing any of it, and the progress indicator has
nothing real to report because there is only one request in flight. Kept
separate, each answers as it finishes, the page fills in as the work completes,
and the activity indicator is showing genuine stages rather than a fiction on a
timer.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from backend.models import (
    BriefingResponse,
    DashboardResponse,
    QuestionsResponse,
    RecommendationsResponse,
    TimelineResponse,
)
from backend.routers import _analysis
from backend.routers._common import require_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analysis"])


@router.get("/briefing/{sid}", response_model=BriefingResponse)
def get_briefing(sid: str) -> BriefingResponse:
    """The five things this user should know about the file they just uploaded.

    Ranked across every source of findings rather than within one, so a serious
    data-quality problem can outrank an interesting trend -- which it should,
    since a trend computed from broken data is not a trend.
    """
    session = require_session(sid)
    return BriefingResponse(**_analysis.get_briefing(session))


@router.get("/dashboard/{sid}", response_model=DashboardResponse)
def get_dashboard(sid: str) -> DashboardResponse:
    """The charts this dataset deserves, chosen by what its columns support."""
    session = require_session(sid)
    return DashboardResponse(**_analysis.get_dashboard(session))


@router.get("/recommendations/{sid}", response_model=RecommendationsResponse)
def get_recommendations(sid: str) -> RecommendationsResponse:
    """What to do about what was found. Always labelled as suggestion."""
    session = require_session(sid)
    return RecommendationsResponse(**_analysis.get_recommendations(session))


@router.get("/questions/{sid}", response_model=QuestionsResponse)
def get_questions(sid: str) -> QuestionsResponse:
    """Questions worth asking, for somebody who does not know what to ask.

    Every suggestion is checked against the dataset's real columns before it is
    offered -- see core.story.questions. A suggested question the assistant
    then cannot answer is worse than no suggestion, because the user blames the
    product rather than the suggestion.
    """
    session = require_session(sid)
    return QuestionsResponse(**_analysis.get_questions(session))


@router.get("/timeline/{sid}", response_model=TimelineResponse)
def get_timeline(sid: str) -> TimelineResponse:
    """What the server actually did to this dataset, with real timestamps.

    The events are recorded at the moment the work happens, in core and in the
    routers, rather than assembled here from the final state. That distinction
    is the difference between a log and a stage set: a reconstructed timeline
    would show the same steps at the same intervals for every dataset, which
    users notice immediately and correctly read as decoration.
    """
    session = require_session(sid)
    return TimelineResponse(events=session.events, n_events=len(session.events))
