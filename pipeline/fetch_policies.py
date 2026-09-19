"""Fetch source policy documents from the CMS Medicare Coverage Database.

Uses the public MCD API (https://api.coverage.cms.gov/v1). No key, no scraping
of the HTML viewer.

Two kinds of document, deliberately handled differently:

* **NCDs** — full text comes back from ``/v1/data/ncd``. It is cached under
  ``pipeline/.cache/policies/`` (gitignored) and used for two things only:
  writing the criteria trees by hand, and chunking for the RAG baseline.
* **LCDs** — ``/v1/data/lcd`` answers 401 without a CMS license token, because
  LCD detail text carries embedded AMA/ADA/AHA material. That is not worked
  around. For LCD-derived policies this script records the identifier, title and
  source URL only; the criteria tree is written in our own words from the
  published policy and no verbatim LCD text is ever committed or shipped.

Run: python3 pipeline/fetch_policies.py
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

API = "https://api.coverage.cms.gov/v1"
VIEWER_NCD = "https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid={id}&ncdver={ver}"
VIEWER_LCD = "https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid={id}&ver={ver}"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE_DIR = os.path.join(HERE, ".cache", "policies")

# The eight policies this project covers. Document ids are resolved against the
# live MCD index at fetch time, so a renumbered document fails loudly instead of
# silently pointing at the wrong policy.
TARGETS = [
    {"policy_id": "lumbar_fusion", "type": "LCD", "display_id": "L37848", "expect_title": "Lumbar Spinal Fusion"},
    {"policy_id": "cgm", "type": "LCD", "display_id": "L33822", "expect_title": "Glucose Monitors"},
    {"policy_id": "bariatric_surgery", "type": "NCD", "display_id": "100.1", "expect_title": "Bariatric Surgery"},
    {"policy_id": "cochlear_implant", "type": "NCD", "display_id": "50.3", "expect_title": "Cochlear Implantation"},
    {"policy_id": "tavr", "type": "NCD", "display_id": "20.32", "expect_title": "Transcatheter Aortic Valve"},
    {"policy_id": "home_oxygen", "type": "NCD", "display_id": "240.2", "expect_title": "Home Use of Oxygen"},
    {"policy_id": "power_wheelchair", "type": "NCD", "display_id": "280.3", "expect_title": "Mobility Assistive Equipment"},
    {"policy_id": "pet_oncology", "type": "NCD", "display_id": "220.6.17", "expect_title": "Positron Emission Tomography"},
]


def get_json(url: str, timeout: int = 45) -> Dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "prior-auth-criteria-engine/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def strip_html(raw: str) -> str:
    # The API double-encodes: the JSON string contains &lt;p&gt; rather than <p>.
    # Unescape first, or stripping tags is a no-op and the entities become tags.
    text = html.unescape(raw)
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"</(p|div|li|tr|h\d)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def load_index(report: str) -> List[Dict[str, Any]]:
    return get_json("{0}/reports/{1}".format(API, report))["data"]


def resolve(target: Dict[str, Any], ncd_index: List[Dict[str, Any]], lcd_index: List[Dict[str, Any]]) -> Dict[str, Any]:
    index = ncd_index if target["type"] == "NCD" else lcd_index
    matches = [row for row in index if row.get("document_display_id") == target["display_id"]]
    if not matches:
        raise SystemExit("{0}: {1} {2} is not in the live MCD index".format(
            target["policy_id"], target["type"], target["display_id"]))
    row = max(matches, key=lambda candidate: candidate.get("document_version", 0))
    if target["expect_title"].lower() not in row.get("title", "").lower():
        raise SystemExit("{0}: {1} is now titled {2!r}; check the document before trusting the tree".format(
            target["policy_id"], target["display_id"], row.get("title")))
    return row


def fetch_ncd_text(document_id: int, version: int) -> Optional[str]:
    url = "{0}/data/ncd?ncdid={1}&ncdver={2}".format(API, document_id, version)
    payload = get_json(url)
    rows = payload.get("data") or []
    if not rows:
        return None
    row = rows[0]
    sections = [row.get("item_service_description") or "", row.get("indications_limitations") or ""]
    return strip_html("\n\n".join(sections))


def main() -> int:
    os.makedirs(CACHE_DIR, exist_ok=True)
    print("resolving document ids against the live MCD index ...")
    ncd_index = load_index("national-coverage-ncd")
    lcd_index = load_index("local-coverage-final-lcds")

    manifest = []
    for target in TARGETS:
        row = resolve(target, ncd_index, lcd_index)
        document_id = row["document_id"]
        version = row["document_version"]
        entry = {
            "policy_id": target["policy_id"],
            "source_type": target["type"],
            "display_id": target["display_id"],
            "title": row["title"],
            "document_id": document_id,
            "document_version": version,
            "retrieved_at": time.strftime("%Y-%m-%d"),
        }

        if target["type"] == "NCD":
            entry["source_url"] = VIEWER_NCD.format(id=document_id, ver=version)
            try:
                text = fetch_ncd_text(document_id, version)
            except urllib.error.HTTPError as error:
                print("  {0}: HTTP {1} fetching text".format(target["policy_id"], error.code))
                text = None
            if text:
                cache_path = os.path.join(CACHE_DIR, "{0}.txt".format(target["policy_id"]))
                with open(cache_path, "w", encoding="utf-8") as handle:
                    handle.write(text)
                entry["text_chars"] = len(text)
                entry["cached_text"] = os.path.relpath(cache_path, ROOT)
            print("  {0:18s} NCD {1:9s} v{2:<3} {3} chars".format(
                target["policy_id"], target["display_id"], version, entry.get("text_chars", 0)))
        else:
            entry["source_url"] = VIEWER_LCD.format(id=document_id, ver=version)
            # Detail text is licence-gated; record that fact rather than routing around it.
            entry["text_access"] = "licence-gated (CMS returns 401 without a licence token); criteria written in our own words"
            print("  {0:18s} LCD {1:9s} v{2:<3} metadata only (licence-gated text)".format(
                target["policy_id"], target["display_id"], version))

        manifest.append(entry)

    manifest_path = os.path.join(CACHE_DIR, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    print("wrote {0}".format(os.path.relpath(manifest_path, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
