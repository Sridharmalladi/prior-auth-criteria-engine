"""Score both systems over the 20 cases and write data/eval/*.json.

Four measures, computed identically for the structured evaluator and for the
RAG baseline:

1. Decision accuracy over three classes, with the full confusion matrix.
2. Clause attribution accuracy — of the cases correctly denied, the fraction
   that name the correct blocking node. For the baseline, its free-text citation
   is mapped to a node by best string match against node labels; that mapping is
   generous to the baseline and is described in the README.
3. Calibration — 10 bins of predicted confidence against observed correctness.
4. Abstention quality — precision and recall on the INDETERMINATE class alone.

The baseline half only appears if ``data/eval/baseline_predictions.json`` exists
(written by ``baseline_rag.py``, which needs an API key). Without it the eval
page says the baseline has not been run rather than showing an invented number.

Run: python3 pipeline/run_eval.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from pipeline.evaluate import evaluate  # noqa: E402

POLICY_DIR = os.path.join(ROOT, "data", "policies")
CASE_DIR = os.path.join(ROOT, "data", "cases")
EVAL_DIR = os.path.join(ROOT, "data", "eval")
BASELINE_PREDICTIONS = os.path.join(EVAL_DIR, "baseline_predictions.json")
EXTRACTED_FACTS = os.path.join(EVAL_DIR, "extracted_facts.json")

LABELS = ["APPROVE", "DENY", "INDETERMINATE"]
BIN_COUNT = 10


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_all() -> Dict[str, Any]:
    policies = {}
    for name in sorted(os.listdir(POLICY_DIR)):
        if name.endswith(".json"):
            policy = load_json(os.path.join(POLICY_DIR, name))
            policies[policy["policy_id"]] = policy
    cases = []
    for name in sorted(os.listdir(CASE_DIR)):
        if name.endswith(".json"):
            cases.append(load_json(os.path.join(CASE_DIR, name)))
    return {"policies": policies, "cases": cases}


# ---------------------------------------------------------------------------
# baseline citation -> node id, deliberately generous
# ---------------------------------------------------------------------------

def normalise(text: str) -> List[str]:
    return [token for token in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(token) > 2]


def map_citation_to_node(citation: str, policy: Dict[str, Any]) -> Optional[str]:
    """Map the baseline's free-text citation onto a node id.

    Token overlap against every node's label, its predicate key and its section,
    with the best scoring node winning. Operator nodes are included, and a single
    shared token is enough to score, so this errs in the baseline's favour: a
    citation that merely mentions the right subject gets credit.
    """
    if not citation:
        return None
    citation_tokens = set(normalise(citation))
    if not citation_tokens:
        return None

    best_node = None
    best_score = 0.0
    for node_id, node in policy["nodes"].items():
        node_tokens = set(normalise(node["label"]))
        node_tokens |= set(normalise(node_id))
        node_tokens |= set(normalise(node.get("source_ref", {}).get("section", "")))
        if node["type"] == "LEAF":
            node_tokens |= set(normalise(node["predicate"]["key"]))
        overlap = len(citation_tokens & node_tokens)
        if not overlap:
            continue
        score = overlap / float(len(node_tokens) ** 0.5 or 1)
        if score > best_score:
            best_score = score
            best_node = node_id
    return best_node


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def confusion_matrix(pairs: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    matrix = dict((gold, dict((pred, 0) for pred in LABELS)) for gold in LABELS)
    for row in pairs:
        if row["predicted"] in LABELS:
            matrix[row["gold"]][row["predicted"]] += 1
    return matrix


def decision_accuracy(pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    correct = sum(1 for row in pairs if row["predicted"] == row["gold"])
    return {
        "correct": correct,
        "total": len(pairs),
        "accuracy": round(correct / float(len(pairs)), 4) if pairs else 0.0,
        "confusion": confusion_matrix(pairs),
    }


def attribution_accuracy(pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Of the cases correctly called DENY, how many name the right clause."""
    eligible = [row for row in pairs
                if row["gold"] == "DENY" and row["predicted"] == "DENY" and row.get("gold_blocking_node")]
    hits = [row for row in eligible if row.get("predicted_blocking_node") == row["gold_blocking_node"]]
    return {
        "correct": len(hits),
        "total": len(eligible),
        "accuracy": round(len(hits) / float(len(eligible)), 4) if eligible else None,
        "misses": [
            {"case_id": row["case_id"], "expected": row["gold_blocking_node"], "got": row.get("predicted_blocking_node")}
            for row in eligible if row not in hits
        ],
    }


def calibration(pairs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    bins = []
    for index in range(BIN_COUNT):
        low = index / float(BIN_COUNT)
        high = (index + 1) / float(BIN_COUNT)
        members = [row for row in pairs
                   if row.get("confidence") is not None
                   and (low <= row["confidence"] < high or (index == BIN_COUNT - 1 and row["confidence"] == 1.0))]
        correct = sum(1 for row in members if row["predicted"] == row["gold"])
        bins.append({
            "bin_low": round(low, 2),
            "bin_high": round(high, 2),
            "count": len(members),
            "mean_confidence": round(sum(row["confidence"] for row in members) / float(len(members)), 4) if members else None,
            "observed_accuracy": round(correct / float(len(members)), 4) if members else None,
        })
    return bins


def abstention_quality(pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    predicted = [row for row in pairs if row["predicted"] == "INDETERMINATE"]
    actual = [row for row in pairs if row["gold"] == "INDETERMINATE"]
    hits = [row for row in predicted if row["gold"] == "INDETERMINATE"]
    precision = len(hits) / float(len(predicted)) if predicted else None
    recall = len(hits) / float(len(actual)) if actual else None
    f1 = None
    if precision and recall and (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)
    return {
        "predicted_count": len(predicted),
        "actual_count": len(actual),
        "true_positives": len(hits),
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
    }


def score(pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "decision": decision_accuracy(pairs),
        "attribution": attribution_accuracy(pairs),
        "calibration": calibration(pairs),
        "abstention": abstention_quality(pairs),
    }


# ---------------------------------------------------------------------------
# diagnosis lines for failures.json
# ---------------------------------------------------------------------------

def diagnose(row: Dict[str, Any], case: Dict[str, Any], policy: Dict[str, Any]) -> str:
    if row["predicted"] != row["gold"]:
        return "decision {0}, expected {1}: {2}".format(
            row["predicted"], row["gold"],
            case.get("note_on_gold") or "check the fact list against the note")
    node_id = row.get("predicted_blocking_node")
    gold_node = row.get("gold_blocking_node")
    node_label = policy["nodes"].get(node_id, {}).get("label", node_id)
    gold_label = policy["nodes"].get(gold_node, {}).get("label", gold_node)
    return "right verdict, wrong clause: cited {0!r}, a reviewer would cite {1!r}".format(node_label, gold_label)


def main() -> int:
    data = load_all()
    policies = data["policies"]
    cases = data["cases"]
    os.makedirs(EVAL_DIR, exist_ok=True)

    structured_rows = []
    per_case = []
    for case in cases:
        policy = policies[case["policy_id"]]
        result = evaluate(policy, case["facts"])
        row = {
            "case_id": case["case_id"],
            "policy_id": case["policy_id"],
            "title": case["title"],
            "gold": case["gold_decision"],
            "gold_blocking_node": case.get("gold_blocking_node"),
            "predicted": result["decision"],
            "predicted_blocking_node": result["blocking_node"],
            "confidence": result["confidence"],
        }
        structured_rows.append(row)
        per_case.append({"structured": row})

    # If extract_facts.py has been run, score the same trees on model-extracted
    # facts as well. Gold-fact accuracy measures the coverage logic; this one
    # measures the whole pipeline, and the gap between them is the extraction
    # error the first number hides.
    extracted_rows = None
    extracted_meta = None
    if os.path.exists(EXTRACTED_FACTS):
        payload = load_json(EXTRACTED_FACTS)
        extracted_meta = payload.get("meta")
        by_case = dict((item["case_id"], item) for item in payload["cases"])
        extracted_rows = []
        for case in cases:
            policy = policies[case["policy_id"]]
            entry = by_case.get(case["case_id"])
            if entry is None:
                continue
            result = evaluate(policy, entry["facts"])
            extracted_rows.append({
                "case_id": case["case_id"],
                "policy_id": case["policy_id"],
                "title": case["title"],
                "gold": case["gold_decision"],
                "gold_blocking_node": case.get("gold_blocking_node"),
                "predicted": result["decision"],
                "predicted_blocking_node": result["blocking_node"],
                "confidence": result["confidence"],
            })
        for index, row in enumerate(extracted_rows):
            per_case[index]["structured_extracted"] = row

    baseline_rows = None
    baseline_meta = None
    if os.path.exists(BASELINE_PREDICTIONS):
        payload = load_json(BASELINE_PREDICTIONS)
        baseline_meta = payload.get("meta")
        by_case = dict((item["case_id"], item) for item in payload["predictions"])
        baseline_rows = []
        for case in cases:
            policy = policies[case["policy_id"]]
            prediction = by_case.get(case["case_id"], {})
            citation = prediction.get("blocking_clause_text", "")
            baseline_rows.append({
                "case_id": case["case_id"],
                "policy_id": case["policy_id"],
                "title": case["title"],
                "gold": case["gold_decision"],
                "gold_blocking_node": case.get("gold_blocking_node"),
                "predicted": prediction.get("decision"),
                "predicted_blocking_node": map_citation_to_node(citation, policy),
                "blocking_clause_text": citation,
                "confidence": prediction.get("confidence"),
            })
        for index, row in enumerate(baseline_rows):
            per_case[index]["baseline"] = row

    metrics = {
        "n_cases": len(cases),
        "n_policies": len(policies),
        "systems": {"structured": score(structured_rows)},
        "baseline_status": "not run — data/eval/baseline_predictions.json is absent",
        "notes": [
            "n = {0}. This is a small sample; the intervals around every number below are wide.".format(len(cases)),
            "Decision accuracy for the criteria graph is computed on hand-labelled gold facts, so it "
            "measures the coverage logic rather than end-to-end extraction.",
            "Cases are synthetic and were written by the author of the system being measured.",
            "Confidence is rule-derived, not calibrated against payer outcomes.",
            "Baseline citations are mapped to nodes by token overlap, which is generous to the baseline.",
        ],
    }
    if extracted_rows:
        metrics["systems"]["structured_extracted"] = score(extracted_rows)
        metrics["extracted_meta"] = extracted_meta
    if baseline_rows is not None:
        metrics["systems"]["baseline"] = score(baseline_rows)
        metrics["baseline_status"] = "run"
        metrics["baseline_meta"] = baseline_meta

    failures = []
    for row in structured_rows:
        case = next(item for item in cases if item["case_id"] == row["case_id"])
        policy = policies[row["policy_id"]]
        wrong_decision = row["predicted"] != row["gold"]
        wrong_clause = (row["gold_blocking_node"]
                        and row["predicted_blocking_node"] != row["gold_blocking_node"])
        if wrong_decision or wrong_clause:
            failures.append({
                "case_id": row["case_id"],
                "title": row["title"],
                "policy_id": row["policy_id"],
                "kind": "decision" if wrong_decision else "attribution",
                "gold_decision": row["gold"],
                "predicted_decision": row["predicted"],
                "gold_blocking_node": row["gold_blocking_node"],
                "predicted_blocking_node": row["predicted_blocking_node"],
                "diagnosis": diagnose(row, case, policy),
            })

    with open(os.path.join(EVAL_DIR, "metrics.json"), "w", encoding="utf-8") as handle:
        json.dump(metrics, handle, indent=1)
        handle.write("\n")
    with open(os.path.join(EVAL_DIR, "results.json"), "w", encoding="utf-8") as handle:
        json.dump(per_case, handle, indent=1)
        handle.write("\n")
    with open(os.path.join(EVAL_DIR, "failures.json"), "w", encoding="utf-8") as handle:
        json.dump(failures, handle, indent=1)
        handle.write("\n")

    structured = metrics["systems"]["structured"]
    print("structured: decision {0}/{1} = {2:.2f}".format(
        structured["decision"]["correct"], structured["decision"]["total"], structured["decision"]["accuracy"]))
    attribution = structured["attribution"]
    if attribution["accuracy"] is None:
        print("structured: attribution n/a (no correctly denied cases)")
    else:
        print("structured: attribution {0}/{1} = {2:.2f}".format(
            attribution["correct"], attribution["total"], attribution["accuracy"]))
    abstention = structured["abstention"]
    print("structured: abstention precision {0} recall {1}".format(abstention["precision"], abstention["recall"]))
    print("{0} failure(s) written to data/eval/failures.json".format(len(failures)))
    if extracted_rows:
        extracted = metrics["systems"]["structured_extracted"]
        print("structured on extracted facts: decision {0}/{1} = {2:.2f}".format(
            extracted["decision"]["correct"], extracted["decision"]["total"], extracted["decision"]["accuracy"]))
    print("baseline: {0}".format(metrics["baseline_status"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
