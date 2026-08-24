"""Assembles the analysis into a document somebody could send to their boss.

WHAT THIS MODULE DOES AND DOES NOT DO
-------------------------------------
It does not analyse anything. Every section below is built from output that
already exists -- the profile, the briefing, the dashboard, the health report,
the insights, the recommendations. If this module computed even one number of
its own, that number could disagree with the one on screen, and a report that
contradicts the app it came from is worse than no report.

So this is an assembler. Its judgement is exercised in three places only:
which sections appear, in what order, and what the connective prose between
them says.

WHY THE ORDER IS WHAT IT IS
---------------------------
Executive summary first, because most readers of most reports read only that.
Data quality BEFORE the findings, not after -- the standard business-report
order buries caveats at the back, which is how a reader gets to page four
believing a number that page nine explains is unreliable. If the data has a
serious problem, the reader learns it before they read anything computed from
that data. Recommendations last, clearly separated and clearly labelled, so
nobody mistakes a suggestion for a measurement.

EXPORT
------
The payload is structured rather than rendered: sections with types, which the
frontend lays out and the browser prints to PDF. Generating a PDF server-side
would mean a rendering dependency, a font stack and a layout engine that agrees
with the one on screen -- three new ways to ship a document that does not match
what the user approved. The browser already has all three and is already
showing them the thing they want to print.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Charts in the report. Fewer than the dashboard shows, and larger: a printed
# page holds less than a screen, and a report that runs to nine figures is one
# nobody finishes.
MAX_REPORT_CHARTS = 4
MAX_FINDINGS = 8
MAX_ISSUES = 8
MAX_COLUMN_ROWS = 40


def _section(kind: str, title: str, **fields: Any) -> Dict[str, Any]:
    """One section of the report, in the shape the renderer reads.

    `kind` drives layout rather than `title` doing it, so that renaming a
    heading is a copy change and not a layout change.
    """
    return {"kind": kind, "title": title, **fields}


def _quality_verdict(assessment: Dict[str, Any]) -> str:
    """The sentence that tells a reader how much to trust everything below.

    Written here rather than reused from core.health because the health screen
    addresses somebody who came to fix the data, and a report addresses
    somebody deciding whether to believe it. Same facts, different question.
    """
    score = assessment.get("score")
    counts = assessment.get("counts", {})
    n_critical = counts.get("critical", 0)

    if score is None:
        return "Data quality was not assessed for this dataset."
    if n_critical:
        return (
            f"This dataset scores {score}/100 for quality, with {n_critical} "
            f"serious issue(s) outstanding. Findings in this report that depend "
            f"on the affected columns should be treated as provisional until "
            f"those are resolved."
        )
    if float(score) >= 90:
        return (
            f"This dataset scores {score}/100 for quality with no serious issues. "
            f"The findings below can be read at face value."
        )
    return (
        f"This dataset scores {score}/100 for quality. The issues found are "
        f"minor, but they are listed below so their effect on the findings can "
        f"be judged."
    )


def _conclusion(
    briefing: Dict[str, Any],
    assessment: Dict[str, Any],
    insights: Dict[str, Any],
) -> str:
    """The closing paragraph, assembled from what the report actually contains.

    Deliberately not a model call. A conclusion is the one part of a document a
    reader assumes was written deliberately, and this one is a restatement of
    the report's own contents -- which is a job for a template that cannot
    wander rather than for prose generation that might.
    """
    points = briefing.get("points") or []
    counts = insights.get("counts") or {}
    headline = points[0]["title"] if points else None

    parts: List[str] = []
    if headline:
        parts.append(f"The most significant finding is: {headline.rstrip('.')}.")

    found = [
        f"{counts[key]} {label}"
        for key, label in (
            ("trends", "trend(s)"),
            ("relationships", "relationship(s)"),
            ("anomalies", "unusual value(s)"),
            ("standouts", "standout group(s)"),
        )
        if counts.get(key)
    ]
    if found:
        parts.append(f"The analysis identified {', '.join(found)}.")

    n_critical = assessment.get("counts", {}).get("critical", 0)
    if n_critical:
        parts.append(
            f"Before acting on any of it, the {n_critical} serious data-quality "
            f"issue(s) listed above should be resolved -- they affect the "
            f"columns several of these findings are computed from."
        )
    else:
        parts.append(
            "No serious data-quality problems were found, so these findings "
            "rest on sound data."
        )

    parts.append(
        "Every figure in this report was computed directly from the uploaded "
        "file. Recommendations are AI-generated suggestions and are marked as "
        "such."
    )
    return " ".join(parts)


def _chart_entry(panel: Dict[str, Any]) -> Dict[str, Any]:
    """One chart in the report, from a dashboard panel.

    Accepts a panel carrying either a live plotly Figure under `figure` or an
    already-serialised one under `figure_json`, because both reach this module
    legitimately: the HTTP layer hands over the cached, serialised dashboard,
    while a script or a test composing one directly has the Figure object. The
    alternative -- requiring one form -- would mean either serialising twice on
    every report request or making this module import plotly to do it once.
    """
    entry = {
        "id": panel.get("id"),
        "title": panel.get("title"),
        "question": panel.get("question"),
        "why": panel.get("why"),
        "code": panel.get("code"),
        "warnings": panel.get("warnings") or [],
    }
    if panel.get("figure_json") is not None:
        entry["figure_json"] = panel["figure_json"]
    elif panel.get("figure") is not None:
        entry["figure"] = panel["figure"]
    return entry


def _column_rows(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The dataset's columns as a table a reader can scan."""
    rows: List[Dict[str, Any]] = []
    for column in profile.get("columns", [])[:MAX_COLUMN_ROWS]:
        rows.append(
            {
                "name": str(column.get("name")),
                "kind": str(column.get("semantic_type")),
                "dtype": str(column.get("dtype")),
                "unique": column.get("n_unique"),
                "missing_pct": column.get("null_pct"),
            }
        )
    return rows


def build(
    *,
    filename: str,
    profile: Dict[str, Any],
    routing: Dict[str, Any],
    briefing: Dict[str, Any],
    insights: Dict[str, Any],
    assessment: Dict[str, Any],
    dashboard: Dict[str, Any],
    recommendations: Dict[str, Any],
    dataset_name: str = "",
) -> Dict[str, Any]:
    """Assemble the report.

    Args:
        filename: the uploaded file's name.
        profile / routing / briefing / insights / assessment / dashboard /
        recommendations: outputs of the corresponding core modules. All are
            required; a report missing one of them would have a hole in it that
            the reader could not see, which is worse than a shorter report.
        dataset_name: display name, defaulting to the filename.

    Returns:
        {"title", "subtitle", "generated_at", "sections": [...], "meta": {...}}

        Every section carries a "kind" the renderer switches on:
            summary | overview | quality | findings | charts | anomalies |
            recommendations | conclusion

    Never raises. A section whose source data is empty is omitted rather than
    rendered blank.
    """
    name = dataset_name or filename or "Untitled dataset"
    generated = datetime.now(timezone.utc)

    sections: List[Dict[str, Any]] = []

    # -- executive summary ---------------------------------------------------
    sections.append(
        _section(
            "summary",
            "Executive summary",
            body=briefing.get("summary", ""),
            headline=briefing.get("headline", ""),
            # The three or four points a reader gets if they read nothing else.
            highlights=[
                {"title": point["title"], "body": point["body"], "kind": point["kind"]}
                for point in (briefing.get("points") or [])[:3]
            ],
        )
    )

    # -- dataset overview ----------------------------------------------------
    sections.append(
        _section(
            "overview",
            "What is in this dataset",
            n_rows=profile.get("n_rows"),
            n_cols=profile.get("n_cols"),
            archetype=routing.get("archetype"),
            reasoning=routing.get("reasoning"),
            routed_by=routing.get("source"),
            columns=_column_rows(profile),
            n_columns_shown=min(len(profile.get("columns", [])), MAX_COLUMN_ROWS),
            kpis=dashboard.get("kpis") or [],
        )
    )

    # -- data quality, BEFORE the findings -----------------------------------
    sections.append(
        _section(
            "quality",
            "Data quality",
            score=assessment.get("score"),
            grade=assessment.get("grade"),
            verdict=_quality_verdict(assessment),
            checks_run=assessment.get("checks_run"),
            counts=assessment.get("counts", {}),
            issues=[
                {
                    "title": issue["title"],
                    "detail": issue["detail"],
                    "why": issue["why"],
                    "severity": issue["severity"],
                    "n_affected": issue["n_affected"],
                    "pct_affected": issue["pct_affected"],
                    "fixable": bool(issue.get("fix")),
                }
                for issue in (assessment.get("issues") or [])[:MAX_ISSUES]
            ],
            clean=assessment.get("clean") or [],
        )
    )

    # -- key findings --------------------------------------------------------
    cards = insights.get("insights") or []
    if cards:
        sections.append(
            _section(
                "findings",
                "Key findings",
                summary=insights.get("summary", ""),
                counts=insights.get("counts", {}),
                findings=[
                    {
                        "headline": card["headline"],
                        "detail": card["detail"],
                        "why": card["why"],
                        "kind": card["kind"],
                        "tone": card.get("tone", "neutral"),
                    }
                    for card in cards[:MAX_FINDINGS]
                ],
            )
        )

    # -- charts --------------------------------------------------------------
    panels = dashboard.get("panels") or []
    if panels:
        sections.append(
            _section(
                "charts",
                "The data in charts",
                note=dashboard.get("note", ""),
                charts=[_chart_entry(panel) for panel in panels[:MAX_REPORT_CHARTS]],
            )
        )

    # -- anomalies, pulled out of the findings on purpose --------------------
    # They get their own section because they are the findings a reader is most
    # likely to want to act on individually, and because they name specific
    # rows -- which is a different kind of content from a trend and reads badly
    # mixed in with one.
    anomalies = [card for card in cards if card.get("kind") == "anomaly"]
    if anomalies:
        sections.append(
            _section(
                "anomalies",
                "Unusual values worth checking",
                note=(
                    "An unusual value is not automatically an error. These are "
                    "the rows that sit furthest outside the normal range for "
                    "their column, listed so somebody who knows the data can "
                    "judge them."
                ),
                anomalies=[
                    {
                        "headline": card["headline"],
                        "detail": card["detail"],
                        "evidence": card.get("evidence") or {},
                    }
                    for card in anomalies[:4]
                ],
            )
        )

    # -- recommendations, last and labelled ----------------------------------
    suggestions = recommendations.get("recommendations") or []
    if suggestions:
        sections.append(
            _section(
                "recommendations",
                "Suggested next steps",
                disclaimer=recommendations.get("disclaimer", ""),
                source=recommendations.get("source", "rules"),
                recommendations=suggestions,
            )
        )

    sections.append(
        _section(
            "conclusion",
            "Conclusion",
            body=_conclusion(briefing, assessment, insights),
        )
    )

    return {
        "title": f"Data analysis: {name}",
        "subtitle": (
            f"{profile.get('n_rows', 0):,} rows, {profile.get('n_cols', 0)} columns"
        ),
        "dataset_name": name,
        "filename": filename,
        "generated_at": generated.isoformat(),
        "generated_display": generated.strftime("%d %B %Y at %H:%M UTC"),
        "sections": sections,
        "meta": {
            "health_score": assessment.get("score"),
            "n_findings": len(cards),
            "n_charts": min(len(panels), MAX_REPORT_CHARTS),
            "n_recommendations": len(suggestions),
            "briefing_source": briefing.get("source", "rules"),
            "recommendations_source": recommendations.get("source", "rules"),
        },
    }


def to_csv(df: pd.DataFrame) -> str:
    """The dataset as CSV text, for the "export processed data" button.

    Exists here rather than inline in the router so that the report and the data
    export are one feature in one place -- and so the index is dropped in
    exactly one spot. A re-exported file that has gained an unnamed index column
    is the classic way a "download your cleaned data" button produces a file
    that fails the very check that prompted the clean.
    """
    return df.to_csv(index=False)
