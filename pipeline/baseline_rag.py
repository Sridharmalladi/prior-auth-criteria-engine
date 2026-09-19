"""The honest ablation: flat chunk retrieval over the same policy text.

This is the system the criteria graph is being compared against, so it is built
to be beaten on the merits, not by handicap:

* Same model, same temperature, same three-class output contract.
* The prompt was written and revised to be competent. It states the three
  classes, tells the model to abstain when documentation is missing, and asks
  for a specific clause citation. That tuning is disclosed on the eval page and
  in the README.
* For the two LCD-derived policies there is no fetched text (licence-gated), so
  the baseline is given the same paraphrased criteria the criteria graph uses,
  flattened to prose. Both systems see the same material.

Chunking: ~400 tokens with 50 of overlap. Embeddings: all-MiniLM-L6-v2 via
sentence-transformers. Retrieval: cosine similarity in numpy — at eight policies
an index would be theatre.

Run: python3 pipeline/baseline_rag.py [--case <case_id>] [--model <id>]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from pipeline.parse_policy import require_key  # noqa: E402

CACHE_DIR = os.path.join(HERE, ".cache", "policies")
CASE_DIR = os.path.join(ROOT, "data", "cases")
POLICY_DIR = os.path.join(ROOT, "data", "policies")
OUT_PATH = os.path.join(ROOT, "data", "eval", "baseline_predictions.json")

DEFAULT_MODEL = os.environ.get("OPENROUTER_PARSE_MODEL", "anthropic/claude-sonnet-4.5")
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_TOKENS = 400
CHUNK_OVERLAP = 50
TOP_K = 5

# Tuned prompt. Revisions made while building it: the three classes were named
# explicitly, INDETERMINATE was defined as "the note does not document it"
# rather than "you are unsure", and the citation was required to be a quotation
# from the retrieved text rather than a summary.
BASELINE_PROMPT = """You decide whether a clinical note satisfies the coverage criteria in the policy excerpts provided.

Answer with JSON:
{"decision": "APPROVE" | "DENY" | "INDETERMINATE",
 "blocking_clause_text": "the specific criterion that is not satisfied, quoted from the excerpts, or empty if approved",
 "confidence": 0.0-1.0,
 "reasoning": "two sentences at most"}

Definitions:
- APPROVE: every applicable criterion in the excerpts is satisfied by facts documented in the note.
- DENY: at least one applicable criterion is documented in the note as not satisfied.
- INDETERMINATE: the note does not document something the criteria require, so the question
  cannot be answered from the record. Use this when information is absent, not when you are
  merely uncertain about a judgement call.

Quote the blocking criterion as specifically as you can: name the threshold and the documented
value where both appear. Consider every excerpt, and note that criteria may be nested — an
alternative ("or") is satisfied by any one branch, while a list of requirements ("and") needs
all of them."""


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def flatten_tree_to_prose(policy: Dict[str, Any]) -> str:
    """Render a criteria tree as prose, for policies whose source text is
    licence-gated. Both systems then work from the same words."""
    lines = ["{0} — coverage criteria".format(policy["title"])]

    def walk(node_id: str, depth: int) -> None:
        node = policy["nodes"][node_id]
        indent = "  " * depth
        if node["type"] == "LEAF":
            predicate = node["predicate"]
            lines.append("{0}- {1} (documented value {2} must be {3} {4}{5}). Section: {6}.".format(
                indent, node["label"], predicate["key"], predicate["op"], predicate["value"],
                " " + predicate["unit"] if predicate.get("unit") else "", node["source_ref"]["section"]))
            return
        connector = {
            "AND": "All of the following are required",
            "OR": "Any one of the following is sufficient",
            "NOT": "The following must not be the case",
            "N_OF": "At least {0} of the following are required".format(node.get("n")),
        }[node["type"]]
        lines.append("{0}- {1}: {2}. Section: {3}.".format(indent, node["label"], connector, node["source_ref"]["section"]))
        for child in node["children"]:
            walk(child, depth + 1)

    walk(policy["root"], 0)
    return "\n".join(lines)


def policy_text(policy: Dict[str, Any]) -> str:
    cached = os.path.join(CACHE_DIR, "{0}.txt".format(policy["policy_id"]))
    if os.path.exists(cached):
        with open(cached, "r", encoding="utf-8") as handle:
            return handle.read()
    return flatten_tree_to_prose(policy)


def chunk(text: str) -> List[str]:
    """~400-token windows with 50 of overlap, counted in whitespace tokens."""
    words = text.split()
    if not words:
        return []
    chunks = []
    step = CHUNK_TOKENS - CHUNK_OVERLAP
    for start in range(0, len(words), step):
        window = words[start:start + CHUNK_TOKENS]
        if not window:
            break
        chunks.append(" ".join(window))
        if start + CHUNK_TOKENS >= len(words):
            break
    return chunks


def build_query(note: str) -> str:
    """The retrieval query is the note itself, trimmed to its clinical content —
    headers and the synthetic-case banner carry no signal."""
    lines = [line for line in note.splitlines()
             if line.strip() and "SYNTHETIC TEACHING CASE" not in line]
    return " ".join(lines)[:2000]


def call_model(key: str, model: str, chunks: List[str], note: str) -> Dict[str, Any]:
    import urllib.request

    excerpts = "\n\n".join("[excerpt {0}]\n{1}".format(index + 1, text) for index, text in enumerate(chunks))
    user = "\n".join([
        "Policy excerpts:",
        excerpts,
        "",
        "Clinical note:",
        '"""',
        note,
        '"""',
    ])
    body = json.dumps({
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": BASELINE_PROMPT}, {"role": "user", "content": user}],
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={"Authorization": "Bearer {0}".format(key), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return json.loads(payload["choices"][0]["message"]["content"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="single case_id; default is all 20")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    key = require_key()
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise SystemExit("baseline needs numpy and sentence-transformers: pip install -r requirements.txt ({0})".format(error))

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

    print("embedding policy chunks with {0} ...".format(EMBED_MODEL))
    encoder = SentenceTransformer(EMBED_MODEL)
    index = {}
    for policy_id, policy in policies.items():
        chunks = chunk(policy_text(policy))
        vectors = encoder.encode(chunks, normalize_embeddings=True)
        index[policy_id] = {"chunks": chunks, "vectors": np.asarray(vectors), "from_text": os.path.exists(
            os.path.join(CACHE_DIR, "{0}.txt".format(policy_id)))}
        print("  {0:18s} {1:3d} chunks{2}".format(
            policy_id, len(chunks), "" if index[policy_id]["from_text"] else "  (from the criteria tree; LCD text is licence-gated)"))

    predictions = []
    for case in cases:
        entry = index[case["policy_id"]]
        query_vector = np.asarray(encoder.encode([build_query(case["note_text"])], normalize_embeddings=True))[0]
        similarities = entry["vectors"] @ query_vector
        order = list(reversed(similarities.argsort()))[:TOP_K]
        retrieved = [entry["chunks"][position] for position in order]

        answer = call_model(key, args.model, retrieved, case["note_text"])
        predictions.append({
            "case_id": case["case_id"],
            "policy_id": case["policy_id"],
            "decision": answer.get("decision"),
            "blocking_clause_text": answer.get("blocking_clause_text", ""),
            "confidence": answer.get("confidence"),
            "reasoning": answer.get("reasoning", ""),
            "retrieved_chunk_ranks": [int(position) for position in order],
            "top_similarity": float(similarities[order[0]]),
        })
        print("{0:24s} {1:14s} {2}".format(
            case["case_id"], str(answer.get("decision")), (answer.get("blocking_clause_text") or "")[:70]))

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump({
            "meta": {
                "model": args.model,
                "embedding_model": EMBED_MODEL,
                "chunk_tokens": CHUNK_TOKENS,
                "chunk_overlap": CHUNK_OVERLAP,
                "top_k": TOP_K,
                "prompt_tuned": True,
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
            "predictions": predictions,
        }, handle, indent=1)
        handle.write("\n")
    print("wrote {0}; now run pipeline/run_eval.py".format(os.path.relpath(OUT_PATH, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
