.PHONY: all work-list match fetch corpus corpus-clone homer homer-clone combine report clean distclean

CORPUS_REPO ?= $(HOME)/git_repos/vocabulary-corpus-prep
AG_CLOZE_CARDS_REPO ?= $(HOME)/git_repos/ag-cloze-cards

# End-to-end: scrape Perseus's catalog -> match great_books.tsv against
# it (+ corpus_map.yaml, resolving some rows to
# greek-learner-texts/vocabulary-corpus-prep or ag-cloze-cards's
# WordHoard Homer parse instead) -> fetch each matched work's Perseus
# vocabulary -> count each corpus/Homer-resolved work's gold lemma
# tagging -> combine every source into the one reusable output file.
# Safe to re-run: fetch skips anything already cached in data/raw/ (see
# fetch_vocab.py), so a re-run after editing aliases.yaml/
# overrides.yaml/corpus_map.yaml only re-does the (cheap, local)
# match/corpus/homer/combine steps.
all: work-list match fetch corpus homer combine

# Re-scrapes Perseus's own work list (data/perseus_works.json) --
# re-run this if Perseus's catalog might have changed since the last run.
work-list:
	uv run python3 fetch_work_list.py

# Re-resolve great_books.tsv against data/perseus_works.json +
# corpus_map.yaml/aliases.yaml/overrides.yaml -> data/matches.yaml.
# Cheap, local, no network -- re-run any time those inputs change.
match:
	uv run python3 match_books.py

# Fetch every unique matched URN's vocabulary list, caching to
# data/raw/ and recording data/fetch_manifest.json. Idempotent: only
# fetches URNs not already recorded as successful. `make fetch
# REDO=1` re-fetches everything.
fetch:
	uv run python3 fetch_vocab.py $(if $(REDO),--redo,)

# Clone greek-learner-texts/vocabulary-corpus-prep to $(CORPUS_REPO) if
# it isn't there already. Not part of `all` -- run once, or point
# CORPUS_REPO at an existing clone.
corpus-clone:
	test -d $(CORPUS_REPO) || git clone \
		https://github.com/greek-learner-texts/vocabulary-corpus-prep.git $(CORPUS_REPO)

# Count lemma frequencies for every corpus_map.yaml-resolved row from
# $(CORPUS_REPO)'s gold per-work tagging -> data/corpus_counts.json.
# Local, no network (beyond corpus-clone, done once).
corpus:
	CORPUS_REPO=$(CORPUS_REPO) uv run python3 corpus_vocab.py

# Clone jaycrick/ag-cloze-cards to $(AG_CLOZE_CARDS_REPO) if it isn't
# there already. Not part of `all` -- run once, or point
# AG_CLOZE_CARDS_REPO at an existing clone.
homer-clone:
	test -d $(AG_CLOZE_CARDS_REPO) || git clone \
		https://github.com/jaycrick/ag-cloze-cards.git $(AG_CLOZE_CARDS_REPO)

# Count WordHoard lemma frequencies for Homer's Iliad/Odyssey by
# shelling out to $(AG_CLOZE_CARDS_REPO)'s own parser (its `uv`
# environment, not this repo's) -> data/homer_counts.json. Local, no
# network (beyond homer-clone and that repo's own `fetch`, done once).
homer:
	AG_CLOZE_CARDS_REPO=$(AG_CLOZE_CARDS_REPO) uv run python3 homer_vocab.py

# Parse data/raw/* + data/corpus_counts.json + data/homer_counts.json ->
# output/master_vocab.csv + .json + output/lemma_join_report.tsv, the
# reusable deliverables.
combine:
	uv run python3 combine.py

# Optional: compare output/master_vocab.csv's top 100 headwords against
# vocabulary-corpus-prep's own top 100 (aggregated across all 49 of its
# works, not just the 6 corpus_map.yaml uses) -> a self-contained,
# sortable output/top100_compare.html. Not part of `all` -- run after
# `make all` has produced master_vocab.csv. Needs $(CORPUS_REPO)
# (`make corpus-clone`).
report:
	CORPUS_REPO=$(CORPUS_REPO) uv run python3 compare_top100.py

# Remove generated data/output, but keep great_books.tsv/aliases.yaml/
# overrides.yaml/corpus_map.yaml (the hand-authored inputs). Does not
# touch $(CORPUS_REPO)/$(AG_CLOZE_CARDS_REPO) -- separate clones, not
# generated here.
clean:
	rm -rf data/perseus_works.json data/matches.yaml data/corpus_counts.json \
		data/homer_counts.json output

# Also drop the fetched raw cache -- a full re-run from `make all`
# after this re-downloads everything from Perseus.
distclean: clean
	rm -rf data/raw data/fetch_manifest.json
