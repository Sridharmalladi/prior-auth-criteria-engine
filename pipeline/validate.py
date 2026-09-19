"""Structural validation for criteria trees.

Pure stdlib and dict-based on purpose: this runs inside the LLM repair loop,
inside pytest, and as a pre-commit check over ``data/policies/*.json`` without
requiring pydantic to be installed.

``validate_policy`` returns a list of human-readable error strings. Empty list
means the tree is admissible. The messages are fed verbatim back to the model
during the repair loop, so they name the offending node id first.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List

OPERATOR_TYPES = {"AND", "OR", "NOT", "N_OF"}
ALL_TYPES = OPERATOR_TYPES | {"LEAF"}
NUMERIC_OPS = {">=", "<="}
SET_OPS = {"includes", "excludes"}
EQUALITY_OPS = {"==", "!="}
ALL_OPS = NUMERIC_OPS | SET_OPS | EQUALITY_OPS


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_predicate(node_id: str, predicate: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(predicate, dict):
        return ["{0}: predicate must be an object".format(node_id)]
    key = predicate.get("key")
    if not isinstance(key, str) or not key:
        errors.append("{0}: predicate.key must be a non-empty string".format(node_id))
    op = predicate.get("op")
    if op not in ALL_OPS:
        return errors + ["{0}: predicate.op {1!r} is not one of {2}".format(node_id, op, sorted(ALL_OPS))]
    if "value" not in predicate:
        return errors + ["{0}: predicate has no value".format(node_id)]
    value = predicate["value"]
    if op in NUMERIC_OPS and not _is_number(value):
        errors.append("{0}: op {1} requires a numeric value, got {2!r}".format(node_id, op, value))
    if op in SET_OPS and not isinstance(value, (str, list)):
        errors.append("{0}: op {1} requires a string or list value, got {2!r}".format(node_id, op, value))
    if op in SET_OPS and isinstance(value, list):
        if not all(isinstance(item, str) for item in value):
            errors.append("{0}: op {1} list values must all be strings".format(node_id, op))
    if op in EQUALITY_OPS and isinstance(value, list):
        errors.append("{0}: op {1} does not accept a list value; use includes/excludes".format(node_id, op))
    unit = predicate.get("unit")
    if unit is not None and not isinstance(unit, str):
        errors.append("{0}: predicate.unit must be a string or null".format(node_id))
    return errors


def _validate_node_shape(node_id: str, node: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    node_type = node.get("type")
    if node_type not in ALL_TYPES:
        return ["{0}: type {1!r} is not one of {2}".format(node_id, node_type, sorted(ALL_TYPES))]

    if not isinstance(node.get("label"), str) or not node.get("label"):
        errors.append("{0}: label must be a non-empty string".format(node_id))

    source_ref = node.get("source_ref")
    if not isinstance(source_ref, dict):
        errors.append("{0}: source_ref is required".format(node_id))
    else:
        for field in ("section", "url"):
            if not isinstance(source_ref.get(field), str) or not source_ref.get(field):
                errors.append("{0}: source_ref.{1} must be a non-empty string".format(node_id, field))

    children = node.get("children", [])
    if not isinstance(children, list) or not all(isinstance(child, str) for child in children):
        return errors + ["{0}: children must be a list of node ids".format(node_id)]

    if node_type == "LEAF":
        if children:
            errors.append("{0}: LEAF must not have children".format(node_id))
        if node.get("predicate") is None:
            errors.append("{0}: LEAF has no predicate".format(node_id))
        else:
            errors.extend(_validate_predicate(node_id, node["predicate"]))
        if node.get("n") is not None:
            errors.append("{0}: n is only meaningful on N_OF nodes".format(node_id))
        return errors

    # operator node
    if node.get("predicate") is not None:
        errors.append("{0}: operator node must not carry a predicate".format(node_id))
    if len(children) < 1:
        errors.append("{0}: {1} node has no children".format(node_id, node_type))
    if node_type in ("AND", "OR") and len(children) < 2:
        errors.append("{0}: {1} node needs at least 2 children, has {2}".format(node_id, node_type, len(children)))
    if node_type == "NOT" and len(children) != 1:
        errors.append("{0}: NOT node needs exactly 1 child, has {1}".format(node_id, len(children)))
    if node_type == "N_OF":
        n = node.get("n")
        if not isinstance(n, int) or isinstance(n, bool):
            errors.append("{0}: N_OF node needs an integer n".format(node_id))
        elif n < 1 or n > len(children):
            errors.append("{0}: N_OF n={1} outside 1..{2}".format(node_id, n, len(children)))
    elif node.get("n") is not None:
        errors.append("{0}: n is only meaningful on N_OF nodes".format(node_id))
    if len(set(children)) != len(children):
        errors.append("{0}: duplicate child ids".format(node_id))
    return errors


def _find_cycles(nodes: Dict[str, Any], root: str) -> List[str]:
    """Iterative DFS with a colour map. Returns one error per back edge found."""
    errors: List[str] = []
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict((node_id, WHITE) for node_id in nodes)
    # Walk from every node, not just the root, so detached cycles are caught too.
    for start in nodes:
        if colour[start] != WHITE:
            continue
        stack = [(start, iter(nodes[start].get("children", []) or []))]
        colour[start] = GREY
        while stack:
            parent, child_iter = stack[-1]
            advanced = False
            for child in child_iter:
                if child not in nodes:
                    continue  # reported separately as a dangling reference
                if colour[child] == GREY:
                    errors.append("cycle: {0} -> {1} closes a loop".format(parent, child))
                elif colour[child] == WHITE:
                    colour[child] = GREY
                    stack.append((child, iter(nodes[child].get("children", []) or [])))
                    advanced = True
                    break
            if not advanced:
                colour[parent] = BLACK
                stack.pop()
    return errors


def validate_policy(policy: Dict[str, Any]) -> List[str]:
    """Return a list of structural errors; empty list means the tree is valid."""
    errors: List[str] = []

    for field in ("policy_id", "title", "source_url", "root"):
        if not isinstance(policy.get(field), str) or not policy.get(field):
            errors.append("policy.{0} must be a non-empty string".format(field))
    if policy.get("source_type") not in ("NCD", "LCD"):
        errors.append("policy.source_type must be NCD or LCD")

    nodes = policy.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        return errors + ["policy.nodes must be a non-empty object"]

    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            errors.append("{0}: node must be an object".format(node_id))
            continue
        if node.get("id") != node_id:
            errors.append("{0}: node.id {1!r} does not match its key".format(node_id, node.get("id")))
        errors.extend(_validate_node_shape(node_id, node))
        for child in node.get("children", []) or []:
            if isinstance(child, str) and child not in nodes:
                errors.append("{0}: child {1!r} does not exist".format(node_id, child))

    root = policy.get("root")
    if root not in nodes:
        return errors + ["policy.root {0!r} is not a node".format(root)]

    errors.extend(_find_cycles(nodes, root))

    # Single root: exactly one node with no parent, and it must be `root`.
    referenced = set()
    for node in nodes.values():
        for child in node.get("children", []) or []:
            referenced.add(child)
    parentless = sorted(node_id for node_id in nodes if node_id not in referenced)
    if parentless != [root]:
        extra = [node_id for node_id in parentless if node_id != root]
        if root in referenced:
            errors.append("root {0} is referenced as a child; tree has no single root".format(root))
        for node_id in extra:
            errors.append("{0}: orphan node, unreachable from root".format(node_id))

    # Reachability: catches nodes that hang off a detached cycle.
    reachable = set()
    stack = [root]
    while stack:
        current = stack.pop()
        if current in reachable or current not in nodes:
            continue
        reachable.add(current)
        stack.extend(nodes[current].get("children", []) or [])
    for node_id in sorted(set(nodes) - reachable):
        message = "{0}: orphan node, unreachable from root".format(node_id)
        if message not in errors:
            errors.append(message)

    return errors


def validate_case(case: Dict[str, Any], policy: Dict[str, Any]) -> List[str]:
    """Check a case against its policy: span integrity and gold-label sanity."""
    errors: List[str] = []
    note = case.get("note_text")
    if not isinstance(note, str) or not note:
        return ["case {0}: note_text missing".format(case.get("case_id"))]
    if case.get("policy_id") != policy.get("policy_id"):
        errors.append("case {0}: policy_id does not match policy".format(case.get("case_id")))

    for fact in case.get("facts", []):
        key = fact.get("key")
        span = fact.get("source_span")
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            errors.append("case {0}/{1}: source_span must be [start, end]".format(case.get("case_id"), key))
            continue
        start, end = span
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
            errors.append("case {0}/{1}: source_span must be a forward in-range pair".format(case.get("case_id"), key))
            continue
        if note[start:end] != fact.get("evidence_text"):
            errors.append(
                "case {0}/{1}: source_span {2} indexes {3!r}, not evidence_text".format(
                    case.get("case_id"), key, list(span), note[start:end]
                )
            )
        confidence = fact.get("confidence")
        if not _is_number(confidence) or not 0.0 <= confidence <= 1.0:
            errors.append("case {0}/{1}: confidence must be in [0, 1]".format(case.get("case_id"), key))

    gold_node = case.get("gold_blocking_node")
    if gold_node is not None and gold_node not in policy.get("nodes", {}):
        errors.append("case {0}: gold_blocking_node {1!r} is not in the policy".format(case.get("case_id"), gold_node))
    if case.get("gold_decision") == "DENY" and not gold_node:
        errors.append("case {0}: denied case must name a gold_blocking_node".format(case.get("case_id")))
    if case.get("gold_decision") not in ("APPROVE", "DENY", "INDETERMINATE"):
        errors.append("case {0}: gold_decision is not a valid label".format(case.get("case_id")))
    return errors


def _main(argv: List[str]) -> int:
    if not argv:
        print("usage: python -m pipeline.validate data/policies/*.json")
        return 2
    failed = 0
    for path in argv:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
        errors = validate_policy(document)
        if errors:
            failed += 1
            print("FAIL {0}".format(path))
            for error in errors:
                print("  - {0}".format(error))
        else:
            print("ok   {0} ({1} nodes)".format(path, len(document["nodes"])))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
