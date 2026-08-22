"""Machinery that makes the displayed code the code that actually ran.

THE PROBLEM this solves: the project's differentiator is that every figure ships
with the source that produced it. The obvious implementation -- plot with real
calls, then hand-write a matching string -- has a fatal flaw: the two drift.
Someone tweaks a colour or an aggregation in the real path, forgets the string,
and the glass box starts lying. A glass box that lies is worse than no glass box,
because the user now has a specific false belief instead of a vague one.

THE FIX: invert the relationship. The code string is not a description of what
happened; it *is* what happened. build() renders a snippet, execute() runs that
exact text, and the returned figure is whatever the snippet produced. Divergence
is not unlikely, it is impossible -- there is only one artefact.

WHY exec() is acceptable here, given it is normally a red flag: the executed text
is never user input. Templates are authored in this repo, and every value spliced
into one goes through repr(), so an uploaded column named
'"); import os; os.system("rm -rf /' becomes a quoted Python string literal and
cannot escape into code position. The uploaded data reaches exec only as the
DataFrame object bound in the namespace, never as source text. Injection would
require an attacker to edit the templates -- at which point they already have the
repo.
"""

from __future__ import annotations

import textwrap
from string import Template
from typing import Any, Dict, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


class Raw(str):
    """A value to splice into a template verbatim instead of via repr().

    Needed for the occasional parameter that is a Python expression rather than
    a literal -- a list built at runtime, a already-formatted call. Kept as an
    explicit opt-in type so that repr() stays the default and forgetting to
    think about quoting fails safe.
    """


# Every snippet is executed with exactly these names pre-bound. Deliberately the
# same set a user would have in a notebook after `import pandas as pd` etc., so
# the snippet that runs here is the snippet that runs there. Snippets also carry
# their own import lines for that reason -- redundant under exec, essential when
# pasted.
def _namespace(df: pd.DataFrame) -> Dict[str, Any]:
    return {"df": df, "pd": pd, "px": px, "go": go}


def render(template: str, **params: Any) -> str:
    """Fill a $-placeholder code template and return runnable Python source.

    WHY string.Template rather than str.format or an f-string: generated code is
    full of literal braces -- plotly's dict arguments, dict comprehensions, set
    literals. With str.format every one of those would need doubling, which makes
    the templates unreadable and the doubling itself a source of bugs. Template's
    $name placeholders do not collide with Python syntax.

    Non-Raw values are inserted with repr(), which is what makes the executed
    source injection-proof (see module docstring) and also produces correct
    quoting for column names containing spaces or apostrophes.
    """
    substitutions = {
        key: str(value) if isinstance(value, Raw) else repr(value)
        for key, value in params.items()
    }
    return Template(textwrap.dedent(template).strip()).substitute(substitutions)


def execute(code: str, df: pd.DataFrame, want: str = "fig") -> go.Figure:
    """Run a rendered snippet and return the figure it bound to `want`.

    Args:
        code: source produced by render().
        df: the DataFrame the snippet expects to find already loaded.
        want: the variable the snippet assigns its figure to.

    Raises:
        RuntimeError: if the snippet ran but produced no Figure under `want`.
            Raised rather than returned because it means a template in this repo
            is broken -- a programming error to fix, not a data condition to
            degrade around. World builders catch data problems before they ever
            reach here.

    Exceptions from the snippet itself are left to propagate unchanged: a
    pandas or plotly traceback pointing at the real failing line is far more
    useful to whoever has to fix the template than a wrapped message would be.
    """
    namespace = _namespace(df)
    exec(code, namespace)  # noqa: S102 - see module docstring for why this is safe

    figure = namespace.get(want)
    if not isinstance(figure, go.Figure):
        raise RuntimeError(
            f"snippet did not bind {want!r} to a plotly Figure "
            f"(got {type(figure).__name__})"
        )
    return figure


def result(
    figures: Optional[Dict[str, go.Figure]] = None,
    stats: Optional[Dict[str, Any]] = None,
    code: Optional[Dict[str, str]] = None,
    warnings: Optional[list] = None,
    status: str = "ok",
    message: str = "",
) -> Dict[str, Any]:
    """Build the dict every world returns, so the renderer has one shape to read.

    figures/stats/code are the contract proper. warnings carries the things the
    builder had to do to the data to make it plottable (rows dropped, dates that
    would not parse) -- the user is entitled to know their 5,000-row upload
    became 300 usable rows, and burying that in a log they will never read would
    be a quiet lie about how trustworthy the chart is.

    status is "ok" or a machine-readable reason the world could not be built,
    matching core.ml.forecast so the presentation layer branches the same way
    everywhere.
    """
    return {
        "figures": figures or {},
        "stats": stats or {},
        "code": code or {},
        "warnings": warnings or [],
        "status": status,
        "message": message,
    }
