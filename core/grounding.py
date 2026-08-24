"""The check that keeps a language model from putting a false number on screen.

THE PROMISE THIS ENFORCES
-------------------------
No figure displayed anywhere in this application is written by a model. Every
number is computed in Python, by pandas, from the user's own rows.

That promise survives contact with a feature like "explain this chart in plain
English" only if it is enforced rather than requested. A system prompt saying
"do not invent numbers" is a request. What follows is the enforcement: the text
a model produces is scanned for numeric tokens, and every token is checked
against the set of numbers that were actually supplied to it. Text containing
an unrecognised figure is discarded and the deterministic sentence is shown
instead.

The consequence is worth stating plainly, because it is the reason the feature
is safe to ship: the worst outcome of a hallucinating model here is prose that
reads slightly more stiffly than it might have. It cannot be a wrong number,
because a wrong number is by construction one that is not in the allowed set.

WHY THIS IS ITS OWN MODULE. It started inside core.story and was needed
verbatim by core.explain, core.compare and core.report within an hour. Four
copies of a security check is four chances for one of them to be quietly
relaxed by someone fixing a false positive in front of them.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Iterable, Optional, Set

logger = logging.getLogger(__name__)

# Matches any number a model might write: 1,234.5  -12  0.87  42%
NUMBER_PATTERN = re.compile(r"-?\d[\d,]*\.?\d*")

# Integers at or below this are treated as words rather than measurements.
#
# A model writing "the top 3 categories" or "in two of the columns" is counting
# things it can see in the payload, not asserting a statistic. Rejecting those
# would fail nearly every rewrite while preventing nothing: a wrong "three"
# cannot mislead someone about their data the way a wrong "1,240,558" can.
SMALL_INTEGER_CEILING = 12


def number_tokens(text: str) -> Set[str]:
    """Every distinct MEASUREMENT in a string, normalised for comparison.

    Commas and trailing zeros are stripped, so "1,200" and "1200.00" and "1200"
    all collapse to one token. Without that, the check would reject a model for
    reformatting a number it had copied perfectly -- and since formatting a
    thousands separator is the single most likely thing a model does to a
    number, the check would reject essentially everything and the feature would
    silently never use the model at all.

    Digits directly PRECEDED BY A LETTER are not measurements and are skipped.
    That rule was added for a real false positive: a column named `pm25`, which
    a fluent writer expands to "PM2.5", made every explanation of an air-quality
    chart fail the check on the token "2.5" -- a number that is not a claim
    about anything, just part of a name. The same applies to Q1, H2O, COVID19
    and every product code in existence.

    The rule is deliberately one-sided. A letter AFTER the digits ("47kg") does
    not exempt anything, because that shape is a value with a unit attached and
    the value still has to be one we computed.
    """
    tokens: Set[str] = set()
    source = text or ""

    for match in NUMBER_PATTERN.finditer(source):
        start = match.start()
        if start > 0 and source[start - 1].isalpha():
            continue
        cleaned = match.group().replace(",", "").lstrip("+").rstrip(".")
        if not cleaned or cleaned == "-":
            continue
        try:
            value = float(cleaned)
        except ValueError:
            continue
        tokens.add(f"{value:.6g}")
    return tokens


def normalise(values: Iterable[Any]) -> Set[str]:
    """Turn computed values into the token form `is_grounded` compares against.

    Accepts whatever the calling module has to hand -- floats, ints, formatted
    strings like "23.4%" -- because forcing each caller to normalise first is
    how one of them ends up passing raw floats and silently allowing nothing.
    """
    tokens: Set[str] = set()
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            try:
                tokens.add(f"{float(value):.6g}")
            except (ValueError, OverflowError):
                continue
        else:
            tokens |= number_tokens(str(value))
    return tokens


def _magnitudes(allowed: Set[str]) -> Set[str]:
    """The allowed tokens with their signs removed.

    Exists because of a false positive worth explaining, since it is the one
    place this check is deliberately loosened.

    A computed change of -20.0% is written by a fluent writer as "a 20% drop" --
    the minus sign becomes the word "drop", which is better English and the same
    fact. Compared strictly, "20" is not "-20", so the sentence was rejected and
    the feature fell back to template prose on essentially every comparison.
    A check that fires on every correct answer is not protecting anything; it is
    just switching the feature off.

    So magnitude is what must be verifiable, and direction is carried by the
    prompt's rules and by the word the model chose. The residual risk is
    narrow and real: a model could write "rose 20%" where the data fell 20%.
    That is a direction error rather than an invented figure -- the number is
    still one that was computed from the user's rows -- and it is the kind of
    error a reader can catch against the chart beside it, which an invented
    number is not.
    """
    magnitudes: Set[str] = set()
    for token in allowed:
        try:
            magnitudes.add(f"{abs(float(token)):.6g}")
        except ValueError:
            continue
    return magnitudes


def is_grounded(text: str, allowed: Set[str]) -> bool:
    """True if every number in `text` was one we supplied.

    Args:
        text: what the model wrote.
        allowed: token set from `normalise` or `number_tokens`.

    Returns:
        False the moment an unrecognised figure appears. There is no partial
        credit: a paragraph with one invented number in it is a paragraph that
        will be believed, so it is discarded whole.
    """
    tokens = number_tokens(text)
    if not tokens:
        return True

    permitted = set(allowed) | _magnitudes(allowed)

    for token in tokens:
        if token in permitted:
            continue
        try:
            value = float(token)
        except ValueError:
            return False
        if f"{abs(value):.6g}" in permitted:
            continue
        if value.is_integer() and 0 <= value <= SMALL_INTEGER_CEILING:
            continue
        return False
    return True


def strip_fences(text: str) -> str:
    """Remove the ```json fences a model adds despite being told not to."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def parse_json(raw: str) -> Dict[str, Any]:
    """Parse a model reply, returning {} rather than raising on nonsense.

    Every caller of this treats an empty dict as "use the deterministic path",
    so a malformed reply degrades to the no-model experience instead of to a
    500. That is why this returns a value for garbage input rather than raising
    -- there is no caller that wants an exception here.
    """
    try:
        parsed = json.loads(strip_fences(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Model reply was not valid JSON")
        return {}
    return parsed if isinstance(parsed, dict) else {}


def keep_if_grounded(text: Optional[str], allowed: Set[str], what: str = "text") -> str:
    """Return `text` if its numbers check out, otherwise "".

    A convenience for the common shape at every call site -- take the model's
    sentence if it is safe, fall back if it is not -- with the rejection logged
    once, here, so that a deployment quietly falling back on every request is
    visible in the log rather than only in the tone of the copy.
    """
    candidate = (text or "").strip()
    if not candidate:
        return ""
    if is_grounded(candidate, allowed):
        return candidate
    logger.info("Discarded ungrounded %s: %r", what, candidate[:120])
    return ""
