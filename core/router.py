"""Archetype routing: decide which world to build for a profiled dataset.

The LLM is used as a *classifier over a summary*, never as a code generator and
never as a consumer of the raw data. That choice is deliberate:

* Privacy/cost -- only a compact schema summary leaves the machine, not the
  user's rows, and the request stays at a few hundred tokens.
* Determinism -- the LLM picks from three fixed archetypes and from column
  names that already exist. Everything it returns is validated against the
  profile before use, so a hallucinated column name degrades to a rule-based
  pick rather than crashing a downstream chart.
* Availability -- classification is genuinely doable with rules alone. The LLM
  adds semantic judgement ("revenue" is a better target than "order_id"), so
  when it is unavailable the app must still work, just less cleverly.

Provider: whichever one core.llm is configured for -- DeepSeek by default,
Gemini when AI_PROVIDER says so. This module does not know which. It hands
core.llm a summary and a system prompt and gets back a string, which is the
only shape of coupling to a vendor that survives the vendor changing.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from core import llm

logger = logging.getLogger(__name__)

MAX_TOKENS = 1000

TIMESERIES = "timeseries"
GEO = "geo"
TABULAR = "tabular"
ARCHETYPES = (TIMESERIES, GEO, TABULAR)

# Numeric columns whose names look like identifiers make terrible chart targets:
# plotting a monotonically increasing key tells you nothing. Used only by the
# rule-based path -- the LLM is expected to work this out from the names.
ID_PATTERN = re.compile(r"(^id$|_id$|^id_|^index$|_key$|_no$|number$)", re.IGNORECASE)

SYSTEM_PROMPT = """You classify tabular datasets so a visualisation app can \
build the right interactive world.

You will receive a JSON summary of a dataset's schema (never the rows themselves).
Choose exactly one archetype:

- "timeseries": the data records how a measure changes over time. Requires a
  genuine datetime column and at least one numeric measure.
- "geo": the data records where things are. Requires a latitude AND a longitude
  column.
- "tabular": everything else -- cross-sectional data compared across categories.

Then pick the columns that world needs, using only names present in the summary:
- time_col: the datetime column to plot along the x-axis (null if none)
- entity_col: the categorical column that best splits the data into groups (null if none)
- target_col: the numeric column that is the interesting measure. Prefer a real
  measure (revenue, temperature, score) over an identifier or a row counter.
- lat_col / lon_col: the coordinate columns (null unless archetype is "geo")

Also give "reasoning": one or two sentences a non-technical user could read,
explaining why this archetype and this target column.

Respond with raw JSON only. No markdown code fences, no preamble, no trailing
commentary. Exactly this shape:
{"archetype": "...", "time_col": "...", "entity_col": "...", "target_col": "...", \
"lat_col": null, "lon_col": null, "reasoning": "..."}"""


def compact_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Shrink a full profile to just what the classifier needs.

    WHY not send the whole profile: it carries per-column min/max/mean and ten
    top values per categorical, which on a wide dataset is thousands of tokens
    of noise for a three-way classification. Sending less is cheaper, faster,
    and measurably less distracting for the model. Three sample values per
    categorical are kept because they help distinguish a real grouping column
    from a status flag.
    """
    columns: List[Dict[str, Any]] = []
    for col in profile.get("columns", []):
        entry: Dict[str, Any] = {
            "name": col["name"],
            "type": col["semantic_type"],
            "n_unique": col["n_unique"],
            "null_pct": col["null_pct"],
        }
        if col.get("top_values"):
            entry["examples"] = [v["value"] for v in col["top_values"][:3]]
        columns.append(entry)

    return {
        "n_rows": profile.get("n_rows"),
        "n_cols": profile.get("n_cols"),
        "has_datetime": profile.get("has_datetime"),
        "has_geo": profile.get("has_geo"),
        "n_numeric": profile.get("n_numeric"),
        "columns": columns,
    }


def strip_code_fences(text: str) -> str:
    """Remove markdown fences an LLM may add despite being told not to.

    Defensive rather than optimistic: the system prompt asks for raw JSON, but
    a single stray fence would otherwise turn a good classification into a
    fallback. Cheap insurance against a well-known failure mode -- and Gemini
    in particular fences JSON output unless firmly told not to.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _columns_by_type(profile: Dict[str, Any]) -> Dict[str, List[str]]:
    """Map semantic_type -> column names, preserving original column order."""
    grouped: Dict[str, List[str]] = {}
    for col in profile.get("columns", []):
        grouped.setdefault(col["semantic_type"], []).append(col["name"])
    return grouped


def _pick_target(profile: Dict[str, Any]) -> Optional[str]:
    """Best numeric column to measure, skipping identifier-looking names."""
    numeric = _columns_by_type(profile).get("numeric", [])
    for name in numeric:
        if not ID_PATTERN.search(name):
            return name
    return numeric[0] if numeric else None


def rule_based_route(profile: Dict[str, Any], why: str) -> Dict[str, Any]:
    """Deterministic routing used whenever the LLM is unavailable or unusable.

    Precedence is geo -> timeseries -> tabular. Geo wins over time because a
    dataset with coordinates *and* timestamps (sensor readings, deliveries) is
    almost always most usefully seen on a map first, with time as a filter --
    and the geo world accepts a time filter, whereas the timeseries world has
    nowhere to put coordinates.
    """
    grouped = _columns_by_type(profile)
    time_col = grouped.get("datetime", [None])[0]
    entity_col = grouped.get("categorical", [None])[0]
    lat_col = grouped.get("geo_lat", [None])[0]
    lon_col = grouped.get("geo_lon", [None])[0]
    target_col = _pick_target(profile)

    if profile.get("has_geo"):
        archetype = GEO
        rule = "latitude and longitude columns were both detected"
    elif profile.get("has_datetime") and profile.get("n_numeric", 0) >= 1:
        archetype = TIMESERIES
        rule = "a datetime column and at least one numeric measure were detected"
    else:
        archetype = TABULAR
        rule = "no usable time or coordinate columns were detected"

    return {
        "archetype": archetype,
        "time_col": time_col,
        "entity_col": entity_col,
        "target_col": target_col,
        "lat_col": lat_col if archetype == GEO else None,
        "lon_col": lon_col if archetype == GEO else None,
        "reasoning": f"Chosen by built-in rules because {rule}. ({why})",
        "source": "fallback",
    }


def _validate(candidate: Dict[str, Any], profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Check an LLM answer against the profile; return None if unsalvageable.

    Trust-but-verify. The model proposes, the profile disposes: a column name
    is accepted only if it exists AND carries a semantic type the world builder
    can actually use. A wrong-but-plausible name (a hallucinated "date" column)
    is silently replaced by the rule-based pick rather than propagated into a
    KeyError three layers down.
    """
    archetype = candidate.get("archetype")
    if archetype not in ARCHETYPES:
        logger.warning("LLM returned unknown archetype %r", archetype)
        return None

    types = {c["name"]: c["semantic_type"] for c in profile.get("columns", [])}

    def keep(key: str, allowed: tuple) -> Optional[str]:
        name = candidate.get(key)
        if name is None:
            return None
        if types.get(name) in allowed:
            return name
        logger.warning("LLM proposed invalid %s=%r; falling back for that field", key, name)
        return None

    rules = rule_based_route(profile, why="repairing fields")
    resolved = {
        "archetype": archetype,
        "time_col": keep("time_col", ("datetime",)) or rules["time_col"],
        "entity_col": keep("entity_col", ("categorical",)) or rules["entity_col"],
        # A category code is a legitimate target for a count-style chart, so
        # numeric and categorical are both accepted here.
        "target_col": keep("target_col", ("numeric", "categorical")) or rules["target_col"],
        "lat_col": keep("lat_col", ("geo_lat",)),
        "lon_col": keep("lon_col", ("geo_lon",)),
        "reasoning": str(candidate.get("reasoning") or "").strip() or "No reasoning returned.",
        "source": "llm",
    }

    # An archetype whose required columns are missing is worse than the honest
    # fallback -- reject it and let the rules decide.
    if resolved["archetype"] == GEO and not (resolved["lat_col"] and resolved["lon_col"]):
        grouped = _columns_by_type(profile)
        resolved["lat_col"] = grouped.get("geo_lat", [None])[0]
        resolved["lon_col"] = grouped.get("geo_lon", [None])[0]
        if not (resolved["lat_col"] and resolved["lon_col"]):
            logger.warning("LLM chose 'geo' but no coordinate pair exists")
            return None
    if resolved["archetype"] == TIMESERIES and not resolved["time_col"]:
        logger.warning("LLM chose 'timeseries' but no datetime column exists")
        return None

    return resolved


def _call_model(summary: str, api_key: Optional[str] = None) -> str:
    """Send the schema summary to the configured model, return its raw text.

    A one-line wrapper over core.llm.complete, kept as a named function for two
    reasons. It is the seam scripts/test_router.py replaces to exercise the
    failure paths without a network, and it is where this module's request
    settings live: temperature 0.0 because this is classification and must be
    repeatable, and JSON mode because the reply is contractually an object.

    The caller still strips fences and still validates every field against the
    profile. A server-side JSON guarantee is worth having and is not worth
    staking the pipeline on.
    """
    return llm.complete(
        summary,
        SYSTEM_PROMPT,
        max_tokens=MAX_TOKENS,
        temperature=0.0,
        json_mode=True,
        api_key_override=api_key,
    )


def route(profile: Dict[str, Any], api_key: Optional[str] = None) -> Dict[str, Any]:
    """Classify a profiled dataset into an archetype and pick its key columns.

    Args:
        profile: output of core.profiler.profile_dataframe.
        api_key: accepted for the callers that pass one, and for a future
            server holding keys per request rather than per process. The key
            actually used is resolved by core.llm from the environment.

    Returns:
        A dict with archetype, time_col, entity_col, target_col, lat_col,
        lon_col, reasoning and source ("llm" or "fallback").

    This function is contractually non-raising. Routing sits between upload and
    every visualisation, so an API outage, a missing key or a malformed
    response must degrade the app rather than end the session.
    """
    if not llm.available(api_key):
        # One check where there used to be three. core.llm.status() knows why
        # -- unimplemented provider, missing client library, absent key -- and
        # says so in a sentence, which is both what the log wants and what a
        # user reading "how did NEXUS decide this" wants.
        reason = llm.status()["reason"]
        logger.info("No language model available; using rule-based routing: %s", reason)
        return rule_based_route(profile, why="no AI model is configured here")

    try:
        raw = _call_model(json.dumps(compact_profile(profile)), api_key)
        candidate = json.loads(strip_code_fences(raw))
        if not isinstance(candidate, dict):
            raise ValueError(f"expected a JSON object, got {type(candidate).__name__}")

        validated = _validate(candidate, profile)
        if validated is None:
            return rule_based_route(
                profile, why="the AI named a column this dataset does not have"
            )

        logger.info("Routed by LLM: %s", validated["archetype"])
        return validated

    except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as exc:
        # The model replied, but not with the JSON contract. AttributeError
        # covers a blocked response whose .text accessor raises.
        logger.warning("Could not parse LLM routing response: %s", exc)
        return rule_based_route(profile, why="the AI's answer could not be read")
    except llm.LLMError as exc:
        # Transport, auth, quota, or a safety filter -- every provider-side
        # failure arrives as this one type, which is the point of core.llm.
        logger.warning("Routing model call failed: %s", exc)
        return rule_based_route(profile, why="the AI service could not be reached")
