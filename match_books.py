#!/usr/bin/env python3
"""Match every great_books.tsv row against Perseus's own catalog
(data/perseus_works.json, from fetch_work_list.py), producing
data/matches.yaml: for each row, either the Perseus URN(s) whose
vocabulary should represent it, a corpus_work_id pointing at gold
local tagging instead, or a reason it has none.

Matching, in order:

1. **corpus_map.yaml** (`corpus_works`: exact (author, title) -> a
   work_id in one of two external gold-tagged sources -- see that
   file's own header for which `source:` tag maps to which counting
   script/repo) -- rows whose vocabulary should come from gold
   per-work tagging rather than Perseus's Vocabulary Tool (see that
   file's own header and README.md for why: real gaps in Perseus's
   lemma inventory, no per-dialogue Plato selection at all, and a
   Homer parse that can't disambiguate epic formulae the way a
   hand-checked tagging can). Checked first; if it applies, nothing
   else runs for that row -- its `matched_urns` stays `[]` (never
   fetched from Perseus), and `corpus_work_id` is set instead.
   `corpus_map.yaml`'s `overlaps` section is applied afterwards, once
   every row is resolved: URNs a corpus work `displaces_urns` are
   removed from every other row's `matched_urns` (see step 5 below).
2. **overrides.yaml** (exact (author, title), or `gbww_title: __ALL__`
   for every row by that author) -- the two rows a human had to decide
   (see that file's own header). Checked first (after corpus_map); if
   it applies, nothing else runs for that row.
3. **aliases.yaml** ((author, title) -> a replacement search title) for
   the handful of pairs that share no usable substring after
   normalization (different English title, transliteration vs.
   translation, etc.).
4. General matching: restrict candidates to the same (normalized)
   author, normalize both titles (lowercase, strip a leading "the"/"a"/
   "an", strip trailing punctuation, collapse whitespace), and match if
   they're equal, one is a substring of the other, or the target equals
   one comma-separated component of the candidate's title (Perseus
   groups several works -- mostly Plato dialogues -- under one
   selectable, comma-joined title; splitting on ", " and matching a
   component is what resolves those without hardcoding every dialogue).
5. **Displacement pass**, after every row above is resolved: the union
   of every `corpus_works` entry's `displaces_urns` is removed from
   every other row's `matched_urns` -- never silently: a row that loses
   a URN this way gets `displaced_urns` recorded alongside whatever
   `matched_urns` remain (or `skip_reason` if none do).

A row with zero matches (and no corpus_work_id) after all of the above
gets `matched_urns: []` and a `skip_reason` -- always recorded, never
silently dropped. Several GBWW rows are expected to land here: pure
category headers ("Dialogues", "The Oresteia"), and authors/works
Perseus's Greek vocab tool simply doesn't carry (Archimedes, Apollonius
of Perga, Nicomachus of Gerasa, most of Aristotle's logical/
biological/psychological works). Rows for authors who wrote in Latin
(Lucretius, Virgil) were removed from great_books.tsv itself rather
than left to skip here -- this catalog is Greek-only, so they could
never match.

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
CORPUS_MAP = Path("corpus_map.yaml")
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


def load_corpus_map() -> tuple[dict[tuple[str, str], dict], list[str]]:
    """(corpus_works keyed by (author, gbww_title), sorted-unique union
    of every entry's displaces_urns)."""
    doc = yaml.safe_load(CORPUS_MAP.read_text(encoding="utf-8"))
    by_title = {(c["author"], c["gbww_title"]): c for c in doc["corpus_works"]}
    displaced: set[str] = set()
    for c in doc["corpus_works"]:
        displaced.update(c.get("displaces_urns") or [])
    return by_title, sorted(displaced)


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
    corpus_by_title, displaced_urns = load_corpus_map()

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

        corpus = corpus_by_title.get((author, title))
        if corpus is not None:
            results.append(
                {
                    **base,
                    "matched_urns": [],
                    "corpus_work_id": corpus["work_id"],
                    "method": "corpus",
                }
            )
            continue

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

    # Displacement pass: URNs a corpus_works entry duplicates are
    # removed from every OTHER row's matched_urns -- recorded, not
    # silently dropped (see module docstring, step 5).
    displaced_set = set(displaced_urns)
    for r in results:
        if r.get("method") == "corpus" or not r["matched_urns"]:
            continue
        hit = [u for u in r["matched_urns"] if u in displaced_set]
        if not hit:
            continue
        r["matched_urns"] = [u for u in r["matched_urns"] if u not in displaced_set]
        r["displaced_urns"] = hit
        if not r["matched_urns"]:
            r["skip_reason"] = (
                f"every matched Perseus URN ({', '.join(hit)}) is fully superseded by a "
                "corpus_map.yaml corpus_works entry -- see corpus_map.yaml"
            )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        yaml.safe_dump({"matches": results}, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )

    corpus_rows = [r for r in results if r.get("method") == "corpus"]
    matched_rows = [r for r in results if r["matched_urns"]]
    skipped_rows = [r for r in results if not r["matched_urns"] and r.get("method") != "corpus"]
    unique_urns = {u for r in matched_rows for u in r["matched_urns"]}
    displaced_rows = [r for r in results if r.get("displaced_urns")]
    print(
        f"{len(results)} rows: {len(matched_rows)} matched (Perseus), "
        f"{len(corpus_rows)} corpus-sourced, {len(skipped_rows)} skipped"
    )
    print(f"{len(unique_urns)} unique Perseus URN(s) to fetch")
    if displaced_rows:
        print(f"{len(displaced_rows)} row(s) had a Perseus URN displaced by a corpus work:")
        for r in displaced_rows:
            print(f"  {r['author']} -- {r['title']}: displaced {r['displaced_urns']}")
    print(f"-> {OUT}")
    print()
    print("skipped:")
    for r in skipped_rows:
        print(f"  {r['author']} -- {r['title']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
