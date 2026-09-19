"""Checks on the committed data: trees, cases, spans and labels.

These run in CI alongside the parity suite. A policy tree that stops validating,
a note that is rewrapped without updating its spans, or a gold label that no
longer matches the facts should all fail the build rather than surface as a
quietly wrong demo.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from pipeline.evaluate import evaluate  # noqa: E402
from pipeline.validate import validate_case, validate_policy  # noqa: E402

POLICY_DIR = os.path.join(ROOT, "data", "policies")
CASE_DIR = os.path.join(ROOT, "data", "cases")


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


POLICIES = {}
for _name in sorted(os.listdir(POLICY_DIR)):
    if _name.endswith(".json"):
        _policy = read(os.path.join(POLICY_DIR, _name))
        POLICIES[_policy["policy_id"]] = _policy

CASES = [read(os.path.join(CASE_DIR, _name)) for _name in sorted(os.listdir(CASE_DIR)) if _name.endswith(".json")]
CASE_IDS = [case["case_id"] for case in CASES]


def test_expected_corpus_size():
    assert len(POLICIES) == 8
    assert len(CASES) == 20


@pytest.mark.parametrize("policy_id", sorted(POLICIES))
def test_policy_is_valid(policy_id):
    assert validate_policy(POLICIES[policy_id]) == []


@pytest.mark.parametrize("policy_id", sorted(POLICIES))
def test_policy_declares_its_provenance(policy_id):
    policy = POLICIES[policy_id]
    assert policy.get("provenance"), "a tree without provenance cannot be audited"
    assert policy.get("verification") in ("checked against source text", "unverified-paraphrase", "machine-generated")
    if policy["source_type"] == "LCD":
        # LCD detail text is licence-gated, so an LCD tree must not claim to have
        # been checked against source text it could not legally be checked against.
        assert policy["verification"] == "unverified-paraphrase"


@pytest.mark.parametrize("policy_id", sorted(POLICIES))
def test_every_node_cites_a_source(policy_id):
    for node in POLICIES[policy_id]["nodes"].values():
        assert node["source_ref"]["section"]
        assert node["source_ref"]["url"].startswith("https://www.cms.gov/")


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_case_is_valid_against_its_policy(case):
    assert validate_case(case, POLICIES[case["policy_id"]]) == []


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_every_span_indexes_its_evidence(case):
    note = case["note_text"]
    for fact in case["facts"]:
        start, end = fact["source_span"]
        assert note[start:end] == fact["evidence_text"], fact["key"]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_facts_use_keys_the_policy_reads(case):
    policy = POLICIES[case["policy_id"]]
    known = {node["predicate"]["key"] for node in policy["nodes"].values() if node["type"] == "LEAF"}
    for fact in case["facts"]:
        assert fact["key"] in known, "{0}: {1} is not read by this policy".format(case["case_id"], fact["key"])


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_evaluator_reproduces_the_gold_decision(case):
    result = evaluate(POLICIES[case["policy_id"]], case["facts"])
    assert result["decision"] == case["gold_decision"]


@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_cases_are_labelled_synthetic(case):
    assert case.get("synthetic") is True


def test_label_distribution():
    counts = {"APPROVE": 0, "DENY": 0, "INDETERMINATE": 0}
    for case in CASES:
        counts[case["gold_decision"]] += 1
    assert counts == {"APPROVE": 8, "DENY": 8, "INDETERMINATE": 4}


def test_at_least_three_cases_have_multiple_independent_failures():
    """The cases that separate a criteria graph from flat retrieval are the ones
    where more than one criterion fails at once."""
    multi = 0
    for case in CASES:
        policy = POLICIES[case["policy_id"]]
        result = evaluate(policy, case["facts"])
        unsatisfied_leaves = [
            node_id for node_id, node in policy["nodes"].items()
            if node["type"] == "LEAF" and result["states"].get(node_id) in ("FALSE", "UNKNOWN")
        ]
        if result["decision"] != "APPROVE" and len(unsatisfied_leaves) >= 2:
            multi += 1
    assert multi >= 3
