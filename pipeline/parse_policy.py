"""LLM policy parsing: fetch -> segment -> parse -> validate -> repair -> emit.

What this script is for
-----------------------
The trees under ``data/policies/`` were written by hand (see
``build_policies.py``). This script runs the same job through a model and writes
its output to ``data/policies/generated/``. Use ``--diff`` to compare the two.

That ordering is deliberate. A generated tree that disagrees with the reviewed
one is a finding either way: either the model missed a scope trap, or the hand
tree did. Treating the model's output as the source of truth would make the
hand review — the highest-value step in this project — unfalsifiable.

Requires OPENROUTER_API_KEY in .env, and the NCD text cache from
``fetch_policies.py``. LCDs are skipped: their detail text is licence-gated.

Run:
    python3 pipeline/parse_policy.py --policy home_oxygen
    python3 pipeline/parse_policy.py --all --diff
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from pipeline.validate import validate_policy  # noqa: E402

CACHE_DIR = os.path.join(HERE, ".cache", "policies")
OUT_DIR = os.path.join(ROOT, "data", "policies", "generated")
REFERENCE_DIR = os.path.join(ROOT, "data", "policies")

DEFAULT_MODEL = os.environ.get("OPENROUTER_PARSE_MODEL", "anthropic/claude-sonnet-4.5")
MAX_REPAIRS = 3

NODE_SCHEMA = {
    "type": "object",
    "required": ["policy_id", "title", "root", "nodes"],
    "properties": {
        "policy_id": {"type": "string"},
        "title": {"type": "string"},
        "root": {"type": "string"},
        "nodes": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["id", "type", "label", "source_ref"],
                "properties": {
                    "id": {"type": "string"},
                    "type": {"enum": ["AND", "OR", "NOT", "N_OF", "LEAF"]},
                    "n": {"type": ["integer", "null"]},
                    "children": {"type": "array", "items": {"type": "string"}},
                    "label": {"type": "string"},
                    "source_ref": {
                        "type": "object",
                        "required": ["section", "url"],
                        "properties": {"section": {"type": "string"}, "url": {"type": "string"}},
                    },
                    "predicate": {
                        "type": ["object", "null"],
                        "required": ["key", "op", "value"],
                        "properties": {
                            "key": {"type": "string"},
                            "op": {"enum": [">=", "<=", "==", "!=", "includes", "excludes"]},
                            "value": {},
                            "unit": {"type": ["string", "null"]},
                        },
                    },
                },
            },
        },
    },
}

SYSTEM_PROMPT = """You convert published coverage policy text into an explicit boolean criteria tree.

Node types: AND, OR, NOT, N_OF (with n), LEAF (with a predicate).
Predicate operators: >=, <=, ==, !=, includes, excludes.

Rules:
- Make every operator explicit. Never flatten a nested requirement into a list of ANDs.
- One requirement per LEAF. A leaf that needs two measurements is two leaves under an AND.
- Every node needs a source_ref naming the section of the policy it came from.
- Use snake_case fact keys that a clinician would recognise, and give numeric leaves a unit.

Scope traps to resolve explicitly, because policy prose hides structure in them:
- "including": decide whether the list enumerates required sub-items (AND) or gives
  examples of one category (a single LEAF). Say which in the node label.
- "unless" / "except" / "non-covered": these are NOT branches, not extra AND conditions.
- An "or" inside an "and" list: bind it to the correct subtree. Getting this wrong
  turns an alternative into a requirement.
- Duration and threshold qualifiers: attach them to the one modality they modify, not
  to its siblings. "X during exercise for a patient whose resting value is Y" is an AND
  of two leaves inside the exercise branch, not a condition on the whole tree.
- "at least one of the following": N_OF with n=1, not OR, when the source counts items.

Return JSON only, matching the schema given."""


def load_env() -> None:
    env_path = os.path.join(ROOT, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require_key() -> str:
    load_env()
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY is not set. Copy .env.example to .env and fill it in.")
    return key


# ---------------------------------------------------------------------------
# graph nodes
# ---------------------------------------------------------------------------

def node_fetch(state: Dict[str, Any]) -> Dict[str, Any]:
    path = os.path.join(CACHE_DIR, "{0}.txt".format(state["policy_id"]))
    if not os.path.exists(path):
        raise SystemExit("no cached text for {0}; run pipeline/fetch_policies.py first "
                         "(LCD text is licence-gated and cannot be parsed this way)".format(state["policy_id"]))
    with open(path, "r", encoding="utf-8") as handle:
        state["text"] = handle.read()
    return state


def node_segment(state: Dict[str, Any]) -> Dict[str, Any]:
    """Split on the lettered/numbered section headings NCDs use, so the model is
    asked about coverage criteria rather than the whole document."""
    text = state["text"]
    pattern = re.compile(r"^\s*([A-Z]\.\s*[A-Z][^\n]{0,80}|\d+\.\s+[A-Z][^\n]{0,80})$", re.M)
    marks = [(match.start(), match.group(1).strip()) for match in pattern.finditer(text)]
    sections = []
    for index, (start, heading) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(text)
        sections.append({"heading": heading, "body": text[start:end].strip()})
    if not sections:
        sections = [{"heading": "full text", "body": text}]

    keep = [section for section in sections
            if re.search(r"cover|indication|criteri|qualif|limitation", section["heading"], re.I)]
    state["sections"] = keep or sections
    return state


def call_model(key: str, model: str, messages: List[Dict[str, str]]) -> str:
    import urllib.request

    body = json.dumps({
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": messages,
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={"Authorization": "Bearer {0}".format(key), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"]


def node_parse(state: Dict[str, Any]) -> Dict[str, Any]:
    body = "\n\n".join("## {0}\n{1}".format(section["heading"], section["body"])
                       for section in state["sections"])
    user = "\n".join([
        "Policy id: {0}".format(state["policy_id"]),
        "Title: {0}".format(state["title"]),
        "Source URL for every source_ref: {0}".format(state["source_url"]),
        "",
        "JSON schema:",
        json.dumps(NODE_SCHEMA),
        "",
        "Policy text:",
        body,
    ])
    content = call_model(state["key"], state["model"],
                         [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}])
    state["candidate"] = json.loads(content)
    return state


def node_validate(state: Dict[str, Any]) -> Dict[str, Any]:
    candidate = state["candidate"]
    candidate.setdefault("policy_id", state["policy_id"])
    candidate.setdefault("title", state["title"])
    candidate.setdefault("source_url", state["source_url"])
    candidate.setdefault("source_type", state["source_type"])
    state["errors"] = validate_policy(candidate)
    return state


def offending_subtree(candidate: Dict[str, Any], errors: List[str]) -> Dict[str, Any]:
    """Feed back only the nodes the errors name, so the repair turn stays small."""
    named = set()
    for error in errors:
        for node_id in candidate.get("nodes", {}):
            if node_id in error:
                named.add(node_id)
    if not named:
        return candidate.get("nodes", {})
    subtree = {}
    for node_id in named:
        node = candidate["nodes"][node_id]
        subtree[node_id] = node
        for child in node.get("children", []) or []:
            if child in candidate["nodes"]:
                subtree[child] = candidate["nodes"][child]
    return subtree


def node_repair(state: Dict[str, Any]) -> Dict[str, Any]:
    state["attempts"] = state.get("attempts", 0) + 1
    user = "\n".join([
        "The tree you returned failed structural validation.",
        "",
        "Errors:",
        "\n".join("- {0}".format(error) for error in state["errors"]),
        "",
        "The nodes the errors name:",
        json.dumps(offending_subtree(state["candidate"], state["errors"]), indent=1),
        "",
        "Return the complete corrected policy JSON, not a fragment.",
    ])
    content = call_model(state["key"], state["model"], [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "assistant", "content": json.dumps(state["candidate"])},
        {"role": "user", "content": user},
    ])
    state["candidate"] = json.loads(content)
    return state


def node_emit(state: Dict[str, Any]) -> Dict[str, Any]:
    os.makedirs(OUT_DIR, exist_ok=True)
    candidate = state["candidate"]
    candidate["provenance"] = "generated by {0} via parse_policy.py; not hand reviewed".format(state["model"])
    candidate["verification"] = "machine-generated"
    path = os.path.join(OUT_DIR, "{0}.json".format(state["policy_id"]))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(candidate, handle, indent=1)
        handle.write("\n")
    state["path"] = path
    return state


def build_graph():
    """LangGraph wiring when it is installed; the same flow runs without it."""
    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        return None

    graph = StateGraph(dict)
    graph.add_node("fetch", node_fetch)
    graph.add_node("segment", node_segment)
    graph.add_node("parse", node_parse)
    graph.add_node("validate", node_validate)
    graph.add_node("repair", node_repair)
    graph.add_node("emit", node_emit)

    graph.set_entry_point("fetch")
    graph.add_edge("fetch", "segment")
    graph.add_edge("segment", "parse")
    graph.add_edge("parse", "validate")
    graph.add_conditional_edges(
        "validate",
        lambda state: "emit" if not state["errors"]
        else ("repair" if state.get("attempts", 0) < MAX_REPAIRS else "emit"),
        {"emit": "emit", "repair": "repair"},
    )
    graph.add_edge("repair", "validate")
    graph.add_edge("emit", END)
    return graph.compile()


def run_without_langgraph(state: Dict[str, Any]) -> Dict[str, Any]:
    state = node_fetch(state)
    state = node_segment(state)
    state = node_parse(state)
    state = node_validate(state)
    while state["errors"] and state.get("attempts", 0) < MAX_REPAIRS:
        state = node_repair(state)
        state = node_validate(state)
    return node_emit(state)


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------

def summarise(policy: Dict[str, Any]) -> Dict[str, Any]:
    counts = {}
    for node in policy["nodes"].values():
        counts[node["type"]] = counts.get(node["type"], 0) + 1
    keys = sorted({node["predicate"]["key"] for node in policy["nodes"].values() if node["type"] == "LEAF"})
    return {"counts": counts, "keys": keys}


def diff_one(policy_id: str) -> None:
    generated_path = os.path.join(OUT_DIR, "{0}.json".format(policy_id))
    reference_path = os.path.join(REFERENCE_DIR, "{0}.json".format(policy_id))
    if not os.path.exists(generated_path):
        print("{0}: no generated tree yet".format(policy_id))
        return
    with open(generated_path, "r", encoding="utf-8") as handle:
        generated = json.load(handle)
    with open(reference_path, "r", encoding="utf-8") as handle:
        reference = json.load(handle)

    left = summarise(reference)
    right = summarise(generated)
    print("\n{0}".format(policy_id))
    print("  node types  hand={0}  generated={1}".format(left["counts"], right["counts"]))
    missing = [key for key in left["keys"] if key not in right["keys"]]
    extra = [key for key in right["keys"] if key not in left["keys"]]
    if missing:
        print("  keys only in the hand tree:      {0}".format(", ".join(missing)))
    if extra:
        print("  keys only in the generated tree: {0}".format(", ".join(extra)))
    if not missing and not extra:
        print("  same fact keys in both trees")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", help="policy_id to parse")
    parser.add_argument("--all", action="store_true", help="parse every NCD-derived policy")
    parser.add_argument("--diff", action="store_true", help="compare generated trees with the hand-written ones")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    manifest_path = os.path.join(CACHE_DIR, "manifest.json")
    if not os.path.exists(manifest_path):
        raise SystemExit("run pipeline/fetch_policies.py first")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = {entry["policy_id"]: entry for entry in json.load(handle)}

    targets = []
    if args.all:
        targets = [entry for entry in manifest.values() if entry["source_type"] == "NCD"]
    elif args.policy:
        if args.policy not in manifest:
            raise SystemExit("unknown policy {0}".format(args.policy))
        targets = [manifest[args.policy]]
    elif args.diff:
        targets = [entry for entry in manifest.values() if entry["source_type"] == "NCD"]
    else:
        parser.error("pass --policy, --all or --diff")

    if not args.diff:
        key = require_key()
        graph = build_graph()
        for entry in targets:
            print("parsing {0} with {1} ...".format(entry["policy_id"], args.model))
            state = {
                "policy_id": entry["policy_id"],
                "title": entry["title"],
                "source_url": entry["source_url"],
                "source_type": entry["source_type"],
                "model": args.model,
                "key": key,
                "attempts": 0,
            }
            result = graph.invoke(state) if graph else run_without_langgraph(state)
            errors = result.get("errors") or []
            status = "valid" if not errors else "STILL INVALID after {0} repair(s)".format(result.get("attempts", 0))
            print("  {0} -> {1} ({2})".format(entry["policy_id"], os.path.relpath(result["path"], ROOT), status))
            for error in errors[:5]:
                print("    - {0}".format(error))

    if args.diff:
        print("\nHand-written tree vs generated tree. Differences are findings, not errors:")
        for entry in targets:
            diff_one(entry["policy_id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
