"""Walk the complete user journey for all three samples against a RUNNING server.

Distinct from scripts/test_api.py, which drives the app in-process through
FastAPI's TestClient. This one talks to a real server over a real socket, so it
is what proves the *deployment* works -- CORS aside, it is exactly the sequence
of calls the browser makes, in the order it makes them:

    upload -> profile -> route -> world -> code panel -> forecast -> chat

Use it after `docker compose up`, or against a local `uvicorn backend.main:app`,
to confirm the stack is actually serving before demonstrating it. A green run
here plus a green scripts/test_api.py means the logic and the deployment are
both good; a green test_api.py alone only means the logic is.

Run:  python scripts/verify_live.py [base_url]
      (default base_url: http://localhost:8000/api)
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/api"
FAIL = 0

def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())

def ok(label, cond, detail=""):
    global FAIL
    if not cond: FAIL += 1
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")

CASES = {"timeseries": "timeseries", "geo": "geo", "tabular": "tabular"}

print("=" * 66)
print(f"Live verification against {BASE}")
print("=" * 66)

try:
    health = call("GET", "/health")
    print(f"  server up: v{health['version']}, {health['sessions']} live session(s)")
except (urllib.error.URLError, OSError) as exc:
    print(f"  Cannot reach {BASE}. Is the server running?  ({exc})")
    sys.exit(1)

for key, expected in CASES.items():
    print(f"\n{'='*66}\n{key}\n{'='*66}")

    s = call("POST", f"/samples/{key}")
    sid = s["session_id"]
    ok("1. upload/sample -> session", bool(sid), s["filename"])
    ok("   profile has every column", len(s["profile"]["columns"]) == s["n_cols"],
       f"{s['n_rows']} rows x {s['n_cols']} cols")

    r = call("GET", f"/route/{sid}")
    ok(f"2. routed to {expected}", r["archetype"] == expected,
       f"source={r['source']}, target={r['target_col']}")
    ok("   reasoning present", bool(r["reasoning"].strip()))

    params = {"freq": "W", "rolling_window": 4} if expected == "timeseries" else {}
    w = call("POST", f"/world/{sid}", {"archetype": expected, "params": params})
    ok("3. world built", w["status"] == "ok", w.get("message", ""))
    ok("   figures returned", len(w["figures_json"]) >= 1, ", ".join(w["figures_json"]))
    parsed_ok = all("data" in json.loads(v) and "layout" in json.loads(v)
                    for v in w["figures_json"].values())
    ok("   every figure JSON.parse-able with data+layout", parsed_ok)
    ok("4. code panel: one snippet per figure",
       set(w["code"]) == set(w["figures_json"]))
    ok("   every snippet is non-trivial python",
       all(len(c.splitlines()) > 4 and "import" in c for c in w["code"].values()),
       f"{[len(c.splitlines()) for c in w['code'].values()]} lines")
    ok("   stats returned", bool(w["stats"]), f"{len(w['stats'])} keys")
    if w["warnings"]:
        print(f"         warnings: {len(w['warnings'])} disclosed")

    if expected == "geo":
        col = next((c for c in s["profile"]["columns"]
                    if c["semantic_type"] == "datetime"), None)
        if col:
            wf = call("POST", f"/world/{sid}", {"archetype": "geo", "params": {
                "time_filter": [col["min_date"][:10], col["max_date"][:10]]}})
            ok("   geo time filter accepted", wf["status"] == "ok",
               f"filter_applied={wf['stats'].get('time_filter_applied')}")

    f = call("POST", f"/forecast/{sid}", {"horizon": 14})
    if expected == "timeseries":
        ok("5. forecast fitted", f["status"] == "ok", f.get("message", ""))
        ok("   both MAEs present", {"test_mae", "baseline_mae"} <= set(f["metrics"]),
           f"model {f['metrics']['test_mae']} vs baseline {f['metrics']['baseline_mae']}")
        ok("   verdict matches the numbers",
           f["beats_baseline"] == (f["metrics"]["test_mae"] < f["metrics"]["baseline_mae"]),
           "beats_baseline" if f["beats_baseline"] else "loses, and says so")
        ok("   predictions carry ISO dates",
           isinstance(f["predictions"][0]["date"], str) and len(f["predictions"]) > 0,
           f"{len(f['predictions'])} rows")
        ok("   future has the requested horizon", len(f["future"]) == 14)
        ok("   feature importances present", len(f["feature_importances"]) == 5,
           ", ".join(list(f["feature_importances"])[:3]))
        ok("   forecast code returned", "RandomForestRegressor" in f["code"])
    else:
        ok("5. forecast declines cleanly", f["status"] != "ok" and bool(f["message"]),
           f["message"][:60])

    c = call("POST", f"/chat/{sid}", {"message": "What is this dataset about?", "history": []})
    ok("6. chat endpoint answers", isinstance(c["reply"], str) and bool(c["reply"]))
    if c["available"]:
        ok("   grounded_on names only real blocks",
           set(c["grounded_on"]) <= {"profile", "routing", f"{expected}_stats",
                                     "forecast_metrics"}, str(c["grounded_on"]))
        print(f"         reply: {c['reply'][:110]}")
    else:
        ok("   unavailable chat claims no sources", c["grounded_on"] == [])
        print("         (LLM quota exhausted -- degradation path verified, "
              "not the answering path)")

    # every payload must survive a strict encoder
    for name, payload in (("world", w), ("forecast", f), ("chat", c), ("profile", s)):
        try:
            json.dumps(payload, allow_nan=False); good = True
        except (TypeError, ValueError) as e:
            good = False; detail = str(e)
        ok(f"7. {name} payload survives json.dumps(allow_nan=False)", good,
           "" if good else detail)

print(f"\n{'='*66}")
print(f"{FAIL} check(s) FAILED" if FAIL else "Full journey verified on all three samples")
print('='*66)
sys.exit(1 if FAIL else 0)
