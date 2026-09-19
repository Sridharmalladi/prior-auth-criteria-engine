"""Copy data/ into docs/data/ so GitHub Pages can serve it.

GitHub Pages serves a single directory. ``data/`` is the canonical location —
the pipeline writes there and the tests read from there — so the site gets a
copy, written by this script and checked by CI. Nothing is edited under
``docs/data``; it is a build output.

Run: python3 pipeline/sync_docs_data.py [--check]
"""

from __future__ import annotations

import filecmp
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SOURCE = os.path.join(ROOT, "data")
DESTINATION = os.path.join(ROOT, "docs", "data")
SUBDIRS = ["policies", "cases", "eval", "parity"]


def files_in(base: str) -> list:
    found = []
    for subdir in SUBDIRS:
        directory = os.path.join(base, subdir)
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if name.endswith(".json"):
                found.append(os.path.join(subdir, name))
    return sorted(found)


def build_manifest() -> dict:
    """The browser cannot list a directory, so the site gets an index of what
    is available: one entry per case, one per policy."""
    cases = []
    for name in sorted(os.listdir(os.path.join(SOURCE, "cases"))):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(SOURCE, "cases", name), "r", encoding="utf-8") as handle:
            case = json.load(handle)
        cases.append({
            "case_id": case["case_id"],
            "policy_id": case["policy_id"],
            "title": case["title"],
            "gold_decision": case["gold_decision"],
        })
    policies = []
    for name in sorted(os.listdir(os.path.join(SOURCE, "policies"))):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(SOURCE, "policies", name), "r", encoding="utf-8") as handle:
            policy = json.load(handle)
        policies.append({
            "policy_id": policy["policy_id"],
            "title": policy["title"],
            "source_type": policy["source_type"],
            "source_url": policy["source_url"],
            "verification": policy.get("verification", ""),
            "node_count": len(policy["nodes"]),
        })
    return {"cases": cases, "policies": policies}


def main(argv: list) -> int:
    check_only = "--check" in argv
    source_files = files_in(SOURCE)
    if not source_files:
        print("no data to sync; run the build scripts first")
        return 1

    stale = []
    for relative in source_files:
        source_path = os.path.join(SOURCE, relative)
        destination_path = os.path.join(DESTINATION, relative)
        if not os.path.exists(destination_path) or not filecmp.cmp(source_path, destination_path, shallow=False):
            stale.append(relative)
            if not check_only:
                os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                shutil.copyfile(source_path, destination_path)

    extra = [relative for relative in files_in(DESTINATION) if relative not in source_files]
    for relative in extra:
        if not check_only:
            os.remove(os.path.join(DESTINATION, relative))

    if check_only:
        if stale or extra:
            print("docs/data is out of date; run python3 pipeline/sync_docs_data.py")
            for relative in stale:
                print("  stale: {0}".format(relative))
            for relative in extra:
                print("  extra: {0}".format(relative))
            return 1
        print("docs/data is in sync ({0} files)".format(len(source_files)))
        return 0

    manifest_path = os.path.join(DESTINATION, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(build_manifest(), handle, indent=1)
        handle.write("\n")

    total_bytes = sum(os.path.getsize(os.path.join(DESTINATION, relative)) for relative in source_files)
    print("synced {0} files to docs/data ({1:.1f} KB)".format(len(source_files), total_bytes / 1024.0))
    if stale:
        print("  updated: {0}".format(", ".join(stale[:6]) + (" ..." if len(stale) > 6 else "")))
    if extra:
        print("  removed: {0}".format(", ".join(extra)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
