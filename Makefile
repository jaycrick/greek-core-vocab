.PHONY: all editions match fetch homer homer-clone combine report clean distclean

AG_CLOZE_CARDS_REPO ?= $(HOME)/git_repos/ag-cloze-cards

# End-to-end: scrape vocab.perseus.org's own editions catalog -> match
# great_books.tsv against it (+ aliases.yaml/overrides.yaml) -> fetch
# each matched work's word list -> combine every fetched work into the
# one reusable output file. Safe to re-run: fetch skips anything
# already recorded as successful in data/fetch_manifest.json, so a
# re-run after editing aliases.yaml/overrides.yaml only re-does the
# (cheap, local) match/combine steps.
all: editions match fetch combine

# Re-scrapes vocab.perseus.org's own editions list
# (data/perseus_editions.json) -- re-run this if the catalog might have
# changed since the last run.
editions:
	uv run python3 fetch_editions.py

# Re-resolve great_books.tsv against data/perseus_editions.json +
# aliases.yaml/overrides.yaml -> data/matches.yaml. Cheap, local, no
# network -- re-run any time those inputs change.
match:
	uv run python3 match_books.py

# Fetch every matched work's word list (after resolving sibling
# editions -- see fetch_vocab.py), caching to data/raw/ and recording
# data/fetch_manifest.json. Idempotent: only fetches works not already
# recorded as successful. `make fetch REDO=1` re-fetches everything.
fetch:
	uv run python3 fetch_vocab.py $(if $(REDO),--redo,)

# Clone jaycrick/ag-cloze-cards to $(AG_CLOZE_CARDS_REPO) if it isn't
# there already. Not part of `all` -- only `report` (below) needs it.
homer-clone:
	test -d $(AG_CLOZE_CARDS_REPO) || git clone \
		https://github.com/jaycrick/ag-cloze-cards.git $(AG_CLOZE_CARDS_REPO)

# Count WordHoard lemma frequencies for Homer's Iliad/Odyssey by
# shelling out to $(AG_CLOZE_CARDS_REPO)'s own parser (its `uv`
# environment, not this repo's) -> data/homer_counts.json. Local, no
# network (beyond homer-clone and that repo's own `fetch`, done once).
# Feeds `report` only -- WordHoard no longer feeds combine.py, see
# README.md.
homer:
	AG_CLOZE_CARDS_REPO=$(AG_CLOZE_CARDS_REPO) uv run python3 homer_vocab.py

# Parse data/raw/* -> output/master_vocab.csv + .json, the reusable
# deliverable.
combine:
	uv run python3 combine.py

# Optional: compare vocab.perseus.org's own Iliad/Odyssey word lists
# against WordHoard's hand-disambiguated tagging of the same two texts
# -> a self-contained, sortable output/homer_compare.html. Not part of
# `all` -- run after `make all homer` has produced
# output/master_vocab.csv + data/homer_counts.json.
report: homer
	uv run python3 compare_homer.py

# Remove generated data/output, but keep great_books.tsv/aliases.yaml/
# overrides.yaml (the hand-authored inputs). Does not touch
# $(AG_CLOZE_CARDS_REPO) -- a separate clone, not generated here.
clean:
	rm -rf data/perseus_editions.json data/matches.yaml data/homer_counts.json output

# Also drop the fetched raw cache -- a full re-run from `make all`
# after this re-downloads everything from vocab.perseus.org.
distclean: clean
	rm -rf data/raw data/fetch_manifest.json
