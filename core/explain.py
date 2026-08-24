"""One button, two registers: "explain this" for someone who does not know, and
for someone who does.

WHY TWO LEVELS RATHER THAN ONE GOOD EXPLANATION
-----------------------------------------------
Because they are answers to different questions. A person looking at a
correlation heatmap for the first time is asking "what am I looking at"; a
person who recognises it is asking "how was this computed and where does it
break". An explanation that serves both is one that bores the second reader
while still using a word the first one does not know.

So the register is a parameter, and the two prompts are genuinely different
instructions rather than the same instruction with "be more technical" appended.
Simple mode is forbidden from naming a statistical method at all. Technical mode
is required to state the method, the sample it ran on, and at least one reason
the result might mislead -- because the most useful thing you can tell an expert
about a computed number is where it stops being trustworthy.

WHAT CAN BE EXPLAINED
---------------------
Anything, as long as the caller hands over the FACTS. This module never touches
a DataFrame and never recomputes anything: the chart, the insight, the health
issue and the KPI were all computed elsewhere, and their evidence dicts are the
input here. That is what keeps one explanation endpoint from becoming a second,
divergent analysis engine -- and it is what makes the grounding check possible,
since the set of legitimate numbers is exactly the set that arrived with the
subject.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Set

from core import charts, grounding, llm
from core.llm import LLMError

logger = logging.getLogger(__name__)

SIMPLE = "simple"
TECHNICAL = "technical"
LEVELS = (SIMPLE, TECHNICAL)

MAX_TOKENS = 550
TEMPERATURE = 0.3

# How deep into a nested evidence dict to walk when collecting the numbers a
# model is allowed to quote. Evidence is shallow by construction, and an
# unbounded walk over a structure that turned out to be cyclic would hang the
# request rather than fail it.
MAX_EVIDENCE_DEPTH = 4


SIMPLE_PROMPT = """You explain one result to someone with no background in data, \
statistics or programming. They are intelligent; they simply have never been \
taught this.

You are given a SUBJECT: what is on their screen, with the numbers that were
computed for it.

ABSOLUTE RULES:
1. Every number you write must appear in the SUBJECT. Do not calculate anything
   new -- not a percentage, not a difference, not a ratio, not a total. If a
   number would help and is not there, leave it out.
2. Never use these words: correlation, coefficient, distribution, variance,
   standard deviation, outlier, aggregation, median, quantile, statistically
   significant, p-value, regression, normalise. Say what they mean instead --
   "these two move together", "how spread out the values are", "a value far
   outside the normal range", "the middle value".
3. Say what the result MEANS for the person's data, not how the chart was drawn.
4. Do not speculate about causes. What the data shows is not why it happened.

STYLE: 2 to 4 short sentences. Lead with the answer. Second person ("your
data", "you can see"). No markdown, no headings, no lists, no jargon.

Respond with raw JSON only, no code fences, exactly this shape:
{"text": "..."}"""


TECHNICAL_PROMPT = """You explain one result to a working analyst who knows \
statistics and wants the method and its limits.

You are given a SUBJECT: what is on screen, with the computed numbers and how
they were derived.

ABSOLUTE RULES:
1. Every number you write must appear in the SUBJECT. Do not calculate anything
   new, including derived statistics. If you want a figure that is not given,
   say what would need to be computed instead of estimating it.
2. State the method actually used, as given in the SUBJECT. Do not invent a
   method, a test, or a confidence interval that was not run.
3. Include at least one specific caveat -- what would make this result
   misleading, what it does not control for, or what the sample size limits.
   Be concrete about THIS result, not generic about statistics.
4. Do not claim causation and do not claim significance unless a test for it is
   named in the SUBJECT.

STYLE: 3 to 5 sentences. Precise, unhedged, technical vocabulary is fine and
expected. No markdown headings, no bullet lists.

Respond with raw JSON only, no code fences, exactly this shape:
{"text": "..."}"""


# What a chart of each kind actually does, stated once so the technical register
# can name the method without the model guessing at it. These are facts about
# this application's own implementation -- see core.charts -- and a model has no
# way of knowing them, so they are supplied rather than requested.
CHART_METHOD = {
    "line": (
        "Values are grouped into time buckets and aggregated within each "
        "bucket, then plotted in time order."
    ),
    "bar": (
        "Rows are grouped by the category column and aggregated within each "
        "group; only the top groups are drawn."
    ),
    "scatter": (
        "One point per row, with an ordinary least-squares line fitted across "
        "them. Large frames are randomly sampled before fitting."
    ),
    "histogram": (
        "Values are placed into equal-width bins and the count in each bin is "
        "drawn. Bin width, not the data, decides how smooth this looks."
    ),
    "box": (
        "Each box spans the interquartile range with the median marked; the "
        "whiskers reach the furthest points within 1.5 IQR of the box."
    ),
    "map": "Each row is placed at its coordinates, sized and coloured by the measure.",
    "heatmap": (
        "Pairwise Pearson correlation between every pair of numeric columns, "
        "computed on rows where both values are present."
    ),
}


def _collect_numbers(value: Any, depth: int = 0) -> Set[str]:
    """Every number anywhere inside an evidence structure.

    Walks dicts and lists because evidence is nested -- an outlier issue carries
    a list of row dicts, each with its own value -- and a whitelist that only
    looked at the top level would reject a model for quoting the very row the
    user clicked on.
    """
    if depth > MAX_EVIDENCE_DEPTH:
        return set()

    if isinstance(value, dict):
        found: Set[str] = set()
        for item in value.values():
            found |= _collect_numbers(item, depth + 1)
        return found
    if isinstance(value, (list, tuple)):
        found = set()
        for item in value:
            found |= _collect_numbers(item, depth + 1)
        return found
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, (int, float)):
        return grounding.normalise([value])
    return grounding.number_tokens(str(value))


def _fallback(subject: Dict[str, Any], level: str) -> str:
    """The explanation shown when no model is configured, or its answer failed.

    Assembled from the same facts the model would have received, so a
    key-less deployment gets a real explanation rather than an apology. It is
    less fluent, and it is never wrong.
    """
    title = str(subject.get("title") or "This result").strip()
    detail = str(subject.get("detail") or "").strip()
    why = str(subject.get("why") or "").strip()
    method = str(subject.get("method") or "").strip()

    if level == TECHNICAL:
        parts = [p for p in (detail, method, why) if p]
        if not parts:
            parts = [f"{title}. No further detail was computed for this item."]
        return " ".join(parts)

    parts = [p for p in (detail or title, why) if p]
    return " ".join(parts) or f"{title}."


def _payload(subject: Dict[str, Any], dataset: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The JSON handed to the model: the subject, and nothing else about the data.

    Note what is absent. No rows, no column values, no sample of the frame --
    only the computed summary of the one thing being explained, plus the shape
    of the dataset for context. The model cannot leak data it was never given,
    which is a structural guarantee rather than a policy.
    """
    payload: Dict[str, Any] = {
        "subject": {
            "what_it_is": subject.get("kind"),
            "title": subject.get("title"),
            "finding": subject.get("detail"),
            "why_it_matters": subject.get("why"),
            "computed_values": subject.get("evidence") or {},
        }
    }
    method = subject.get("method")
    if method:
        payload["subject"]["how_it_was_computed"] = method
    if dataset:
        payload["dataset"] = {
            "n_rows": dataset.get("n_rows"),
            "n_columns": dataset.get("n_cols") or dataset.get("n_columns"),
        }
    return payload


def explain(
    subject: Dict[str, Any],
    *,
    level: str = SIMPLE,
    dataset: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Explain one computed result at the requested level of detail.

    Args:
        subject: what to explain. Recognised keys:
            kind     -- "chart", "insight", "health_issue", "kpi", "stat"
            title    -- the headline as displayed
            detail   -- the deterministic sentence already computed for it
            why      -- why it matters, if the source produced one
            method   -- how it was computed; supplied for charts from
                        CHART_METHOD, and required for a good technical answer
            evidence -- the numbers behind it, in any nested shape
        level: "simple" or "technical". Anything else is treated as simple,
            because an unrecognised register should degrade to the safer one.
        dataset: optional {"n_rows", "n_cols"} for context.
        api_key: per-request override, threaded to core.llm.

    Returns:
        {"text": str, "level": str, "source": "llm"|"rules", "title": str}

    Never raises. Every failure path returns the deterministic explanation, so
    the button always does something when pressed.
    """
    level = level if level in LEVELS else SIMPLE
    title = str(subject.get("title") or "This result")
    fallback = _fallback(subject, level)

    if not llm.available(api_key):
        return {"text": fallback, "level": level, "source": "rules", "title": title}

    # The whitelist: every number in the evidence, plus any already present in
    # the deterministic sentences, plus the dataset shape. A model quoting the
    # row count in an explanation is quoting something true.
    allowed = _collect_numbers(subject.get("evidence"))
    allowed |= grounding.number_tokens(str(subject.get("detail") or ""))
    allowed |= grounding.number_tokens(str(subject.get("why") or ""))
    allowed |= grounding.number_tokens(title)
    if dataset:
        allowed |= grounding.normalise(
            [dataset.get("n_rows"), dataset.get("n_cols"), dataset.get("n_columns")]
        )

    prompt = TECHNICAL_PROMPT if level == TECHNICAL else SIMPLE_PROMPT

    try:
        raw = llm.complete(
            json.dumps(_payload(subject, dataset), default=str),
            prompt,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            json_mode=True,
            api_key_override=api_key,
        )
    except LLMError as exc:
        logger.info("Explanation unavailable: %s", exc)
        return {"text": fallback, "level": level, "source": "rules", "title": title}

    parsed = grounding.parse_json(raw)
    text = grounding.keep_if_grounded(
        str(parsed.get("text") or ""), allowed, f"{level} explanation"
    )

    if not text:
        return {"text": fallback, "level": level, "source": "rules", "title": title}

    return {"text": text, "level": level, "source": "llm", "title": title}


def subject_from_chart(panel: Dict[str, Any]) -> Dict[str, Any]:
    """Build an explain subject from a dashboard panel or a built chart.

    The method string comes from CHART_METHOD rather than from the panel,
    because how a chart was computed is a fact about core.charts that the panel
    does not carry -- and a technical explanation that guesses at the method is
    worse than one that omits it.
    """
    spec = panel.get("spec") or {}
    kind = str(spec.get("chart") or "")
    columns = [
        str(spec[key]) for key in ("x", "y", "lat", "lon") if spec.get(key)
    ] + [str(c) for c in (spec.get("columns") or [])]

    method = CHART_METHOD.get(kind, "")
    if spec.get("agg"):
        method += f" The values are combined using {spec['agg']}."
    if spec.get("freq"):
        # FREQ_LABELS, not the raw code. Passing "D" through produced a
        # technical explanation reading "grouped into D buckets", where the
        # model reasonably took D for a count it had not been given -- a
        # sentence that is not wrong so much as meaningless, from an internal
        # alias that was never meant to be read by anyone.
        label = charts.FREQ_LABELS.get(spec["freq"], str(spec["freq"]))
        method += f" Rows are grouped into {label} buckets."

    question = panel.get("question") or ""
    title = panel.get("title") or question or "This chart"

    return {
        "kind": "chart",
        "title": title,
        # Phrased as a statement rather than passed through as the bare
        # question, because `detail` is what the no-model fallback prints
        # verbatim -- and an explanation that opens by asking the reader a
        # question reads as though it failed to load.
        "detail": (
            f"This chart is here to answer: {question.rstrip('?')}?" if question
            else f"{title}."
        ),
        "why": panel.get("why") or "",
        "method": method.strip(),
        "evidence": {
            "chart_type": kind,
            "columns_used": columns,
            **({"warnings": panel["warnings"]} if panel.get("warnings") else {}),
        },
    }


def subject_from_insight(card: Dict[str, Any]) -> Dict[str, Any]:
    """Build an explain subject from a core.insights card."""
    return {
        "kind": "insight",
        "title": card.get("headline") or "This finding",
        "detail": card.get("detail") or "",
        "why": card.get("why") or "",
        "method": _INSIGHT_METHOD.get(str(card.get("kind")), ""),
        "evidence": card.get("evidence") or {},
    }


def subject_from_issue(issue: Dict[str, Any]) -> Dict[str, Any]:
    """Build an explain subject from a core.health issue."""
    fix = issue.get("fix") or {}
    return {
        "kind": "health_issue",
        "title": issue.get("title") or "This data issue",
        "detail": issue.get("detail") or "",
        "why": issue.get("why") or "",
        "method": (
            f"Detected by the {issue.get('kind')} check across "
            f"{issue.get('n_affected')} affected row(s), "
            f"{issue.get('pct_affected')}% of the file."
            + (f" Proposed repair: {fix.get('description')}" if fix else "")
        ),
        "evidence": {
            "n_affected": issue.get("n_affected"),
            "pct_affected": issue.get("pct_affected"),
            "severity": issue.get("severity"),
            **(issue.get("evidence") or {}),
        },
    }


# How core.insights computes each kind of card. Same reasoning as CHART_METHOD:
# these are facts about this repository, supplied so the technical register can
# be accurate rather than plausible.
_INSIGHT_METHOD = {
    "trend": (
        "The mean of the first third of the series is compared with the mean of "
        "the last third, rather than first and last points, so a single unusual "
        "day at either end cannot decide the direction."
    ),
    "relationship": (
        "Pearson correlation over rows where both columns are present."
    ),
    "anomaly": (
        "Values beyond 3x the interquartile range from the quartiles are "
        "flagged. That fence is wider than the textbook 1.5x, which over-flags "
        "on real business data."
    ),
    "standout": (
        "Group means compared against the overall mean, for groups large enough "
        "to be stable."
    ),
    "prediction": (
        "A random forest over lag and calendar features, scored on a held-out "
        "final portion of the series against a naive same-as-yesterday baseline."
    ),
    "data_issue": "Counted directly over the column.",
}


def levels() -> List[Dict[str, str]]:
    """The registers this module offers, for a UI that wants to render a toggle."""
    return [
        {
            "id": SIMPLE,
            "label": "Simple",
            "description": "Plain language, no statistics vocabulary.",
        },
        {
            "id": TECHNICAL,
            "label": "Technical",
            "description": "Method, assumptions and where the result breaks down.",
        },
    ]
