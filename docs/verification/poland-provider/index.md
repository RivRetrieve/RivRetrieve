# Poland page verification

Checked 2026-09-27 (UTC) on macOS arm64, CPython 3.13, with `uv sync`. No credentials
are needed. Tested revision: merge `b65ab75de6b94ab760a0986a4ea7c373f23d4e54`, which
brings `docs/provider-poland` up to `main` at `f08ea0a`. The resumed checks also
include `main` at `bcf6faa`. The final branch also includes `main` at `565d391`;
its additional Python changes are docstrings only (verified by comparing parsed
syntax trees with docstrings removed). No production code or catalogue was changed
by this documentation revision.

## Reproduce

From the checkout root, point `RIVRETRIEVE_CACHE_DIR` at a cache directory, then
execute every reader snippet in its documented order. The first snippet downloads and
compiles the national archive; allow the time and disk space given on the page.

```bash
RIVRETRIEVE_CACHE_DIR=<cache directory> uv run python docs/verification/poland-provider/verify_examples.py
uv run pytest -q tests/test_poland_documentation.py tests/test_documentation.py tests/test_supporting_documentation.py tests/test_reference_contracts.py
uv run mkdocs build --strict -d <scratch directory>
```

The verifier uses only the public API, with no fixtures or monkeypatches, and compares
each printed result with the page's following output block.

## Live evidence

The fresh national download on 2026-09-27 ran from 18:38:14 to 20:03:24 UTC
(5,110 seconds) and returned a validated store. It downloaded 867 files
(121,848,536 bytes), with a source vintage of 2025-10-31. The compiled store
occupied about 223 MB; working files reached at least 9 GB. These figures describe
that run, not a performance guarantee. Slow compilation is tracked in #392 as an
enhancement.

The retrieval and cache-status snippets were then run against that live store.
Their printed output matched all four output blocks in the reviewed draft: seven discharge
rows (the first three values 999, 1010 and 1020 m³/s), vintage 2025-10-31,
4.74 m stage, and seven null temperature rows. Retrieval provenance listed all
867 publisher artifacts. `rr.to_utc` refused the unknown time zone as expected.

The subsequent all-snippet verifier was interrupted during another download. Its
partial log is not evidence of a second successful download. On resume, the leftover
`.store.staging-*` directory was removed; the complete store was retained. No fresh
download was started. Check for leftover staging directories after every successful
download.

To recheck the printed outputs without downloading or rebuilding the store:

```bash
RIVRETRIEVE_CACHE_DIR=<existing live cache directory> uv run python docs/verification/poland-provider/verify_examples.py --reuse-store
```

This mode skips only the download snippet and uses the public API for the remaining
snippets. It is a check of the retained live store, not a new acquisition check.
The resumed run on 2026-09-27 (21:10–21:34 UTC) matched all four printed output
blocks in that draft, with zero mismatches. Human review then removed the stage,
temperature and cache-status demonstrations to keep the provider page focused.
The remaining discharge example and its output are unchanged. No staging directory remained after the check.

The resumed documentation test command passed all 45 tests (one dependency
deprecation warning). `uv run mkdocs build --strict` passed, as did Ruff lint and
format checks for the verifier and documentation test. The earlier full-suite log
was interrupted; it is not evidence of a completed full-suite pass.

## Recorded tests

`tests/test_poland_documentation.py` compiles a store from the committed
`tests/test_data/pl_imgw_annual/codz_2024.zip` (retrieved 2026-09-20) and replays the
retrieval snippets with network access disabled. It checks their printed output, the
publisher URL in the provenance, the `to_utc` refusal, the catalogue counts, the
product facts and the index link. It is not live acquisition evidence.

## Claims and limits

- **Packaged catalogue.** 1,301 stations; each lists `discharge_daily`, `stage_daily`
  and `water_temperature_daily`, so 3,903 station-product pairs, all with availability
  `unknown` and no record dates. Frequency is `daily`; the statistic is not
  established, so `statistic="mean"` matches none of them. Stage is declared in `cm`
  and returned in `m`. Every station has `crs="unknown"`. Coordinates come from the
  recovered upstream table `poland_sites.csv`; the catalogue provenance records a later
  GRDC workbook that corroborates every field but is not established as their origin.
  `provider.json` declares bulk observations.
- **Code.** `pl_imgw/bulk.py` reads the publisher's directory listings, accepts one
  monthly or annual edition per year, refuses gaps or overlapping editions, and refuses
  a listed history ending before an existing valid store. Empty cells become
  `published_blank`, the codes 9999, 99999.999 and 99.9 become `published_null`, and
  every other value, including 999, is kept. Dates are labelled at midnight with
  `time_zone="unknown"`. Transport retries (at most three attempts) are documented in
  the usage guide.
- **Coordinate attribution.** Human review confirmed that GRDC supplied the Poland
  coordinates. The reader page states that attribution directly; the historical
  acquisition distinction above remains in this maintainer record.
- **Sources.** The regulations, field description, notice (`UWAGA.txt`), station list
  and change list fetched on 2026-09-27 were identical to the 2026-09-25 copies apart
  from whitespace in the regulations. The station list has 1,301 rows and no
  coordinates. The 2025 yearbook (identical to the committed copy) gives 952 operating
  stations, 916/714/93 stations with daily stage, discharge and temperature in the
  Central Historical Database, 10-minute means at automatic stations and 06:00 UTC
  readings elsewhere. `imgw.pl` could not be reached on 2026-09-27; its "O Instytucie"
  page was last checked on 2026-09-25.
- The checks establish one station, three quantities and one week. They do not
  establish continuous history, national coverage, the statistic of any series, the
  day boundary, a vertical reference, a coordinate reference system or quality
  approval. No legal conclusion about which conditions of the regulations apply to a
  particular use is drawn.

Exploratory logs, the full download log and source snapshots are preserved outside the
Git diff at `.worktrees/poland-provider-evidence-2026-09-24/` in the maintainer checkout.
