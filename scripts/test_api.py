"""Drive the FastAPI layer end to end for each sample CSV, through TestClient.

This is not a retest of core/ -- scripts/test_profiler.py, test_router.py,
test_worlds.py and test_ml.py already cover the logic. What is tested here is
everything the HTTP boundary added:

  * the endpoint contract (status codes, response shapes, typed fields)
  * SERIALISATION. Every payload is round-tripped through json.dumps() with the
    default encoder, which is the exact check that catches a numpy scalar
    escaping from pandas. It is the most likely silent failure in the whole
    port: numpy types serialise fine through many code paths and then break on
    one uncommon branch, in production, in front of an examiner.
  * NaN and Infinity. json.dumps() accepts both by default and emits tokens
    that are not valid JSON, so allow_nan=False is used deliberately -- a
    payload that only survives a permissive encoder has not survived.
  * the error paths: 404, 400, 413, 422.

Run:  python scripts/test_api.py
"""

from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import create_app  # noqa: E402
from backend.session import store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "samples")

EXPECTED_ARCHETYPE = {
    "sales_timeseries.csv": "timeseries",
    "air_quality_geo.csv": "geo",
    "employees_tabular.csv": "tabular",
}

FAILURES = 0
client = TestClient(create_app())


def check(label: str, condition: bool, detail: str = "") -> None:
    global FAILURES
    if not condition:
        FAILURES += 1
    print(f"  [{'OK ' if condition else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")


def check_json_safe(label: str, payload: object) -> None:
    """Assert a payload survives the stdlib encoder with no numpy and no NaN.

    allow_nan=False is the point of this helper. With the default (True),
    json.dumps happily writes bare NaN/Infinity tokens, the test passes, and the
    browser's JSON.parse then rejects the response with a syntax error at some
    character offset in a 200KB body. Failing here instead is worth the strictness.
    """
    try:
        json.dumps(payload, allow_nan=False)
        check(label, True)
    except (TypeError, ValueError) as exc:
        check(label, False, f"{type(exc).__name__}: {exc}")


def upload(filename: str) -> dict:
    with open(os.path.join(SAMPLES, filename), "rb") as handle:
        content = handle.read()
    response = client.post(
        "/api/upload", files={"file": (filename, content, "text/csv")}
    )
    check(f"{filename}: upload -> 201", response.status_code == 201, str(response.status_code))
    return response.json()


# --------------------------------------------------------------------- health
def test_health() -> None:
    print("\nhealth")
    response = client.get("/api/health")
    body = response.json()
    check("GET /api/health -> 200", response.status_code == 200)
    check("status is ok", body.get("status") == "ok", str(body))
    check("version present", bool(body.get("version")), str(body))
    check_json_safe("health payload is JSON-safe", body)


# --------------------------------------------------------------------- errors
def test_error_paths() -> None:
    print("\nerror paths")

    response = client.get("/api/route/not-a-real-session")
    check("unknown session -> 404", response.status_code == 404, str(response.status_code))
    check(
        "404 body is a plain string detail",
        isinstance(response.json().get("detail"), str),
        str(response.json()),
    )

    response = client.post(
        "/api/upload", files={"file": ("notes.txt", b"hello", "text/plain")}
    )
    check("non-CSV upload -> 400", response.status_code == 400, str(response.status_code))

    response = client.post("/api/upload", files={"file": ("empty.csv", b"", "text/csv")})
    check("empty CSV -> 400", response.status_code == 400, str(response.status_code))

    # ~52MB of valid-looking CSV: the cap must trip on byte count during the
    # read, before pandas is ever handed the bytes. If this ever came back 201
    # it would mean a 13-million-row frame had just been parsed and cached.
    oversize = b"a,b\n" + (b"1,2\n" * 13_500_000)
    check("oversize fixture really is >50MB", len(oversize) > 50 * 1024 * 1024,
          f"{len(oversize) / 1024 / 1024:.1f}MB")
    response = client.post(
        "/api/upload", files={"file": ("big.csv", oversize, "text/csv")}
    )
    check("oversize upload -> 413", response.status_code == 413, str(response.status_code))

    session = upload("sales_timeseries.csv")
    sid = session["session_id"]

    response = client.post(
        f"/api/world/{sid}", json={"archetype": "timeseries", "params": {"freq": "Q"}}
    )
    check("invalid freq -> 422", response.status_code == 422, str(response.status_code))
    check(
        "422 detail is a flattened string",
        isinstance(response.json().get("detail"), str),
        str(response.json()),
    )

    response = client.post(
        f"/api/world/{sid}",
        json={"archetype": "timeseries", "params": {"rolling_window": 0}},
    )
    check("rolling_window 0 -> 422", response.status_code == 422, str(response.status_code))

    response = client.post(f"/api/world/{sid}", json={"archetype": "nonsense"})
    check("unknown archetype -> 422", response.status_code == 422, str(response.status_code))

    response = client.post(f"/api/forecast/{sid}", json={"horizon": -1})
    check("negative horizon -> 422", response.status_code == 422, str(response.status_code))

    response = client.post("/api/forecast/not-a-real-session", json={"horizon": 7})
    check("forecast on dead session -> 404", response.status_code == 404, str(response.status_code))


# --------------------------------------------------------------- full journey
def test_sample(filename: str) -> None:
    print(f"\n{filename}")
    expected = EXPECTED_ARCHETYPE[filename]

    session = upload(filename)
    sid = session["session_id"]
    check("session_id returned", bool(sid))
    check("filename echoed", session["filename"] == filename)
    check("n_rows > 0", session["n_rows"] > 0, str(session["n_rows"]))
    check("n_cols > 0", session["n_cols"] > 0, str(session["n_cols"]))
    check(
        "profile has one entry per column",
        len(session["profile"]["columns"]) == session["n_cols"],
    )
    check_json_safe("upload payload is JSON-safe", session)

    # ---- routing
    response = client.get(f"/api/route/{sid}")
    routing = response.json()
    check("GET /api/route -> 200", response.status_code == 200)
    check(
        f"archetype is {expected}",
        routing["archetype"] == expected,
        f"got {routing['archetype']} via {routing['source']}",
    )
    check("source is llm or fallback", routing["source"] in ("llm", "fallback"))
    check("reasoning is non-empty", bool(routing["reasoning"].strip()))
    check_json_safe("routing payload is JSON-safe", routing)

    # ---- world
    params: dict = {}
    if expected == "timeseries":
        params = {"freq": "W", "rolling_window": 4}
    body = {"archetype": expected, "params": params}
    response = client.post(f"/api/world/{sid}", json=body)
    world = response.json()
    check("POST /api/world -> 200", response.status_code == 200, str(response.status_code))
    check("world status ok", world["status"] == "ok", world.get("message", ""))
    check("at least one figure returned", len(world["figures_json"]) >= 1)
    check(
        "every figure is a JSON *string*",
        all(isinstance(v, str) for v in world["figures_json"].values()),
    )
    for name, blob in world["figures_json"].items():
        parsed = json.loads(blob)
        check(
            f"figure {name!r} parses and has data+layout",
            "data" in parsed and "layout" in parsed,
        )
    check(
        "one code string per figure",
        set(world["code"]) == set(world["figures_json"]),
        f"code={sorted(world['code'])} figures={sorted(world['figures_json'])}",
    )
    check("stats is non-empty", bool(world["stats"]))
    check_json_safe("world payload is JSON-safe", world)

    # The archetype override must be honoured, and a world that cannot be built
    # must come back as a clean 200 with an explanation -- never a 500.
    response = client.post(f"/api/world/{sid}", json={"archetype": "tabular"})
    check("override to tabular -> 200", response.status_code == 200, str(response.status_code))
    override = response.json()
    check("override echoes requested archetype", override["archetype"] == "tabular")
    check(
        "override is ok or explains itself",
        override["status"] == "ok" or bool(override["message"]),
        str(override["status"]),
    )
    check_json_safe("override payload is JSON-safe", override)

    # Routing must not have been mutated by the override.
    check(
        "routing unchanged after override",
        client.get(f"/api/route/{sid}").json()["archetype"] == expected,
    )

    # ---- forecast
    response = client.post(f"/api/forecast/{sid}", json={"horizon": 14})
    forecast = response.json()
    check("POST /api/forecast -> 200", response.status_code == 200, str(response.status_code))
    check_json_safe("forecast payload is JSON-safe", forecast)

    if expected == "timeseries":
        check("forecast succeeded", forecast["status"] == "ok", forecast.get("message", ""))
        check("predictions is a list of records", isinstance(forecast["predictions"], list))
        check("predictions non-empty", len(forecast["predictions"]) > 0)
        first = forecast["predictions"][0]
        check(
            "prediction record has date/actual/predicted",
            {"date", "actual", "predicted"} <= set(first),
            str(first),
        )
        check(
            "prediction date is an ISO string",
            isinstance(first["date"], str) and first["date"][:4].isdigit(),
            str(first["date"]),
        )
        check(
            "prediction values are floats, not numpy",
            type(first["actual"]) is float and type(first["predicted"]) is float,
            f"{type(first['actual'])}, {type(first['predicted'])}",
        )
        check("future has horizon rows", len(forecast["future"]) == 14, str(len(forecast["future"])))
        check(
            "future record has date/predicted",
            {"date", "predicted"} <= set(forecast["future"][0]),
            str(forecast["future"][0]),
        )
        check("both MAEs present", {"test_mae", "baseline_mae"} <= set(forecast["metrics"]))
        check("beats_baseline is a bool", type(forecast["beats_baseline"]) is bool)
        check("verdict is non-empty", bool(forecast["verdict"]))
        check("feature importances present", len(forecast["feature_importances"]) > 0)
        check("forecast code returned", bool(forecast["code"].strip()))
    else:
        check(
            "non-timeseries forecast declines cleanly",
            forecast["status"] != "ok" and bool(forecast["message"]),
            str(forecast["status"]),
        )


# -------------------------------------------------------------------- samples
def test_samples_endpoint() -> None:
    print("\nsample loaders")
    response = client.get("/api/samples")
    listing = response.json()
    check("GET /api/samples -> 200", response.status_code == 200)
    check("three samples listed", len(listing) == 3, str(len(listing)))
    check_json_safe("sample listing is JSON-safe", listing)

    response = client.post("/api/samples/timeseries")
    check("POST /api/samples/timeseries -> 201", response.status_code == 201,
          str(response.status_code))
    check("sample load opens a session", bool(response.json().get("session_id")))

    response = client.post("/api/samples/../../secrets")
    check("path traversal is rejected", response.status_code in (404, 405),
          str(response.status_code))


# -------------------------------------------------------------------- session
def test_session_lifetime() -> None:
    print("\nsession store")
    from backend.session import SessionStore  # local: only this test needs it
    import pandas as pd

    ephemeral = SessionStore(ttl_seconds=0)
    created = ephemeral.create("x.csv", pd.DataFrame({"a": [1]}), {}, {})
    check("expired session is not returned", ephemeral.get(created.id) is None)

    bounded = SessionStore(max_sessions=2)
    ids = [bounded.create(f"{i}.csv", pd.DataFrame({"a": [i]}), {}, {}).id for i in range(3)]
    check("LRU cap holds at max_sessions", bounded.count() == 2, str(bounded.count()))
    check("least recently used was evicted", bounded.get(ids[0]) is None)
    check("most recent survives", bounded.get(ids[2]) is not None)


def main() -> int:
    print("=" * 68)
    print("API test suite -- backend/ over core/")
    print("=" * 68)

    if not os.path.isdir(SAMPLES):
        print(f"\nsamples/ not found at {SAMPLES}. Run scripts/make_samples.py first.")
        return 1

    store.clear()
    test_health()
    test_error_paths()
    for filename in EXPECTED_ARCHETYPE:
        test_sample(filename)
    test_samples_endpoint()
    test_session_lifetime()

    print("\n" + "=" * 68)
    if FAILURES:
        print(f"{FAILURES} check(s) FAILED")
    else:
        print("All checks passed")
    print("=" * 68)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
