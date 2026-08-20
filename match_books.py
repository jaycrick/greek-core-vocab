#!/usr/bin/env python3
"""Match every great_books.tsv row against vocab.perseus.org's own
catalog (data/perseus_editions.json, from fetch_editions.py), producing
data/matches.yaml: for each row, either the CTS URN(s) whose vocabulary
should represent it, or a reason it has none.

Matching, in order:

1. **overrides.yaml** (exact (author, title)) -- rows a human had to
   pin explicitly (see that file's own header: Plutarch's *Lives*,
   whose 16 available editions are titled "unknown" on the site itself
   and so can't be title-matched at all). Checked first; if it applies,
   nothing else runs for that row.
2. **aliases.yaml** ((author, title) -> a replacement search title) for
   pairs that share no usable substring after normalization (different
   English title, transliteration vs. translation, Latin vs. English
   title -- vocab.perseus.org titles many works in Latin).
3. General matching: restrict candidates to the same (normalized)
   author, normalize both titles (lowercase, strip a leading "the"/"a"/
   "an", strip trailing punctuation, collapse whitespace), and match if
   they're equal, one is a word-level substring of the other, or the
   target equals one comma-separated component of the candidate's title
   (Perseus groups a few works under one comma-joined title).

A row with zero matches gets `matched_urns: []` and a `skip_reason` --
always recorded, never silently dropped. Expected skips: pure
category-header rows ("Dialogues", "The Oresteia"), and authors/works
vocab.perseus.org's catalog doesn't carry at all -- notably about three
dozen works the OLD Perseus hopper did carry (most of Euripides and
Aristophanes, roughly half of Plato, Aristotle's Ethics/Politics/
Rhetoric/Metaphysics, Epictetus, Marcus Aurelius, most of Plutarch's
individual Lives) -- see README.md's coverage-regression table. Rows
for authors who wrote in Latin (Lucretius, Virgil) were removed from
great_books.tsv itself rather than left to show up as a skip here.

A matched row's `matched_urns` may contain more than one CTS URN for
the SAME underlying work (36 works site-wide have >1 edition -- e.g.
Aeschylus's plays each have an `opp-grc3` and a `perseus-grc2`
edition). match_books.py does not resolve that here -- it has no
reason to fetch anything -- fetch_vocab.py does, by probing each
sibling's token count and keeping one (see its own docstring); this
row-level matched_urns list is the full candidate set that step reads.

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
EDITIONS = Path("data/perseus_editions.json")
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


def load_editions() -> list[dict[str, str]]:
    return json.loads(EDITIONS.read_text(encoding="utf-8"))


def load_aliases() -> dict[tuple[str, str], str]:
    doc = yaml.safe_load(ALIASES.read_text(encoding="utf-8"))
    return {(a["author"], a["gbww_title"]): a["perseus_title"] for a in doc["aliases"]}


def load_overrides() -> dict[tuple[str, str], dict]:
    doc = yaml.safe_load(OVERRIDES.read_text(encoding="utf-8"))
    return {(o["author"], o["gbww_title"]): o for o in doc["overrides"]}


def match_row(
    row: dict[str, str],
    editions_by_author: dict[str, list[dict[str, str]]],
    aliases: dict[tuple[str, str], str],
) -> tuple[list[str], str]:
    """(matched_urns, method) for one great_books.tsv row, via the
    alias + normalize/substring/comma-component matching described in
    this module's docstring (overrides are handled by the caller,
    before this is reached)."""
    author, title = row["author"], row["title"]
    is_alias = (author, title) in aliases
    search_title = aliases.get((author, title), title)
    target = normalize(search_title)
    target_words = target.split()
    candidates = editions_by_author.get(author.lower(), [])

    # An alias already names the exact intended title (that's the whole
    # point of adding one) -- word-subsequence containment is NOT
    # applied for alias-driven searches, only exact equality (still
    # allowing a comma-joined component match, for a grouped Perseus
    # title). Skipping containment here matters in practice:
    # vocab.perseus.org's many short Latin titles collide under
    # containment alone -- e.g. Hippocrates' alias target "De diaeta in
    # morbis acutis" word-subsequence-contains the unrelated, separate
    # work "De diaeta"; Aristotle's alias "Physica" would otherwise also
    # catch "Physica (textus alter)", an alternate-recension edition of
    # the same nominal title but not the same content. Equality alone
    # -- since every alias target is copied verbatim from the catalog's
    # own title string -- can't mismatch that way.
    matched: dict[str, str] = {}  # urn -> which candidate title matched
    for e in candidates:
        cand_norm = normalize(e["title"])
        cand_words = cand_norm.split()
        if target == cand_norm:
            matched[e["urn"]] = e["title"]
            continue
        if (
            not is_alias
            and target
            and (
                _is_word_subsequence(target_words, cand_words)
                or _is_word_subsequence(cand_words, target_words)
            )
        ):
            matched[e["urn"]] = e["title"]
            continue
        components = [normalize(c) for c in e["title"].split(",")]
        if target in components:
            matched[e["urn"]] = e["title"]

    if not matched:
        return [], ""
    method = "alias" if (author, title) in aliases else "normalized-match"
    return sorted(matched), method


def main() -> int:
    rows = load_great_books()
    editions = load_editions()
    aliases = load_aliases()
    overrides = load_overrides()

    editions_by_author: dict[str, list[dict[str, str]]] = {}
    for e in editions:
        editions_by_author.setdefault(e["author"].lower(), []).append(e)

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

        override = overrides.get((author, title))
        if override is not None:
            results.append(
                {**base, "matched_urns": list(override["urns"]), "method": "override"}
            )
            continue

        urns, method = match_row(row, editions_by_author, aliases)
        if urns:
            results.append({**base, "matched_urns": urns, "method": method})
        else:
            results.append(
                {
                    **base,
                    "matched_urns": [],
                    "skip_reason": (
                        f"no vocab.perseus.org Greek text found for {author!r}, {title!r}"
                    ),
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
    print(f"{len(unique_urns)} unique candidate URN(s) (before sibling-edition dedup) -> {OUT}")
    print()
    print("skipped:")
    for r in skipped_rows:
        print(f"  {r['author']} -- {r['title']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
