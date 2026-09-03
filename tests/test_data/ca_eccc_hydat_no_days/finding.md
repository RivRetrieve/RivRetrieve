# HYDAT `NO_DAYS` official-semantics finding

## Disposition

`DLY_FLOWS.NO_DAYS` and `DLY_LEVELS.NO_DAYS` denote the number of calendar days in the row's year/month. They do not denote the last populated day or the number of observations. The two reported `DLY_LEVELS` rows contain erroneous `NO_DAYS` metadata. Their later `LEVELn` cells are valid published daily observations, not stale cells and not structurally unused cells.

A decoder must derive the valid day slots from `YEAR` and `MONTH`, inspect every slot from day 1 through the real calendar-month length, and never truncate at `NO_DAYS`. It must retain `NO_DAYS` verbatim because the anomalous values cannot be reconstructed from the decoded dates. It must preserve or emit every in-calendar value cell and its paired `FLOW_SYMBOLn` or `LEVEL_SYMBOLn`. It must retain `FULL_MONTH`, `DLY_LEVELS.PRECISION_CODE`, symbols, monthly aggregates, and extrema under the existing source-column evidence contract. Slots beyond the real calendar length are structurally unused; the complete database audit found no populated such slot.

## Verbatim official database definitions

Source: ECCC, [`HYDAT_Definition_EN.pdf`](https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/HYDAT_Definition_EN.pdf), pages 4–5 in the captured PDF.

For both `DLY_FLOWS` and `DLY_LEVELS`, the field description is:

> `NO_DAYS` ... `Number of days in this month`

For both tables, the separate field description is:

> `FULL_MONTH` ... `Flags whether the data exist for every day of the month`

The same definition lists `FLOW1` as “Daily flow value (m^3/s)” and `LEVEL1` as “Daily water level value (m)”, followed by “Flow, Symbol (for 31 days)” and “Level, Symbol (for 31 days).” There is no documented rule that makes `NO_DAYS` a positional cutoff.

Captured PDF: `tests/test_data/ca_eccc_hydat_no_days/HYDAT_Definition_EN.pdf`  
Requested/final URL: `https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/HYDAT_Definition_EN.pdf`  
Retrieval: 2026-09-02T18:07:04.779288Z to 2026-09-02T18:07:05.513719Z  
HTTP: 200, `application/pdf`, no redirects  
Bytes: 51748  
SHA-256: `b3ab1954bf5aeedb026cebe939764fcfbda0266fb267cb6a7315544c9be8e1ee`  
Server `Last-Modified`: `Mon, 09 May 2016 19:29:44 GMT`

## Official web-service corroboration

ECCC's official `WebService_Guidelines_HistoricalDailyData.pdf` says that if data are available for the requested station, parameter, and period, the returned CSV contains those data. Its documented endpoint is `https://wateroffice.ec.gc.ca/services/daily_data/csv/inline`.

Guideline capture: `tests/test_data/ca_eccc_hydat_no_days/WebService_Guidelines_HistoricalDailyData.pdf`  
Requested/final URL: `https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/Document/WebService_Guidelines_HistoricalDailyData.pdf`  
Retrieval: 2026-09-02T18:07:05.514676Z to 2026-09-02T18:07:06.671591Z  
HTTP: 200, `application/pdf`, no redirects  
Bytes: 288257  
SHA-256: `5affda6f03271194b04d8b1882eeaecbd629a86fa7ef0be8b5243a9aea4b87d5`

### `07HF001`, March 2013

SQLite: `NO_DAYS=20`, `FULL_MONTH=0`, `PRECISION_CODE=8`; populated `LEVEL12` through `LEVEL31` (20 values). `LEVEL12=5.551000118255615`, symbol `A`; `LEVEL21=5.072000026702881`; `LEVEL31=5.703000068664551`. All later symbols are null. `DATA_SYMBOLS` defines `A` as `Partial Day`.

The official API CSV publishes 20 observations dated 2013-03-12 through 2013-03-31. Thus it expressly publishes 11 observations whose day number exceeds `NO_DAYS`, including 2013-03-21 through 2013-03-31. Every API value and symbol matches SQLite at the API's three-decimal representation.

CSV: `tests/test_data/ca_eccc_hydat_no_days/07HF001_level_2013-03.csv`  
Requested/final URL: `https://wateroffice.ec.gc.ca/services/daily_data/csv/inline?stations%5B%5D=07HF001&parameters%5B%5D=level&start_date=2013-03-01&end_date=2013-03-31`  
Retrieval: 2026-09-02T18:07:06.672728Z to 2026-09-02T18:07:07.251789Z  
HTTP: 200, `text/csv; charset=utf-8`, content encoding `gzip`, no redirects  
Decoded CSV bytes: 981  
Decoded CSV SHA-256: `b6d049e72a493e49d91fe10ac12cb314fbb481988fc1b26c47eb646f8fae3b87`  
Untouched wire body: `tests/test_data/ca_eccc_hydat_no_days/07HF001_level_2013-03.csv.http-wire.gz` (236 bytes, SHA-256 `0bca94ab6fd24a22d12933e187b2fc10b05a10ba8b2d29992ece8ee6791c7403`)

### `07HF001`, May 2014

SQLite: `NO_DAYS=29`, `FULL_MONTH=0`, `PRECISION_CODE=8`; populated `LEVEL3` through `LEVEL31` (29 values). `LEVEL3=6.296999931335449`, symbol `A`; `LEVEL30=5.336999893188477`; `LEVEL31=5.235000133514404`. All later symbols are null.

The official API CSV publishes 29 observations dated 2014-05-03 through 2014-05-31. Thus it expressly publishes `LEVEL30` and `LEVEL31`, whose day numbers exceed `NO_DAYS`. Every API value and symbol matches SQLite at the API's three-decimal representation.

CSV: `tests/test_data/ca_eccc_hydat_no_days/07HF001_level_2014-05.csv`  
Requested/final URL: `https://wateroffice.ec.gc.ca/services/daily_data/csv/inline?stations%5B%5D=07HF001&parameters%5B%5D=level&start_date=2014-05-01&end_date=2014-05-31`  
Retrieval: 2026-09-02T18:07:07.252892Z to 2026-09-02T18:07:07.812337Z  
HTTP: 200, `text/csv; charset=utf-8`, content encoding `gzip`, no redirects  
Decoded CSV bytes: 1395  
Decoded CSV SHA-256: `f0b27c934f56dabdff7830b6c0b848a8c61f260d0c8a59c36b3be558e9d67ed8`  
Untouched wire body: `tests/test_data/ca_eccc_hydat_no_days/07HF001_level_2014-05.csv.http-wire.gz` (303 bytes, SHA-256 `bee1544b3b71c694c81ae06e15106d749209ed018ff5d1fa1fac4f16ed65b5ce`)

## Whole-database observations

Official release artifact: `Hydat_sqlite3_20260717.zip`, 278,852,677 bytes, SHA-256 `b05eb121a547ca4a179a27aa47c354089fd902e93e5dc1e4a5416fc4641eb298`.

* `DLY_LEVELS`: 840,225 rows; exactly 2 rows have any populated `LEVELn` where `n > NO_DAYS`. They are the two rows above.
* `DLY_FLOWS`: 1,779,871 rows; zero rows have any populated `FLOWn` where `n > NO_DAYS`.
* Neither table has any populated value in a slot beyond the actual calendar length.
* `NO_DAYS` cannot mean count of available data. For example, `DLY_LEVELS` contains 8,796 rows with `NO_DAYS=31` but only one populated level, and `DLY_FLOWS` contains 4,537 such rows.
* The SQLite `CREATE TABLE` declaration gives `NO_DAYS INTEGER` and has no constraint or cutoff rule.

Exact captured SQLite rows are in `sqlite_rows_07HF001.json`. The 62-day cell comparison is in `sqlite_vs_official_api.csv`; all 62 comparisons agree, including null dates. The reproducible audit predicate is in `audit_query.sql`, with results in `audit_result.json`.
