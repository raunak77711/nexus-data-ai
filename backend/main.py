"""FastAPI application: wiring, CORS, and the error handling every route shares.

The app object is built by a factory rather than declared at module scope so the
test suite can construct an isolated instance, and so nothing happens at import
time that a test would have to undo.

ERROR POLICY
------------
No endpoint is allowed to leak a stack trace. Three handlers below cover every
way a request can fail, and all three emit the same one-field shape
``{"detail": "<sentence>"}`` -- so the frontend has exactly one error branch to
write, and a 500 tells the user what to do without telling an attacker what the
server is made of. Tracebacks go to the server log, where they are useful.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import __version__
from backend.routers import (
    analysis,
    assistant,
    chart,
    chat,
    datasets,
    explain,
    forecast,
    health,
    insights,
    preview,
    quality,
    report,
    route,
    samples,
    simulate,
    upload,
    world,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Vite's default port, plus every port it falls back to when that one is taken --
# which happens constantly during development and produces a CORS error that
# looks nothing like "your dev server moved".
#
# Enumerating the fallbacks by hand does not work. Vite walks 5173, 5174, 5175,
# ... for as many stale dev servers as happen to be running, so any fixed list
# is one stray process away from being wrong. The symptom when it is wrong is
# this application's own "NEXUS is not responding" banner -- which is a lie: the
# request reached the server and the server answered, and the browser threw the
# answer away for want of a header. That is an expensive lie to debug, because
# every obvious check (is uvicorn up? does /api/health return 200?) passes.
#
# So: a regex over loopback on ANY port. Not "*", which is incompatible with
# credentialed requests and normalises a habit that is wrong the moment this is
# deployed anywhere real. This widens exactly one dimension -- the port on the
# developer's own machine -- and still refuses every remote origin. Starlette
# fullmatches this against the Origin header, so it cannot be prefix-tricked by
# an origin like http://localhost:5173.evil.com.
ALLOWED_ORIGIN_REGEX = r"http://(localhost|127\.0\.0\.1):\d+"

API_PREFIX = "/api"


def create_app() -> FastAPI:
    """Build the application: routers, CORS, and the shared error handlers."""
    app = FastAPI(
        title="NEXUS Data AI API",
        version=__version__,
        description=(
            "Upload data. Discover intelligence. Profile a CSV, route it to the "
            "right kind of world, surface what is in it in plain language, ask "
            "questions that are answered by real calculations -- with the code "
            "that produced every figure."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=ALLOWED_ORIGIN_REGEX,
        allow_credentials=True,
        # DELETE is here for /api/datasets/{sid}. It is enumerated rather than
        # widened to "*" for the same reason the origin is a regex rather than a
        # wildcard: the list should say what this API actually does.
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    for module in (
        health, upload, samples, route, world, forecast, chat, assistant,
        insights, chart, simulate, preview,
        # The autonomous-analysis half of the product.
        analysis, quality, explain, datasets, report,
    ):
        app.include_router(module.router, prefix=API_PREFIX)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Render a deliberate HTTPException in the shared one-field shape.

        Starlette's default already emits ``{"detail": ...}``, but ``detail`` may
        be any object. Coercing to str here guarantees the frontend never has to
        ask what type it got.
        """
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc.detail)})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """Flatten pydantic's error list into one readable sentence.

        FastAPI's default 422 body is a list of objects with a ``loc`` path -- a
        precise machine format that is useless to put in front of a user. This
        turns it into "freq: input should be 'D', 'W' or 'M'", which can be
        rendered straight into the UI.
        """
        parts = []
        for error in exc.errors():
            location = ".".join(str(p) for p in error.get("loc", []) if p != "body")
            parts.append(f"{location or 'request'}: {error.get('msg', 'invalid')}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": "; ".join(parts) or "Invalid request."},
        )

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        """Last resort. Log the traceback, return a sentence.

        This is the handler that keeps the promise in the module docstring. Note
        that it is a genuine catch-all rather than a bare ``except`` inside a
        route: catching broadly is correct *here*, at the process boundary,
        precisely so that no individual route has to.
        """
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": (
                    "Something went wrong on the server. The error has been "
                    "logged; please try again."
                )
            },
        )

    return app


app = create_app()
