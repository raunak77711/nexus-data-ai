"""Pydantic request and response models -- the typed contract between the two halves.

WHY typed models instead of returning bare dicts, which FastAPI would happily
serialise anyway:

  * The response model IS the API documentation. FastAPI generates the OpenAPI
    schema from these classes, so /docs stays correct by construction instead of
    by somebody remembering to update a wiki.
  * A field the frontend depends on cannot silently disappear. If a refactor in
    core/ stops producing ``beats_baseline``, the response fails validation on
    the server -- loudly, in a log, at the point of the mistake -- rather than
    arriving in React as ``undefined`` and rendering an empty box.
  * Request models give 422 for free, with a body that names the offending
    field. Hand-rolled validation would be both more code and less precise.

WHY several fields are typed ``Dict[str, Any]`` rather than fully modelled:
``stats`` genuinely has a different shape per archetype (the timeseries world
returns a trend direction, the geo world returns a bounding box), and ``profile``
has per-column keys that depend on the column's semantic type. Modelling those
as a union of three shapes would encode core/'s internals into the HTTP layer
and force a change here every time a world learns a new statistic. The
boundary that is actually worth policing is the *envelope*, and the envelope is
strict.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Archetype = Literal["timeseries", "geo", "tabular"]


# --------------------------------------------------------------------- health
class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    sessions: int = Field(description="Live sessions held by this process.")


# --------------------------------------------------------------------- upload
class UploadResponse(BaseModel):
    session_id: str
    filename: str
    n_rows: int
    n_cols: int
    profile: Dict[str, Any] = Field(
        description="core.profiler.profile_dataframe output, unmodified."
    )


class SampleInfo(BaseModel):
    """One bundled example file, offered as a one-click loader on the empty state."""

    key: str
    filename: str
    label: str
    description: str
    n_bytes: int


# ---------------------------------------------------------------------- route
class RouteResponse(BaseModel):
    """core.router.route output, field for field.

    Modelled fully -- unlike ``stats`` -- because this shape is fixed, small, and
    is exactly what the routing banner in the UI reads. ``source`` in particular
    must never go missing: it is what tells the user whether the AI or the
    fallback rules made the decision.
    """

    archetype: Archetype
    time_col: Optional[str] = None
    entity_col: Optional[str] = None
    target_col: Optional[str] = None
    lat_col: Optional[str] = None
    lon_col: Optional[str] = None
    reasoning: str
    source: Literal["llm", "fallback"]


# ---------------------------------------------------------------------- world
class WorldParams(BaseModel):
    """Controls for a world build. Every field optional; each world reads its own.

    Bounds are declared here rather than checked inside the endpoint so that an
    out-of-range value is rejected as a 422 naming the field, before any pandas
    work happens. core/'s builders raise ValueError for the same conditions --
    that is their contract with any caller -- but a ValueError surfacing as a 500
    would be the wrong status code for what is plainly a bad request.
    """

    freq: Optional[Literal["D", "W", "M"]] = None
    rolling_window: Optional[int] = Field(default=None, ge=1, le=365)
    time_filter: Optional[List[str]] = Field(
        default=None,
        min_length=2,
        max_length=2,
        description="Inclusive [start, end] pair of ISO date strings, geo world only.",
    )


class WorldRequest(BaseModel):
    archetype: Archetype
    params: WorldParams = Field(default_factory=WorldParams)


class WorldResponse(BaseModel):
    figures_json: Dict[str, str] = Field(
        description="{figure_name: plotly fig.to_json() string}. A string, not an "
        "object, so the payload is exactly what plotly.js consumes."
    )
    stats: Dict[str, Any]
    code: Dict[str, str]
    warnings: List[str]
    status: str
    message: str
    archetype: Archetype


# ------------------------------------------------------------------- forecast
class ForecastRequest(BaseModel):
    horizon: int = Field(default=7, ge=1, le=365, description="Days to project forward.")


class ForecastResponse(BaseModel):
    status: str
    message: str
    warnings: List[str]
    metrics: Dict[str, Any]
    beats_baseline: bool
    verdict: str
    predictions: List[Dict[str, Any]] = Field(
        description="Scored test window: [{date, actual, predicted}, ...]"
    )
    future: List[Dict[str, Any]] = Field(
        description="Projection past the data: [{date, predicted}, ...]"
    )
    feature_importances: Dict[str, Any]
    code: str


# ----------------------------------------------------------------------- chat
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: List[ChatMessage] = Field(default_factory=list, max_length=40)


class ChatResponse(BaseModel):
    reply: str
    grounded_on: List[str] = Field(
        description="Names of the context blocks the answer was allowed to use, "
        "shown under the reply so the user can see what it was based on."
    )
    available: bool = Field(
        default=True,
        description="False when the LLM could not be reached, so the UI can say "
        "chat is unavailable rather than pretending the reply is an answer.",
    )


# ---------------------------------------------------------------------- error
class ErrorResponse(BaseModel):
    """The single error shape every failure path returns.

    One shape means the frontend has exactly one error branch to write, and
    ``detail`` is always a string -- FastAPI's default for a validation error is
    a list of objects, which would otherwise force the client to type-switch on
    the body.
    """

    detail: str
