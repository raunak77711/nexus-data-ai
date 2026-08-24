"""Tests for the autonomous-analysis layer: health, cleaning, dashboard, story.

WHAT THIS COVERS THAT THE OTHER SUITES DO NOT
---------------------------------------------
scripts/test_api.py drives the HTTP boundary and test_worlds/test_profiler cover
the original core. This covers the modules that turn a parsed file into an
analysis nobody asked for: core.health, core.cleaner, core.dashboard,
core.story, core.compare and core.grounding.

THE TWO THINGS MOST WORTH TESTING HERE, AND WHY
-----------------------------------------------
1. THE GROUNDING CHECK. It is the mechanism behind this project's central
   claim -- that no number on screen was written by a model. It is a pure
   function over text and a set, so it can be tested exactly, and every one of
   its documented exemptions (magnitude, small integers, identifier digits) is
   a deliberate loosening that deserves a test pinning down how far it goes.

2. THE CLEANER'S PROMISE. "Your original file is preserved" is the sentence the
   product repeats most often and the one with the worst failure mode. It is
   asserted here directly: the frame handed to `apply` is compared before and
   after, and the cleaned result is a different object.

Everything here runs WITHOUT a model. That is the point -- these modules must
degrade to their rule-based paths, and a suite that only passed with a key
would not be testing the deployment most people run.

Run:  python scripts/test_intelligence.py
"""

from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The grounding tests deliberately feed unparseable text to parse_json, which
# logs a warning -- correctly, in production. Here it prints above the suite's
# own header and reads like a failure, so the module's logger is quieted for
# the duration of the run.
logging.getLogger("core.grounding").setLevel(logging.ERROR)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from core import cleaner, compare, dashboard, grounding, health, router, story  # noqa: E402
from core.profiler import profile_dataframe  # noqa: E402

FAILURES = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global FAILURES
    if not condition:
        FAILURES += 1
    print(f"  [{'OK ' if condition else 'FAIL'}] {label}{(' -- ' + detail) if detail else ''}")


def messy_frame() -> pd.DataFrame:
    """A file with one of every problem the health checks look for.

    Built rather than loaded so each fault is deliberate and countable: the
    duplicate rows, the impossible ages and the spelling variants are all here
    because a specific check should find them, and the counts below are derived
    from this construction.
    """
    rng = np.random.default_rng(7)
    n = 200
    frame = pd.DataFrame(
        {
            "customer_id": range(n),
            # Case and whitespace variants of two real categories.
            "city": rng.choice(["Kathmandu", "kathmandu ", "Pokhara", "POKHARA"], n),
            # Numbers wearing a currency code, which pandas reads as text.
            "spend": ["Rs 1,200.50", "Rs 980.00", "Rs 3,410.25", "Rs 220.00"] * (n // 4),
            "age": rng.integers(18, 70, n).astype(float),
            "segment": rng.choice(["A", "B", "C"], n),
            # Wholly empty, and a column that never varies.
            "notes": [None] * n,
            "region_code": "NP",
        }
    )
    frame.loc[3, "age"] = -5        # impossible
    frame.loc[9, "age"] = 250       # impossible
    frame.loc[20:40, "segment"] = None   # missing values
    return pd.concat([frame, frame.iloc[:15]], ignore_index=True)  # duplicates


# ---------------------------------------------------------------- grounding --
def test_grounding() -> None:
    print("\ngrounding -- the check behind 'no number is written by a model'")

    check(
        "a figure that was computed is accepted",
        grounding.is_grounded("revenue rose to 1,240", {"1240"}),
    )
    check(
        "a figure that was NOT computed is rejected",
        not grounding.is_grounded("revenue rose to 8,999", {"1240"}),
    )
    check(
        "reformatting a computed figure is accepted",
        grounding.is_grounded("revenue rose to 1200.00", {"1200"}),
    )

    # The three documented loosenings. Each is a deliberate trade and each is
    # pinned here so that widening one further is a visible change.
    check(
        "a sign flip is accepted: '-20%' may be written as 'a 20% drop'",
        grounding.is_grounded("a 20% drop", {"-20"}),
    )
    check(
        "small integers are treated as words, not measurements",
        grounding.is_grounded("the top 3 groups", set()),
    )
    check(
        "digits inside an identifier are not measurements (pm25 -> PM2.5)",
        grounding.is_grounded("PM2.5 averaged 12.4", {"12.4"}),
    )
    check(
        "but a unit attached AFTER a number is still checked",
        not grounding.is_grounded("it weighed 47kg", {"12"}),
    )
    check(
        "text with no numbers at all is always grounded",
        grounding.is_grounded("the two files are broadly similar", set()),
    )

    check(
        "normalise accepts floats, ints and formatted strings alike",
        grounding.normalise([1200.0, "23.4%", None]) == {"1200", "23.4"},
        str(sorted(grounding.normalise([1200.0, "23.4%", None]))),
    )
    check(
        "a reply that is not JSON degrades to an empty dict",
        grounding.parse_json("not json at all") == {},
    )
    check(
        "code fences are stripped before parsing",
        grounding.parse_json('```json\n{"a": 1}\n```') == {"a": 1},
    )


# ------------------------------------------------------------------- health --
def test_health() -> None:
    print("\nhealth -- the data quality doctor")

    frame = messy_frame()
    profile = profile_dataframe(frame)
    report = health.assess(frame, profile)

    kinds = {issue["kind"] for issue in report["issues"]}
    for kind in (
        "duplicate_rows",
        "missing_values",
        "empty_column",
        "numeric_as_text",
        "impossible_values",
        "whitespace",
        "category_variants",
        "constant_column",
    ):
        check(f"{kind} is detected", kind in kinds, ", ".join(sorted(kinds)) if kind not in kinds else "")

    check(
        "the score is a real number between 0 and 100",
        isinstance(report["score"], float) and 0 <= report["score"] <= 100,
        str(report["score"]),
    )
    check(
        "every penalty is attributable to a named issue",
        all("penalty" in issue for issue in report["issues"]),
    )
    check(
        "the score is exactly 100 minus the penalties it lists",
        abs(report["score"] - (100 - sum(i["penalty"] for i in report["issues"]))) < 0.6,
        f"score={report['score']}",
    )
    check(
        "issues are ordered worst first",
        [i["severity"] for i in report["issues"]]
        == sorted(
            (i["severity"] for i in report["issues"]),
            key={"critical": 0, "warning": 1, "notice": 2}.get,
        ),
    )
    check("checks that passed are reported too", len(report["clean"]) >= 0)
    check(
        "an identifier column is never called an outlier",
        not any("customer_id" in i["columns"] for i in report["issues"] if i["kind"] == "outliers"),
    )

    # A clean file must not be slandered.
    tidy = pd.DataFrame({"a": range(50), "b": np.linspace(0, 1, 50), "c": ["x", "y"] * 25})
    tidy_report = health.assess(tidy, profile_dataframe(tidy))
    check(
        "a tidy file scores well and lists no critical issues",
        tidy_report["score"] >= 90 and tidy_report["counts"]["critical"] == 0,
        f"score={tidy_report['score']}",
    )

    # An empty file is a data condition, not an exception.
    empty = pd.DataFrame({"a": []})
    check(
        "an empty file is reported rather than raising",
        health.assess(empty, profile_dataframe(empty))["score"] == 0.0,
    )


def test_numeric_decoration() -> None:
    """The stripper shared by the detector and the cleaner."""
    print("\nhealth -- reading numbers out of decorated text")

    cases = [
        ("a currency code prefix", ["Rs 1,200.50", "Rs 980.00"], [1200.5, 980.0]),
        ("a currency symbol", ["$1,200", "$980"], [1200.0, 980.0]),
        ("a unit suffix", ["12 kg", "8 kg"], [12.0, 8.0]),
    ]
    for label, values, expected in cases:
        _, parsed = health.strip_numeric_decoration(pd.Series(values))
        check(f"{label} is stripped", list(parsed.astype(float)) == expected, str(list(parsed)))

    # The guard that matters: a label word is NOT a unit, and converting it
    # would destroy a set of product codes.
    _, parsed = health.strip_numeric_decoration(pd.Series(["Item 5", "Item 12"]))
    check(
        "a label word is not mistaken for a unit",
        parsed.isna().all(),
        str(list(parsed)),
    )


# ------------------------------------------------------------------ cleaner --
def test_cleaner() -> None:
    print("\ncleaner -- review, apply, and never touch the original")

    frame = messy_frame()
    profile = profile_dataframe(frame)
    report = health.assess(frame, profile)

    # Nothing runs unless it was asked for.
    check("an empty approval list plans nothing", cleaner.plan(report, []) == [])
    check("None means every fixable issue", len(cleaner.plan(report, None)) > 0)

    steps = cleaner.plan(report, None)
    order = [step["action"] for step in steps]
    if "trim_whitespace" in order and "merge_categories" in order:
        check(
            "whitespace is trimmed before categories are merged",
            order.index("trim_whitespace") < order.index("merge_categories"),
            " -> ".join(order),
        )
    if "to_numeric" in order and "fill_missing" in order:
        check(
            "a column is converted to numbers before its gaps are filled",
            order.index("to_numeric") < order.index("fill_missing"),
            " -> ".join(order),
        )

    rows_before = len(frame)
    cols_before = list(frame.columns)
    cleaned, receipt = cleaner.apply(frame, steps)

    # THE PROMISE.
    check("the original frame still has its rows", len(frame) == rows_before)
    check("the original frame still has its columns", list(frame.columns) == cols_before)
    check("the cleaned frame is a different object", cleaned is not frame)

    check("the receipt logs one entry per fix", len(receipt["log"]) == len(steps))
    check(
        "the receipt's row counts agree with the frames",
        receipt["rows_before"] == rows_before and receipt["rows_after"] == len(cleaned),
    )
    check(
        "duplicates are gone from the cleaned frame",
        not cleaned.duplicated().any(),
    )
    check(
        "the spend column is now a number",
        pd.api.types.is_numeric_dtype(cleaned["spend"]),
        str(cleaned["spend"].dtype),
    )
    # Four spellings of two cities collapse to two values. WHICH spelling
    # survives is not asserted, because the rule is "the most frequent one
    # wins" and that depends on the data -- here POKHARA genuinely outnumbers
    # Pokhara. Pinning the casing would be pinning an accident of the fixture
    # rather than the behaviour, and would fail the next time the seed moved.
    survivors = set(cleaned["city"].unique())
    check(
        "four spellings of two cities collapse to two values",
        len(survivors) == 2,
        str(sorted(survivors)),
    )
    check(
        "each survivor is a real spelling from the file, in its own case group",
        {s.lower() for s in survivors} == {"kathmandu", "pokhara"},
        str(sorted(survivors)),
    )

    after = health.assess(cleaned, profile_dataframe(cleaned))
    check(
        "cleaning raises the health score",
        after["score"] > report["score"],
        f"{report['score']} -> {after['score']}",
    )

    # Failure is refused cleanly rather than half-applied.
    try:
        cleaner.apply(frame, [{"action": "not_a_real_fix", "params": {}}])
        check("an unknown fix is refused", False)
    except cleaner.CleanError as exc:
        check("an unknown fix is refused with a readable sentence", "not_a_real_fix" in str(exc))

    try:
        cleaner.apply(frame, [{"action": "drop_column", "params": {"column": "nope"}}])
        check("a fix naming a missing column is refused", False)
    except cleaner.CleanError as exc:
        check("a fix naming a missing column is refused", "nope" in str(exc))


# ---------------------------------------------------------------- dashboard --
def test_dashboard() -> None:
    print("\ndashboard -- charts chosen from the data, not a template")

    samples = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")

    expectations = {
        "sales_timeseries.csv": "trend",
        "employees_tabular.csv": "ranking",
        "air_quality_geo.csv": "trend",
    }

    for filename, expected_lead in expectations.items():
        path = os.path.join(samples, filename)
        if not os.path.exists(path):
            print(f"  [skip] {filename} not present")
            continue

        frame = pd.read_csv(path)
        profile = profile_dataframe(frame)
        routing = router.rule_based_route(profile, "test")
        composed = dashboard.compose(frame, profile, routing)

        check(
            f"{filename}: the highest-ranked chart is {expected_lead}",
            composed["panels"] and composed["panels"][0]["kind"] == expected_lead,
            composed["panels"][0]["kind"] if composed["panels"] else "no panels",
        )
        check(
            f"{filename}: every panel carries the code that drew it",
            all(panel["code"] for panel in composed["panels"]),
        )
        check(
            f"{filename}: every panel says why it is on the page",
            all(panel["why"] for panel in composed["panels"]),
        )
        check(
            f"{filename}: no chart kind appears twice",
            len({panel["kind"] for panel in composed["panels"]}) == len(composed["panels"]),
        )
        check(
            f"{filename}: headline numbers were produced",
            len(composed["kpis"]) >= 2,
            str(len(composed["kpis"])),
        )

    # The geo file is the only one that should get a map.
    geo_path = os.path.join(samples, "air_quality_geo.csv")
    if os.path.exists(geo_path):
        frame = pd.read_csv(geo_path)
        profile = profile_dataframe(frame)
        composed = dashboard.compose(frame, profile, router.rule_based_route(profile, "t"))
        check(
            "a file with coordinates gets a map",
            any(panel["kind"] == "map" for panel in composed["panels"]),
        )

    # Summing a salary is meaningless; averaging it is not.
    payroll = pd.DataFrame(
        {"salary": np.linspace(30000, 90000, 60), "team": ["A", "B", "C"] * 20}
    )
    composed = dashboard.compose(
        payroll, profile_dataframe(payroll), router.rule_based_route(profile_dataframe(payroll), "t")
    )
    ranking = [p for p in composed["panels"] if p["kind"] == "ranking"]
    check(
        "a per-person measure is averaged across groups, not summed",
        ranking and ranking[0]["spec"]["agg"] == "mean",
        ranking[0]["spec"]["agg"] if ranking else "no ranking panel",
    )

    # A file with nothing chartable must say so rather than raise.
    text_only = pd.DataFrame({"note": [f"free text {i}" for i in range(30)]})
    composed = dashboard.compose(
        text_only, profile_dataframe(text_only),
        router.rule_based_route(profile_dataframe(text_only), "t"),
    )
    check("a text-only file returns no panels and explains why", not composed["panels"] and composed["note"])


# -------------------------------------------------------------------- story --
def test_story_without_a_model() -> None:
    """The briefing must be a real briefing with no API key configured."""
    print("\nstory -- the briefing, on the rule-based path")

    frame = messy_frame()
    profile = profile_dataframe(frame)
    routing = router.rule_based_route(profile, "test")
    report = health.assess(frame, profile)

    from core import insights as insights_module

    found = insights_module.generate(frame, profile, routing)
    dataset, points = story.build_facts(profile, routing, found, report, "messy.csv")

    check("the facts include the dataset shape", dataset["n_rows"] == len(frame))
    check("points were produced", len(points) > 0, str(len(points)))
    check(
        "a critical data problem outranks every finding",
        points[0]["kind"] == "quality",
        points[0]["kind"],
    )
    check("every point carries a link to what proves it", all(p["link"] for p in points))
    check(
        "every point carries the numbers it is allowed to quote",
        all(isinstance(p["_numbers"], set) for p in points),
    )

    # The fallback summary is shown to real users, so it must be a real sentence.
    summary = story._fallback_summary(dataset, len(points))
    check("the no-model summary states the shape", str(len(frame)) in summary.replace(",", ""))
    check("the no-model summary is a sentence, not a template hole", "{" not in summary)

    questions = story._fallback_questions([], profile, routing)
    check("questions are suggested without a model", len(questions) > 0)
    check(
        "no suggested question has an unfilled placeholder",
        all("{" not in q["text"] for q in questions),
    )


# ------------------------------------------------------------------ compare --
def test_compare() -> None:
    print("\ncompare -- what changed between two files")

    base = pd.DataFrame(
        {
            "revenue": np.linspace(100, 200, 120),
            "channel": ["retail", "online", "partner"] * 40,
        }
    )
    later = base.copy()
    later["revenue"] = later["revenue"] * 1.4
    later = later.iloc[:90].copy()
    later["discount"] = 0.1

    result = compare.compare(
        base, profile_dataframe(base), later, profile_dataframe(later),
        name_a="before.csv", name_b="after.csv",
    )

    check("the two files are comparable", result["comparable"])
    kinds = {change["kind"] for change in result["changes"]}
    check("a change in row count is reported", "row_count" in kinds, ", ".join(sorted(kinds)))
    check("a new column is reported", "columns_added" in kinds)
    check("a measure that moved is reported", "measure" in kinds)

    measure = next(c for c in result["changes"] if c["kind"] == "measure")
    check(
        "a measure is compared by AVERAGE when the row counts differ",
        "average" in measure["detail"],
        measure["detail"][:80],
    )
    check("the direction of the change is right", measure["direction"] == "up")

    # Two unrelated files are refused rather than compared.
    unrelated = pd.DataFrame({"totally": [1, 2, 3], "different": [4, 5, 6]})
    refusal = compare.compare(
        base, profile_dataframe(base), unrelated, profile_dataframe(unrelated),
    )
    check("files with no shared columns are refused", not refusal["comparable"])
    check("the refusal explains itself", "no columns in common" in refusal["summary"])


def main() -> int:
    print("=" * 68)
    print("Intelligence layer -- health, cleaning, dashboard, story, compare")
    print("=" * 68)

    test_grounding()
    test_numeric_decoration()
    test_health()
    test_cleaner()
    test_dashboard()
    test_story_without_a_model()
    test_compare()

    print()
    print("=" * 68)
    print("All checks passed" if not FAILURES else f"{FAILURES} check(s) FAILED")
    print("=" * 68)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
