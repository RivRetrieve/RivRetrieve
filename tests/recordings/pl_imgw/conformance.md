# IMGW native archive conformance

## Established scope

Explicit download compiles monthly archives through 2022 and the currently published annual archives from 2023. The shared store reader serves local observations. No archive release or packaging regime becomes a source-series variant. Source frequency is daily. The source fields retain water level in cm, discharge in m³/s and water temperature in °C, with unknown archive-wide statistic, day definition, zone and vertical reference. Access products are `stage_daily`, `discharge_daily`, and `water_temperature_daily`; no mean aliases remain.

The catalogue station inventory is a recorded snapshot. Neither it nor the compiled artifact establishes exhaustive current/historical publisher methods. Existing GRDC station provenance and private-evidence boundaries remain unchanged.

## Exact source evidence

The private source archive retains untouched HTTP response bytes and adjacent URL, retrieval instant, status and SHA-256 records under `tests/test_data/pl_imgw_annual/` in the external evidence directory for:

- Official `2024/codz_2024.zip`, SHA-256 `c40ebcda7a6b7ee30c936531fd0f391ba34d5bdf1545b535c3347c39319651fa` (1,753,371 bytes).
- `CODZ_publiczne_format.txt`, SHA-256 `d8e7cbbc7680663d99813dd5f9abd793384b2f560600229625bb808ea71ef362`. This defines COSTAN [cm], COPRZP [m^3/s], COPTMP [st. C], hydrological year/month and calendar month. Missing codes are 9999, 99999.999 and 99.9 respectively. 999 is not a missing-flow code.
- `UWAGA.txt`, which describes temporary annual packaging and changed text quoting, preserving field order. Its promise to regenerate older packaging is not treated as a timeless annual-format guarantee.
- Official [Rocznik Hydrologiczny 2025](https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/Roczniki/Rocznik%20hydrologiczny/Rocznik%20Hydrologiczny%202025.pdf), SHA-256 `c2ad75c472ab46363fb149ac5cf982230e2506d7e0b73b8e4eecb6623fa2a916` (7,887,451 bytes).

The retained monthly `pl_imgw_codz_2022_01.recording.json` remains exact publisher evidence: 24,897 records expand into 74,691 native cells. The small annual fixture used in older tests is not substituted for the new exact annual capture.

## Statistic evidence and limits

Yearbook p.7 states that automatic-station daily levels are chronological means of ten-minute measurements, whereas observer-only daily levels are 06 UTC values. Page8 separately makes this same distinction for discharge. Page9 says daily water temperatures come from measurements at 06 UTC. Page13 notes exceptions when recorders do not operate and daily tables contain 06 UTC measurements. These independently contradict an unconditional mean classification for all three quantities.

The yearbook p.5 describes daily values held in the Central Historical Database (CBDH), then selects 80 level, 80 discharge and18 temperature stations for publication. It does not identify every CODZ station/era or connect field tokens to a complete method inventory. Consequently the library does not extrapolate a universal mean, instantaneous support or06 UTC anchor to the full1951-onward CODZ archive. Precise mean predicates exclude these unknown-statistic series; broad quantity and daily-frequency predicates retain them. The separately inspected2018 official yearbook gives the same mixed-method account, but is not needed as an additional packaged fixture. Earlier library catalogue listings and inaccessible HISTKLIM pages did not establish earlier CODZ method continuity.

## Parser and public proof

`test_pl_imgw_annual.py` compiles the exact2024 archive through the production certified streaming compiler, then uses public find/fetch against the store with network access forbidden. It preserves the outer-quoted CSV layer, native source cells and blank temperature cells. GOZDOWICE152140020 on2024-01-01 publishes999.000m³/s; public retrieval preserves999 rather than null. Native113cm becomes1.13m through the shared conversion exactly once. Receipts remain RivRetrieve-encoded native store excerpts, not reconstructed publisher ZIP bytes.

The definition document calls post2024 missing data `NULL`, but the exact2024 CSV encodes empty fields and has no literal `NULL` token. Those observed fields remain `published_blank`. The document does not prove a literal text token must be accepted; an unobserved nonnumeric token remains a source structure refusal, not a silently guessed missing value. Declared numeric sentinel controls exercise the same compiler.

The sole production decoder is streaming. Scientific sentinel and schema regressions no longer exercise the superseded whole-archive implementation. Compilation retains source-unit accounting and atomic refusal/rollback. Full-history download was not repeated; annual and monthly exact artifacts prove their respective enrolled protocol forms, not completeness of every historical archive.

## Incompatible stores

Old compiled products ending in `_daily_mean` carried the former unsupported global claim. Public reads refuse manifests containing retired access products before querying a subset, under every issue policy, with an explicit rebuild instruction and all files intact. No fabricated identities, aliases or automatic migration are supplied. The tiny retired revision5 store is an explicitly authored incompatibility control, not publisher observation evidence.

Źródłem pochodzenia danych jest Instytut Meteorologii i Gospodarki Wodnej – Państwowy Instytut Badawczy.
