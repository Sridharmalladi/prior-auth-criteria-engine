"""Three-valued criteria-tree evaluator.

This file and ``docs/js/evaluator.js`` are two implementations of one contract.
They are held together by ``data/parity/fixtures.json`` and the parity CI job.
Any change here must be mirrored there in the same commit.

Pure stdlib, dict-based, no pydantic import: the deterministic core must run
anywhere, including inside a browser after a mechanical port.
"""

from __future__ import annotations

import json
import math
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

TRUE = "TRUE"
FALSE = "FALSE"
UNKNOWN = "UNKNOWN"

# Sentinel used when a candidate blocking node has no meaningful numeric gap
# (booleans, set membership, missing facts). Keeps ordering total and stable.
NO_DELTA = float("inf")


def _round4(value: float) -> float:
    """Half-up rounding to 4 dp. Defined explicitly because Python's round()
    is half-to-even and JS's toFixed() is neither; parity needs one rule."""
    scaled = value * 10000.0
    return math.floor(scaled + 0.5) / 10000.0 if scaled >= 0 else -(math.floor(-scaled + 0.5) / 10000.0)


# --------------------------------------------------------------------------
# predicates
# --------------------------------------------------------------------------

def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return [value]


def _equal_values(left: Any, right: Any) -> bool:
    """Strict equality, matched to JS semantics: Python treats True == 1 as
    true and JS does not, so bool/number crossings compare unequal here."""
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, list) != isinstance(right, list):
        return False
    return left == right


def apply_predicate(predicate: Dict[str, Any], fact_value: Any) -> str:
    """Apply one predicate to one observed value. Never returns UNKNOWN:
    absence is handled by the caller, not here."""
    op = predicate["op"]
    target = predicate["value"]

    if op == ">=":
        if not isinstance(fact_value, (int, float)) or isinstance(fact_value, bool):
            return FALSE
        return TRUE if fact_value >= target else FALSE
    if op == "<=":
        if not isinstance(fact_value, (int, float)) or isinstance(fact_value, bool):
            return FALSE
        return TRUE if fact_value <= target else FALSE
    if op == "==":
        return TRUE if _equal_values(fact_value, target) else FALSE
    if op == "!=":
        return FALSE if _equal_values(fact_value, target) else TRUE
    if op == "includes":
        observed = _as_list(fact_value)
        required = _as_list(target)
        return TRUE if all(item in observed for item in required) else FALSE
    if op == "excludes":
        observed = _as_list(fact_value)
        forbidden = _as_list(target)
        return TRUE if all(item not in observed for item in forbidden) else FALSE
    raise ValueError("unknown operator {0!r}".format(op))


def required_delta(predicate: Dict[str, Any], fact_value: Any) -> float:
    """How far the documented value is from clearing this predicate.

    Used only as the final tie-break between equally shallow blocking
    candidates, so that 'two more months of PT' outranks 'lose 40 BMI points'.
    Non-numeric predicates return NO_DELTA and therefore sort last.
    """
    op = predicate["op"]
    target = predicate["value"]
    if op not in (">=", "<="):
        return NO_DELTA
    if not isinstance(fact_value, (int, float)) or isinstance(fact_value, bool):
        return NO_DELTA
    if op == ">=":
        return max(0.0, float(target) - float(fact_value))
    return max(0.0, float(fact_value) - float(target))


# --------------------------------------------------------------------------
# tree walk
# --------------------------------------------------------------------------

def _combine(node_type: str, child_states: Sequence[str], n: Optional[int]) -> str:
    if node_type == "AND":
        if FALSE in child_states:
            return FALSE
        if UNKNOWN in child_states:
            return UNKNOWN
        return TRUE
    if node_type == "OR":
        if TRUE in child_states:
            return TRUE
        if UNKNOWN in child_states:
            return UNKNOWN
        return FALSE
    if node_type == "NOT":
        child = child_states[0]
        if child == TRUE:
            return FALSE
        if child == FALSE:
            return TRUE
        return UNKNOWN
    if node_type == "N_OF":
        true_count = sum(1 for state in child_states if state == TRUE)
        unknown_count = sum(1 for state in child_states if state == UNKNOWN)
        if true_count >= (n or 0):
            return TRUE
        if true_count + unknown_count < (n or 0):
            return FALSE
        return UNKNOWN
    raise ValueError("unknown node type {0!r}".format(node_type))


def _leaf_state(node: Dict[str, Any], facts_by_key: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
    predicate = node["predicate"]
    fact = facts_by_key.get(predicate["key"])
    if fact is None:
        return UNKNOWN, None
    return apply_predicate(predicate, fact["value"]), fact


def _depths(nodes: Dict[str, Any], root: str) -> Dict[str, int]:
    """Shortest distance from the root, breadth-first."""
    depths = {root: 0}
    queue = [root]
    while queue:
        current = queue.pop(0)
        for child in nodes[current].get("children", []) or []:
            if child in depths or child not in nodes:
                continue
            depths[child] = depths[current] + 1
            queue.append(child)
    return depths


def _post_order(nodes: Dict[str, Any], root: str) -> List[str]:
    """Children before parents, iteratively (trees here are shallow, but the
    JS twin must not rely on recursion limits either)."""
    order: List[str] = []
    seen = set()
    stack: List[Tuple[str, bool]] = [(root, False)]
    while stack:
        node_id, expanded = stack.pop()
        if expanded:
            order.append(node_id)
            continue
        if node_id in seen or node_id not in nodes:
            continue
        seen.add(node_id)
        stack.append((node_id, True))
        for child in reversed(nodes[node_id].get("children", []) or []):
            stack.append((child, False))
    return order


def _format_value(value: Any, unit: Optional[str]) -> str:
    if isinstance(value, bool):
        text = "yes" if value else "no"
    elif isinstance(value, list):
        text = ", ".join(str(item) for item in value)
    elif isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        text = str(value)
    return "{0} {1}".format(text, unit) if unit else text


OP_WORDS = {
    ">=": "at least",
    "<=": "at most",
    "==": "exactly",
    "!=": "anything other than",
    "includes": "must include",
    "excludes": "must not include",
}


def _reason(state: str, predicate: Dict[str, Any], fact: Optional[Dict[str, Any]]) -> str:
    needed = "{0} {1}".format(OP_WORDS[predicate["op"]], _format_value(predicate["value"], predicate.get("unit")))
    if fact is None:
        return "not documented; policy requires {0}".format(needed)
    observed = _format_value(fact["value"], fact.get("unit") or predicate.get("unit"))
    return "documented {0}; policy requires {1}".format(observed, needed)


def propagate(policy: Dict[str, Any], facts: Sequence[Dict[str, Any]],
              overrides: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Walk the tree once and return node states plus leaf bindings.

    ``overrides`` forces a node into a given state before it propagates upward;
    that is how the counterfactual flips behind blocking-clause selection are
    done. Selection lives in ``evaluate``, never here, so a flip cannot re-enter
    selection and recurse.
    """
    nodes = policy["nodes"]
    root = policy["root"]
    overrides = overrides or {}
    facts_by_key = {}
    for fact in facts:
        facts_by_key[fact["key"]] = fact

    states: Dict[str, str] = {}
    bindings: List[Dict[str, Any]] = []

    for node_id in _post_order(nodes, root):
        node = nodes[node_id]
        if node["type"] == "LEAF":
            state, fact = _leaf_state(node, facts_by_key)
            bindings.append({
                "node_id": node_id,
                "fact_key": node["predicate"]["key"],
                "state": state,
                "reason": _reason(state, node["predicate"], fact),
            })
        else:
            child_states = [states[child] for child in node["children"]]
            state = _combine(node["type"], child_states, node.get("n"))
        if node_id in overrides:
            state = overrides[node_id]
        states[node_id] = state

    return {"states": states, "bindings": bindings, "root_state": states[root]}


def evaluate(policy: Dict[str, Any], facts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Full evaluation: states, bindings, decision, blocking clause, confidence."""
    root = policy["root"]
    depths = _depths(policy["nodes"], root)
    walk = propagate(policy, facts)
    states = walk["states"]
    root_state = walk["root_state"]

    decision = {TRUE: "APPROVE", FALSE: "DENY", UNKNOWN: "INDETERMINATE"}[root_state]
    blocking_node = select_blocking_node(policy, facts, states, depths)
    scores = confidence(policy, states, depths, decision)

    return {
        "policy_id": policy["policy_id"],
        "decision": decision,
        "root_state": root_state,
        "states": states,
        "depths": depths,
        "bindings": sorted(walk["bindings"], key=lambda binding: binding["node_id"]),
        "blocking_node": blocking_node,
        "satisfaction": scores["satisfaction"],
        "confidence": scores["confidence"],
        "weight_true": scores["weight_true"],
        "weight_false": scores["weight_false"],
        "weight_unknown": scores["weight_unknown"],
    }


# --------------------------------------------------------------------------
# blocking clause selection
# --------------------------------------------------------------------------

def _leaf_key(node_id: str, nodes: Dict[str, Any], states: Dict[str, str],
              depths: Dict[str, int], facts_by_key: Dict[str, Any], delta_first: bool) -> Tuple:
    """Ordering key for one candidate leaf.

    ``delta_first`` picks which of the two orderings applies:
      * False -> (state, depth, delta, id): the reported blocking clause. Depth
        first, so a wrong indication outranks a therapy gap buried three levels
        down; a case that fails on both should be reported at the top.
      * True  -> (state, delta, depth, id): choosing between the arms of an OR.
        Depth is meaningless there (the arms are alternatives, not siblings in
        a conjunction), so the cheapest arm wins.
    """
    node = nodes[node_id]
    state = states[node_id]
    # Documented outcomes rank above documentation gaps. A leaf reached through
    # a NOT blocks while TRUE (the exclusion fired), so the test is "is this
    # documented", not "is this FALSE".
    state_rank = 1 if state == UNKNOWN else 0
    fact = facts_by_key.get(node["predicate"]["key"])
    delta = required_delta(node["predicate"], fact["value"]) if fact else NO_DELTA
    if delta_first:
        return (state_rank, delta, depths.get(node_id, 0), node_id)
    return (state_rank, depths.get(node_id, 0), delta, node_id)


def _true_leaf_count(nodes: Dict[str, Any], states: Dict[str, str], node_id: str) -> int:
    """Leaves already satisfied inside a subtree — how much of this arm the
    note has already paid for."""
    count = 0
    stack = [node_id]
    seen = set()
    while stack:
        current = stack.pop()
        if current in seen or current not in nodes:
            continue
        seen.add(current)
        node = nodes[current]
        if node["type"] == "LEAF":
            if states.get(current) == TRUE:
                count += 1
        else:
            stack.extend(node.get("children", []) or [])
    return count


def collect_candidates(policy: Dict[str, Any], states: Dict[str, str], depths: Dict[str, int],
                       facts_by_key: Dict[str, Any], node_id: str, want: str) -> List[str]:
    """Leaves that would have to change for ``node_id`` to reach ``want``.

    This walks *down* the failing paths instead of flipping leaves one at a
    time and asking whether the root moved. A flip test cannot see a case with
    two independent failures — neither flip alone changes the verdict, so
    nothing is reported — and those are precisely the cases that matter here.

    Where alternatives exist (OR, N_OF, and the child of a falsified AND) only
    the cheapest arm is descended into: an arm is cheaper when it needs fewer
    leaves changed, then when more of it is already satisfied, then on the
    delta-first leaf key.
    """
    nodes = policy["nodes"]
    if states.get(node_id) == want:
        return []
    node = nodes[node_id]
    node_type = node["type"]

    if node_type == "LEAF":
        return [node_id]

    children = node.get("children", []) or []

    def descend(child_id: str, child_want: str) -> List[str]:
        return collect_candidates(policy, states, depths, facts_by_key, child_id, child_want)

    def branch_cost(child_id: str, candidates: List[str]) -> Tuple:
        best = min(
            (_leaf_key(leaf_id, nodes, states, depths, facts_by_key, True) for leaf_id in candidates),
            default=(2, NO_DELTA, 0, ""),
        )
        return (len(candidates), -_true_leaf_count(nodes, states, child_id), best, child_id)

    def cheapest(pairs: List[Tuple[str, List[str]]], take: int) -> List[str]:
        ranked = sorted(pairs, key=lambda pair: branch_cost(pair[0], pair[1]))
        chosen: List[str] = []
        for child_id, candidates in ranked[:max(0, take)]:
            for leaf_id in candidates:
                if leaf_id not in chosen:
                    chosen.append(leaf_id)
        return chosen

    def union(pairs: List[Tuple[str, List[str]]]) -> List[str]:
        return cheapest(pairs, len(pairs))

    if node_type == "NOT":
        return descend(children[0], FALSE if want == TRUE else TRUE)

    if node_type == "AND":
        if want == TRUE:
            pairs = [(child, descend(child, TRUE)) for child in children if states.get(child) != TRUE]
            return union(pairs)
        pairs = [(child, descend(child, FALSE)) for child in children if states.get(child) != FALSE]
        return cheapest(pairs, 1)

    if node_type == "OR":
        if want == TRUE:
            pairs = [(child, descend(child, TRUE)) for child in children if states.get(child) != TRUE]
            return cheapest(pairs, 1)
        pairs = [(child, descend(child, FALSE)) for child in children if states.get(child) != FALSE]
        return union(pairs)

    if node_type == "N_OF":
        n = node.get("n") or 0
        true_count = sum(1 for child in children if states.get(child) == TRUE)
        if want == TRUE:
            pairs = [(child, descend(child, TRUE)) for child in children if states.get(child) != TRUE]
            return cheapest(pairs, max(0, n - true_count))
        surplus = true_count - (n - 1)
        if surplus > 0:
            pairs = [(child, descend(child, FALSE)) for child in children if states.get(child) == TRUE]
            return cheapest(pairs, surplus)
        pairs = [(child, descend(child, FALSE)) for child in children if states.get(child) != FALSE]
        return union(pairs)

    raise ValueError("unknown node type {0!r}".format(node_type))


def select_blocking_node(policy: Dict[str, Any], facts: Sequence[Dict[str, Any]],
                         states: Dict[str, str], depths: Dict[str, int]) -> Optional[str]:
    """Pick the single clause a reviewer should act on.

    Only leaves are candidates. An operator node is by construction shallower
    than every leaf beneath it, so allowing operator nodes would make the answer
    a depth-1 AND on every case — true, and useless to a reviewer, who needs the
    documentable fact, not the branch that contains it.

    Ranking, in order:
      1. FALSE leaves rank above UNKNOWN leaves — a documented failure is a
         harder blocker than a documentation gap.
      2. Shallowest leaf, since it gates the most of the tree.
      3. Smallest required delta (two more months of therapy beats 40 BMI points).
      4. Node id, so the answer is deterministic.
    """
    root = policy["root"]
    if states[root] == TRUE:
        return None

    nodes = policy["nodes"]
    facts_by_key = dict((fact["key"], fact) for fact in facts)
    candidates = collect_candidates(policy, states, depths, facts_by_key, root, TRUE)
    candidates = [leaf_id for leaf_id in candidates if leaf_id in depths]
    if not candidates:
        return None
    return min(candidates, key=lambda leaf_id: _leaf_key(leaf_id, nodes, states, depths, facts_by_key, False))


# --------------------------------------------------------------------------
# confidence
# --------------------------------------------------------------------------

def confidence(policy: Dict[str, Any], states: Dict[str, str], depths: Dict[str, int],
               decision: str) -> Dict[str, float]:
    """Rule-derived, not calibrated against payer outcomes.

    Each leaf carries weight w = 1 / (1 + depth), so a criterion that gates a
    whole branch counts for more than one buried inside an alternative. With
    S, F, U the shares of leaf weight that are TRUE, FALSE and UNKNOWN:

        satisfaction = clamp(S - 0.5 * U, 0, 1)

        APPROVE       -> satisfaction
        DENY          -> 1 - U                 (a denial is only as solid as the record is complete)
        INDETERMINATE -> 0.5 + 0.5 * U         (the more of the record is missing, the surer the abstention)
    """
    nodes = policy["nodes"]
    total = 0.0
    weight_true = 0.0
    weight_false = 0.0
    weight_unknown = 0.0

    for node_id, node in nodes.items():
        if node["type"] != "LEAF" or node_id not in depths:
            continue
        weight = 1.0 / (1.0 + depths[node_id])
        total += weight
        state = states.get(node_id)
        if state == TRUE:
            weight_true += weight
        elif state == FALSE:
            weight_false += weight
        else:
            weight_unknown += weight

    if total == 0.0:
        return {"satisfaction": 0.0, "confidence": 0.0,
                "weight_true": 0.0, "weight_false": 0.0, "weight_unknown": 0.0}

    share_true = weight_true / total
    share_false = weight_false / total
    share_unknown = weight_unknown / total
    satisfaction = min(1.0, max(0.0, share_true - 0.5 * share_unknown))

    if decision == "APPROVE":
        value = satisfaction
    elif decision == "DENY":
        value = 1.0 - share_unknown
    else:
        value = 0.5 + 0.5 * share_unknown

    return {
        "satisfaction": _round4(satisfaction),
        "confidence": _round4(min(1.0, max(0.0, value))),
        "weight_true": _round4(share_true),
        "weight_false": _round4(share_false),
        "weight_unknown": _round4(share_unknown),
    }


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def _main(argv: List[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m pipeline.evaluate data/policies/<policy>.json data/cases/<case>.json")
        return 2
    with open(argv[0], "r", encoding="utf-8") as handle:
        policy = json.load(handle)
    with open(argv[1], "r", encoding="utf-8") as handle:
        case = json.load(handle)
    result = evaluate(policy, case["facts"])
    print(json.dumps({
        "case_id": case["case_id"],
        "decision": result["decision"],
        "gold_decision": case.get("gold_decision"),
        "blocking_node": result["blocking_node"],
        "gold_blocking_node": case.get("gold_blocking_node"),
        "confidence": result["confidence"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
