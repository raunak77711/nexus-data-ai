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
from backend.routers import forecast, health, route, samples, upload, world

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Vite's default port, plus the port it falls back to when the first is taken --
# which happens constantly during development and produces a CORS error that
# looks nothing like "your dev server moved". An explicit list rather than "*"
# because "*" is incompatible with credentialed requests and normalises a habit
# that is wrong the moment this is deployed anywhere real.
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
]

API_PREFIX = "/api"


def create_app() -> FastAPI:
    """Build the application: routers, CORS, and the shared error handlers."""
    app = FastAPI(
        title="AI Data Worlds API",
        version=__version__,
        description=(
            "Upload a CSV, get a profiled, AI-routed, interactive world back -- "
            "with the code that produced every figure."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # chat is added in step 4; see backend/routers/chat.py
    for module in (health, upload, samples, route, world, forecast):
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
