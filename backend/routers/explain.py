"""The "explain this" endpoint, at two levels of detail.

WHY THE REQUEST NAMES A THING RATHER THAN DESCRIBING ONE
---------------------------------------------------------
The obvious API would let the client post whatever is on screen and ask for it
to be explained. It is the wrong design for one specific reason: the numbers in
that payload would come from the client, and the whole grounding guarantee in
this project rests on the explanation being checked against numbers the SERVER
computed. A client that posted its own figures could have them explained back
as though they were real, and the check would pass every time because the
client supplied both sides of it.

So a request names a target and a reference -- "the insight with this id", "the
health issue with this id", "the chart with this id" -- and the server looks up
what it computed. What can be explained is exactly what the server can prove.
An unknown reference is a 404, which is correct: the thing being asked about
does not exist.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, status

from backend.models import ExplainRequest, ExplainResponse
from backend.routers import _analysis
from backend.routers._common import require_session
from backend.session import Session
from core import explain as explain_module

logger = logging.getLogger(__name__)

router = APIRouter(tags=["explain"])


def _find_insight(session: Session, ref: str) -> Optional[Dict[str, Any]]:
    insights = _analysis.get_insights(session)
    for card in insights.get("insights", []):
        if str(card.get("id")) == ref:
            return card
    return None


def _find_issue(session: Session, ref: str) -> Optional[Dict[str, Any]]:
    assessment = _analysis.get_health(session)
    for issue in assessment.get("issues", []):
        if str(issue.get("id")) == ref:
            return issue
    return None


def _find_panel(session: Session, ref: str) -> Optional[Dict[str, Any]]:
    dashboard = _analysis.get_dashboard(session)
    for panel in dashboard.get("panels", []):
        if str(panel.get("id")) == ref:
            return panel
    return None


def _find_kpi(session: Session, ref: str) -> Optional[Dict[str, Any]]:
    """KPIs are matched on their label, since they carry no id of their own.

    They are generated from the data and have no natural key -- adding one would
    mean inventing a stable identifier for "the third headline number", which is
    less robust than the label it already displays.
    """
    dashboard = _analysis.get_dashboard(session)
    for kpi in dashboard.get("kpis", []):
        if str(kpi.get("label")) == ref:
            return kpi
    return None


@router.post("/explain/{sid}", response_model=ExplainResponse)
def explain(sid: str, request: ExplainRequest) -> ExplainResponse:
    """Explain one computed result, simply or technically.

    Both levels are real explanations rather than one text with jargon added:
    the simple register is forbidden from naming a statistical method at all,
    and the technical one is required to state the method and at least one way
    the result could mislead. See core.explain for the two prompts.
    """
    session = require_session(sid)
    ref = request.ref.strip()

    if request.target == "insight":
        card = _find_insight(session, ref)
        subject = explain_module.subject_from_insight(card) if card else None
    elif request.target == "health_issue":
        issue = _find_issue(session, ref)
        subject = explain_module.subject_from_issue(issue) if issue else None
    elif request.target == "chart":
        panel = _find_panel(session, ref)
        subject = explain_module.subject_from_chart(panel) if panel else None
    else:  # kpi -- the only remaining member of the Literal
        kpi = _find_kpi(session, ref)
        subject = (
            {
                "kind": "kpi",
                "title": f"{kpi.get('label')}: {kpi.get('value')}",
                "detail": (
                    f"{kpi.get('label')} is {kpi.get('value')}. {kpi.get('note', '')}"
                ),
                "why": "",
                "method": "Computed directly over the column, across every row.",
                "evidence": {
                    "label": kpi.get("label"),
                    "value": kpi.get("value"),
                    "note": kpi.get("note"),
                },
            }
            if kpi
            else None
        )

    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"There is nothing on this dataset with the reference {ref!r}, so "
                f"there is nothing to explain. It may belong to an analysis that "
                f"was replaced when the data was cleaned -- reload the page."
            ),
        )

    result = explain_module.explain(
        subject,
        level=request.level,
        dataset={
            "n_rows": session.profile.get("n_rows"),
            "n_cols": session.profile.get("n_cols"),
        },
    )
    return ExplainResponse(**result)
