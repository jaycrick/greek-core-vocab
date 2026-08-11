#!/usr/bin/env python3
"""Match every great_books.tsv row against Perseus's own catalog
(data/perseus_works.json, from fetch_work_list.py), producing
data/matches.yaml: for each row, either the Perseus URN(s) whose
vocabulary should represent it, or a reason it has none.

Matching, in order:

1. **overrides.yaml** (exact (author, title), or `gbww_title: __ALL__`
   for every row by that author) -- the two rows a human had to decide
   (see that file's own header). Checked first; if it applies, nothing
   else runs for that row.
2. **aliases.yaml** ((author, title) -> a replacement search title) for
   the handful of pairs that share no usable substring after
   normalization (different English title, transliteration vs.
   translation, etc.).
3. General matching: restrict candidates to the same (normalized)
   author, normalize both titles (lowercase, strip a leading "the"/"a"/
   "an", strip trailing punctuation, collapse whitespace), and match if
   they're equal, one is a substring of the other, or the target equals
   one comma-separated component of the candidate's title (Perseus
   groups several works -- mostly Plato dialogues -- under one
   selectable, comma-joined title; splitting on ", " and matching a
   component is what resolves those without hardcoding every dialogue).

A row with zero matches after all three gets `matched_urns: []` and a
`skip_reason` -- always recorded, never silently dropped. Several
GBWW rows are expected to land here: pure category headers ("Dialogues",
"The Oresteia"), authors/works Perseus's Greek vocab tool simply doesn't
carry (Archimedes, Apollonius of Perga, Nicomachus of Gerasa, most of
Aristotle's logical/biological/psychological works), and the Latin GBWW
rows (Lucretius, Virgil) under this Greek-only catalog.

Usage
-----
    uv run python3 match_books.py
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import yaml

GREAT_BOOKS = Path("great_books.tsv")
WORKS = Path("data/perseus_works.json")
ALIASES = Path("aliases.yaml")
OVERRIDES = Path("overrides.yaml")
OUT = Path("data/matches.yaml")

_LEADING_ARTICLE_RE = re.compile(r"^(the|an?)\s+")
_PUNCT_RE = re.compile(r"[.,;:'’\"]")
_WS_RE = re.compile(r"\s+")


def normalize(title: str) -> str:
    t = title.lower()
    t = _PUNCT_RE.sub("", t)
    t = _WS_RE.sub(" ", t).strip()
    t = _LEADING_ARTICLE_RE.sub("", t)
    return t


def _is_word_subsequence(needle: list[str], haystack: list[str]) -> bool:
    """True if `needle`'s words appear, in order, as a CONTIGUOUS run
    inside `haystack`'s words -- a word-level substring check. Plain
    character-substring matching is too loose here: "physics" is a
    character-substring of "metaphysics" (a different, unrelated
    Aristotle work) even though they share no word. Word-level
    containment still correctly matches e.g. "elements" inside "the
    thirteen books of euclid's elements", or "peloponnesian war" inside
    "history of the peloponnesian war"."""
    if not needle or len(needle) > len(haystack):
        return False
    n = len(needle)
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def load_great_books() -> list[dict[str, str]]:
    with GREAT_BOOKS.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def load_works() -> list[dict[str, str]]:
    return json.loads(WORKS.read_text(encoding="utf-8"))


def load_aliases() -> dict[tuple[str, str], str]:
    doc = yaml.safe_load(ALIASES.read_text(encoding="utf-8"))
    return {(a["author"], a["gbww_title"]): a["perseus_title"] for a in doc["aliases"]}


def load_overrides() -> tuple[dict[tuple[str, str], dict], dict[str, dict]]:
    doc = yaml.safe_load(OVERRIDES.read_text(encoding="utf-8"))
    exact: dict[tuple[str, str], dict] = {}
    by_author_all: dict[str, dict] = {}
    for o in doc["overrides"]:
        if o["gbww_title"] == "__ALL__":
            by_author_all[o["author"]] = o
        else:
            exact[(o["author"], o["gbww_title"])] = o
    return exact, by_author_all


def match_row(
    row: dict[str, str],
    works_by_author: dict[str, list[dict[str, str]]],
    aliases: dict[tuple[str, str], str],
) -> tuple[list[str], str]:
    """(matched_urns, method) for one great_books.tsv row, via the
    alias + normalize/substring/comma-component matching described in
    this module's docstring (overrides are handled by the caller,
    before this is reached)."""
    author, title = row["author"], row["title"]
    search_title = aliases.get((author, title), title)
    target = normalize(search_title)
    target_words = target.split()
    candidates = works_by_author.get(author.lower(), [])

    matched: dict[str, str] = {}  # urn -> which candidate title matched
    for w in candidates:
        cand_norm = normalize(w["title"])
        cand_words = cand_norm.split()
        if target == cand_norm:
            matched[w["urn"]] = w["title"]
            continue
        if target and (
            _is_word_subsequence(target_words, cand_words)
            or _is_word_subsequence(cand_words, target_words)
        ):
            matched[w["urn"]] = w["title"]
            continue
        components = [normalize(c) for c in w["title"].split(",")]
        if target in components:
            matched[w["urn"]] = w["title"]

    if not matched:
        return [], ""
    method = "alias" if (author, title) in aliases else "normalized-match"
    return sorted(matched), method


def main() -> int:
    rows = load_great_books()
    works = load_works()
    aliases = load_aliases()
    override_exact, override_all = load_overrides()

    works_by_author: dict[str, list[dict[str, str]]] = {}
    for w in works:
        works_by_author.setdefault(w["author"].lower(), []).append(w)

    results: list[dict[str, Any]] = []
    for row in rows:
        author, title = row["author"], row["title"]
        base = {
            "title": title,
            "author": author,
            "group": row["group"],
            "year": row["year"],
            "seq": row["seq"],
        }

        override = override_exact.get((author, title)) or override_all.get(author)
        if override is not None:
            results.append(
                {**base, "matched_urns": list(override["urns"]), "method": "override"}
            )
            continue

        urns, method = match_row(row, works_by_author, aliases)
        if urns:
            results.append({**base, "matched_urns": urns, "method": method})
        else:
            results.append(
                {
                    **base,
                    "matched_urns": [],
                    "skip_reason": f"no Perseus Greek text found for {author!r}, {title!r}",
                }
            )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        yaml.safe_dump({"matches": results}, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )

    matched_rows = [r for r in results if r["matched_urns"]]
    skipped_rows = [r for r in results if not r["matched_urns"]]
    unique_urns = {u for r in matched_rows for u in r["matched_urns"]}
    print(f"{len(results)} rows: {len(matched_rows)} matched, {len(skipped_rows)} skipped")
    print(f"{len(unique_urns)} unique Perseus URN(s) to fetch")
    print(f"-> {OUT}")
    print()
    print("skipped:")
    for r in skipped_rows:
        print(f"  {r['author']} -- {r['title']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
