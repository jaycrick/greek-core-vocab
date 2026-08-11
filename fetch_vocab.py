#!/usr/bin/env python3
"""Fetch Perseus's weighted-frequency vocabulary list for every unique
Perseus URN referenced in data/matches.yaml, caching each to
data/raw/<id>.xml (or data/raw/<id>.table.html on fallback -- see
below) and recording what actually happened per URN in
data/fetch_manifest.json.

Why a fallback ladder: `output=xml&filt=100` (every word, not just a
percentile) is unreliable for big texts -- confirmed empirically that it
504s near-instantly for the Iliad (looks like a cached negative response
rather than a real per-request timeout), while `output=table` at the
same `filt=100` succeeds in ~25s, and dropping to `filt=75`/`50` (still
XML) also succeeds. So each URN tries, in order, until one works:

    1. xml,   filt=100  (every word -- the best case)
    2. table, filt=100  (same coverage, HTML instead of XML)
    3. xml,   filt=75
    4. xml,   filt=50

Whichever succeeds is recorded in the manifest (`method`, `filt`) --
this is the transparency trail for "the Iliad's contribution is the
top 75% of its vocabulary, not literally all of it," etc. A URN already
present in the manifest with `success: true` is skipped (idempotent,
resumable); `--redo` forces every URN to be re-fetched.

Usage
-----
    uv run python3 fetch_vocab.py [--redo]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests
import yaml

MATCHES = Path("data/matches.yaml")
RAW_DIR = Path("data/raw")
MANIFEST = Path("data/fetch_manifest.json")
BASE_URL = "https://www.perseus.tufts.edu/hopper/vocablist"
UA = "greek-core-vocab/0.1 (github.com/jaycrick/greek-core-vocab)"

# (output, filt), tried in order until one works.
_LADDER = [("xml", 100), ("table", 100), ("xml", 75), ("xml", 50)]

_ATTEMPTS_PER_RUNG = 2
_RETRY_DELAY_S = 3
_POLITE_DELAY_S = 1.5


def urn_id(urn: str) -> str:
    """ "Perseus:text:1999.01.0133" -> "1999.01.0133" -- safe as a
    filename, and every URN observed shares the "Perseus:text:" prefix
    so nothing is lost by dropping it."""
    prefix = "Perseus:text:"
    if not urn.startswith(prefix):
        raise ValueError(f"unexpected URN shape (no {prefix!r} prefix): {urn!r}")
    return urn[len(prefix) :]


def cache_path(urn: str, output: str) -> Path:
    ext = "xml" if output == "xml" else "table.html"
    return RAW_DIR / f"{urn_id(urn)}.{ext}"


def looks_valid(output: str, text: str) -> bool:
    if output == "xml":
        # A full ET.fromstring() parse, not just a substring check --
        # observed at least once in practice: Perseus's server started
        # a normal-looking XML response, hit a Hibernate lazy-init
        # exception rendering one particular lemma partway through, and
        # dumped a raw Java stack trace into the body instead of
        # closing the document. That response still contains "<?xml"
        # and "<frequency>" near the top, so a substring check alone
        # accepted it as valid -- only a real parse catches it.
        import xml.etree.ElementTree as ET

        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return False
        return root.find("frequency") is not None
    return 'id="vocab_list"' in text and "<tr" in text


def fetch_one(urn: str, output: str, filt: int) -> str | None:
    params = {
        "lang": "greek",
        "works": urn,
        "sort": "weighted_freq",
        "filt": str(filt),
        "output": output,
    }
    for attempt in range(1, _ATTEMPTS_PER_RUNG + 1):
        try:
            resp = requests.get(
                BASE_URL, params=params, headers={"User-Agent": UA}, timeout=120
            )
        except requests.RequestException as e:
            print(f"    [{output} filt={filt} attempt {attempt}] request error: {e}")
            time.sleep(_RETRY_DELAY_S)
            continue
        if resp.status_code == 200 and looks_valid(output, resp.text):
            return resp.text
        print(
            f"    [{output} filt={filt} attempt {attempt}] "
            f"status={resp.status_code} valid={looks_valid(output, resp.text)}"
        )
        time.sleep(_RETRY_DELAY_S)
    return None


def fetch_urn(urn: str) -> dict:
    for output, filt in _LADDER:
        path = cache_path(urn, output)
        print(f"  trying {output} filt={filt} ...")
        text = fetch_one(urn, output, filt)
        time.sleep(_POLITE_DELAY_S)
        if text is not None:
            path.write_text(text, encoding="utf-8")
            return {
                "urn": urn,
                "success": True,
                "method": output,
                "filt": filt,
                "cache_file": str(path),
            }
    return {"urn": urn, "success": False, "method": None, "filt": None, "cache_file": None}


def unique_urns() -> list[str]:
    doc = yaml.safe_load(MATCHES.read_text(encoding="utf-8"))
    urns: set[str] = set()
    for row in doc["matches"]:
        urns.update(row["matched_urns"])
    return sorted(urns)


def load_manifest() -> dict[str, dict]:
    if not MANIFEST.is_file():
        return {}
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {e["urn"]: e for e in entries}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--redo", action="store_true", help="re-fetch every URN, ignoring cache")
    args = ap.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    urns = unique_urns()
    manifest = load_manifest()

    for i, urn in enumerate(urns, start=1):
        if not args.redo and manifest.get(urn, {}).get("success"):
            continue
        print(f"[{i}/{len(urns)}] {urn}")
        manifest[urn] = fetch_urn(urn)

    MANIFEST.write_text(
        json.dumps([manifest[u] for u in urns], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    ok = [u for u in urns if manifest[u]["success"]]
    failed = [u for u in urns if not manifest[u]["success"]]
    by_rung: dict[tuple[str, int], int] = {}
    for u in ok:
        key = (manifest[u]["method"], manifest[u]["filt"])
        by_rung[key] = by_rung.get(key, 0) + 1

    print(f"\n{len(ok)}/{len(urns)} URNs fetched successfully -> {MANIFEST}")
    for (method, filt), n in sorted(by_rung.items(), key=lambda kv: -kv[1]):
        print(f"  {n} via {method} filt={filt}")
    if failed:
        print(f"{len(failed)} FAILED (see {MANIFEST}):")
        for u in failed:
            print(f"  {u}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
