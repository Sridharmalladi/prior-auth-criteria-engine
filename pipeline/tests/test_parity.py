"""The contract test: fixtures vs Python, and Python vs JS, field by field.

Two separate claims are checked here, and they are not the same claim:

1. The Python evaluator matches the hand-written expectations in
   ``data/parity/fixtures.json``. The fixtures are the spec.
2. The JS evaluator returns byte-identical results to the Python one — states,
   bindings, blocking clause and confidence, not just the verdict. A demo whose
   browser logic quietly drifts from the evaluated numbers is worse than no demo.

Run: pytest pipeline/tests -q
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from pipeline.evaluate import evaluate  # noqa: E402
from pipeline.validate import validate_policy  # noqa: E402

FIXTURES_PATH = os.path.join(ROOT, "data", "parity", "fixtures.json")
JS_RUNNER = os.path.join(HERE, "parity_js.mjs")


def load_fixtures():
    with open(FIXTURES_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


FIXTURES = load_fixtures()
FIXTURE_IDS = [fixture["name"] for fixture in FIXTURES]


def test_fixture_set_is_substantial():
    assert len(FIXTURES) >= 60, "parity suite is meant to be broad, not a smoke test"
    assert len(set(FIXTURE_IDS)) == len(FIXTURE_IDS), "fixture names must be unique"


def test_every_operator_and_state_is_covered():
    seen_types = set()
    seen_ops = set()
    seen_states = set()
    for fixture in FIXTURES:
        seen_states.add(fixture["expected_state"])
        for node in fixture["tree"]["nodes"].values():
            seen_types.add(node["type"])
            if node["type"] == "LEAF":
                seen_ops.add(node["predicate"]["op"])
    assert seen_types == {"AND", "OR", "NOT", "N_OF", "LEAF"}
    assert seen_ops == {">=", "<=", "==", "!=", "includes", "excludes"}
    assert seen_states == {"TRUE", "FALSE", "UNKNOWN"}


@pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
def test_fixture_tree_is_structurally_valid(fixture):
    assert validate_policy(fixture["tree"]) == []


@pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
def test_python_matches_fixture(fixture):
    result = evaluate(fixture["tree"], fixture["facts"])
    assert result["root_state"] == fixture["expected_state"]
    assert result["blocking_node"] == fixture["expected_blocking_node"]


@pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
def test_approved_cases_have_no_blocking_clause(fixture):
    result = evaluate(fixture["tree"], fixture["facts"])
    if result["decision"] == "APPROVE":
        assert result["blocking_node"] is None
    else:
        # every denied or indeterminate fixture must name something actionable
        assert result["blocking_node"] is not None


@pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
def test_blocking_clause_is_an_actionable_leaf(fixture):
    """The blocking clause is always a leaf, and always one the note would have
    to change. Note that a leaf under a NOT blocks while TRUE — an exclusion
    that fired — so TRUE is a legitimate blocking state."""
    result = evaluate(fixture["tree"], fixture["facts"])
    blocking = result["blocking_node"]
    if blocking is None:
        return
    node = fixture["tree"]["nodes"][blocking]
    assert node["type"] == "LEAF"
    assert blocking in result["depths"], "blocking clause must be reachable from the root"


@pytest.mark.parametrize("fixture", FIXTURES, ids=FIXTURE_IDS)
def test_confidence_is_in_range(fixture):
    result = evaluate(fixture["tree"], fixture["facts"])
    assert 0.0 <= result["confidence"] <= 1.0
    assert 0.0 <= result["satisfaction"] <= 1.0
    # the three shares are each rounded to 4 dp before being reported, so they
    # sum to 1 only within that rounding
    total = result["weight_true"] + result["weight_false"] + result["weight_unknown"]
    assert abs(total - 1.0) < 1e-3


def _run_js():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; JS half of the parity contract not checked")
    completed = subprocess.run(
        [node, JS_RUNNER, FIXTURES_PATH],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    return json.loads(completed.stdout.decode("utf-8"))


def test_js_matches_python_on_every_field():
    js_results = _run_js()
    assert len(js_results) == len(FIXTURES)

    disagreements = []
    for fixture, js_result in zip(FIXTURES, js_results):
        assert fixture["name"] == js_result["name"]
        py_result = evaluate(fixture["tree"], fixture["facts"])
        for field in ("root_state", "decision", "blocking_node", "satisfaction", "confidence"):
            if py_result[field] != js_result[field]:
                disagreements.append("{0}.{1}: python={2!r} js={3!r}".format(
                    fixture["name"], field, py_result[field], js_result[field]))
        if py_result["states"] != js_result["states"]:
            disagreements.append("{0}.states differ".format(fixture["name"]))
        if py_result["bindings"] != js_result["bindings"]:
            disagreements.append("{0}.bindings differ".format(fixture["name"]))

    assert not disagreements, "evaluators disagree:\n" + "\n".join(disagreements)


def test_js_matches_fixture_expectations():
    js_results = _run_js()
    for fixture, js_result in zip(FIXTURES, js_results):
        assert js_result["root_state"] == fixture["expected_state"], fixture["name"]
        assert js_result["blocking_node"] == fixture["expected_blocking_node"], fixture["name"]
