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
class AssistantStatus(BaseModel):
    """Whether a language model is reachable, and which one.

    On the health response rather than an endpoint of its own because the
    frontend already polls health to decide whether the server is up, and "is
    the server up" and "can it answer in its own words" are questions asked at
    the same moment by the same code. Carries no key material -- only whether
    one is present.
    """

    available: bool
    provider: str = ""
    model: str = ""
    reason: str = Field(
        default="",
        description="Why the assistant is not available, when it is not. For the "
        "developer reading /api/health, not for the user.",
    )


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    sessions: int = Field(description="Live sessions held by this process.")
    assistant: AssistantStatus


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
        description="False when no answer could be produced at all, so the UI can "
        "say so rather than pretending the reply is an answer.",
    )
    answered_by: Literal["computed", "model", "summaries", "unavailable"] = Field(
        default="summaries",
        description="Where the reply came from. 'computed' means pandas produced "
        "the numbers and the wording is templated; 'model' means pandas produced "
        "the numbers and the model wrote the sentence; 'summaries' means it was "
        "answered from cached statistics with no fresh calculation. Shown to the "
        "user, because how an answer was reached is part of the answer.",
    )
    tool: Optional[str] = Field(
        default=None, description="Which calculation ran, if one did."
    )
    action: Optional[Dict[str, Any]] = Field(
        default=None,
        description="A chart spec the client may POST to /chart/{sid} to show the "
        "answer. Pre-validated against the dataset.",
    )
    table: Optional[Dict[str, Any]] = Field(
        default=None, description="Tabular result rows, when the answer is a list."
    )
    data: Optional[Dict[str, Any]] = Field(
        default=None, description="The raw computed numbers behind the reply."
    )
    followups: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Suggested next questions, each a different kind of move "
        "away from what was just answered. Every one is checked against the "
        "dataset's real columns first, since a suggestion the assistant then "
        "cannot answer reads as a broken product rather than a bad suggestion.",
    )


# ------------------------------------------------------------------ assistant
class AssistantRequest(BaseModel):
    """One message from the chat bubble.

    `session_id` is optional and that is the whole point of this endpoint: the
    bubble is on the home page too, where nothing has been uploaded yet. An
    unknown or expired id is not an error here either -- it degrades to help
    about the app, which is what somebody with a timed-out upload needs.
    """

    message: str = Field(min_length=1, max_length=4000)
    history: List[ChatMessage] = Field(default_factory=list, max_length=40)
    session_id: Optional[str] = Field(
        default=None,
        description="The open dataset, if there is one. Absent on the home page.",
    )


class AssistantResponse(BaseModel):
    """One reply, plus enough for the UI to be honest about where it came from."""

    reply: str
    available: bool = True
    answered_by: Literal[
        "computed", "model", "summaries", "unavailable", "guide", "guide_offline"
    ] = Field(
        default="guide",
        description="Where the reply came from. The first four are core.chat's "
        "and mean a calculation over real rows was involved; 'guide' and "
        "'guide_offline' are help about the app, the latter from the built-in "
        "FAQ when no model is reachable.",
    )
    about: Literal["data", "app"] = Field(
        default="app",
        description="Which assistant answered. The UI uses this to decide "
        "whether to show the 'worked out from your rows' note.",
    )
    action: Optional[Dict[str, Any]] = Field(
        default=None, description="A chart spec the client may render, if any."
    )
    table: Optional[Dict[str, Any]] = Field(
        default=None, description="Tabular result rows, when the answer is a list."
    )


# ------------------------------------------------------------------- insights
class Insight(BaseModel):
    """One finding, written for a reader with no statistics background.

    `evidence` is Dict[str, Any] for the same reason `stats` is: an anomaly's
    evidence and a trend's evidence share no fields, and modelling their union
    would mean every field optional and none meaningful. What IS policed is the
    envelope -- a card without a headline, or with an action the UI cannot
    execute, must never reach the client.
    """

    id: str
    kind: Literal["trend", "relationship", "anomaly", "segment", "quality", "forecast"]
    tone: Literal["neutral", "positive", "warning"] = "neutral"
    headline: str
    detail: str
    why: str
    evidence: Dict[str, Any] = Field(default_factory=dict)
    action: Optional[Dict[str, Any]] = Field(
        default=None,
        description="A chart spec the client can POST to /chart/{sid} to see "
        "this finding. Already validated against the dataset, so a rendered "
        "button is a button that works.",
    )


class InsightCounts(BaseModel):
    """How many of each kind of finding there are.

    Counts everything found, not everything shown: the card list is truncated
    for readability and these are not, so the overview stays truthful about the
    dataset even when the insights screen is showing the best twelve.
    """

    trends: int = 0
    relationships: int = 0
    anomalies: int = 0
    predictions: int = 0
    standouts: int = 0
    data_issues: int = 0


class DataShape(BaseModel):
    """The plain counts the overview screen leads with."""

    n_rows: int
    n_cols: int
    n_datetime: int = 0
    n_numeric: int = 0
    n_categorical: int = 0
    n_geo: int = 0
    n_text: int = 0


class InsightsResponse(BaseModel):
    summary: str
    counts: InsightCounts
    shape: DataShape
    insights: List[Insight]


# --------------------------------------------------------------------- chart
class ChartRequest(BaseModel):
    """A structured visualisation command.

    Deliberately NOT free-form. Every field is either an enum or a column name
    that core.charts resolves against the frame, which is what makes this
    endpoint safe to expose to something an LLM produced -- see core/charts.py.
    """

    chart: Literal["line", "bar", "scatter", "histogram", "box", "map"]
    x: Optional[str] = None
    y: Optional[str] = None
    lat: Optional[str] = None
    lon: Optional[str] = None
    agg: Optional[Literal["sum", "mean", "median", "count", "min", "max"]] = None
    freq: Optional[Literal["D", "W", "M"]] = None
    limit: Optional[int] = Field(default=None, ge=1, le=20)
    ascending: bool = False
    title: Optional[str] = Field(default=None, max_length=120)


class ChartResponse(BaseModel):
    figure_json: str = Field(
        description="plotly fig.to_json() output. A string, not an object, so "
        "the payload is exactly what plotly.js consumes."
    )
    code: str = Field(
        description="The Python that produced this figure -- the same text that "
        "was executed, not a description of it."
    )
    title: str
    spec: Dict[str, Any]
    warnings: List[str] = Field(default_factory=list)


# ------------------------------------------------------------------ simulate
class SimulateRequest(BaseModel):
    pct_change: float = Field(
        ge=-90, le=200, description="How far to move the driver, in percent."
    )
    target: Optional[str] = Field(
        default=None, description="The measure to project. Defaults to the routed one."
    )
    driver: Optional[str] = Field(
        default=None,
        description="The measure to move. Defaults to the target itself, which "
        "makes the projection straight arithmetic rather than an estimate.",
    )


class SimulateOptions(BaseModel):
    available: bool
    columns: List[str]
    default_target: Optional[str] = None
    suggested_driver: Optional[str] = None
    min_pct: float
    max_pct: float


class SimulateResponse(BaseModel):
    status: Literal["ok", "unsupported"]
    message: str
    caveats: List[str] = Field(default_factory=list)
    basis: Optional[Literal["direct", "relationship"]] = None
    target: Optional[str] = None
    driver: Optional[str] = None
    pct_change: Optional[float] = None
    baseline: Optional[Dict[str, float]] = None
    projected: Optional[Dict[str, float]] = None
    delta: Optional[Dict[str, float]] = None
    rows_used: Optional[int] = None
    confidence: Optional[Dict[str, Any]] = None


# ------------------------------------------------------------------- preview
class PreviewResponse(BaseModel):
    """A window onto the actual rows, for the Explore screen.

    Capped server-side rather than trusted to a client-supplied limit, because
    the whole frame is in memory and serialising a million rows to JSON would
    take the process down for everyone holding a session.
    """

    columns: List[str]
    rows: List[List[Any]]
    n_rows_total: int
    n_rows_returned: int
    truncated: bool
    profile: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="The per-column profile for the rows being returned. Sent "
        "with the preview rather than fetched separately because the two must "
        "describe the SAME frame: after a clean the columns and their types "
        "change, and a profile fetched from anywhere else would describe the "
        "uploaded file while the rows beside it came from the cleaned one.",
    )


# ------------------------------------------------------- autonomous analysis
#
# The models below share a convention worth stating once: their list items are
# typed Dict[str, Any] rather than modelled field by field. That is the same
# judgement the module docstring makes about `stats` and `profile`, applied to
# richer payloads -- an insight card, a health issue and a dashboard panel each
# carry an `evidence` dict whose keys depend on which analysis pass produced it,
# and modelling that as a union would encode core/'s internals into the HTTP
# layer and force a change here every time a pass learns a new statistic.
#
# What IS policed is the envelope: the top-level fields the frontend switches
# on. Those are named and typed, so a refactor that stops producing `score` or
# `panels` fails loudly on the server rather than rendering as undefined.


class HealthResponseBody(BaseModel):
    """A dataset's quality report -- the Data Health screen."""

    score: Optional[float] = Field(
        default=None,
        description="0-100, or null when the checks could not be run.",
    )
    grade: str
    verdict: str
    headline: str
    issues: List[Dict[str, Any]]
    counts: Dict[str, int]
    n_fixable: int
    checks_run: int
    sampled: bool = Field(
        default=False,
        description="True when the checks ran on a sample of a very large file.",
    )
    n_rows: int
    n_cols: int
    clean: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Checks that found nothing, so a short issue list is legible.",
    )


class CleanRequest(BaseModel):
    """Which repairs the user approved.

    `issue_ids` of None means every fixable issue -- the "fix everything"
    button. An EMPTY LIST means none, which is a different request and must not
    be conflated with None; that distinction is why this is Optional rather than
    defaulting to an empty list.
    """

    issue_ids: Optional[List[str]] = None


class CleanPlanResponse(BaseModel):
    """What would be changed, before anything is."""

    steps: List[Dict[str, Any]]
    n_steps: int
    note: str


class CleanResponse(BaseModel):
    """What was actually changed, after the fact."""

    summary: str
    log: List[Dict[str, Any]]
    applied: List[str]
    rows_before: int
    rows_after: int
    cols_before: int
    cols_after: int
    cells_changed: int
    health: Dict[str, Any] = Field(
        description="The re-run health report, so the score updates immediately."
    )
    is_cleaned: bool


class BriefingResponse(BaseModel):
    """The AI briefing: what this dataset is and what matters in it."""

    headline: str
    summary: str
    points: List[Dict[str, Any]]
    source: Literal["llm", "rules"]
    n_considered: int


class DashboardResponse(BaseModel):
    """The auto-composed dashboard: chosen charts and headline numbers."""

    kpis: List[Dict[str, Any]]
    panels: List[Dict[str, Any]]
    note: str
    n_considered: int
    time_col: Optional[str] = None
    measures: List[str] = Field(default_factory=list)


class RecommendationsResponse(BaseModel):
    """Suggested next steps, always carrying their own disclaimer.

    `disclaimer` is part of the payload rather than frontend copy on purpose: a
    caller rendering these somewhere else must not be able to present a model's
    inference as a measurement by forgetting to add the label.
    """

    recommendations: List[Dict[str, Any]]
    source: Literal["llm", "rules"]
    disclaimer: str


class QuestionsResponse(BaseModel):
    """Questions this dataset can answer, for a user who does not have any."""

    questions: List[Dict[str, Any]]
    source: Literal["llm", "rules"]


class TimelineResponse(BaseModel):
    """What the server did to this dataset, and when."""

    events: List[Dict[str, Any]]
    n_events: int


class ExplainRequest(BaseModel):
    """Ask for one thing on screen to be explained.

    `target` names what to explain and `ref` identifies which one -- an insight
    id, a health issue id, a dashboard panel id. The pair is used instead of a
    free-form payload so the server explains something it computed rather than
    something the client described, which is what keeps the explanation
    grounded in real numbers.
    """

    target: Literal["insight", "health_issue", "chart", "kpi"]
    ref: str
    level: Literal["simple", "technical"] = "simple"


class ExplainResponse(BaseModel):
    """One explanation, at one level of detail."""

    text: str
    level: Literal["simple", "technical"]
    source: Literal["llm", "rules"]
    title: str


class DatasetSummary(BaseModel):
    """One card on the My Datasets screen."""

    id: str
    filename: str
    n_rows: int
    n_cols: int
    created_at: str
    last_seen: str
    health_score: Optional[float] = None
    health_grade: Optional[str] = None
    archetype: Optional[str] = None
    is_cleaned: bool = False
    analysed: bool = False
    n_events: int = 0
    loaded: bool = Field(
        default=False,
        description="Whether the frame is currently parsed in memory.",
    )


class CompareRequest(BaseModel):
    """Compare the current dataset against another stored one."""

    other_id: str


class CompareResponse(BaseModel):
    """What changed between two datasets."""

    comparable: bool = Field(
        description="False when the two files share no columns at all."
    )
    changes: List[Dict[str, Any]]
    columns: Dict[str, Any]
    shape: Dict[str, Any]
    summary: str
    n_changes: int
    conflicts: Dict[str, Any] = Field(default_factory=dict)
    source: Literal["llm", "rules"] = "rules"


class ReportResponse(BaseModel):
    """A full analysis report, structured for the renderer to lay out."""

    title: str
    subtitle: str
    dataset_name: str
    filename: str
    generated_at: str
    generated_display: str
    sections: List[Dict[str, Any]]
    meta: Dict[str, Any]


class FollowUpsResponse(BaseModel):
    """What to ask next, after an answer."""

    followups: List[Dict[str, Any]]


# ---------------------------------------------------------------------- error
class ErrorResponse(BaseModel):
    """The single error shape every failure path returns.

    One shape means the frontend has exactly one error branch to write, and
    ``detail`` is always a string -- FastAPI's default for a validation error is
    a list of objects, which would otherwise force the client to type-switch on
    the body.
    """

    detail: str
