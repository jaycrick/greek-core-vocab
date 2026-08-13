#!/usr/bin/env python3
"""Parse every successfully-fetched Perseus work in
data/fetch_manifest.json PLUS every corpus-sourced work in
data/corpus_counts.json (see corpus_vocab.py), collapse identical
headwords together (within and across both sources), sum their
frequencies, and write the single reusable deliverable:
output/master_vocab.csv (+ a .json mirror). Also writes
output/lemma_join_report.tsv, the transparency trail for how each
corpus lemma was joined onto the Perseus-derived vocabulary (see
step 3 below).

Collapsing key: NFC-normalized Unicode headword/lemma. Perseus's own
identifier is a beta-code string (`lemma/headword` in the XML, the
`l=` query param of a table row's word link); the corpus repo's
lemma.tsv already gives Unicode. Unicode is the only key both sources
can share -- Perseus entries are converted via `beta_code`, corpus
lemmas are used as-is (NFC-normalized by corpus_vocab.py already).
Perseus doesn't fully disambiguate homographs at this field -- two
different LSJ senses can share one headword, split apart only in the
`lexiconQueries`/"Lexicon Entries" refs -- so grouping on the headword
string alone is both the direct reading of "collapse identical forms
into one reading" and the natural join key across works. Collisions
between two distinct beta-code forms converging on one Unicode form
are rare in practice (one observed among 34,484 headwords: Ὀλυμπιάς)
-- `headword_betacode` becomes a semicolon-joined set to keep every
observed spelling visible.

Overlap downweighting: corpus_map.yaml's `overlaps` list names Perseus
volumes that are KEPT (they carry a Great Books dialogue with no other
source) but PARTLY duplicate a corpus-sourced work. Each such volume's
every entry is scaled by `1 - dup_tokens/volume_sum_wf`, computed at
run time from data/corpus_counts.json's token counts and this run's
own summed weightedFrequency for that volume -- see README.md's
overlap-accounting table for the numbers this produces on the current
data (~0.545 and ~0.739).

Combine function: SUM each headword's (scaled) weightedFrequency and
raw corpus lemma count across every work it appears in (a user
decision -- rewards a word for being both locally frequent and used
widely, the standard way to merge frequency lists; see README.md).
The two figures are on the same scale: Perseus's weightedFrequency
summed over a whole work recovers that work's token count (Republic
volume 1999.01.0167 sums to 87,466; the corpus repo's own Republic
token count is 87,070, 0.5% apart), so summing them together is a
direct combination, not an apples-to-oranges one.

Join report (step 3): most corpus lemmas match an existing Perseus
Unicode headword exactly. A minority don't, for two different reasons
that get resolved differently:
  - orthographic variants (e.g. σῴζω/σώζω, πρωΐ/πρωί) -- resolved via
    an accent-blind fallback key (NFD, strip combining marks, casefold)
    against the ORIGINAL Perseus-only headword set, used only when
    that fallback is unambiguous (exactly one candidate).
  - genuine gaps in Perseus's own lemma inventory (confirmed by
    grepping the raw XML: no simplex ἀφίστημι/καταλείπω, no Σωκράτης
    at all) or corpus-only proper nouns -- these get a brand-new,
    corpus-only row; there is nothing to join them to.
output/lemma_join_report.tsv records every corpus (work_id, lemma)
pair's resolution so this is auditable, not asserted.

Usage
-----
    uv run python3 combine.py
"""

from __future__ import annotations

import csv
import json
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import beta_code
import yaml

from fetch_vocab import urn_id

MANIFEST = Path("data/fetch_manifest.json")
CORPUS_COUNTS = Path("data/corpus_counts.json")
CORPUS_MAP = Path("corpus_map.yaml")
OUT_CSV = Path("output/master_vocab.csv")
OUT_JSON = Path("output/master_vocab.json")
OUT_JOIN_REPORT = Path("output/lemma_join_report.tsv")


@dataclass
class Entry:
    headword: str  # beta-code
    weighted_frequency: float
    short_definition: str


@dataclass
class Group:
    perseus_weighted_frequency: float = 0.0
    corpus_count: int = 0
    has_perseus: bool = False
    betacodes: set[str] = field(default_factory=set)
    urns: set[str] = field(default_factory=set)  # short Perseus URN ids
    corpus_work_ids: set[str] = field(default_factory=set)
    short_definition: str = ""


def parse_xml(text: str) -> list[Entry]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(text)
    entries = []
    for freq in root.findall("frequency"):
        lemma = freq.find("lemma")
        headword = (lemma.findtext("headword") or "").strip() if lemma is not None else ""
        if not headword:
            continue
        short_def = (
            (lemma.findtext("shortDefinition") or "").strip() if lemma is not None else ""
        )
        wf_text = (freq.findtext("weightedFrequency") or "0").strip()
        entries.append(Entry(headword, float(wf_text), short_def))
    return entries


class _TableParser(HTMLParser):
    """Walks a `<table id="vocab_list">` (see fetch_vocab.py's module
    docstring for why this format sometimes has to stand in for XML),
    collecting the same three fields XML gives directly: the word's
    beta-code (from its link's `l=` query param -- the same value the
    XML `headword` field holds), the "This Word" weighted-frequency
    column, and the definition column. Column order, 0-indexed:
    0 count (blank), 1 word, 2 max freq, 3 min freq, 4 THIS WORD
    weighted freq, 5 total weighted freq, 6 key term score,
    7 definition, 8 lexicon entries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_vocab_table = False
        self.table_depth = 0
        self.in_row = False
        self.in_cell = False
        self.row_cells: list[str] = []
        self.cell_text: list[str] = []
        self.row_headword: str | None = None
        self.entries: list[Entry] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrd = dict(attrs)
        if tag == "table" and attrd.get("id") == "vocab_list":
            self.in_vocab_table = True
            self.table_depth = 0
            return
        if not self.in_vocab_table:
            return
        if tag == "table":
            self.table_depth += 1
        elif tag == "tr" and self.table_depth == 0:
            self.in_row = True
            self.row_cells = []
            self.row_headword = None
        elif tag == "td" and self.in_row:
            self.in_cell = True
            self.cell_text = []
        elif tag == "a" and self.in_row and self.row_headword is None:
            href = attrd.get("href") or ""
            if href.startswith("morph?"):
                query = parse_qs(urlparse(href).query)
                if "l" in query:
                    self.row_headword = query["l"][0]

    def handle_endtag(self, tag: str) -> None:
        if not self.in_vocab_table:
            return
        if tag == "table":
            if self.table_depth == 0:
                self.in_vocab_table = False
            else:
                self.table_depth -= 1
        elif tag == "td" and self.in_cell:
            self.in_cell = False
            self.row_cells.append("".join(self.cell_text).strip())
        elif tag == "tr" and self.in_row:
            self.in_row = False
            if self.row_headword and len(self.row_cells) >= 8:
                wf_raw = self.row_cells[4].replace(",", "")
                try:
                    wf = float(wf_raw)
                except ValueError:
                    wf = 0.0
                self.entries.append(Entry(self.row_headword, wf, self.row_cells[7]))

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_text.append(data)


def parse_table(text: str) -> list[Entry]:
    parser = _TableParser()
    parser.feed(text)
    return parser.entries


def accent_blind_key(s: str) -> str:
    """NFD-decompose, drop combining marks, casefold -- a join key for
    orthographic variants that share no exact Unicode string (accent
    placement/breathing differences between the corpus repo's editorial
    choices and Perseus's, e.g. σῴζω vs σώζω, πρωΐ vs πρωί)."""
    decomposed = unicodedata.normalize("NFD", s)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return unicodedata.normalize("NFC", stripped).casefold()


def load_overlaps() -> list[dict]:
    doc = yaml.safe_load(CORPUS_MAP.read_text(encoding="utf-8"))
    return doc.get("overlaps") or []


def load_corpus_counts() -> list[dict]:
    if not CORPUS_COUNTS.is_file():
        return []
    return json.loads(CORPUS_COUNTS.read_text(encoding="utf-8"))


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    # --- Pass 1: parse every Perseus work, keep per-URN entries so an
    # overlap's scale can be computed from this run's own totals. ---
    per_urn_entries: dict[str, list[Entry]] = {}
    parsed_ok = 0
    parse_failures: list[str] = []
    for entry in manifest:
        if not entry["success"]:
            continue
        path = Path(entry["cache_file"])
        text = path.read_text(encoding="utf-8")
        try:
            work_entries = parse_xml(text) if entry["method"] == "xml" else parse_table(text)
        except Exception as e:  # noqa: BLE001 -- one bad file shouldn't abort the run
            parse_failures.append(f"{entry['urn']}: {e}")
            continue
        if not work_entries:
            parse_failures.append(f"{entry['urn']}: parsed 0 entries")
            continue
        parsed_ok += 1
        per_urn_entries[entry["urn"]] = work_entries

    corpus_counts = load_corpus_counts()
    corpus_by_id = {rec["work_id"]: rec for rec in corpus_counts}

    # --- Overlap scales, computed from this run's actual data. ---
    overlaps = load_overlaps()
    scale_by_urn: dict[str, float] = {}
    if overlaps:
        print("overlap downweighting:")
    for ov in overlaps:
        urn = ov["urn"]
        dup_tokens = sum(corpus_by_id[w]["token_count"] for w in ov["duplicated_by"])
        volume_sum_wf = sum(e.weighted_frequency for e in per_urn_entries.get(urn, []))
        scale = max(0.0, 1.0 - dup_tokens / volume_sum_wf) if volume_sum_wf else 1.0
        scale_by_urn[urn] = scale
        print(
            f"  {urn}: dup_tokens={dup_tokens:,} volume_sum_wf={volume_sum_wf:,.1f} "
            f"-> scale={scale:.3f}"
        )

    # --- Pass 2: fold Perseus entries into Unicode-keyed groups. ---
    groups: dict[str, Group] = {}
    conversion_failures = 0
    for urn, work_entries in per_urn_entries.items():
        scale = scale_by_urn.get(urn, 1.0)
        for e in work_entries:
            try:
                unicode_form = unicodedata.normalize(
                    "NFC", beta_code.beta_code_to_greek(e.headword)
                )
            except Exception:  # noqa: BLE001 -- keep the beta-code form, don't drop the word
                unicode_form = e.headword
                conversion_failures += 1
            g = groups.setdefault(unicode_form, Group())
            g.perseus_weighted_frequency += e.weighted_frequency * scale
            g.has_perseus = True
            g.betacodes.add(e.headword)
            g.urns.add(urn_id(urn))
            if not g.short_definition and e.short_definition:
                g.short_definition = e.short_definition

    # Accent-blind fallback lookup, built from Perseus-only keys BEFORE
    # any corpus lemma is folded in -- an unambiguous 1:1 mapping only.
    accent_map: dict[str, list[str]] = {}
    for key in groups:
        accent_map.setdefault(accent_blind_key(key), []).append(key)

    # --- Pass 3: fold corpus lemma counts in, recording how each
    # (work_id, lemma) pair was joined. ---
    join_rows: list[tuple[str, str, int, str, str]] = []
    for rec in corpus_counts:
        work_id = rec["work_id"]
        for lemma, count in rec["lemma_counts"].items():
            if lemma in groups:
                key = lemma
                resolution = "exact" if groups[key].has_perseus else "corpus-only"
            else:
                candidates = accent_map.get(accent_blind_key(lemma), [])
                if len(candidates) == 1:
                    key = candidates[0]
                    resolution = "accent-blind"
                else:
                    key = lemma
                    resolution = "corpus-only"
            g = groups.setdefault(key, Group())
            g.corpus_count += count
            g.corpus_work_ids.add(work_id)
            join_rows.append((work_id, lemma, count, resolution, key))

    OUT_JOIN_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with OUT_JOIN_REPORT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["work_id", "lemma", "count", "resolution", "joined_key"])
        writer.writerows(sorted(join_rows, key=lambda r: (r[3], r[0], -r[2])))

    corpus_only_lemmas = {r[4] for r in join_rows if r[3] == "corpus-only"}
    accent_blind_hits = sum(1 for r in join_rows if r[3] == "accent-blind")

    # --- Assemble output rows. ---
    rows = []
    for headword, g in groups.items():
        rows.append(
            {
                "headword_unicode": headword,
                "headword_betacode": ";".join(sorted(g.betacodes)),
                "combined_weighted_frequency": round(
                    g.perseus_weighted_frequency + g.corpus_count, 4
                ),
                "perseus_weighted_frequency": round(g.perseus_weighted_frequency, 4),
                "corpus_count": g.corpus_count,
                "works_count": len(g.urns) + len(g.corpus_work_ids),
                "short_definition": g.short_definition,
                "source_urns": ";".join(sorted(g.urns) + sorted(g.corpus_work_ids)),
            }
        )

    rows.sort(key=lambda r: (-r["combined_weighted_frequency"], r["headword_unicode"]))

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n{parsed_ok}/{len([e for e in manifest if e['success']])} fetched works parsed")
    if parse_failures:
        print(f"{len(parse_failures)} parse failure(s):")
        for f_ in parse_failures:
            print(f"  {f_}")
    if conversion_failures:
        print(f"{conversion_failures} headword(s) failed beta-code conversion (kept as-is)")
    if corpus_counts:
        print(f"{len(corpus_counts)} corpus work(s) folded in from {CORPUS_COUNTS}")
        print(
            f"  lemma join: {accent_blind_hits} accent-blind, "
            f"{len(corpus_only_lemmas)} corpus-only (no Perseus match) -> {OUT_JOIN_REPORT}"
        )
    print(f"{len(rows)} distinct headwords -> {OUT_CSV}, {OUT_JSON}")
    print("\ntop 20 by combined weighted frequency:")
    for r in rows[:20]:
        print(
            f"  {r['headword_unicode']:12s} {r['combined_weighted_frequency']:>10.2f}  "
            f"({r['works_count']} works)  {r['short_definition']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
