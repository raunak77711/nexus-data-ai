"""Lazily computes each piece of a dataset's analysis, once, and caches it.

WHY THIS IS A SHARED MODULE RATHER THAN CODE IN EACH ROUTER
------------------------------------------------------------
Six endpoints need the health report. The briefing needs the insights AND the
health report. The report needs all six. If each router computed what it needed,
opening the report page would recompute an analysis the user had already sat
through on three previous screens -- and, worse, could produce a different one:
the briefing's wording comes from a model, so two computations of "the same"
briefing are not the same briefing, and a user who saw one sentence on the story
page and a different sentence in their exported PDF would be right to distrust
both.

So every derived artefact is computed here, cached on the session, and returned
by reference. The cache is keyed by nothing at all -- it is simply a field on
the session -- because the only input is the session's frame, and the only thing
that changes the frame is a clean, which calls `session.invalidate()` and clears
every field at once.

THE DEPENDENCY ORDER
--------------------
    profile, routing      computed at upload
    insights, health      independent, from the frame
    dashboard             independent, from the frame
    briefing              needs insights + health
    recommendations       needs insights + health
    questions             needs insights

Each function below asks for what it needs rather than assuming a caller ran
things in order, so any endpoint can be the first one hit.

FAILURE POLICY
--------------
Analysis is best-effort. A pass that raises is logged and returns an empty but
well-formed result, because a story page missing its health badge is a smaller
failure than a story page that will not load. The one exception is `insights`,
which raises 500 -- it is the load-bearing analysis, and silently returning
"nothing found" for a dataset full of findings would be a lie rather than a
degradation.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import pandas as pd
from fastapi import HTTPException, status

from backend.serialisation import jsonable
from backend.session import Session, store
from core import dashboard as dashboard_module
from core import health as health_module
from core import insights as insights_module
from core import story as story_module

logger = logging.getLogger(__name__)

# The exceptions a pandas-driven analysis pass can raise for reasons that are
# about the data rather than about our code. Caught as a group because the
# response to all of them is identical -- log it, degrade that one section --
# and enumerating them at seven call sites would guarantee the lists diverge.
DATA_ERRORS = (
    KeyError, IndexError, TypeError, ValueError, ArithmeticError,
    AttributeError, pd.errors.DataError,
)


def get_insights(session: Session) -> Dict[str, Any]:
    """Everything worth telling the user about the data, computed once.

    Raises 500 on failure rather than degrading. See the module docstring: an
    empty findings list is a claim about the dataset, and making that claim
    because of an internal error would be worse than an honest failure.
    """
    if session.insights is not None:
        return session.insights

    try:
        result = insights_module.generate(session.df, session.profile, session.routing)
    except DATA_ERRORS as exc:
        # core.insights runs each pass in its own try/except, so reaching here
        # means something outside those passes broke -- our bug, not the data's.
        logger.exception("Insight generation failed for %s", session.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "The dataset could not be analysed. The error has been logged; "
                "please try again."
            ),
        ) from exc

    session.insights = jsonable(result)
    counts = result.get("counts", {})
    session.record(
        "analysed",
        f"Found {counts.get('trends', 0)} trend(s), "
        f"{counts.get('relationships', 0)} relationship(s) and "
        f"{counts.get('anomalies', 0)} unusual value(s).",
        **{key: int(value) for key, value in counts.items()},
    )
    return session.insights


def get_health(session: Session) -> Dict[str, Any]:
    """The data quality report, computed once."""
    if session.health is not None:
        return session.health

    try:
        result = health_module.assess(session.df, session.profile)
    except DATA_ERRORS:
        logger.exception("Health assessment failed for %s", session.id)
        # A well-formed empty report rather than an exception: every screen that
        # shows a health badge can render "not assessed" and stay usable.
        result = {
            "score": None, "grade": "Unknown",
            "verdict": "The quality checks could not be run on this dataset.",
            "headline": "Data quality could not be assessed.",
            "issues": [], "counts": {"critical": 0, "warning": 0, "notice": 0},
            "n_fixable": 0, "checks_run": 0, "sampled": False,
            "n_rows": int(len(session.df)), "n_cols": int(len(session.df.columns)),
            "clean": [],
        }

    session.health = jsonable(result)
    if result.get("score") is not None:
        session.record(
            "quality_checked",
            f"Checked data quality: scored {result['score']} out of 100 across "
            f"{result.get('checks_run', 0)} checks.",
            score=result["score"],
            n_issues=len(result.get("issues", [])),
        )
        # So the My Datasets card can show a health score without loading the
        # whole dataset back into memory.
        store.touch_index(session)
    return session.health


def get_dashboard(session: Session) -> Dict[str, Any]:
    """The auto-composed dashboard, built once.

    Figures are the expensive part of this payload and the reason it is cached
    hardest: a six-panel dashboard is six plotly figures, each a substantial
    JSON document, and rebuilding them on every navigation would make moving
    between screens feel like reloading the app.
    """
    if session.dashboard is not None:
        return session.dashboard

    try:
        result = dashboard_module.compose(session.df, session.profile, session.routing)
    except DATA_ERRORS:
        logger.exception("Dashboard composition failed for %s", session.id)
        result = {
            "kpis": [], "panels": [],
            "note": "The charts for this dataset could not be built.",
            "n_considered": 0, "time_col": None, "measures": [],
        }

    # A plotly Figure has to go through plotly's own encoder, not the generic
    # walk in `jsonable` -- which raises on one rather than guessing, precisely
    # so this conversion cannot be forgotten. The figure becomes a JSON STRING
    # under `figure_json`, matching what /chart and /world already return, so
    # the frontend has one way to render a chart rather than two.
    result = {
        **result,
        "panels": [
            {
                **{key: value for key, value in panel.items() if key != "figure"},
                "figure_json": panel["figure"].to_json(),
            }
            for panel in result.get("panels", [])
        ],
    }

    session.dashboard = jsonable(result)
    if result.get("panels"):
        session.record(
            "charts_built",
            f"Built {len(result['panels'])} chart(s) chosen for this data.",
            n_panels=len(result["panels"]),
            kinds=[panel["kind"] for panel in result["panels"]],
        )
    return session.dashboard


def get_briefing(session: Session) -> Dict[str, Any]:
    """The AI briefing, written once.

    Cached more firmly than the computed analyses, and for a different reason.
    The others are cached because recomputing them is slow; this is cached
    because recomputing it produces DIFFERENT WORDS. A user who read a sentence
    on the story page and saw a different one in their report would have no way
    to tell which was authoritative, and both would be.
    """
    if session.briefing is not None:
        return session.briefing

    insights = get_insights(session)
    health = get_health(session)

    try:
        result = story_module.brief(
            session.profile,
            session.routing,
            insights,
            health,
            filename=session.filename,
        )
    except DATA_ERRORS:
        logger.exception("Briefing failed for %s", session.id)
        result = {
            "headline": "I've analysed your data.",
            "summary": (
                f"This file has {len(session.df):,} rows and "
                f"{len(session.df.columns)} columns."
            ),
            "points": [], "source": "rules", "n_considered": 0,
        }

    session.briefing = jsonable(result)
    session.record(
        "briefed",
        f"Wrote the briefing: {len(result.get('points', []))} key point(s).",
        source=result.get("source"),
    )
    return session.briefing


def get_recommendations(session: Session) -> Dict[str, Any]:
    """AI-generated suggested next steps, written once."""
    if session.recommendations is not None:
        return session.recommendations

    insights = get_insights(session)
    health = get_health(session)

    try:
        result = story_module.recommend(
            session.profile, session.routing, insights, health
        )
    except DATA_ERRORS:
        logger.exception("Recommendations failed for %s", session.id)
        result = {
            "recommendations": [], "source": "rules",
            "disclaimer": (
                "AI-generated suggestions based on patterns in your data."
            ),
        }

    session.recommendations = jsonable(result)
    return session.recommendations


def get_questions(session: Session) -> Dict[str, Any]:
    """Questions this dataset can answer, for a user who has none."""
    if session.suggested_questions is not None:
        return session.suggested_questions

    insights = get_insights(session)

    try:
        result = story_module.questions(session.profile, session.routing, insights)
    except DATA_ERRORS:
        logger.exception("Question suggestions failed for %s", session.id)
        result = {"questions": [], "source": "rules"}

    session.suggested_questions = jsonable(result)
    return session.suggested_questions
