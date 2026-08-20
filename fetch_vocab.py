#!/usr/bin/env python3
"""Fetch vocab.perseus.org's word list for every work data/matches.yaml
matched, caching each to data/raw/<safe-urn>.html and recording what
happened per URN in data/fetch_manifest.json.

Two passes over the unique CTS URNs data/matches.yaml's rows collected:

1. **Sibling-edition dedup.** 36 works site-wide have more than one
   edition (e.g. every Aeschylus play has an `opp-grc3` and a
   `perseus-grc2` edition -- genuinely different texts, confirmed:
   Persians is 5,081 tokens in one, 5,665 in the other). Counting both
   would double-count the play. URNs are grouped by CTS
   `<textgroup>.<work>` (ignoring the trailing `.<edition>` component);
   a group of one is its own winner with no network cost. A group of
   more than one is resolved by probing each candidate's page 1 (small,
   no `?page=all`) for its own stated token total, then picking, in
   order: the edition vocab.perseus.org itself marks Core Reading List
   (data/perseus_editions.json's `core` flag -- its own editorial pick);
   otherwise the edition with the most tokens; otherwise the
   lexicographically lowest URN. The losing sibling(s) are recorded as
   `alternate_urns` on the winner's manifest entry -- never silently
   dropped.
2. **Fetch.** `GET /word-list/<urn>/?page=all` for each winner -> one
   request returns the whole list (confirmed: the Iliad's 6,830 lemmas
   in one ~7.6 MB response, ~9s). Parsed row count and the summed
   `count` column are checked against the page's own stated lemma/token
   totals -- a real integrity check (replacing the old hopper fetcher's
   `looks_valid()` heuristics, which existed for old-hopper-specific
   failure modes -- 504s, mid-document Java stack traces -- that don't
   exist here). A mismatch is a failed fetch, retried.

A URN already recorded in the manifest with `success: true` is skipped
(idempotent, resumable) unless `--redo` is passed.

Usage
-----
    uv run python3 fetch_vocab.py [--redo]
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import requests
import yaml

MATCHES = Path("data/matches.yaml")
EDITIONS = Path("data/perseus_editions.json")
RAW_DIR = Path("data/raw")
MANIFEST = Path("data/fetch_manifest.json")
BASE_URL = "https://vocab.perseus.org/word-list"
UA = "greek-core-vocab/0.2 (github.com/jaycrick/greek-core-vocab)"

_ATTEMPTS = 3
_RETRY_DELAY_S = 3
_POLITE_DELAY_S = 1.0

_HEADER_RE = re.compile(r"(?:of )?<b>([\d,]+)</b>\s*lemmas;\s*<b>([\d,]+)</b>\s*tokens")
_ROW_RE = re.compile(
    r'<th class="lemma_text"><a href="/lemma/(\d+)/[^"]*">(.*?)</a>\s*'
    r'<td class="shortdef">(.*?)\s*'
    r'<td class="count">([\d,]+)\s*'
    r'<td class="frequency">\(([^)]*)\)\s*'
    r'<td class="frequency">\(([^)]*)\)\s*'
    r'<td class="frequency">\(([^)]*)\)',
    re.S,
)


def urn_id(urn: str) -> str:
    """'urn:cts:greekLit:tlg0085.tlg002.opp-grc3' -> the last colon-
    component, already filename-safe (dots/hyphens only)."""
    return urn.rsplit(":", 1)[-1]


def group_key(urn: str) -> str:
    """Same CTS textgroup+work, ignoring which edition -- the unit
    sibling-edition dedup groups on. 'tlg0085.tlg002.opp-grc3' ->
    'tlg0085.tlg002'."""
    parts = urn_id(urn).split(".")
    return ".".join(parts[:2])


def cache_path(urn: str) -> Path:
    return RAW_DIR / f"{urn_id(urn)}.html"


def _get(url: str) -> requests.Response | None:
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=120)
        except requests.RequestException as e:
            print(f"    [attempt {attempt}] request error: {e}")
            time.sleep(_RETRY_DELAY_S)
            continue
        if resp.status_code == 200:
            return resp
        print(f"    [attempt {attempt}] status={resp.status_code}")
        time.sleep(_RETRY_DELAY_S)
    return None


def probe(urn: str) -> int | None:
    """Fetch just page 1 and return its stated token total, or None on
    failure. Used only to rank sibling editions -- doesn't need every
    row, just the header."""
    resp = _get(f"{BASE_URL}/{urn}/")
    time.sleep(_POLITE_DELAY_S)
    if resp is None:
        return None
    m = _HEADER_RE.search(resp.text)
    return int(m.group(2).replace(",", "")) if m else None


def resolve_winners(
    candidate_urns: set[str], editions_by_urn: dict[str, dict]
) -> list[dict]:
    """One record per distinct CTS work: {urn (winner), group_key,
    alternate_urns, alternates_reason}."""
    groups: dict[str, list[str]] = {}
    for urn in candidate_urns:
        groups.setdefault(group_key(urn), []).append(urn)

    resolved = []
    for key, urns in sorted(groups.items()):
        if len(urns) == 1:
            resolved.append({"urn": urns[0], "group_key": key, "alternate_urns": []})
            continue
        print(f"  sibling editions for {key}: {urns} -- probing token counts")
        tokens_by_urn = {u: probe(u) for u in urns}
        for u, t in tokens_by_urn.items():
            print(f"    {u}: {t if t is not None else 'probe failed'} tokens")

        def sort_key(u: str, tokens_by_urn: dict[str, int | None] = tokens_by_urn) -> tuple:
            # min() over this picks: core edition first (False < True,
            # so "not core" sorts a core edition to the front), then
            # most tokens (negated so the largest sorts smallest), then
            # lowest URN string as the final tiebreak.
            core = editions_by_urn.get(u, {}).get("core", False)
            tokens = tokens_by_urn.get(u) or -1
            return (not core, -tokens, u)

        winner = min(urns, key=sort_key)
        alternates = [u for u in urns if u != winner]
        print(f"    -> winner {winner}; alternate(s) not fetched: {alternates}")
        resolved.append({"urn": winner, "group_key": key, "alternate_urns": alternates})
    return resolved


def looks_valid(text: str) -> tuple[bool, str]:
    """A real integrity check: the page's own stated lemma count must
    equal the number of rows actually parsed, and the page's own stated
    token count must equal the summed `count` column -- not a substring
    heuristic. Returns (ok, detail-for-log)."""
    header = _HEADER_RE.search(text)
    if header is None:
        return False, "no lemmas/tokens header found"
    stated_lemmas, stated_tokens = int(header.group(1).replace(",", "")), int(
        header.group(2).replace(",", "")
    )
    rows = _ROW_RE.findall(text)
    parsed_tokens = sum(int(r[3].replace(",", "")) for r in rows)
    if len(rows) != stated_lemmas:
        return False, f"parsed {len(rows)} rows, page states {stated_lemmas} lemmas"
    if parsed_tokens != stated_tokens:
        return False, f"parsed rows sum to {parsed_tokens} tokens, page states {stated_tokens}"
    return True, f"{len(rows)} lemmas, {parsed_tokens} tokens"


def fetch_winner(urn: str) -> dict:
    path = cache_path(urn)
    for attempt in range(1, _ATTEMPTS + 1):
        resp = _get(f"{BASE_URL}/{urn}/?page=all")
        if resp is None:
            continue
        ok, detail = looks_valid(resp.text)
        print(f"    [attempt {attempt}] {detail}")
        if ok:
            path.write_text(resp.text, encoding="utf-8")
            header = _HEADER_RE.search(resp.text)
            time.sleep(_POLITE_DELAY_S)
            return {
                "success": True,
                "cache_file": str(path),
                "lemmas": int(header.group(1).replace(",", "")),
                "tokens": int(header.group(2).replace(",", "")),
            }
        time.sleep(_RETRY_DELAY_S)
    return {"success": False, "cache_file": None, "lemmas": None, "tokens": None}


def unique_matched_urns() -> set[str]:
    doc = yaml.safe_load(MATCHES.read_text(encoding="utf-8"))
    urns: set[str] = set()
    for row in doc["matches"]:
        urns.update(row["matched_urns"])
    return urns


def load_editions_by_urn() -> dict[str, dict]:
    editions = json.loads(EDITIONS.read_text(encoding="utf-8"))
    return {e["urn"]: e for e in editions}


def load_manifest() -> dict[str, dict]:
    if not MANIFEST.is_file():
        return {}
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {e["urn"]: e for e in entries}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--redo", action="store_true", help="re-fetch every winner, ignoring cache")
    args = ap.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    candidate_urns = unique_matched_urns()
    editions_by_urn = load_editions_by_urn()
    manifest = load_manifest()

    print(f"{len(candidate_urns)} unique candidate URN(s); resolving sibling editions...")
    winners = resolve_winners(candidate_urns, editions_by_urn)
    print(f"{len(winners)} distinct work(s) to fetch\n")

    for i, w in enumerate(winners, start=1):
        urn = w["urn"]
        meta = editions_by_urn.get(urn, {})
        entry = {
            "urn": urn,
            "group_key": w["group_key"],
            "author": meta.get("author", ""),
            "title": meta.get("title", ""),
            "core": meta.get("core", False),
            "alternate_urns": w["alternate_urns"],
        }
        if not args.redo and manifest.get(urn, {}).get("success"):
            entry.update(
                {
                    k: manifest[urn][k]
                    for k in ("success", "cache_file", "lemmas", "tokens")
                }
            )
            manifest[urn] = entry
            continue
        print(f"[{i}/{len(winners)}] {urn} ({entry['author']} -- {entry['title']})")
        entry.update(fetch_winner(urn))
        manifest[urn] = entry

    winner_urns = [w["urn"] for w in winners]
    MANIFEST.write_text(
        json.dumps([manifest[u] for u in winner_urns], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    ok = [u for u in winner_urns if manifest[u]["success"]]
    failed = [u for u in winner_urns if not manifest[u]["success"]]
    print(f"\n{len(ok)}/{len(winner_urns)} works fetched successfully -> {MANIFEST}")
    if failed:
        print(f"{len(failed)} FAILED (see {MANIFEST}):")
        for u in failed:
            print(f"  {u}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
