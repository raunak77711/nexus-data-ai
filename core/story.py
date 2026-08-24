"""The briefing: what a analyst would tell you about this file in ninety seconds.

WHAT THIS MODULE IS FOR
-----------------------
Everything else in core/ produces findings. core.insights returns a ranked list
of cards, core.health returns a scored list of issues, core.dashboard returns a
set of charts. All three are correct and none of them is an answer to the
question a person actually arrives with, which is "what am I looking at, and
what should I care about?"

A list is not a story. This module turns the findings into one: a paragraph
saying what the dataset appears to BE, then the handful of things that matter
most, ranked across every source rather than within one, each linked to the
thing that proves it.

THE GROUNDING GUARANTEE, AND HOW IT IS ENFORCED
-----------------------------------------------
This project's standing rule is that no number displayed anywhere is ever
written by a language model. That rule is easy to state and easy to violate by
accident the moment a model is asked to write prose ABOUT numbers, which is
exactly what this module does.

So it is enforced structurally rather than by instruction. Every candidate point
is computed first, in Python, with its numbers already formatted into a
deterministic sentence. The model is then asked only to REPHRASE what it was
given, and its output goes through `_grounded`, which extracts every numeric
token from the rewritten text and checks each one against the set of numbers
that were supplied for that point. A point whose rewrite contains a number
nobody computed is discarded and the deterministic sentence is used instead.

That check is the load-bearing part. It means the worst a hallucinating model
can do here is fail to improve the wording -- it cannot put a false figure on
the screen, because a false figure is definitionally one that is not in the
allowed set. The app is fully functional with no model configured at all; what
a key buys is fluency, which is precisely what it should buy.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd

from core import grounding, llm
from core.llm import LLMError

logger = logging.getLogger(__name__)

# Five is the brief. It is the number in the product's own promise -- "here are
# the most important things you should know" -- and a brief that runs to twelve
# points is a list again.
MAX_KEY_POINTS = 5

MAX_RECOMMENDATIONS = 4
MAX_QUESTIONS = 6

BRIEF_TOKENS = 900
RECOMMEND_TOKENS = 800
QUESTION_TOKENS = 500

# Higher than the classifier paths in this project and lower than free chat.
# These are sentences a person reads for tone as much as content; a greedy
# decode makes five points that all begin the same way.
TEMPERATURE = 0.4


# Every finding kind, mapped to how it should read in a briefing. The icon is
# part of the data rather than the frontend's business because the ordering and
# the icon are two views of the same judgement about what kind of thing this is,
# and splitting them across two files guarantees they drift.
KIND_STYLE = {
    "trend": {"icon": "trend", "tone": "info", "label": "Trend"},
    "relationship": {"icon": "link", "tone": "info", "label": "Relationship"},
    "anomaly": {"icon": "alert", "tone": "warning", "label": "Anomaly"},
    "standout": {"icon": "star", "tone": "positive", "label": "Standout"},
    "prediction": {"icon": "forecast", "tone": "info", "label": "Forecast"},
    "data_issue": {"icon": "shield", "tone": "warning", "label": "Data quality"},
    "shape": {"icon": "grid", "tone": "neutral", "label": "Overview"},
    "quality": {"icon": "shield", "tone": "warning", "label": "Data quality"},
}

BRIEF_PROMPT = """You are a data analyst writing the opening briefing for \
someone who has just uploaded a dataset and has not looked at it yet.

You are given a JSON object with:
  - "dataset": what the file contains (shape, columns, what it appears to be)
  - "points": findings the app has ALREADY COMPUTED, each with an id, a
    deterministic sentence, and the exact numbers that appear in it.

Your job is to REPHRASE each point so it reads like a person wrote it, and to
write one short opening paragraph describing what this dataset appears to be.

ABSOLUTE RULES - these override everything else:

1. You may ONLY use numbers that already appear in the point you are rewriting.
   Copy them exactly as given, including the % sign, the commas and the decimal
   places. Do NOT calculate, round, combine, convert or approximate any number.
   Do not introduce a number that is not in that point's "numbers" list.
2. Do not change what a point CLAIMS. You are changing the wording, not the
   finding. If a point says a measure fell, it fell.
3. Do not add causes. "Sales fell 18%" must not become "sales fell 18% because
   of seasonality" - you do not know that.
4. Keep every point's "id" exactly as given.

STYLE: a "title" of at most 7 words, sentence case, stating the finding itself
rather than its category - "Revenue climbed 23% since March", not "Trend
detected". Then a "body" of one or two plain sentences a non-technical reader
understands. No jargon, no markdown, no bullet points, no headings.

The "summary" paragraph: two or three sentences on what this dataset appears to
be and what it is useful for. It may reference the shape numbers given in
"dataset". It must not contain any other number.

Respond with raw JSON only, no code fences, exactly this shape:
{"summary": "...", "points": [{"id": "<unchanged>", "title": "...", "body": "..."}]}"""


RECOMMEND_PROMPT = """You are a data analyst suggesting what someone should DO \
about what was found in their dataset.

You are given a JSON object with the dataset's shape and a list of FINDINGS the
app computed. Each finding is a fact, already verified.

Write up to 4 recommendations. A recommendation says what action the findings
support, and names which finding supports it.

ABSOLUTE RULES:
1. Every recommendation must follow from a finding you were given. Name the
   finding's id in "basis".
2. You may reference a number only if it appears in that finding. Do not
   compute new ones.
3. These are suggestions, not conclusions. Write them as things worth doing or
   checking, never as statements of established fact about the user's business.
4. If a finding is a data-quality problem, the recommendation is to fix the data
   before trusting analysis that depends on it - say which analysis.
5. Do not recommend anything generic ("consider further analysis", "monitor
   regularly"). If the findings do not support a specific action, return fewer
   recommendations. Returning 1 good one is better than 4 empty ones.

STYLE: "title" is an imperative of at most 8 words ("Investigate the March drop
in Category A"). "body" is one or two sentences saying why, referencing the
finding. Plain language.

Respond with raw JSON only, no code fences, exactly this shape:
{"recommendations": [{"title": "...", "body": "...", "basis": "<finding id>",
"confidence": "high"|"medium"|"low"}]}"""


QUESTION_PROMPT = """You suggest questions someone should ask about their \
dataset. They do not know what is in it and do not know what is worth asking.

You are given the dataset's columns (names and kinds only, never values) and a
list of findings the app already computed.

Write up to 6 questions the user could type into a data assistant.

RULES:
1. Every question must be answerable from THIS dataset's columns. Never ask
   about a column that is not listed.
2. Use the real column names, in natural phrasing - "Which department has the
   highest average salary?" not "Which category has the highest metric?"
3. Vary them: one about the overall shape, one about a ranking, one about a
   relationship or trend if the columns support it, one about something unusual.
4. Ask them the way a person types, not the way a report is titled. No question
   longer than 12 words.
5. Do not ask a question a finding has already answered outright.

Respond with raw JSON only, no code fences, exactly this shape:
{"questions": [{"text": "...", "why": "<at most 8 words on what it reveals>"}]}"""


# --------------------------------------------------------------- grounding --
# The check itself lives in core.grounding, which is imported rather than
# reimplemented here -- see that module's docstring for why it is shared. These
# aliases keep the call sites below reading as prose.
_number_tokens = grounding.number_tokens
_grounded = grounding.is_grounded
_parse = grounding.parse_json


# ------------------------------------------------------------------- facts --
def _friendly(name: str) -> str:
    return str(name).replace("_", " ").replace("-", " ").strip()


def _describe_dataset(
    profile: Dict[str, Any], routing: Dict[str, Any], filename: str
) -> Dict[str, Any]:
    """The shape block: what the file is, in numbers the model may quote."""
    kinds: Dict[str, int] = {}
    for column in profile.get("columns", []):
        kind = str(column.get("semantic_type"))
        kinds[kind] = kinds.get(kind, 0) + 1

    return {
        "filename": filename,
        "n_rows": int(profile.get("n_rows") or 0),
        "n_columns": int(profile.get("n_cols") or 0),
        "column_kinds": kinds,
        "columns": [
            {"name": str(c.get("name")), "kind": str(c.get("semantic_type"))}
            for c in profile.get("columns", [])[:40]
        ],
        "looks_like": routing.get("archetype"),
        "why": routing.get("reasoning", ""),
        "time_column": routing.get("time_col"),
        "main_measure": routing.get("target_col"),
    }


def _point(
    point_id: str,
    kind: str,
    title: str,
    body: str,
    *,
    score: float,
    link: Optional[Dict[str, Any]] = None,
    numbers: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """One thing worth knowing, with everything needed to verify and open it.

    `numbers` is the whitelist for this point's rewrite. It is derived from the
    deterministic body rather than passed in separately, so a point can never
    be created with a whitelist that disagrees with its own text.
    """
    style = KIND_STYLE.get(kind, KIND_STYLE["shape"])
    allowed = set(numbers or []) | _number_tokens(title) | _number_tokens(body)
    return {
        "id": point_id,
        "kind": kind,
        "label": style["label"],
        "icon": style["icon"],
        "tone": style["tone"],
        "title": title,
        "body": body,
        # `link` is what makes a briefing point clickable: it names the thing
        # elsewhere in the app that proves this point -- an insight card, a
        # chart spec to draw, or the health issue it came from.
        "link": link,
        "_score": float(score),
        "_numbers": allowed,
    }


def _points_from_insights(insights: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Turn insight cards into briefing points.

    The cards are already ranked against each other by core.insights, so the
    score here preserves that order while leaving room above and below for
    health and shape points to interleave.
    """
    points: List[Dict[str, Any]] = []
    cards = insights.get("insights", []) or []

    for position, card in enumerate(cards):
        kind = str(card.get("kind", "shape"))
        headline = str(card.get("headline") or "").strip()
        detail = str(card.get("detail") or "").strip()
        if not headline:
            continue

        # Insight cards lead with the finding and follow with the evidence,
        # which is the right order for a briefing too.
        body = detail or str(card.get("why") or "")
        points.append(
            _point(
                f"insight:{card.get('id')}",
                kind,
                headline,
                body,
                # Descending from 100 so the first card outranks everything
                # except a critical data-quality problem, which is scored above.
                score=100.0 - position,
                link={
                    "kind": "insight",
                    "insight_id": card.get("id"),
                    "chart": card.get("action"),
                },
                numbers=_number_tokens(str(card.get("why") or "")),
            )
        )

    return points


def _points_from_health(assessment: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Turn the health report into briefing points.

    Only the serious issues, and only the top two of those. A briefing is not
    the health screen -- it says "your data has a problem, go and look" and
    links to the place where all of them are listed. Filling the five most
    important things with five missing-value warnings would be accurate and
    useless.
    """
    points: List[Dict[str, Any]] = []
    issues = assessment.get("issues", []) or []
    critical = [i for i in issues if i.get("severity") == "critical"]

    for issue in critical[:2]:
        points.append(
            _point(
                f"health:{issue['id']}",
                "quality",
                str(issue.get("title") or "Data quality problem"),
                str(issue.get("detail") or "") + " " + str(issue.get("why") or ""),
                # Above every insight: a finding computed from broken data is
                # not a finding, so the user needs to know the data is broken
                # before they read anything else.
                score=200.0 - issues.index(issue),
                link={"kind": "health", "issue_id": issue.get("id")},
            )
        )

    score = assessment.get("score")
    if score is not None and not critical:
        # No critical problems is itself worth one line, because "is this data
        # any good" is a question every user has and most never ask out loud.
        n_checks = int(assessment.get("checks_run") or 0)
        points.append(
            _point(
                "health:score",
                "quality",
                f"Data quality scores {score} out of 100",
                f"{assessment.get('verdict', '')} "
                f"{n_checks} checks were run and "
                f"{len(issues)} issue(s) were found, none of them serious.",
                score=40.0,
                link={"kind": "health"},
                numbers={f"{float(score):.6g}", f"{n_checks:.6g}", f"{len(issues):.6g}"},
            )
        )

    return points


def _shape_point(dataset: Dict[str, Any]) -> Dict[str, Any]:
    """The one point that is always available, even for an empty finding list."""
    kinds = dataset["column_kinds"]
    parts = []
    for kind, label in (
        ("numeric", "measure"), ("categorical", "category"),
        ("datetime", "date"), ("geo_lat", "coordinate"), ("text", "text"),
    ):
        count = kinds.get(kind, 0)
        if count:
            parts.append(f"{count} {label}{'s' if count != 1 else ''}")

    return _point(
        "shape",
        "shape",
        f"{dataset['n_rows']:,} rows across {dataset['n_columns']} columns",
        f"This file holds {', '.join(parts) or 'no recognisable columns'}."
        + (
            f" It is organised around `{dataset['time_column']}`, so it can be "
            f"read as a history rather than a snapshot."
            if dataset.get("time_column") else ""
        ),
        score=30.0,
        link={"kind": "data"},
    )


def build_facts(
    profile: Dict[str, Any],
    routing: Dict[str, Any],
    insights: Dict[str, Any],
    assessment: Dict[str, Any],
    filename: str = "",
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Everything the briefing could say, computed and ranked.

    Returns (dataset_block, ranked_points). Separated from `brief` below so the
    report builder and the recommendation pass can reuse the same facts without
    re-deriving them -- and so the deterministic content of a briefing can be
    tested without a model.
    """
    dataset = _describe_dataset(profile, routing, filename)

    points: List[Dict[str, Any]] = []
    points.extend(_points_from_health(assessment))
    points.extend(_points_from_insights(insights))
    points.append(_shape_point(dataset))

    points.sort(key=lambda p: p["_score"], reverse=True)
    return dataset, points


# ------------------------------------------------------------------ briefs --
def _rewrite_points(
    dataset: Dict[str, Any],
    points: List[Dict[str, Any]],
    api_key: Optional[str],
) -> Tuple[str, Dict[str, Dict[str, str]], str]:
    """Ask the model to rephrase the computed points. Never trusted blindly.

    Returns (summary, {point_id: {"title", "body"}}, source). On any failure --
    no key, a timeout, unparseable JSON -- the rewrites dict is empty and the
    caller uses its deterministic text, which is why every failure path here is
    a `return` rather than a `raise`.
    """
    payload = {
        "dataset": {
            "filename": dataset["filename"],
            "n_rows": dataset["n_rows"],
            "n_columns": dataset["n_columns"],
            "column_kinds": dataset["column_kinds"],
            "columns": dataset["columns"][:25],
            "looks_like": dataset["looks_like"],
        },
        "points": [
            {
                "id": point["id"],
                "category": point["label"],
                "sentence": f"{point['title']}. {point['body']}",
                "numbers": sorted(point["_numbers"]),
            }
            for point in points
        ],
    }

    try:
        raw = llm.complete(
            json.dumps(payload, default=str),
            BRIEF_PROMPT,
            max_tokens=BRIEF_TOKENS,
            temperature=TEMPERATURE,
            json_mode=True,
            api_key_override=api_key,
        )
    except LLMError as exc:
        logger.info("Briefing rewrite unavailable: %s", exc)
        return "", {}, "rules"

    parsed = _parse(raw)
    if not parsed:
        return "", {}, "rules"

    allowed_ids = {point["id"] for point in points}
    by_id = {point["id"]: point for point in points}
    rewrites: Dict[str, Dict[str, str]] = {}

    for entry in parsed.get("points", []) or []:
        if not isinstance(entry, dict):
            continue
        point_id = str(entry.get("id") or "")
        if point_id not in allowed_ids:
            # An id the model invented refers to no finding, so there is
            # nothing for the rewrite to be a rewrite OF.
            continue
        title = str(entry.get("title") or "").strip()
        body = str(entry.get("body") or "").strip()
        if not title or not body:
            continue

        allowed = by_id[point_id]["_numbers"]
        if not _grounded(title, allowed) or not _grounded(body, allowed):
            logger.info("Discarded ungrounded rewrite for %s", point_id)
            continue
        rewrites[point_id] = {"title": title, "body": body}

    summary = str(parsed.get("summary") or "").strip()
    # The summary may quote the shape numbers and nothing else.
    shape_numbers = {
        f"{float(dataset['n_rows']):.6g}",
        f"{float(dataset['n_columns']):.6g}",
    } | {f"{float(v):.6g}" for v in dataset["column_kinds"].values()}
    if summary and not _grounded(summary, shape_numbers):
        logger.info("Discarded ungrounded briefing summary")
        summary = ""

    return summary, rewrites, "llm" if (rewrites or summary) else "rules"


def _fallback_summary(dataset: Dict[str, Any], n_points: int) -> str:
    """The summary paragraph, written without a model.

    This is not a placeholder. An app with no key configured shows this, and it
    has to be a real sentence somebody is happy to read -- so it is assembled
    from the same facts the model would have been given.
    """
    kinds = dataset["column_kinds"]
    shape = (
        f"This file has {dataset['n_rows']:,} rows and "
        f"{dataset['n_columns']} columns"
    )

    if dataset.get("time_column") and dataset.get("main_measure"):
        character = (
            f", and it tracks `{dataset['main_measure']}` over time using "
            f"`{dataset['time_column']}`, so it can be read as a history."
        )
    elif kinds.get("geo_lat"):
        character = ", and it carries coordinates, so its values have places."
    elif kinds.get("numeric") and kinds.get("categorical"):
        character = (
            f", and it measures {kinds.get('numeric', 0)} thing(s) across "
            f"{kinds.get('categorical', 0)} way(s) of grouping them."
        )
    else:
        character = "."

    return (
        shape + character
        + f" I checked it for quality problems, trends, relationships and "
        f"unusual values, and found {n_points} thing(s) worth telling you about."
    )


def brief(
    profile: Dict[str, Any],
    routing: Dict[str, Any],
    insights: Dict[str, Any],
    assessment: Dict[str, Any],
    *,
    filename: str = "",
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """The dataset briefing: what this is, and the things that matter most.

    Args:
        profile: core.profiler.profile_dataframe output.
        routing: core.router.route output.
        insights: core.insights.generate output.
        assessment: core.health.assess output.
        filename: shown in the briefing; never used to infer anything.
        api_key: per-request override, threaded to core.llm.

    Returns:
        {"headline": str, "summary": str, "points": [...],
         "source": "llm"|"rules", "n_considered": int}

        Each point carries id, kind, label, icon, tone, title, body and link.
        `link` is what the UI opens when the point is clicked.

    Never raises. A model failure costs fluency, not the briefing.
    """
    dataset, ranked = build_facts(profile, routing, insights, assessment, filename)
    chosen = ranked[:MAX_KEY_POINTS]

    summary, rewrites, source = ("", {}, "rules")
    if chosen and llm.available(api_key):
        try:
            summary, rewrites, source = _rewrite_points(dataset, chosen, api_key)
        except (ValueError, TypeError, KeyError) as exc:
            # A malformed reply that got past _parse. Cost is the rewrite only.
            logger.warning("Briefing rewrite failed: %s", exc)

    points: List[Dict[str, Any]] = []
    for point in chosen:
        rewrite = rewrites.get(point["id"], {})
        points.append(
            {
                "id": point["id"],
                "kind": point["kind"],
                "label": point["label"],
                "icon": point["icon"],
                "tone": point["tone"],
                "title": rewrite.get("title") or point["title"],
                "body": rewrite.get("body") or point["body"],
                "link": point["link"],
                # Honest per-point provenance. A briefing where three points
                # were rephrased and two were not is the normal outcome of the
                # grounding check, and the UI is entitled to know which is which.
                "written_by": "llm" if point["id"] in rewrites else "rules",
            }
        )

    return {
        "headline": (
            f"I've analysed your data. Here are the "
            f"{len(points)} thing(s) you should know."
            if points
            else "I've analysed your data."
        ),
        "summary": summary or _fallback_summary(dataset, len(ranked)),
        "points": points,
        "source": source,
        "n_considered": len(ranked),
    }


# --------------------------------------------------------- recommendations --
def _fallback_recommendations(
    points: List[Dict[str, Any]], assessment: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Recommendations without a model: only the ones a rule can honestly make.

    Deliberately few. A rule can say "fix this data problem before trusting
    these numbers" because that follows from the finding by definition. It
    cannot say "shift marketing spend toward Segment A", so it does not, and
    the list is short rather than padded.
    """
    recommendations: List[Dict[str, Any]] = []

    n_critical = assessment.get("counts", {}).get("critical", 0)
    n_fixable = assessment.get("n_fixable", 0)
    if n_critical:
        recommendations.append(
            {
                "title": "Fix the data problems before drawing conclusions",
                "body": (
                    f"{n_critical} serious quality issue(s) were found. Numbers "
                    f"computed over data with these problems can be wrong in ways "
                    f"that look plausible."
                    + (
                        f" {n_fixable} of the issues can be repaired automatically "
                        f"on the Health screen."
                        if n_fixable else ""
                    )
                ),
                "basis": "health",
                "confidence": "high",
            }
        )

    for point in points:
        if point["kind"] == "anomaly":
            recommendations.append(
                {
                    "title": "Check the unusual rows individually",
                    "body": (
                        f"{point['title']}. An unusual value is either an error "
                        f"worth correcting or a real case worth understanding, and "
                        f"only someone who knows the data can say which."
                    ),
                    "basis": point["id"],
                    "confidence": "medium",
                }
            )
            break

    for point in points:
        if point["kind"] == "relationship":
            recommendations.append(
                {
                    "title": "Test whether the relationship holds",
                    "body": (
                        f"{point['title']}. Two things moving together is not one "
                        f"causing the other -- worth checking against a period or "
                        f"a group the pattern was not found in."
                    ),
                    "basis": point["id"],
                    "confidence": "medium",
                }
            )
            break

    return recommendations[:MAX_RECOMMENDATIONS]


def recommend(
    profile: Dict[str, Any],
    routing: Dict[str, Any],
    insights: Dict[str, Any],
    assessment: Dict[str, Any],
    *,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """What to do about what was found.

    Returns:
        {"recommendations": [{"title", "body", "basis", "confidence"}],
         "source": "llm"|"rules", "disclaimer": str}

    Every recommendation is labelled as a suggestion, in the payload rather than
    only in the interface, so a caller that renders this somewhere else cannot
    accidentally present a model's inference as a finding.
    """
    dataset, ranked = build_facts(profile, routing, insights, assessment)
    points = ranked[:8]

    disclaimer = (
        "AI-generated suggestions based on patterns in your data. They are "
        "starting points for investigation, not conclusions -- the data shows "
        "what happened, not why."
    )

    if not llm.available(api_key) or not points:
        return {
            "recommendations": _fallback_recommendations(points, assessment),
            "source": "rules",
            "disclaimer": disclaimer,
        }

    payload = {
        "dataset": {
            "n_rows": dataset["n_rows"],
            "n_columns": dataset["n_columns"],
            "looks_like": dataset["looks_like"],
        },
        "findings": [
            {
                "id": point["id"],
                "category": point["label"],
                "finding": f"{point['title']}. {point['body']}",
            }
            for point in points
        ],
        "data_quality": {
            "score": assessment.get("score"),
            "critical_issues": assessment.get("counts", {}).get("critical", 0),
            "fixable": assessment.get("n_fixable", 0),
        },
    }

    try:
        raw = llm.complete(
            json.dumps(payload, default=str),
            RECOMMEND_PROMPT,
            max_tokens=RECOMMEND_TOKENS,
            temperature=TEMPERATURE,
            json_mode=True,
            api_key_override=api_key,
        )
    except LLMError as exc:
        logger.info("Recommendations unavailable: %s", exc)
        return {
            "recommendations": _fallback_recommendations(points, assessment),
            "source": "rules",
            "disclaimer": disclaimer,
        }

    parsed = _parse(raw)
    allowed_ids = {point["id"] for point in points} | {"health"}
    # One pooled whitelist rather than a per-point one: a recommendation is
    # allowed to draw on several findings at once, so the numbers it may quote
    # are the union of the numbers in the findings it was given.
    allowed_numbers: Set[str] = set()
    for point in points:
        allowed_numbers |= point["_numbers"]
    for key in ("score", "critical_issues", "fixable"):
        value = payload["data_quality"].get(key)
        if isinstance(value, (int, float)):
            allowed_numbers.add(f"{float(value):.6g}")

    recommendations: List[Dict[str, Any]] = []
    for entry in parsed.get("recommendations", []) or []:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()
        body = str(entry.get("body") or "").strip()
        basis = str(entry.get("basis") or "").strip()
        if not title or not body:
            continue
        if basis and basis not in allowed_ids:
            # A recommendation citing a finding that does not exist is not
            # traceable, and an untraceable recommendation is an opinion.
            logger.info("Discarded recommendation citing unknown basis %r", basis)
            continue
        if not _grounded(title, allowed_numbers) or not _grounded(body, allowed_numbers):
            logger.info("Discarded ungrounded recommendation %r", title)
            continue
        confidence = str(entry.get("confidence") or "medium").lower()
        recommendations.append(
            {
                "title": title,
                "body": body,
                "basis": basis,
                "confidence": confidence if confidence in ("high", "medium", "low") else "medium",
            }
        )

    if not recommendations:
        return {
            "recommendations": _fallback_recommendations(points, assessment),
            "source": "rules",
            "disclaimer": disclaimer,
        }

    return {
        "recommendations": recommendations[:MAX_RECOMMENDATIONS],
        "source": "llm",
        "disclaimer": disclaimer,
    }


# --------------------------------------------------------------- questions --
def _fallback_questions(
    df_columns: Sequence[str],
    profile: Dict[str, Any],
    routing: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Suggested questions built from the columns, with no model involved.

    These are real questions about the user's actual columns -- not
    "Summarise the data" -- because the whole purpose of this feature is to help
    somebody who does not know what is askable, and a generic prompt teaches
    them nothing about their own file.
    """
    grouped: Dict[str, List[str]] = {}
    for column in profile.get("columns", []):
        grouped.setdefault(str(column.get("semantic_type")), []).append(
            str(column.get("name"))
        )

    numeric = grouped.get("numeric", [])
    categorical = grouped.get("categorical", [])
    time_col = routing.get("time_col")
    measure = routing.get("target_col") or (numeric[0] if numeric else None)

    questions: List[Dict[str, Any]] = [
        {"text": "What is the most surprising thing in this data?",
         "why": "Opens with whatever ranked highest"},
    ]

    if measure and categorical:
        questions.append(
            {
                "text": f"Which {_friendly(categorical[0])} has the highest "
                        f"{_friendly(measure)}?",
                "why": "Ranks the groups against each other",
            }
        )
    if measure and time_col:
        questions.append(
            {
                "text": f"How has {_friendly(measure)} changed over time?",
                "why": "Shows the direction of travel",
            }
        )
    if len(numeric) >= 2:
        questions.append(
            {
                "text": f"Is there a relationship between {_friendly(numeric[0])} "
                        f"and {_friendly(numeric[1])}?",
                "why": "Tests whether they move together",
            }
        )
    if measure:
        questions.append(
            {
                "text": f"What is the average {_friendly(measure)}?",
                "why": "The single number people ask for first",
            }
        )
        questions.append(
            {
                "text": f"Are there any unusual {_friendly(measure)} values?",
                "why": "Finds the rows worth checking",
            }
        )

    questions.append({"text": "What should I investigate first?",
                      "why": "Turns the findings into a next step"})

    return questions[:MAX_QUESTIONS]


def questions(
    profile: Dict[str, Any],
    routing: Dict[str, Any],
    insights: Dict[str, Any],
    *,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Questions this dataset can actually answer, for someone who has none.

    Returns {"questions": [{"text", "why"}], "source": "llm"|"rules"}.

    A question naming a column that does not exist is worse than no suggestion
    at all -- the user asks it, the assistant cannot answer, and the product
    looks broken at the exact moment it was trying to be helpful. So every
    model-written question is checked against the real column list before it is
    offered.
    """
    columns = [str(c.get("name")) for c in profile.get("columns", [])]
    fallback = _fallback_questions(columns, profile, routing)

    if not llm.available(api_key) or not columns:
        return {"questions": fallback, "source": "rules"}

    payload = {
        "columns": [
            {"name": str(c.get("name")), "kind": str(c.get("semantic_type"))}
            for c in profile.get("columns", [])[:40]
        ],
        "findings": [
            str(card.get("headline"))
            for card in (insights.get("insights") or [])[:6]
        ],
    }

    try:
        raw = llm.complete(
            json.dumps(payload, default=str),
            QUESTION_PROMPT,
            max_tokens=QUESTION_TOKENS,
            temperature=0.6,
            json_mode=True,
            api_key_override=api_key,
        )
    except LLMError as exc:
        logger.info("Suggested questions unavailable: %s", exc)
        return {"questions": fallback, "source": "rules"}

    parsed = _parse(raw)
    lowered_columns = {c.lower() for c in columns}
    friendly_columns = {_friendly(c).lower() for c in columns}

    suggested: List[Dict[str, Any]] = []
    for entry in parsed.get("questions", []) or []:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "").strip()
        if not text or len(text) > 120:
            continue
        # A question that mentions no column at all is fine -- "what should I
        # investigate first?" is a good suggestion. What must not survive is a
        # question naming a column that does not exist, because the user will
        # ask it and the assistant will fail on it.
        #
        # Only tokens that LOOK like a column reference are checked: backticked
        # names, and snake_case words, which is how a model writes a column name
        # when it is copying one. Checking every word would reject ordinary
        # English, since "the" is not a column either.
        mentions_unknown = False
        for backticked, snake_case in re.findall(r"`([^`]+)`|(\b\w+_\w+\b)", text):
            name = (backticked or snake_case).strip().lower()
            if name and name not in lowered_columns and name not in friendly_columns:
                mentions_unknown = True
                break
        if mentions_unknown:
            logger.info("Discarded question naming an unknown column: %r", text)
            continue
        suggested.append({"text": text, "why": str(entry.get("why") or "").strip()})

    if not suggested:
        return {"questions": fallback, "source": "rules"}

    return {"questions": suggested[:MAX_QUESTIONS], "source": "llm"}
