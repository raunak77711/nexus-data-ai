"""The report endpoint: the whole analysis as one document.

This route is the only place in the API that deliberately does a lot of work in
one request. Everywhere else the app fetches pieces separately so the page can
fill in progressively; here the user has pressed "Generate report" and is
waiting for a document, and a document that arrives in seven fragments is not a
document.

Because every piece is cached on the session by backend.routers._analysis, the
cost of this call depends entirely on how much of the app the user has already
looked at. Someone who read the story, the dashboard and the health screen gets
their report instantly. Someone who pressed the button straight after uploading
pays for the full analysis once, here -- which is the right place to pay it,
since it is the one moment they have explicitly asked to wait.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from backend.models import ReportResponse
from backend.routers import _analysis
from backend.routers._common import require_session
from backend.serialisation import jsonable
from core import report as report_module

logger = logging.getLogger(__name__)

router = APIRouter(tags=["report"])


@router.get("/report/{sid}", response_model=ReportResponse)
def get_report(sid: str) -> ReportResponse:
    """Assemble the full analysis report for one dataset.

    Returns structured sections rather than a rendered PDF. The browser already
    has a layout engine, the fonts and the exact styling the user has been
    looking at; generating a PDF server-side would mean reproducing all three
    and shipping a document that does not match what they approved.
    """
    session = require_session(sid)

    try:
        document = report_module.build(
            filename=session.filename,
            profile=session.profile,
            routing=session.routing,
            briefing=_analysis.get_briefing(session),
            insights=_analysis.get_insights(session),
            assessment=_analysis.get_health(session),
            dashboard=_analysis.get_dashboard(session),
            recommendations=_analysis.get_recommendations(session),
        )
    except HTTPException:
        # get_insights raises this deliberately when the analysis genuinely
        # failed. Re-raised unchanged so the user sees that reason rather than
        # a generic report error that hides it.
        raise
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        logger.exception("Report assembly failed for %s", sid)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "The report could not be assembled. The error has been logged; "
                "your data is unaffected."
            ),
        ) from exc

    session.record(
        "reported",
        f"Generated the report: {len(document['sections'])} sections, "
        f"{document['meta'].get('n_charts', 0)} chart(s).",
        n_sections=len(document["sections"]),
    )

    return ReportResponse(**jsonable(document))
