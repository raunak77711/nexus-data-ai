"""The one place this project talks to a language model.

WHY THIS MODULE EXISTS
----------------------
Provider details used to live in two functions -- ``core.router._call_gemini``
and ``core.chat._call_gemini`` -- each of which claimed in its own docstring
that "swapping provider means rewriting this and nothing else". Both were
right individually and wrong together: a swap meant rewriting *two* functions
that had to agree, plus the ``PROVIDER == "gemini"`` guard duplicated at every
call site. The failure that produced this module is exactly that. Setting
``AI_PROVIDER=deepseek`` in .env did not select DeepSeek; it matched none of
the guards and silently turned the model off, so the app fell back to its
rule-based paths and looked, from the outside, like a broken chatbot.

So the boundary is drawn once, here. Everything above it -- routing, chat,
the guide -- asks for a completion and gets back a string. Nothing above it
knows which vendor answered, what the request body looked like, or which
exception types that vendor raises.

WHAT CROSSES THE BOUNDARY
-------------------------
Down:   a system prompt, a payload string, a token cap, a temperature, and
        whether the reply must be JSON.
Up:     the reply text, or ``LLMError``.

That is the whole contract. In particular no DataFrame, no row and no column
of values can cross it, because there is no parameter through which one could
-- the same structural guarantee core.chat relies on, restated at the layer
that actually opens the socket.

ONE EXCEPTION TYPE
------------------
Every provider failure -- auth, quota, timeout, DNS, a 500, a blocked
candidate -- arrives at the caller as ``LLMError``. Callers are written to
degrade rather than crash, and a caller that has to enumerate one vendor's
exception hierarchy to do that is a caller coupled to the vendor. Genuine
programming errors in this module are *not* wrapped: they propagate and get
fixed.

PROVIDERS
---------
"deepseek" (default): the OpenAI-compatible chat-completions API, spoken over
    httpx directly. No SDK, deliberately -- the request is one POST with four
    fields, and httpx is already a dependency named in this project's except
    clauses. Adding the ``openai`` package to send it would be a dependency
    bought for nothing.
"gemini": Google's google-genai SDK, unchanged from the code this module
    replaced, so an existing GOOGLE_API_KEY deployment keeps working.

Any other value turns the model off. That is a supported deployment: the
profiler, the charts, the insights and the forecast are all computed locally
and do not need a model at all.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()


class LLMError(RuntimeError):
    """Any failure to get a completion out of the configured provider."""


# --------------------------------------------------------------- configuration


def _env(name: str, default: str) -> str:
    """Read an env var, treating an EMPTY value as unset.

    os.getenv returns "" for a variable that is set-but-blank, which is not
    what a caller passing a default means. This matters concretely rather than
    theoretically: docker-compose.yml passes every one of these through as
    ``${VAR:-}``, so on a host that has not exported them the container starts
    with them all set to the empty string. Without this, DEEPSEEK_BASE_URL
    would be "" and every request would go to "/chat/completions" -- a failure
    whose symptom (the assistant silently degrades) points nowhere near its
    cause (a shell variable that was never set).
    """
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


DEEPSEEK = "deepseek"
GEMINI = "gemini"

# Default changed from "gemini" to "deepseek" because that is what this
# deployment is configured for. The value is still read from the environment,
# so the default only decides what happens when nothing is set.
PROVIDER = _env("AI_PROVIDER", DEEPSEEK).lower()

# Base URL is overridable because DeepSeek documents two of them (the default
# and a beta host), and because pointing this at any other OpenAI-compatible
# endpoint -- a local llama.cpp server, an internal gateway -- then costs a
# config line rather than a code change.
DEEPSEEK_BASE_URL = _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = _env("DEEPSEEK_MODEL", "deepseek-chat")

# Gemini's model id is a live dependency rather than a free choice: Google
# retires ids server-side, and gemini-2.0-flash already 404s. Kept overridable
# for the same reason it always was.
GEMINI_MODEL = _env("NEXUS_AI_MODEL", "gemini-3.6-flash")

# Two numbers rather than one. Connecting is either going to work in a moment
# or not at all, so a long connect timeout only delays the fallback; reading a
# generated answer legitimately takes seconds. A single combined timeout has to
# be set to the larger of the two, which makes an unreachable host cost the
# read budget before the app gives up on it.
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 60.0

# google-genai is optional: a deployment that only uses DeepSeek should not
# need it installed. The import failure is recorded rather than raised so that
# `status()` can explain the situation instead of the process dying at import.
try:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types as genai_types

    GEMINI_IMPORT_ERROR: Optional[str] = None
    GEMINI_ERRORS: tuple = (genai_errors.APIError,)
except ImportError as _exc:  # pragma: no cover - depends on install state
    genai = None
    genai_types = None
    GEMINI_IMPORT_ERROR = str(_exc)
    GEMINI_ERRORS = ()

# httpx is not optional -- it is how the default provider talks -- but it is
# still imported defensively so a broken install produces an app running on its
# rule-based paths with an explanation, rather than an ImportError at startup.
try:
    import httpx

    HTTPX_IMPORT_ERROR: Optional[str] = None
    HTTP_ERRORS: tuple = (httpx.HTTPError,)
except ImportError as _exc:  # pragma: no cover - depends on install state
    httpx = None
    HTTPX_IMPORT_ERROR = str(_exc)
    HTTP_ERRORS = ()


def api_key(override: Optional[str] = None) -> Optional[str]:
    """The key for the configured provider, or None if it is not set.

    Read on every call rather than captured at import, so a key added to .env
    while a dev server is reloading takes effect without a restart -- and so a
    test can monkeypatch the environment without reimporting the module.

    `override` exists because core.router.route and core.chat.answer both
    document an api_key argument as their per-request key. Threading it through
    here keeps that promise true rather than leaving it as a parameter that is
    accepted and quietly ignored -- which is worse than not having one.
    """
    if override is not None and override.strip():
        return override.strip()
    if PROVIDER == DEEPSEEK:
        key = os.getenv("DEEPSEEK_API_KEY")
    elif PROVIDER == GEMINI:
        key = os.getenv("GOOGLE_API_KEY")
    else:
        return None
    key = (key or "").strip()
    # Placeholder keys are treated as absent. .env.example ships with
    # "your-...-key-here", and a user who copies it without editing should get
    # the honest "no key configured" path rather than a 401 from the vendor
    # rendered as a mysterious outage.
    if not key or key.startswith("your-"):
        return None
    return key


def model_name() -> str:
    """The model id that would be used, for logs and for the health endpoint."""
    return DEEPSEEK_MODEL if PROVIDER == DEEPSEEK else GEMINI_MODEL


def _sdk_missing() -> Optional[str]:
    """The import error blocking the configured provider, if there is one."""
    if PROVIDER == DEEPSEEK:
        return HTTPX_IMPORT_ERROR
    if PROVIDER == GEMINI:
        return GEMINI_IMPORT_ERROR
    return None


def available(override: Optional[str] = None) -> bool:
    """Can a completion actually be requested right now?

    Three things have to hold: the provider is one we implement, its client
    library imported, and a key is configured. Callers use this to choose a
    path *before* spending a round trip, which is why it is a cheap local
    check and not a ping.
    """
    return (
        PROVIDER in (DEEPSEEK, GEMINI)
        and _sdk_missing() is None
        and bool(api_key(override))
    )


def status() -> Dict[str, Any]:
    """A description of the model configuration, fit to send to the frontend.

    Deliberately carries no key material -- only whether one is present. The
    UI uses `available` to decide whether to promise the assistant answers in
    its own words, and `reason` is for the developer looking at /api/health
    wondering why it does not.
    """
    if PROVIDER not in (DEEPSEEK, GEMINI):
        reason = f"AI_PROVIDER={PROVIDER!r} is not a provider this app implements."
    elif _sdk_missing() is not None:
        reason = f"The {PROVIDER} client library is not installed: {_sdk_missing()}"
    elif not api_key():
        env_var = "DEEPSEEK_API_KEY" if PROVIDER == DEEPSEEK else "GOOGLE_API_KEY"
        reason = f"No {env_var} is configured."
    else:
        reason = ""

    return {
        "available": available(),
        "provider": PROVIDER,
        "model": model_name() if PROVIDER in (DEEPSEEK, GEMINI) else "",
        "reason": reason,
    }


# ------------------------------------------------------------------- providers


def _complete_deepseek(
    payload: str,
    system_prompt: str,
    key: str,
    max_tokens: int,
    temperature: float,
    json_mode: bool,
    history: Optional[List[Dict[str, str]]],
) -> str:
    """One POST to an OpenAI-compatible /chat/completions endpoint.

    ``response_format={"type": "json_object"}`` is DeepSeek's constrained
    decoding. It carries a documented requirement -- the word "json" must
    appear in the prompt -- which every prompt in this project satisfies
    because they all end by specifying a JSON shape. It is still only a
    server-side guarantee, so callers keep stripping fences and validating:
    the pipeline does not stake correctness on a vendor honouring a flag.
    """
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    # History, when supplied, sits between the system prompt and the question
    # in the order the conversation happened. Roles are filtered rather than
    # trusted: an unexpected role is a 400 from the vendor, and the caller
    # assembling history from user input should not be able to cause one.
    for turn in history or []:
        role = turn.get("role")
        content = str(turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": payload})

    body: Dict[str, Any] = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    try:
        response = httpx.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT),
        )
    except HTTP_ERRORS as exc:
        # Transport-level: DNS, refused connection, TLS, timeout. The vendor
        # never answered, so there is no status code to report.
        raise LLMError(f"Could not reach {PROVIDER}: {exc}") from exc

    if response.status_code != 200:
        # The body of an error response is the useful part -- "insufficient
        # balance", "invalid api key" -- and it goes to the log, not to the
        # user, who gets the caller's fallback sentence instead.
        detail = response.text[:300].replace("\n", " ")
        raise LLMError(f"{PROVIDER} returned HTTP {response.status_code}: {detail}")

    try:
        choices = response.json()["choices"]
        content = choices[0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LLMError(f"{PROVIDER} returned a body this app cannot read: {exc}") from exc

    return content or ""


def _complete_gemini(
    payload: str,
    system_prompt: str,
    key: str,
    max_tokens: int,
    temperature: float,
    json_mode: bool,
    history: Optional[List[Dict[str, str]]],
) -> str:
    """The google-genai path, preserved so an existing Gemini key still works.

    A client is constructed per call rather than cached at module scope: the
    key is read per call (see api_key()), and a module-level client would
    silently pin the first key it ever saw. Construction is local object setup,
    not a round trip, so the cost is nothing next to the request.
    """
    contents: List[Any] = []
    for turn in history or []:
        role = turn.get("role")
        content = str(turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            # Gemini names the assistant role "model"; the rest of this project
            # speaks OpenAI's vocabulary, so the translation happens here at
            # the boundary rather than in every caller.
            contents.append(
                genai_types.Content(
                    role="model" if role == "assistant" else "user",
                    parts=[genai_types.Part(text=content)],
                )
            )
    contents.append(
        genai_types.Content(role="user", parts=[genai_types.Part(text=payload)])
    )

    config: Dict[str, Any] = {
        "system_instruction": system_prompt,
        "max_output_tokens": max_tokens,
        "temperature": temperature,
        # No tools are supplied, so the SDK's automatic function-calling loop
        # can only add a warning and a wasted branch. Disabling it states the
        # intent: one request, one answer, no agentic loop. "The model cannot
        # execute anything" is a load-bearing claim in this project and should
        # be visible at the request that makes it.
        "automatic_function_calling": genai_types.AutomaticFunctionCallingConfig(
            disable=True
        ),
    }
    if json_mode:
        config["response_mime_type"] = "application/json"

    try:
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=genai_types.GenerateContentConfig(**config),
        )
    except (GEMINI_ERRORS + HTTP_ERRORS) as exc:
        # httpx errors are caught alongside the SDK's own because google-genai
        # raises the raw transport exception for DNS and timeout failures
        # rather than wrapping them.
        raise LLMError(f"Could not reach {PROVIDER}: {exc}") from exc

    # .text is None (not "") when a candidate was blocked or came back with no
    # parts. Returning "" lets the caller's parse fail into its normal fallback
    # instead of raising TypeError from a None.
    return response.text or ""


def complete(
    payload: str,
    system_prompt: str,
    *,
    max_tokens: int = 1000,
    temperature: float = 0.2,
    json_mode: bool = True,
    history: Optional[List[Dict[str, str]]] = None,
    api_key_override: Optional[str] = None,
) -> str:
    """Send one request to the configured provider and return its raw text.

    Args:
        payload: the user-role content. Callers send a JSON document.
        system_prompt: the instructions, sent in the provider's system slot.
        max_tokens: cap on the reply. Every caller sets one; an answer longer
            than its cap is padding, and padding is where invention lives.
        temperature: 0.0 for classification, low-but-not-zero for prose.
        json_mode: ask the provider to constrain decoding to a JSON object.
            Set False when the reply is meant to be read by a person.
        history: prior turns as [{"role": "user"|"assistant", "content": str}],
            for the one caller that holds a conversation.
        api_key_override: use this key instead of the environment's.

    Returns:
        The reply text, unparsed and unvalidated. Validation is the caller's
        job and stays the caller's job: this function does not know what shape
        any particular request expects back.

    Raises:
        LLMError: for every provider-side failure, including "not configured".
    """
    key = api_key(api_key_override)
    if not available(api_key_override) or key is None:
        # Raising rather than returning "" so a caller cannot mistake an
        # unconfigured app for a model that answered with nothing.
        raise LLMError(status()["reason"] or "No language model is configured.")

    provider_fn = _complete_deepseek if PROVIDER == DEEPSEEK else _complete_gemini
    text = provider_fn(
        payload, system_prompt, key, max_tokens, temperature, json_mode, history
    )

    logger.debug("%s/%s answered with %d chars", PROVIDER, model_name(), len(text))
    return text
