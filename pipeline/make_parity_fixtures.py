"""Generate data/parity/fixtures.json — the contract between the two evaluators.

Every expected_state / expected_blocking_node in this file is written by hand
from the three-valued rules, not read back out of the evaluator. That is the
whole point: if the Python evaluator disagrees with a fixture, the fixture is
the spec and the evaluator has a bug.

Run: python3 pipeline/make_parity_fixtures.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_PATH = os.path.join(ROOT, "data", "parity", "fixtures.json")

REF = {"section": "fixture", "url": "https://example.invalid/fixture"}


def leaf(node_id: str, key: str, op: str, value: Any, unit: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": node_id,
        "type": "LEAF",
        "n": None,
        "children": [],
        "label": "{0} {1} {2}".format(key, op, value),
        "source_ref": REF,
        "predicate": {"key": key, "op": op, "value": value, "unit": unit},
    }


def op_node(node_id: str, node_type: str, children: List[str], n: Optional[int] = None) -> Dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "n": n,
        "children": children,
        "label": node_type,
        "source_ref": REF,
        "predicate": None,
    }


def tree(root: str, *nodes: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "policy_id": "fixture",
        "title": "parity fixture",
        "source_url": "https://example.invalid/fixture",
        "source_type": "NCD",
        "root": root,
        "nodes": dict((node["id"], node) for node in nodes),
    }


def fact(key: str, value: Any, unit: Optional[str] = None) -> Dict[str, Any]:
    return {
        "key": key,
        "value": value,
        "unit": unit,
        "confidence": 1.0,
        "source_span": [0, 4],
        "evidence_text": "stub",
    }


FIXTURES: List[Dict[str, Any]] = []


def add(name: str, policy: Dict[str, Any], facts: List[Dict[str, Any]],
        expected_state: str, expected_blocking_node: Optional[str]) -> None:
    FIXTURES.append({
        "name": name,
        "tree": policy,
        "facts": facts,
        "expected_state": expected_state,
        "expected_blocking_node": expected_blocking_node,
    })


# ---------------------------------------------------------------------------
# 1. every leaf operator, in all three outcomes
# ---------------------------------------------------------------------------

OP_CASES = [
    # op, predicate value, satisfying fact, failing fact
    (">=", 6, 6, 4),
    ("<=", 35, 35, 41),
    ("==", True, True, False),
    ("!=", "stage_iv", "stage_ii", "stage_iv"),
    ("includes", ["pt", "nsaid"], ["pt", "nsaid", "injection"], ["pt"]),
    ("excludes", ["active_infection"], ["copd"], ["active_infection", "copd"]),
]

for op, target, pass_value, fail_value in OP_CASES:
    single = tree("root", leaf("root", "k", op, target))
    add("leaf_{0}_true".format(op), single, [fact("k", pass_value)], "TRUE", None)
    add("leaf_{0}_false".format(op), single, [fact("k", fail_value)], "FALSE", "root")
    add("leaf_{0}_unknown".format(op), single, [], "UNKNOWN", "root")

# boundary values sit on the satisfying side of >= and <=
add("leaf_gte_boundary", tree("root", leaf("root", "k", ">=", 6)), [fact("k", 6)], "TRUE", None)
add("leaf_lte_boundary", tree("root", leaf("root", "k", "<=", 35)), [fact("k", 35)], "TRUE", None)
# a numeric operator applied to a non-numeric documented value fails, it does not abstain
add("leaf_gte_on_string", tree("root", leaf("root", "k", ">=", 6)), [fact("k", "six")], "FALSE", "root")
add("leaf_gte_on_bool", tree("root", leaf("root", "k", ">=", 1)), [fact("k", True)], "FALSE", "root")
# true is not 1 and 1 is not true, in either language
add("leaf_eq_bool_vs_number", tree("root", leaf("root", "k", "==", True)), [fact("k", 1)], "FALSE", "root")
add("leaf_neq_bool_vs_number", tree("root", leaf("root", "k", "!=", True)), [fact("k", 1)], "TRUE", None)
# a scalar documented value is treated as a one-item set by includes/excludes
add("leaf_includes_scalar_fact", tree("root", leaf("root", "k", "includes", "pt")), [fact("k", "pt")], "TRUE", None)
add("leaf_excludes_scalar_fact", tree("root", leaf("root", "k", "excludes", "sepsis")), [fact("k", "sepsis")], "FALSE", "root")

# ---------------------------------------------------------------------------
# 2. AND propagation
# ---------------------------------------------------------------------------

AND3 = tree(
    "and",
    op_node("and", "AND", ["a", "b", "c"]),
    leaf("a", "a", ">=", 6, "months"),
    leaf("b", "b", "==", True),
    leaf("c", "c", "<=", 35),
)
add("and_all_true", AND3, [fact("a", 8, "months"), fact("b", True), fact("c", 30)], "TRUE", None)
add("and_one_false", AND3, [fact("a", 4, "months"), fact("b", True), fact("c", 30)], "FALSE", "a")
add("and_one_unknown", AND3, [fact("a", 8, "months"), fact("c", 30)], "UNKNOWN", "b")
add("and_false_beats_unknown", AND3, [fact("c", 41)], "FALSE", "c")
add("and_all_unknown", AND3, [], "UNKNOWN", "a")
add("and_two_false", AND3, [fact("a", 4, "months"), fact("b", False), fact("c", 30)], "FALSE", "a")

# ---------------------------------------------------------------------------
# 3. OR propagation
# ---------------------------------------------------------------------------

OR3 = tree(
    "or",
    op_node("or", "OR", ["a", "b", "c"]),
    leaf("a", "a", ">=", 6, "months"),
    leaf("b", "b", "==", True),
    leaf("c", "c", "<=", 35),
)
add("or_one_true", OR3, [fact("a", 8, "months"), fact("b", False), fact("c", 41)], "TRUE", None)
add("or_all_false", OR3, [fact("a", 4, "months"), fact("b", False), fact("c", 41)], "FALSE", "a")
# root is UNKNOWN, but a documented failure still outranks a documentation gap
add("or_unknown_with_false", OR3, [fact("a", 4, "months"), fact("c", 41)], "UNKNOWN", "a")
add("or_true_beats_unknown", OR3, [fact("b", True)], "TRUE", None)
add("or_all_unknown", OR3, [], "UNKNOWN", "a")

# ---------------------------------------------------------------------------
# 4. NOT propagation
# ---------------------------------------------------------------------------

NOT_TREE = tree(
    "not",
    op_node("not", "NOT", ["x"]),
    leaf("x", "contraindication", "==", True),
)
add("not_over_true", NOT_TREE, [fact("contraindication", True)], "FALSE", "x")
add("not_over_false", NOT_TREE, [fact("contraindication", False)], "TRUE", None)
add("not_over_unknown", NOT_TREE, [], "UNKNOWN", "x")

NOT_NESTED = tree(
    "and",
    op_node("and", "AND", ["ok", "not"]),
    leaf("ok", "indication", "==", True),
    op_node("not", "NOT", ["x"]),
    leaf("x", "exclusion", "==", True),
)
add("not_inside_and_blocks", NOT_NESTED, [fact("indication", True), fact("exclusion", True)], "FALSE", "x")
add("not_inside_and_passes", NOT_NESTED, [fact("indication", True), fact("exclusion", False)], "TRUE", None)
add("not_inside_and_unknown", NOT_NESTED, [fact("indication", True)], "UNKNOWN", "x")

# ---------------------------------------------------------------------------
# 5. N_OF propagation
# ---------------------------------------------------------------------------

N_OF_3 = tree(
    "n",
    op_node("n", "N_OF", ["a", "b", "c"], n=2),
    leaf("a", "a", "==", True),
    leaf("b", "b", "==", True),
    leaf("c", "c", "==", True),
)
add("n_of_met", N_OF_3, [fact("a", True), fact("b", True), fact("c", False)], "TRUE", None)
add("n_of_exactly_met", N_OF_3, [fact("a", True), fact("b", True)], "TRUE", None)
add("n_of_unreachable", N_OF_3, [fact("a", True), fact("b", False), fact("c", False)], "FALSE", "b")
add("n_of_still_reachable", N_OF_3, [fact("a", True), fact("b", False)], "UNKNOWN", "b")
add("n_of_all_unknown", N_OF_3, [], "UNKNOWN", "a")
add("n_of_all_false", N_OF_3, [fact("a", False), fact("b", False), fact("c", False)], "FALSE", "a")

N_OF_ALL = tree(
    "n",
    op_node("n", "N_OF", ["a", "b"], n=2),
    leaf("a", "a", "==", True),
    leaf("b", "b", "==", True),
)
add("n_of_equals_len_met", N_OF_ALL, [fact("a", True), fact("b", True)], "TRUE", None)
add("n_of_equals_len_missed", N_OF_ALL, [fact("a", True), fact("b", False)], "FALSE", "b")

N_OF_ONE = tree(
    "n",
    op_node("n", "N_OF", ["a", "b"], n=1),
    leaf("a", "a", "==", True),
    leaf("b", "b", "==", True),
)
add("n_of_one_behaves_like_or", N_OF_ONE, [fact("a", False), fact("b", True)], "TRUE", None)
add("n_of_one_all_false", N_OF_ONE, [fact("a", False), fact("b", False)], "FALSE", "a")

# ---------------------------------------------------------------------------
# 6. deep nesting
# ---------------------------------------------------------------------------

DEEP = tree(
    "root",
    op_node("root", "AND", ["indication", "conservative", "safety"]),
    leaf("indication", "diagnosis", "includes", ["spondylolisthesis"]),
    op_node("conservative", "OR", ["pt_path", "contraindicated"]),
    op_node("pt_path", "AND", ["pt_months", "pt_documented"]),
    leaf("pt_months", "pt_duration_months", ">=", 6, "months"),
    leaf("pt_documented", "pt_documented", "==", True),
    leaf("contraindicated", "pt_contraindicated", "==", True),
    op_node("safety", "NOT", ["active_infection"]),
    leaf("active_infection", "active_infection", "==", True),
)
add(
    "deep_all_paths_satisfied",
    DEEP,
    [fact("diagnosis", ["spondylolisthesis"]), fact("pt_duration_months", 8, "months"),
     fact("pt_documented", True), fact("active_infection", False)],
    "TRUE",
    None,
)
add(
    "deep_or_rescued_by_alternative",
    DEEP,
    [fact("diagnosis", ["spondylolisthesis"]), fact("pt_duration_months", 2, "months"),
     fact("pt_documented", True), fact("pt_contraindicated", True), fact("active_infection", False)],
    "TRUE",
    None,
)
add(
    "deep_short_therapy_blocks",
    DEEP,
    [fact("diagnosis", ["spondylolisthesis"]), fact("pt_duration_months", 4, "months"),
     fact("pt_documented", True), fact("pt_contraindicated", False), fact("active_infection", False)],
    "FALSE",
    "pt_months",
)
add(
    "deep_exclusion_blocks_at_depth_one",
    DEEP,
    [fact("diagnosis", ["spondylolisthesis"]), fact("pt_duration_months", 8, "months"),
     fact("pt_documented", True), fact("active_infection", True)],
    "FALSE",
    "active_infection",
)
add(
    "deep_two_independent_failures",
    DEEP,
    [fact("diagnosis", ["low_back_pain"]), fact("pt_duration_months", 4, "months"),
     fact("pt_documented", True), fact("pt_contraindicated", False), fact("active_infection", False)],
    "FALSE",
    "indication",
)
add(
    "deep_missing_documentation_abstains",
    DEEP,
    [fact("diagnosis", ["spondylolisthesis"]), fact("pt_duration_months", 8, "months"),
     fact("active_infection", False)],
    "UNKNOWN",
    "pt_documented",
)
add("deep_all_unknown", DEEP, [], "UNKNOWN", "indication")

FIVE_DEEP = tree(
    "l0",
    op_node("l0", "AND", ["l1", "sibling"]),
    leaf("sibling", "sibling", "==", True),
    op_node("l1", "OR", ["l2", "alt1"]),
    leaf("alt1", "alt1", "==", True),
    op_node("l2", "AND", ["l3", "alt2"]),
    leaf("alt2", "alt2", "==", True),
    op_node("l3", "N_OF", ["d1", "d2", "d3"], n=2),
    leaf("d1", "d1", "==", True),
    leaf("d2", "d2", "==", True),
    leaf("d3", "d3", "==", True),
)
add(
    "five_deep_satisfied",
    FIVE_DEEP,
    [fact("sibling", True), fact("alt2", True), fact("d1", True), fact("d2", True), fact("d3", False)],
    "TRUE",
    None,
)
add(
    "five_deep_blocked_at_top",
    FIVE_DEEP,
    [fact("sibling", False), fact("alt1", True)],
    "FALSE",
    "sibling",
)
add(
    "five_deep_unknown_deep_branch",
    FIVE_DEEP,
    [fact("sibling", True), fact("alt1", False), fact("alt2", True), fact("d1", True)],
    "UNKNOWN",
    # the partly-satisfied arm is the cheaper one to finish, so the gap inside
    # it is reported rather than the untouched alternative
    "d2",
)

# ---------------------------------------------------------------------------
# 7. blocking-clause ranking
# ---------------------------------------------------------------------------

RANK_STATE = tree(
    "root",
    op_node("root", "AND", ["false_leaf", "unknown_leaf"]),
    leaf("false_leaf", "bmi", ">=", 35),
    leaf("unknown_leaf", "counselling", "==", True),
)
# rule 1: a documented failure outranks a documentation gap
add("rank_false_over_unknown", RANK_STATE, [fact("bmi", 30)], "FALSE", "false_leaf")

RANK_DEPTH = tree(
    "root",
    op_node("root", "AND", ["shallow", "branch"]),
    leaf("shallow", "shallow", "==", True),
    op_node("branch", "AND", ["deep_a", "deep_b"]),
    leaf("deep_a", "deep_a", "==", True),
    leaf("deep_b", "deep_b", "==", True),
)
# rule 2: among equally-false leaves, the shallower one is the one to fix
add(
    "rank_shallowest_wins",
    RANK_DEPTH,
    [fact("shallow", False), fact("deep_a", False), fact("deep_b", True)],
    "FALSE",
    "shallow",
)

RANK_DELTA = tree(
    "root",
    op_node("root", "AND", ["months", "bmi"]),
    leaf("months", "pt_duration_months", ">=", 6, "months"),
    leaf("bmi", "bmi", ">=", 75),
)
# rule 3: same state, same depth — two months of therapy is a smaller ask than 40 BMI points
add(
    "rank_smallest_delta_wins",
    RANK_DELTA,
    [fact("pt_duration_months", 4, "months"), fact("bmi", 35)],
    "FALSE",
    "months",
)

RANK_ID = tree(
    "root",
    op_node("root", "AND", ["alpha", "beta"]),
    leaf("alpha", "alpha", "==", True),
    leaf("beta", "beta", "==", True),
)
# rule 4: identical on every other axis — node id breaks the tie, deterministically
add("rank_node_id_tiebreak", RANK_ID, [fact("alpha", False), fact("beta", False)], "FALSE", "alpha")

# an OR whose alternatives are all false: no single flip is privileged, id decides
RANK_OR = tree(
    "root",
    op_node("root", "OR", ["opt_a", "opt_b"]),
    leaf("opt_a", "opt_a", "==", True),
    leaf("opt_b", "opt_b", "==", True),
)
add("rank_or_all_false", RANK_OR, [fact("opt_a", False), fact("opt_b", False)], "FALSE", "opt_a")

# a leaf whose flip cannot change the root is not a candidate: opt_b is already
# satisfied via the OR, so the AND's other arm is the only blocking clause
RANK_IRRELEVANT = tree(
    "root",
    op_node("root", "AND", ["gate", "choice"]),
    leaf("gate", "gate", "==", True),
    op_node("choice", "OR", ["opt_a", "opt_b"]),
    leaf("opt_a", "opt_a", "==", True),
    leaf("opt_b", "opt_b", "==", True),
)
add(
    "rank_ignores_non_pivotal_leaf",
    RANK_IRRELEVANT,
    [fact("gate", False), fact("opt_a", True), fact("opt_b", False)],
    "FALSE",
    "gate",
)

# approved cases have no blocking clause at all
add(
    "approved_has_no_blocking_node",
    RANK_IRRELEVANT,
    [fact("gate", True), fact("opt_a", True), fact("opt_b", False)],
    "TRUE",
    None,
)

# inside an N_OF that is already unreachable, every false leaf is pivotal;
# the shallowest-then-id rule keeps the answer stable
N_OF_RANK = tree(
    "root",
    op_node("root", "N_OF", ["c1", "c2", "c3"], n=2),
    leaf("c1", "c1", ">=", 10),
    leaf("c2", "c2", ">=", 10),
    leaf("c3", "c3", ">=", 10),
)
add(
    "n_of_blocking_smallest_delta",
    N_OF_RANK,
    [fact("c1", 2), fact("c2", 9), fact("c3", 1)],
    "FALSE",
    "c2",
)

# ---------------------------------------------------------------------------
# 8. degenerate shapes
# ---------------------------------------------------------------------------

add("single_leaf_root_true", tree("root", leaf("root", "k", "==", True)), [fact("k", True)], "TRUE", None)
add("single_leaf_root_unknown", tree("root", leaf("root", "k", "==", True)), [], "UNKNOWN", "root")

SHARED_KEY = tree(
    "root",
    op_node("root", "AND", ["low", "high"]),
    leaf("low", "bmi", ">=", 35),
    leaf("high", "bmi", "<=", 60),
)
add("two_leaves_one_fact_key", SHARED_KEY, [fact("bmi", 40)], "TRUE", None)
add("two_leaves_one_fact_key_blocked", SHARED_KEY, [fact("bmi", 70)], "FALSE", "high")

EXTRA_FACTS = tree("root", leaf("root", "k", "==", True))
add("unused_facts_are_ignored", EXTRA_FACTS, [fact("k", True), fact("unused", 99)], "TRUE", None)

NOT_OVER_OR = tree(
    "root",
    op_node("root", "NOT", ["any_exclusion"]),
    op_node("any_exclusion", "OR", ["e1", "e2"]),
    leaf("e1", "e1", "==", True),
    leaf("e2", "e2", "==", True),
)
add("not_over_or_clean", NOT_OVER_OR, [fact("e1", False), fact("e2", False)], "TRUE", None)
add("not_over_or_one_hit", NOT_OVER_OR, [fact("e1", False), fact("e2", True)], "FALSE", "e2")
add("not_over_or_unknown", NOT_OVER_OR, [fact("e1", False)], "UNKNOWN", "e2")

DOUBLE_NOT = tree(
    "root",
    op_node("root", "NOT", ["inner"]),
    op_node("inner", "NOT", ["x"]),
    leaf("x", "x", "==", True),
)
add("double_negation_true", DOUBLE_NOT, [fact("x", True)], "TRUE", None)
add("double_negation_false", DOUBLE_NOT, [fact("x", False)], "FALSE", "x")
add("double_negation_unknown", DOUBLE_NOT, [], "UNKNOWN", "x")


def main() -> int:
    sys.path.insert(0, ROOT)
    from pipeline.evaluate import evaluate  # noqa: E402
    from pipeline.validate import validate_policy  # noqa: E402

    failures = []
    for fixture in FIXTURES:
        errors = validate_policy(fixture["tree"])
        if errors:
            failures.append("{0}: invalid tree: {1}".format(fixture["name"], errors[0]))
            continue
        result = evaluate(fixture["tree"], fixture["facts"])
        if result["root_state"] != fixture["expected_state"]:
            failures.append("{0}: state {1}, fixture says {2}".format(
                fixture["name"], result["root_state"], fixture["expected_state"]))
        if result["blocking_node"] != fixture["expected_blocking_node"]:
            failures.append("{0}: blocking {1}, fixture says {2}".format(
                fixture["name"], result["blocking_node"], fixture["expected_blocking_node"]))

    if failures:
        print("{0} fixture(s) disagree with the Python evaluator:".format(len(failures)))
        for failure in failures:
            print("  - {0}".format(failure))
        return 1

    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(FIXTURES, handle, indent=1)
        handle.write("\n")
    print("wrote {0} fixtures to {1}".format(len(FIXTURES), OUT_PATH))
    return 0


if __name__ == "__main__":
    sys.exit(main())
