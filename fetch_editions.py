#!/usr/bin/env python3
"""Scrape vocab.perseus.org's Editions List into
data/perseus_editions.json: one record per edition of a Greek text
available in the new Perseus Greek Vocabulary Tool
(https://vocab.perseus.org/), replacing fetch_work_list.py's old-hopper
equivalent (data/perseus_works.json).

The editions page (https://vocab.perseus.org/editions/) is plain
server-rendered HTML, no JS/auth needed: one `<h4>author</h4>` per
text-group, followed by one `<div class="row">` per edition:

    <h4>Homer</h4>
      <div class="row">
        <div class="col">
          <a href="/word-list/urn:cts:greekLit:tlg0012.tlg001.perseus-grc2/">Iliad</a>*
        </div>
        ...

The URN is a CTS URN (`urn:cts:greekLit:<textgroup>.<work>.<edition>`),
not the old hopper's `Perseus:text:<ed>.<vol>.<work>` scheme -- nothing
here needs converting between the two. A trailing `*` immediately after
the closing `</a>` (a bare text node, not part of the link) marks the
edition as part of Perseus's own Core Reading List
(https://vocab.perseus.org/editions/?core) -- recorded as `core: true`,
not matched against, just carried through for combine.py's reference
columns.

Usage
-----
    uv run python3 fetch_editions.py
"""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import requests

URL = "https://vocab.perseus.org/editions/"
OUT = Path("data/perseus_editions.json")
_WORD_LIST_PREFIX = "/word-list/"
_MIN_EXPECTED = 500  # sanity floor; 901 editions observed when this was written


class EditionsParser(HTMLParser):
    """Walks the page once: each `<h4>` sets the current author, each
    `/word-list/<urn>/` link inside a following row becomes one edition
    record. The bare text immediately after a link's `</a>` is checked
    for a leading `*` (core-reading-list marker) before anything else
    resets that state."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current_author = ""
        self.in_h4 = False
        self.h4_parts: list[str] = []
        self.in_link = False
        self.link_urn: str | None = None
        self.title_parts: list[str] = []
        self.pending: dict[str, str | bool] | None = None
        self.editions: list[dict[str, str | bool]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrd = dict(attrs)
        if tag == "h4":
            self.in_h4 = True
            self.h4_parts = []
        elif tag == "a":
            href = attrd.get("href") or ""
            if href.startswith(_WORD_LIST_PREFIX):
                self.in_link = True
                self.link_urn = href[len(_WORD_LIST_PREFIX) :].strip("/")
                self.title_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "h4" and self.in_h4:
            self.in_h4 = False
            self.current_author = "".join(self.h4_parts).strip()
        elif tag == "a" and self.in_link:
            self.in_link = False
            title = "".join(self.title_parts).strip()
            self.pending = {
                "author": self.current_author,
                "title": title,
                "urn": self.link_urn,
                "core": False,
            }
            self.editions.append(self.pending)

    def handle_data(self, data: str) -> None:
        if self.in_h4:
            self.h4_parts.append(data)
        elif self.in_link:
            self.title_parts.append(data)
        elif self.pending is not None:
            if data.lstrip().startswith("*"):
                self.pending["core"] = True
            self.pending = None  # only the text node right after </a> counts


def fetch_editions() -> list[dict[str, str | bool]]:
    resp = requests.get(URL, headers={"User-Agent": "greek-core-vocab/0.2"}, timeout=30)
    resp.raise_for_status()
    parser = EditionsParser()
    parser.feed(resp.text)
    if len(parser.editions) < _MIN_EXPECTED:
        raise SystemExit(
            f"found only {len(parser.editions)} editions (expected >= {_MIN_EXPECTED}) -- "
            "did vocab.perseus.org change the /editions/ page's markup?"
        )
    return parser.editions


def main() -> int:
    editions = fetch_editions()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(editions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    core_n = sum(1 for e in editions if e["core"])
    print(f"{len(editions)} editions ({core_n} core reading list) -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
