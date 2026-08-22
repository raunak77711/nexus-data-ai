"""HTTP layer for AI Data Worlds.

This package is the *only* place that knows about HTTP. Everything it serves is
computed by core/, which has no web-framework imports at all. That split is why
replacing Streamlit with FastAPI + React was a rewrite of the presentation layer
rather than a rewrite of the project: core/ was not touched.

Responsibilities kept here deliberately:
  * transport      -- status codes, CORS, multipart parsing, size limits
  * serialisation  -- turning plotly Figures, DataFrames and numpy scalars into
                      something json.dumps() will accept
  * session lifetime -- holding a parsed DataFrame between requests

Responsibilities explicitly NOT here: profiling, routing, world building,
forecasting, chat grounding. Those live in core/ so they stay testable without a
server and reusable without a browser.
"""

__version__ = "1.0.0"
