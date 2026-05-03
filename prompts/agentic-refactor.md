# Refactor pulpo.club into an agent-pluggable architecture + enforce tests on every PR

You are working on `pulpo.club`, a Salvadoran beach + raw-land aggregator. The
repo crawls boutique-broker sites, normalizes mixed units (vrs² / manzanas /
m²), ranks listings on a four-factor investment composite, and ships a weekly
Wednesday refresh to a Vercel-hosted dashboard.

Read `README.md` first. Then skim `pulpo/scrapers/base.py`,
`pulpo/scrapers/__init__.py`, every module under `pulpo/scrapers/`,
`pulpo/normalize.py`, `pulpo/ranker.py`, `automation/run.py`, and
`tests/test_units.py` so you understand the current shape before changing
anything.

## Goal

Two outcomes:

1. **Agent-pluggable architecture.** Today every "scraper" subclasses
   `BaseScraper`, which assumes an HTML index→detail crawl. That assumption
   already fails for `pulpo/scrapers/century21.py` (single embedded-JSON
   fetch, overrides `crawl()` entirely) and will fail for the eventual
   API-driven Kazu rework. The base class is doing too much. Generalize so
   sources, enrichers, and ranker legs are all plug-ins under a small set
   of registries — adding a new agent for a new task is a single new file
   plus a one-line registration, never a base-class edit.

2. **Tests enforced on every PR.** Today `tests/test_units.py` is the only
   test, and there's no CI. We want: (a) per-source tests against saved
   fixtures, (b) a pipeline smoke test, (c) GitHub Actions that runs pytest
   on every PR, (d) a check that fails the build if a PR adds a new
   scraper/enricher/ranker-leg without a corresponding test file.

## Hard constraints

- **Do not break the existing offline pipeline.** `python3 -m pulpo.cli
  --offline` and `python3 automation/run.py` (with `PULPO_OFFLINE=1`) must
  continue to produce `samples/ranked.csv` and `web/data/ranked.json` with
  at least 21 listings (current fixture count). Run both before declaring
  any phase done.
- **Do not break `tests/test_units.py`.** It must keep passing.
- **Backwards compatibility for existing scrapers.** `goodlife` and
  `oceanside` are calibrated against real saved HTML in
  `samples/calibration/{goodlife,oceanside}/` — their parser logic must
  not change. `kazu` is in fixture-only mode (the panel API host is on a
  proxy denylist); leave that constraint alone.
- **Respect the C21 override.** `pulpo/scrapers/century21.py` overrides
  `crawl()` because the data is in an embedded JSON blob, not paginated
  HTML. Whatever protocol you design must accommodate this case as a
  first-class citizen, not as an exception.
- **No new third-party deps without naming them in your summary.** If you
  add anything to `requirements.txt`, justify it in one line.
- **Conventional commits, small PRs.** Commit each phase separately so the
  diff is reviewable.

## Phase 1 — pytest scaffolding for scrapers

Goal: make it trivial to assert "given saved HTML/JSON for source X, the
parser extracts these specific fields."

1. Create `tests/scrapers/__init__.py` and `tests/scrapers/conftest.py`.
   The conftest exposes a `load_sample(source, filename)` fixture that
   reads from `samples/calibration/<source>/<filename>` and returns the
   raw text, plus a helper to instantiate the scraper class for a source
   without invoking `__init__`'s network setup (use `offline=True`).
2. Write `tests/scrapers/test_goodlife.py` and
   `tests/scrapers/test_oceanside.py`. Each test loads the existing
   calibration HTML files, calls `parse_detail_page` (or the equivalent
   for index pages) directly, and asserts the parsed dict has non-empty
   `title`, `raw_price_text`, `raw_size_text`, `location_text`. Use
   actual values from the saved samples — these are regression tests, so
   they should be specific (e.g., `assert "$350,000" in result["title"]`
   for the saved goodlife Zonte page).
3. Write `tests/scrapers/test_century21.py` that exercises
   `_extract_results` against a small synthetic HTML string containing a
   `window.REP_LOG_APP_PROPS.data.results` JSON blob with two sample
   records (one in `LAND_TYPES`, one not, to verify filtering).
4. Add `tests/test_pipeline_smoke.py` that runs the full offline
   pipeline (call `automation/run.py`'s `main()` directly with
   `PULPO_OFFLINE=1` and `PULPO_LIMIT=10`) and asserts: pipeline exits 0,
   `web/data/ranked.json` exists, length ≥ 15, every record has a
   non-null `rank` and `rank_score`.
5. Add `pytest` and `pytest-cov` to `requirements.txt`.

Acceptance: `pytest -q` runs all tests (units + scrapers + smoke) and
passes. `python3 -m pulpo.cli --offline` still works.

## Phase 2 — GitHub Actions CI

1. Create `.github/workflows/ci.yml` triggered on `push` and
   `pull_request`. Steps:
   - Checkout, set up Python 3.10, install `requirements.txt`.
   - Run `pytest --cov=pulpo --cov-report=term-missing`.
   - Cache pip between runs.
2. Update README.md with a CI badge and a one-line "tests must pass before
   merge" note.

Acceptance: CI runs green on the next push. (You can't actually push, but
the workflow file should be syntactically valid — `actionlint` it
mentally and use the standard `actions/checkout@v4` + `actions/setup-python@v5`.)

## Phase 3 — "tests required for new agents" check

1. Create `.github/workflows/tests-required.yml` (or extend ci.yml) with a
   job that, on `pull_request`, computes the diff of changed files and
   fails if any newly added file under `pulpo/scrapers/`, `pulpo/agents/`,
   or `pulpo/enrichers/` does not have a corresponding test file under
   `tests/scrapers/`, `tests/agents/`, or `tests/enrichers/`.
2. Use a tiny Python script under `.github/scripts/check_tests_added.py`
   that the workflow invokes — easier to maintain than inline shell.
3. Skip the check if the PR has the label `no-test-required` (escape hatch
   for docs-only or pure refactor PRs).
4. Add a `CONTRIBUTING.md` at the repo root that explains: each new
   agent under `pulpo/{scrapers,agents,enrichers}/` must ship with a
   matching test file; otherwise CI fails.

Acceptance: dry-run the script locally against a synthetic diff to confirm
it would fail correctly when a test is missing and pass when it is present.

## Phase 4 — Source protocol + HtmlIndexCrawler split

This is the biggest change. Do it carefully and in one atomic commit so
all scrapers move together.

1. Create `pulpo/agents/__init__.py` with three registries: `SOURCES`,
   `ENRICHERS`, `RANKER_LEGS` (plain dicts keyed by slug). Each registry
   has a `register(slug, obj)` helper.
2. Create `pulpo/agents/source.py` defining a `Source` Protocol:

   ```python
   class Source(Protocol):
       slug: str
       def crawl(self, limit: int = 30, offline: bool | None = None) -> list[dict]: ...
   ```

3. Move the HTML index/detail walking logic out of `BaseScraper` into a
   composable `pulpo/agents/html_crawler.py` named `HtmlIndexCrawler`.
   It exposes `walk(list_url, parse_index, parse_detail, max_pages,
   request_delay) -> list[dict]`. No inheritance — just a function/class
   the source modules instantiate when they need it.
4. Rewrite `pulpo/scrapers/goodlife.py`, `pulpo/scrapers/oceanside.py`,
   and `pulpo/scrapers/kazu.py` so they (a) define a small class with
   `parse_index_page` / `parse_detail_page`, (b) implement `crawl()` by
   delegating to `HtmlIndexCrawler.walk(...)`, (c) keep the
   fixture-fallback path. **Selectors must be untouched** — only the
   surrounding plumbing moves. Run the calibration harness before and
   after to confirm 100% coverage is preserved on goodlife and oceanside.
5. Rewrite `pulpo/scrapers/century21.py` as a `Source` that uses neither
   the HTML crawler nor the base class — it's just a class implementing
   `crawl()` directly. It already does this; you're just removing the
   vestigial `BaseScraper` inheritance.
6. Delete `pulpo/scrapers/base.py` (or shrink it to a deprecated
   re-export shim if you're worried about external imports — there are
   none in this repo, so just delete).
7. Replace `pulpo/scrapers/__init__.py`'s `REGISTRY` with a populated
   `SOURCES` dict imported from `pulpo/agents/`. Keep `REGISTRY` as a
   deprecated alias for one release.
8. Update `automation/run.py` and `pulpo/cli.py` to read from
   `pulpo.agents.SOURCES` instead of `pulpo.scrapers.REGISTRY`.

Acceptance: offline pipeline still produces 21 ranked listings, all
scraper tests still pass, calibration harness reports 100% on
goodlife+oceanside, no scraper module subclasses anything from
`pulpo/scrapers/base.py`.

## Phase 5 — Ranker legs as plug-ins

1. Read `pulpo/ranker.py`. The four legs (value, quality, liquidity,
   upside) are currently hardcoded.
2. Define `pulpo/agents/ranker_leg.py` with a `RankerLeg` Protocol:

   ```python
   class RankerLeg(Protocol):
       slug: str
       weight: float           # default weight
       env_weight_key: str     # e.g. "PULPO_W_VALUE"
       def score(self, listing: Listing, comp_pool: list[Listing]) -> float: ...
   ```

3. Extract each leg into its own module under `pulpo/ranker_legs/`:
   `value.py`, `quality.py`, `liquidity.py`, `upside.py`. Each registers
   with `RANKER_LEGS` on import.
4. Rewrite `pulpo/ranker.py`'s `rank()` so it walks `RANKER_LEGS`,
   computes each leg's 0–100 score, applies the env-overridable weights,
   and produces the composite. The CLI weights tuner (env vars) must
   still work, and the dashboard's leg-by-leg display must not break
   (same field names on Listing).
5. Add `tests/agents/test_ranker_legs.py` covering each leg in isolation
   against a tiny hand-built listing pool.

Acceptance: top-5 of `python3 -m pulpo.cli --offline` is unchanged from
before this phase. Composite scores match to within 0.1 (rounding noise
acceptable). Env-var weight overrides still reshuffle the leaderboard.

## Phase 6 (optional, lower priority) — LLM extraction fallback

If you have time:

1. Create `pulpo/agents/llm_extract.py` with a `Source`-shaped fallback
   that takes raw HTML + a Pydantic schema and calls Claude Haiku via the
   Anthropic SDK to extract the fields. Include a hard timeout, a token
   budget, and a `extraction_method: "llm"` tag on the output dict.
2. Wire it into `HtmlIndexCrawler.walk` as an opt-in: if the
   selector-based parser returns no usable fields and
   `PULPO_LLM_FALLBACK=1` is set, retry with the LLM agent.
3. Document the cost envelope in `pulpo/agents/llm_extract.py`'s
   docstring (Haiku pricing × expected weekly volume).
4. Add `anthropic>=0.40` to `requirements.txt` (justify in summary).

Acceptance: a deliberately-broken-selector test for goodlife still
returns parsed fields when the LLM fallback is enabled and the
`ANTHROPIC_API_KEY` env var is set, and skips gracefully when not.

## Verification before declaring done

Run, in order, and report the output of each:

```bash
pytest -q
python3 -m pulpo.cli --offline
python3 automation/run.py
python3 automation/calibrate.py --all
```

All four must complete with no errors. The first two must show ≥21
ranked listings. The calibration harness must report 100% on goodlife
and oceanside.

## Final summary

Write a short summary (≤ 200 words) covering: what changed at the
architecture level, which phases you completed (and which you skipped
and why), any deviations from this plan and the reason, any new
dependencies, and a one-paragraph "how to add a new agent" snippet
suitable for `CONTRIBUTING.md` / the docstring of `pulpo/agents/__init__.py`.

If you hit any blocker that requires my judgment (e.g. a calibration
sample is missing, an existing test fails for a reason that isn't
obviously a regression you caused, a dep won't install in CI), stop and
ask — don't paper over it.
