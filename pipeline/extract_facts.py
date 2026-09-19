"""Extract facts from notes with a cheap model, verifying every span.

Two properties matter more than accuracy here:

* **A fact whose evidence cannot be found verbatim in the note is dropped.** Not
  repaired, not kept with a lower confidence — dropped. An unverifiable span is
  an unverifiable fact.
* **Absence is never filled in.** The model is told to omit a key it cannot
  support, because UNKNOWN is a meaningful state downstream: it is what turns a
  case into an abstention instead of a denial.

Output goes to ``data/eval/extracted_facts.json``. It does not overwrite the
hand-labelled facts in ``data/cases/``; those stay the gold standard. Score the
extracted facts with ``python3 pipeline/run_eval.py --facts extracted``.

Run: python3 pipeline/extract_facts.py [--case <case_id>] [--model <id>]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from pipeline.parse_policy import require_key  # noqa: E402

CASE_DIR = os.path.join(ROOT, "data", "cases")
POLICY_DIR = os.path.join(ROOT, "data", "policies")
OUT_PATH = os.path.join(ROOT, "data", "eval", "extracted_facts.json")

DEFAULT_MODEL = os.environ.get("OPENROUTER_EXTRACT_MODEL", "anthropic/claude-haiku-4.5")

PROMPT = """You extract structured facts from a clinical note. You do not decide coverage.

Return JSON: {"facts": [{"key": ..., "value": ..., "unit": ..., "confidence": 0-1, "evidence_text": ...}]}

Rules:
- Use only the keys listed below. Match the expected type exactly.
- evidence_text must be copied from the note character for character, including punctuation.
  It is checked against the note and any fact that fails the check is discarded.
- Never infer a value to fill a key. If the note does not document it, omit the key.
  A missing key is a meaningful signal downstream; a guessed value destroys it.
- A documented negative is a fact, not an omission: "no middle ear infection" is value false.
- Report the value as documented, without converting it to what the policy asks for."""


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def keys_for_policy(policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    seen = {}
    for node in policy["nodes"].values():
        if node["type"] != "LEAF":
            continue
        predicate = node["predicate"]
        if predicate["key"] in seen:
            continue
        value = predicate["value"]
        expects = ("array of strings" if isinstance(value, list)
                   else "boolean" if isinstance(value, bool)
                   else "number" if isinstance(value, (int, float))
                   else "string")
        seen[predicate["key"]] = {
            "key": predicate["key"],
            "expects": expects,
            "unit": predicate.get("unit"),
            "asked_by": node["label"],
        }
    return list(seen.values())


def verify(facts: List[Dict[str, Any]], note: str, allowed: set) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    kept = []
    dropped = []
    for fact in facts or []:
        key = fact.get("key")
        evidence = fact.get("evidence_text")
        if key not in allowed:
            dropped.append({"key": str(key), "reason": "key is not in this policy"})
            continue
        if not isinstance(evidence, str) or not evidence:
            dropped.append({"key": key, "reason": "no evidence_text"})
            continue
        index = note.find(evidence)
        if index == -1:
            dropped.append({"key": key, "reason": "evidence_text is not in the note verbatim"})
            continue
        if note.find(evidence, index + 1) != -1:
            # Ambiguous evidence still gets a span, but the first occurrence is
            # recorded and the ambiguity is reported.
            dropped.append({"key": key, "reason": "evidence appears more than once; first occurrence used"})
        kept.append({
            "key": key,
            "value": fact.get("value"),
            "unit": fact.get("unit"),
            "confidence": fact.get("confidence") if isinstance(fact.get("confidence"), (int, float)) else 0.5,
            "source_span": [index, index + len(evidence)],
            "evidence_text": evidence,
        })
    return kept, dropped


def call_model(key: str, model: str, policy: Dict[str, Any], note: str) -> Dict[str, Any]:
    import urllib.request

    user = "\n".join([
        "Keys for policy {0}:".format(policy["policy_id"]),
        json.dumps(keys_for_policy(policy), indent=1),
        "",
        "Note:",
        '"""',
        note,
        '"""',
    ])
    body = json.dumps({
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": user}],
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={"Authorization": "Bearer {0}".format(key), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return json.loads(payload["choices"][0]["message"]["content"])


def compare_with_gold(extracted: List[Dict[str, Any]], gold: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Key-level agreement against the hand labels: what was found, missed, invented."""
    extracted_by_key = {fact["key"]: fact for fact in extracted}
    gold_by_key = {fact["key"]: fact for fact in gold}
    agree = [key for key in gold_by_key if key in extracted_by_key
             and json.dumps(extracted_by_key[key]["value"], sort_keys=True) == json.dumps(gold_by_key[key]["value"], sort_keys=True)]
    wrong_value = [key for key in gold_by_key if key in extracted_by_key and key not in agree]
    missed = [key for key in gold_by_key if key not in extracted_by_key]
    invented = [key for key in extracted_by_key if key not in gold_by_key]
    return {"agree": agree, "wrong_value": wrong_value, "missed": missed, "not_in_gold": invented}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="single case_id; default is all 20")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    key = require_key()
    policies = {}
    for name in sorted(os.listdir(POLICY_DIR)):
        if name.endswith(".json"):
            policy = load_json(os.path.join(POLICY_DIR, name))
            policies[policy["policy_id"]] = policy

    cases = []
    for name in sorted(os.listdir(CASE_DIR)):
        if not name.endswith(".json"):
            continue
        case = load_json(os.path.join(CASE_DIR, name))
        if args.case and case["case_id"] != args.case:
            continue
        cases.append(case)

    results = []
    for case in cases:
        policy = policies[case["policy_id"]]
        allowed = {entry["key"] for entry in keys_for_policy(policy)}
        payload = call_model(key, args.model, policy, case["note_text"])
        kept, dropped = verify(payload.get("facts"), case["note_text"], allowed)
        comparison = compare_with_gold(kept, case["facts"])
        results.append({
            "case_id": case["case_id"],
            "policy_id": case["policy_id"],
            "facts": kept,
            "dropped": dropped,
            "vs_gold": comparison,
        })
        print("{0:24s} kept {1:2d}  dropped {2:2d}  agree {3:2d}  wrong {4:2d}  missed {5:2d}".format(
            case["case_id"], len(kept), len(dropped),
            len(comparison["agree"]), len(comparison["wrong_value"]), len(comparison["missed"])))

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump({
            "meta": {"model": args.model, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "n_cases": len(results)},
            "cases": results,
        }, handle, indent=1)
        handle.write("\n")

    total_gold = sum(len(item["vs_gold"]["agree"]) + len(item["vs_gold"]["wrong_value"]) + len(item["vs_gold"]["missed"])
                     for item in results)
    total_agree = sum(len(item["vs_gold"]["agree"]) for item in results)
    if total_gold:
        print("\nkey-level agreement with the hand labels: {0}/{1} = {2:.2f}".format(
            total_agree, total_gold, total_agree / float(total_gold)))
    print("wrote {0}".format(os.path.relpath(OUT_PATH, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
