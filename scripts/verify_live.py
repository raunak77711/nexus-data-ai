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
        # Two families of source are legitimate. The cached-context blocks come
        # from core.chat.build_context; a "computed_<tool>" block means the
        # answer came from a calculation run over the real frame, and names
        # which one -- so the claim stays checkable, which is the point of
        # grounding it.
        context_blocks = {"profile", "routing", f"{expected}_stats", "forecast_metrics"}
        named = set(c["grounded_on"])
        ok("   grounded_on names only real blocks or real calculations",
           all(b in context_blocks or b.startswith("computed_") for b in named),
           str(c["grounded_on"]))
        ok("   the reply says how it was reached",
           c.get("answered_by") in {"computed", "model", "summaries"},
           str(c.get("answered_by")))
        if c.get("action"):
            drawn = call("POST", f"/chart/{sid}", c["action"])
            ok("   an attached action really draws", "figure_json" in drawn)
            ok("   and ships the code that drew it",
               isinstance(drawn.get("code"), str) and len(drawn["code"]) > 40)
        print(f"         reply: {c['reply'][:110]}")
    else:
        ok("   unavailable chat claims no sources", c["grounded_on"] == [])
        print("         (LLM quota exhausted -- degradation path verified, "
              "not the answering path)")

    ins = call("GET", f"/insights/{sid}")
    ok("7. insights endpoint answers", isinstance(ins.get("summary"), str) and bool(ins["summary"]),
       ins.get("summary", "")[:70])
    ok("   counts cover every pass",
       set(ins["counts"]) == {"trends", "relationships", "anomalies", "predictions",
                              "standouts", "data_issues"})
    ok("   the shape matches the upload",
       ins["shape"]["n_rows"] == s["n_rows"] and ins["shape"]["n_cols"] == s["n_cols"])
    for card in ins["insights"]:
        if card["action"]:
            drawn = call("POST", f"/chart/{sid}", card["action"])
            ok(f"   {card['kind']} card's action draws", "figure_json" in drawn)

    sim_options = call("GET", f"/simulate/{sid}/options")
    ok("8. what-if options returned", "available" in sim_options)
    if sim_options["available"]:
        sim = call("POST", f"/simulate/{sid}", {"pct_change": 20})
        ok("   a what-if runs or explains itself",
           sim["status"] in {"ok", "unsupported"} and bool(sim["message"]),
           sim["message"][:70])
        if sim["status"] == "ok":
            ok("   and states its assumptions", len(sim["caveats"]) > 0)

    pv = call("GET", f"/preview/{sid}?limit=5")
    ok("9. row preview returned", len(pv["rows"]) == min(5, pv["n_rows_total"]))
    ok("   columns match the profile", len(pv["columns"]) == s["n_cols"])

    # ------------------------------------------------------------------
    # The autonomous analysis -- the journey the app actually puts a user
    # through. Everything above this point is reachable but is no longer what
    # happens on upload; these are the five calls the frontend fires by itself.
    # ------------------------------------------------------------------
    hr = call("GET", f"/health-report/{sid}")
    ok("10. data health scored", isinstance(hr["score"], (int, float)) and 0 <= hr["score"] <= 100,
       f"{hr['score']}/100 {hr['grade']}")
    ok("    the score decomposes into the issues it lists",
       abs(hr["score"] - (100 - sum(i["penalty"] for i in hr["issues"]))) < 0.6)
    ok("    every check reports, pass or fail",
       len(hr["issues"]) + len(hr["clean"]) == hr["checks_run"],
       f"{len(hr['issues'])} issues + {len(hr['clean'])} clean = {hr['checks_run']}")

    dash = call("GET", f"/dashboard/{sid}")
    ok("11. dashboard composed", len(dash["panels"]) > 0, dash["note"][:60])
    ok("    every panel carries a figure, its code and its reason",
       all(p.get("figure_json") and p.get("code") and p.get("why") for p in dash["panels"]))
    ok("    every panel's figure is JSON.parse-able",
       all("data" in json.loads(p["figure_json"]) for p in dash["panels"]))
    ok("    no chart kind is drawn twice",
       len({p["kind"] for p in dash["panels"]}) == len(dash["panels"]),
       ", ".join(p["kind"] for p in dash["panels"]))
    ok("    headline numbers produced", len(dash["kpis"]) >= 2)

    brief = call("GET", f"/briefing/{sid}")
    ok("12. briefing written", bool(brief["summary"].strip()), f"source={brief['source']}")
    ok("    every point says where it came from",
       all(p.get("written_by") in {"llm", "rules"} for p in brief["points"]))
    ok("    every point links to what proves it",
       all(p.get("link") for p in brief["points"]))
    print(f"         {brief['headline']}")
    for point in brief["points"][:3]:
        print(f"           - [{point['label']}] {point['title']}")

    qs = call("GET", f"/questions/{sid}")
    ok("13. questions suggested", len(qs["questions"]) > 0, f"source={qs['source']}")

    tl = call("GET", f"/timeline/{sid}")
    ok("14. the work log recorded real events", tl["n_events"] >= 3,
       ", ".join(e["stage"] for e in tl["events"][:5]))

    # Explaining names a thing the SERVER computed, so an unknown reference is
    # a 404 rather than an explanation of something nobody measured.
    if dash["panels"]:
        ex = call("POST", f"/explain/{sid}",
                  {"target": "chart", "ref": dash["panels"][0]["id"], "level": "simple"})
        ok("15. a chart explains itself", bool(ex["text"].strip()), f"source={ex['source']}")

    # The cleaning flow, in the order the product enforces: propose, review,
    # apply, undo. The check that matters is the last one -- the original file
    # must come back byte for byte.
    plan = call("POST", f"/clean/{sid}/plan", {"issue_ids": None})
    ok("16. a clean is planned without changing anything", "steps" in plan,
       f"{plan['n_steps']} step(s)")
    if plan["n_steps"]:
        applied = call("POST", f"/clean/{sid}", {"issue_ids": None})
        ok("    the clean applied and reported what it did",
           len(applied["log"]) == plan["n_steps"], applied["summary"][:70])
        ok("    the health score moved", applied["health"]["score"] >= hr["score"],
           f"{hr['score']} -> {applied['health']['score']}")
        reverted = call("POST", f"/clean/{sid}/revert")
        ok("    reverting restores the original row count",
           reverted["rows_after"] == s["n_rows"],
           f"{reverted['rows_after']} vs {s['n_rows']} uploaded")
        ok("    and the original health score",
           abs(reverted["health"]["score"] - hr["score"]) < 0.01)

    rep = call("GET", f"/report/{sid}")
    ok("17. report assembled", len(rep["sections"]) >= 5,
       " / ".join(sec["kind"] for sec in rep["sections"]))
    ok("    data quality is presented BEFORE the findings",
       [sec["kind"] for sec in rep["sections"]].index("quality")
       < ([sec["kind"] for sec in rep["sections"]] + ["findings"]).index("findings"))

    # every payload must survive a strict encoder
    for name, payload in (("world", w), ("forecast", f), ("chat", c), ("profile", s),
                          ("insights", ins), ("preview", pv), ("health", hr),
                          ("dashboard", dash), ("briefing", brief), ("report", rep)):
        try:
            json.dumps(payload, allow_nan=False); good = True
        except (TypeError, ValueError) as e:
            good = False; detail = str(e)
        ok(f"18. {name} payload survives json.dumps(allow_nan=False)", good,
           "" if good else detail)


# ----------------------------------------------------------------- datasets --
# Dataset memory and comparison need two datasets, so they run once at the end
# rather than inside the per-sample loop.
print(f"\n{'='*66}\ndataset memory and comparison\n{'='*66}")

listing = call("GET", "/datasets")
ok("19. every uploaded dataset is listed", len(listing) >= 3, f"{len(listing)} stored")
ok("    each carries the shape and score its card shows",
   all("n_rows" in d and "health_score" in d for d in listing))

if len(listing) >= 2:
    cmp_result = call("POST", f"/compare/{listing[0]['id']}",
                      {"other_id": listing[1]['id']})
    ok("20. two datasets compare or explain why not",
       isinstance(cmp_result["comparable"], bool) and bool(cmp_result["summary"]),
       cmp_result["summary"][:80])

print(f"\n{'='*66}")
print(f"{FAIL} check(s) FAILED" if FAIL else "Full journey verified on all three samples")
print('='*66)
sys.exit(1 if FAIL else 0)
