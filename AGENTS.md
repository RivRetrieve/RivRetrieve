# Project Instructions

A rule appears in this file only if (a) it encodes a project choice that cannot be inferred from the code, or (b) default model output violates it. Practices a model already follows unprompted, and anything ruff or ty enforces mechanically, are deliberately absent.

## 0. Project Overview

RivRetrieve downloads river gauge data from national hydrology agencies and returns it in one shape.

The promise it cannot break: **faithful, traceable access through one consistent shape across every provider.** A user can trust a number and follow it back to its source.

The boundary that keeps that promise finite: **harmonise identity and physics, never harmonise judgement.** Units, column shape, time representation and product identity are objective, so we convert them. Quality codes, station identity across borders, and river naming are interpretation, so we surface them exactly as the source gave them and adjudicate nothing.

Domain terms are defined in `CONTEXT.md`. Decisions that are hard to reverse are recorded in `docs/adr/`.

## 1. Python Environment

Use `uv` exclusively.

- Add dependencies: `uv add <package>` (dev: `uv add --dev <package>`)
- Sync environment: `uv sync`
- Run anything: `uv run <command>`, tests: `uv run pytest`

Do not use `pip`, `poetry`, `conda`, or `pip-tools` directly.

Format, lint, and type-check with:

```bash
uv run ruff format
uv run ruff check --fix
uv run ty check
```

## 2. Design Doctrine

Four rules. They are one design stance seen four ways: a module means one thing, receives exactly what it needs, in types that cannot lie, and dies rather than guess.

### 2.1 Denotation line

Before implementing a module, state in one line what it computes as a mathematical object, and record that line in the module docstring. Carriers must be named domain types, not placeholders.

```
preprocess : RawForcing × Attributes → Dataset   (pure)
training run = fold(update, θ₀, batches)
evaluation = map(metric) over (basin × model) pairs
```

If the line cannot be written, the design is not ready; say so instead of coding around it. In review, when the denotation line and the diff disagree, one of them is wrong.

### 2.2 Authority narrows

All wiring happens at the composition root: only the entry point (CLI command or `main()`) reads config files, reads environment variables, resolves paths, and opens stores. Every other module receives what it needs as arguments.

At every call, pass the narrowest argument that suffices: the two columns, not the DataFrame; the file path, not the directory; the three fields, not the config object. A function outside the entry module whose signature accepts the full config, or which constructs a `Path` from a literal, is a violation.

### 2.3 Parse, don't validate

Convert raw input (CLI args, YAML, NetCDF attributes) into domain types once, at the composition root. Downstream functions accept and return only domain types for concepts that carry an invariant or unit ambiguity: identifiers, physical quantities, config. A `float` that might be mm/day or m³/s must not exist past the boundary.

Enums over booleans: never `bool` for a domain state with two named possibilities. Use an `Enum` or `Literal["upstream", "downstream"]`, not `upstream: bool` — applies to parameters, fields, and return values.

Limits: domain types (`NewType`, frozen dataclass, enum) are for concepts with invariants, not for every value. Bulk numerical data stays in `xarray`/`polars` carriers; do not wrap arrays in classes.

### 2.4 Fail loud

Crash early on broken assumptions. No fallback values for required inputs (`.get(key, default)` on a required config key is a bug). No exception handler that logs and continues.

The one exception: a batch loop over independent items (e.g. per-basin processing) may have exactly one named isolation point that catches per-item failure, records which item failed and why, and continues. That point exists once per pipeline, not once per function.

## 3. Testing Complex Data Objects

Prefer library-specific assertions over manual element-wise checks of lengths, schemas, coordinates, shapes, or dtypes.

```python
np.testing.assert_allclose(result, expected)
xr.testing.assert_identical(result, expected)
pl_testing.assert_frame_equal(result_df, expected_df)
```

## 4. Packaged Catalogue Rule

Packaged catalogue generation has two regimes, keyed on whether the provider has both a committed
native table and origin declarations.

The committed native table carries provenance. Produce it with the provider's `refresh` operation
against the live provider API. It may instead be materialized from a `tests/test_data/` fixture only
when that fixture has been verified content-identical to a live payload and the repository record
states the source URL, retrieval instant, canonicalization method, and digest. Nothing unattested
may enter the repository from a fixture. A third sanctioned route is a live fetch performed outside
the executor sandbox and supplied as an orchestrator step input. That input requires the same complete
attestation: exact request URL or URLs, UTC retrieval instant, row or feature count, canonicalization
method, and SHA-256 digest.


An orchestrator may also perform a live fetch outside a network-disabled executor and supply the
complete response as a step input. This route is sanctioned only when the same repository record
contains every exact request URL, one UTC retrieval instant per supplied file, or a single campaign instant when the fetch is atomic, the accepted row and station counts,
the deterministic canonicalization and ordering rules, SHA-256 evidence, and a semantic frame
comparison between the committed native content and a fresh materialization of the complete supplied
response.

A fourth sanctioned route is a recovered historical import whose complete committed payload cannot
be reproduced from publisher routes. Its repository record must name the third-party materialization
and exact commit, establish raw-byte SHA-256 identity, use a defensible provenance lower-bound instant,
cross-check the complete identifier set against an independent live source, and measure coverage,
precision, and agreement against every available publisher route. This route is closed to every
provider whose complete committed payload can be reproduced by a publisher route. It is permitted only
where the repository record explicitly establishes why every available publisher route is insufficient;
a partial or coarser live route does not by itself close the recovered route.

- Poland recovered native-table attestation: `tests/test_data/pl_imgw_stations.csv` is byte-identical
  to `rivretrieve/cached_site_data/poland_sites.csv` in `kratzert/RivRetrieve-Python` at commit
  `f67f6d8507a55144bf235feb3f27f65648b90f83`. It contains 1,301 recovered rows and has raw SHA-256
  `8c4cdd675c2811cd3b91a5889cbcd4273830c2fa4ee90ad6142c69ba7a198f49`. That upstream commit's
  timestamp, `2025-10-10T18:46:34Z`, is the native rows' defensible provenance lower bound. The
  IMGW-to-GRDC email delivery and `hydrodownloadR`'s later `Metadata_GRDC_30.10.2025.xlsx`
  materialization corroborate the recovery. The later spreadsheet is not established as the fixture's
  exact delivery, and its later `source_stamp` is not the native timestamp. Provenance is recovered,
  so an unestablished-provenance escalation is unnecessary. The coordinates in `bczernecki/climate`
  are a different, falsified candidate dataset and are not the geometry source.

  The orchestrator retrieved
  `GET https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/lista_stacji_hydro.csv`
  outside the executor sandbox at `2026-08-02T19:54:27Z`. The response has 66,632 raw bytes,
  SHA-256 `4b401f44942b59ac82b4485d07194215d5847127aefc8ba911386720a7e24755`, and 1,301
  CP1250, headerless, comma-delimited, quoted four-column rows. Stripping only leading whitespace
  from station identifiers yields 1,301 unique nine-character identifiers. Sorting those identifiers,
  serializing the list as compact JSON with separators `(",", ":")`, and UTF-8 encoding it yields
  SHA-256 `1afe2782a67081642aabebd40b0b7547e7c3b9231fb26a79b738175860a3fc20`, exactly equal to
  the recovered identifier set. The roster contains no geometry and contributes none to the native rows.

  The orchestrator also supplied `inputs/apiinfo.html`, `inputs/kody_stacji.csv`, and
  `inputs/hydro_api.json`; fresh-clone tests consume their byte-identical committed copies
  `tests/test_data/pl_imgw_apiinfo.html`, `tests/test_data/pl_imgw_kody_stacji.csv`, and
  `tests/test_data/pl_imgw_hydro_api.json`. All were captured at `2026-08-02T18:45:32Z`:
  `GET https://danepubliczne.imgw.pl/pl/apiinfo` returned 37,075 HTML bytes with SHA-256
  `9b82e28e580d4b22ab6475e129f4dd6d798a0c860d52b9e2f9d2bc3098418d9c`;
  `GET https://danepubliczne.imgw.pl/datastore/getfiledown/Arch/Telemetria/Hydro/kody_stacji.csv`
  returned 68,371 bytes and 887 unique stations in clean UTF-8, semicolon-delimited CRLF form with
  whole-arc-second DMS coordinates, with SHA-256
  `0ffbaa1cbda89bf9092d728552cce63ae95fd830d16b8e98d5b8de9d4b57aab5`; and
  `GET https://danepubliczne.imgw.pl/api/data/hydro/?format=json` returned 554,065 JSON bytes and
  913 published station rows, 32 with zero or absent coordinates, with SHA-256
  `e2b61c8772ca53e8a39a9296362b0ba1b87205afbf156b49691fb6f86679eb1f`.

  The 881 API rows with usable non-zero coordinates have IDs that are a subset of the 887
  `kody_stacji.csv` IDs, and therefore the 779 API-covered committed stations are a subset of the
  784 CSV-covered committed stations. The 32 zero-or-absent-coordinate API rows are exactly the 32
  published API IDs absent from the CSV. Separately, of all 913 published API IDs, 106 are absent
  from the 1,301-station recovered/roster set. Publisher-route union coverage is 784 and leaves 517
  recovered stations uncovered. Deterministic DMS conversion uses
  `degrees + minutes / 60 + seconds / 3600`; at `1.5 / 3600` degrees absolute tolerance on each axis,
  zero of 784 pairs are exact, 779 agree on both axes, and five are accepted disagreements. Station
  `154180190` is worst at a maximum absolute axis difference of approximately `0.0053675` degrees
  (`0.0054` degrees). The 913-row JSON is rejected as replacement geometry because it is partial,
  includes 32 unusable coordinate rows, and does not reproduce the recovered population or precision.

  The recovered import is sanctioned because the live publisher route covers only 784 of the 1,301 committed stations (60%), leaves 517 stations (40%) without publisher-published coordinates, and publishes only whole-arc-second coordinates where the recovered import provides all 1,301 stations at finer precision, so the live route cannot reproduce the committed catalogue.

  The committed native table preserves the seven source columns in declared order, sorts rows by exact
  `gauge_id`, and appends the single UTC-microsecond lower-bound `retrieved_at`. Its content digest is
  computed from an object containing columns in exact schema order and positional rows sorted by
  `gauge_id`; timestamps have exactly six fractional digits and `Z`, and compact JSON uses sorted object
  keys, separators `(",", ":")`, `ensure_ascii=False`, and UTF-8. The full-frame SHA-256 is
  `c7fb3582edcc4b66a154d5dac52acd22d2847cd04ed54f5ee94fbf7c8bc6d9ec`, recomputed from the
  Parquet reread in the same run that writes it.

### 4.1 Providers with a committed native table and origins

For a provider with both a committed native table and origin declarations (currently `ba_fhmzbih`,
`ca_eccc`, `ch_foen`, `cz_chmi`, `fr_hubeau`, `jp_mlit`, `lt_lhmt`, `pl_imgw`, `th_thaiwater`,
`usgs_nwis`, and `za_dws`), the four
canonical packaged catalogue artifacts (`catalogue/provider.json`, `catalogue/products.parquet`,
`catalogue/stations.parquet`, and
`catalogue/station_products.parquet`) are a pure, network-free function of that committed table and
the provider's origins. Generating the canonical artifacts from a live API is forbidden because it
would reintroduce the nondeterminism the pure build removes. In particular, future USGS canonical
generation must use its committed `native.parquet`, never `--live` or supplied RDB payloads. Future
Poland canonical generation must likewise use committed `native.parquet` plus origins, never `--live`,
supplied live JSON, or a fixture-backed canonical route.

- South Africa DWS native-table attestation: the live host returned HTTP 403 to the orchestrator from
  two independent egress points; the network-disabled executor did not perform a fetch. The
  orchestrator supplied these nine Internet Archive captures, each with its own UTC retrieval instant:

| File | Archived request URL | Origin URL | Snapshot | Bytes | SHA-256 | Retrieved at |
|---|---|---|---:|---:|---|---|
| `HyCatalogue.aspx` | `http://web.archive.org/web/20260311133455id_/https://www.dws.gov.za/hydrology/Verified/HyCatalogue.aspx` | `https://www.dws.gov.za/hydrology/Verified/HyCatalogue.aspx` | `20260311133455` | 6,778 | `6cf0495ce6ef31bba2d0e746cc8c001d91a8ac8b2c4e634b57f9099d5edafc71` | `2026-08-02T18:47:00Z` |
| `WMA1_Limpopo-Olifants_River.pdf` | `http://web.archive.org/web/20251122081546id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA1_Limpopo-Olifants_River.pdf` | `https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA1_Limpopo-Olifants_River.pdf` | `20251122081546` | 977,280 | `b6efb89b9f74e0fe9bdca4f2984ce008d77b8f5692fd359a485b9ea4d8ad06a8` | `2026-08-02T18:47:01Z` |
| `WMA2_Inkomati-Usuthu_River.pdf` | `http://web.archive.org/web/20251127140120id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA2_Inkomati-Usuthu_River.pdf` | `https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA2_Inkomati-Usuthu_River.pdf` | `20251127140120` | 449,874 | `16186305a3fff3bdda90eaf0889827a773014837bdbb4cb2ab0f0ae1a2a360cf` | `2026-08-02T18:47:02Z` |
| `WMA3_Pongola-Mtamvuna_River.pdf` | `http://web.archive.org/web/20251127181748id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA3_Pongola-Mtamvuna_River.pdf` | `https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA3_Pongola-Mtamvuna_River.pdf` | `20251127181748` | 689,780 | `b9f0e0445484c980b708ff78c7a1cc8803a7d10f4d73c33925d5cae184611c8c` | `2026-08-02T18:47:03Z` |
| `WMA4_Vaal-Orange_River.pdf` | `http://web.archive.org/web/20251126040946id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA4_Vaal-Orange_River.pdf` | `https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA4_Vaal-Orange_River.pdf` | `20251126040946` | 1,179,466 | `dc502341aaf4928def221e32dc9543fd5a9f982aee9df7de4950e95805cf5bc3` | `2026-08-02T18:47:04Z` |
| `WMA5_Mzimvubu-Tsitsikamma_River.pdf` | `http://web.archive.org/web/20251127142153id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA5_Mzimvubu-Tsitsikamma_River.pdf` | `https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA5_Mzimvubu-Tsitsikamma_River.pdf` | `20251127142153` | 671,281 | `0d76cedcfdafe2ce9dc8e93eef909e288f6826d7ab729a4856b1cb3c6e0fdde0` | `2026-08-02T18:47:05Z` |
| `WMA6_Breede-Olifants_River.pdf` | `http://web.archive.org/web/20251121090856id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA6_Breede-Olifants_River.pdf` | `https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA6_Breede-Olifants_River.pdf` | `20251121090856` | 930,945 | `6fb1d753b22bb4fbe038913249d0c2c8b58a619df35754918061c52163acd91e` | `2026-08-02T18:47:06Z` |
| `WMA7_Eswatini_River.pdf` | `http://web.archive.org/web/20251121161554id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA7_Eswatini_River.pdf` | `https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA7_Eswatini_River.pdf` | `20251121161554` | 192,256 | `f820f9002cdba9a0f44b1ac98b1d160b2755dc0ddb27713bac6c435d3c8a7e86` | `2026-08-02T18:47:07Z` |
| `WMA8_Lesotho_River.pdf` | `http://web.archive.org/web/20251121113702id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA8_Lesotho_River.pdf` | `https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA8_Lesotho_River.pdf` | `20251121113702` | 214,048 | `9511f46b79d172a2e2540d90bb1679b93670ce75e9b0dc8660f1fde78277ee26` | `2026-08-02T18:47:09Z` |

  All manifest HTTP statuses are 200. Deterministic PDF text parsing produces respectively 544, 210,
  417, 702, 406, 567, 19, and 40 rows, totaling 2,905 rows and 2,905 unique `Station` values. It
  repairs 40 standard-code rows lost because their drainage region is blank plus the suffixed codes
  `A2H090Q` and `B6H018M01`. The schema, in order, is `Station`, `Description`,
  `Latitude (dd:mm:ss)`, `Longitude (dd:mm:ss)`, `Drainage Region`, `Catchment Area km**2`,
  `WMA source-file identity`, and UTC-microsecond `retrieved_at`. Source DMS and catchment strings,
  null drainage regions, and exact PDF filenames remain unchanged; rows sort by exact `Station`, and
  each row carries its originating PDF's retrieval instant. Full-table canonicalization emits a
  compact UTF-8 JSON outer list of row lists in schema and row order, with `ensure_ascii=False`,
  `allow_nan=False`, JSON nulls, and UTC datetimes rendered with exactly six fractional digits and
  `Z`. Its SHA-256 is `7949369cf573d675cf8cb2374fa172038e10e492299572df442834d6a08e40fc`.
  Fresh materialization of all supplied bytes is exactly semantically frame-equal to the committed
  native table. `tests/test_data/za_dws_metadata.json` is the `A1H001`, `A2H090Q`, and `A8H017`
  subset derived from `WMA1_Limpopo-Olifants_River.pdf`, whose attested SHA-256 is
  `b6efb89b9f74e0fe9bdca4f2984ce008d77b8f5692fd359a485b9ea4d8ad06a8`; every fixture value is
  identical to its corresponding committed-native row.

- USGS native-table attestation: the orchestrator made the following 102 requests for the ordered
  51-code (50 states plus DC) `_US_STATE_CODES` scope at `2026-08-02T01:14:11Z`:

- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=AL&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=AL&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=AK&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=AK&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=AZ&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=AZ&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=AR&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=AR&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=CA&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=CA&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=CO&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=CO&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=CT&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=CT&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=DE&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=DE&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=FL&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=FL&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=GA&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=GA&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=HI&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=HI&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=ID&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=ID&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=IL&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=IL&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=IN&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=IN&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=IA&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=IA&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=KS&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=KS&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=KY&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=KY&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=LA&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=LA&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=ME&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=ME&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MD&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MD&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MA&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MA&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MI&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MI&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MN&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MN&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MS&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MS&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MO&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MO&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MT&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=MT&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NE&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NE&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NV&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NV&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NH&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NH&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NJ&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NJ&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NM&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NM&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NY&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NY&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NC&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=NC&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=ND&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=ND&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=OH&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=OH&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=OK&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=OK&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=OR&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=OR&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=PA&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=PA&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=RI&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=RI&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=SC&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=SC&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=SD&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=SD&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=TN&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=TN&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=TX&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=TX&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=UT&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=UT&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=VT&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=VT&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=VA&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=VA&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=WA&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=WA&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=WV&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=WV&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=WI&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=WI&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=WY&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=WY&siteOutput=expanded`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=DC&seriesCatalogOutput=true`
- `GET https://waterservices.usgs.gov/nwis/site/?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd=DC&siteOutput=expanded`

  The [USGS Site Service documentation](https://waterservices.usgs.gov/docs/site-service/site-service-details/)
  states that `hasDataTypeCd` selects sites, `seriesCatalogOutput=true` returns period-of-record
  rows, and `siteOutput=expanded` cannot be combined with `seriesCatalogOutput=true`. The complete
  supplied response contained 55 codes and 110 files. Every entry passed `MANIFEST.sha256`; the
  manifest's SHA-256 is `d29ee34feaef0dda458c369ed5448e96b7e8b7064176a5f94360881b6cbdf34a`.
  The exact 102 consumed manifest lines have SHA-256
  `e197d3d5eb6f971e631693d7d6e2b26d1c7b7031850d62ed11f5891011dbc6bc`.

  The accepted 51-code scope has 26,258 stations in each pass, 2,036,546 series rows, zero
  cross-pass orphans, only `NAD83` in `dec_coord_datum_cd`, and both `dv` and `uv` source
  rows. The excluded `GU`, `MP`, `PR`, and `VI` files account for 275 stations. The complete
  supplied 55-code census has 26,533 stations in each pass, 2,055,307 series rows, and zero
  cross-pass orphans.

  Canonicalization keeps all 42 expanded fields as exact scalar strings; checks the twelve repeated
  series-pass station fields byte-for-byte against them; retains the twelve series-only fields as
  aligned `List(String)` columns; preserves duplicate complete series rows; sorts complete
  24-field series rows lexicographically in source header order within each station; sorts stations
  by exact `site_no`; and appends the single UTC-microsecond `retrieved_at`. No field is trimmed,
  renamed, parsed, converted, or harmonized. The compact UTF-8 JSON list of sorted `site_no`
  values, serialized with separators `(",", ":")` and `ensure_ascii=False`, has SHA-256
  `8ad79dac66b25a9dc46ebd30b650c1e647b44d9b31c9bc4fdd17c5e46f4ee241`. The full table is
  serialized as a compact UTF-8 JSON outer list of row lists in the declared schema
  order, using the same separators and `ensure_ascii=False`; `retrieved_at` is rendered as an
  RFC 3339 UTC string with exactly six fractional digits and `Z`. Its SHA-256, emitted by the same
  regeneration run that writes the native table, is
  `e4384cea2ff00e5a120d244977d2dd75bc00ec4c8ba941e3e83f06239cd5777f`. A fresh reconstruction
  from the attested response was compared with the committed native table using exact semantic frame
  equality; Parquet byte equality is not the provenance criterion.

- Czechia native-table attestation: the orchestrator performed
  `GET https://opendata.chmi.cz/hydrology/historical/metadata/meta1.json` outside the executor
  sandbox at `2026-08-02T00:14:31Z`, received 831 rows with 23 header columns, and supplied the
  complete JSON response. Canonicalization serializes the complete parsed JSON object with
  `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, UTF-8 encodes the
  result, and takes SHA-256; the result was
  `a75f5ae23d8e9108cedb613d320ac3f3daf7be071442a3a91d23b323721cc9e9`. The committed native table
  content digest sorts rows by `objID`, represents the columns in schema order and each row as an
  aligned positional list, renders the UTC `retrieved_at` as an ISO 8601 string ending in `Z`, then
  uses the same JSON serialization, UTF-8 encoding, and SHA-256 procedure; its result is
  `b13d49902967e6f2fe182348999d24af711868f0c38032c425485aa41a66dd2b`. The active three-row
  fixture is an explicitly identified verbatim subset, not content-identical to the complete
  response. Its predecessor was source-incorrect in every row:
  `0-203-1-016000` carried `50.0014 / 14.4092` instead of `50.3427582 / 15.9249555`;
  `0-203-1-020000` carried `50.3500 / 14.4741` instead of `50.3517105 / 16.1299498` (longitude
  wrong by 1.66 degrees); and `0-204-1-001000` was not published by the source.

- Lithuania native-table attestation: the orchestrator performed
  `GET https://api.meteo.lt/v1/hydro-stations` outside the executor sandbox at
  `2026-08-01T18:31:08Z`, received 97 stations, and verified the live payload content-identical to
  `tests/test_data/lithuania_metadata_stations.json`. Canonicalization sorts stations by `code`,
  serializes JSON with sorted object keys and compact separators `(",", ":")` using Python's
  default `ensure_ascii=True`, UTF-8 encodes the result, and takes SHA-256; both inputs produced
  `02d16a6e872939b43ee7ae6d1c54e00b6b924f3d9a3f9a7553fc13680edc12d8`.

- Canada native-table attestation: the orchestrator performed nine paged requests outside the executor
  sandbox at `2026-08-02T01:09:10Z`, with paging completed at `2026-08-02T01:09:20Z`:
  `GET https://api.weather.gc.ca/collections/hydrometric-stations/items?f=json&limit=1000&offset=0`,
  `GET https://api.weather.gc.ca/collections/hydrometric-stations/items?f=json&limit=1000&offset=1000`,
  `GET https://api.weather.gc.ca/collections/hydrometric-stations/items?f=json&limit=1000&offset=2000`,
  `GET https://api.weather.gc.ca/collections/hydrometric-stations/items?f=json&limit=1000&offset=3000`,
  `GET https://api.weather.gc.ca/collections/hydrometric-stations/items?f=json&limit=1000&offset=4000`,
  `GET https://api.weather.gc.ca/collections/hydrometric-stations/items?f=json&limit=1000&offset=5000`,
  `GET https://api.weather.gc.ca/collections/hydrometric-stations/items?f=json&limit=1000&offset=6000`,
  `GET https://api.weather.gc.ca/collections/hydrometric-stations/items?f=json&limit=1000&offset=7000`, and
  `GET https://api.weather.gc.ca/collections/hydrometric-stations/items?f=json&limit=1000&offset=8000`.
  The assembled FeatureCollection contains 8,057 native features and has zero missing station ids,
  zero duplicate station ids, zero invalid coordinate rows, and zero disagreements among feature
  `id`, `IDENTIFIER`, and `STATION_NUMBER`, yielding 8,057 usable canonical stations. Canonicalization
  serializes the complete assembled FeatureCollection in attested page order using sorted object keys,
  compact separators `(",", ":")`, `ensure_ascii=False`, and UTF-8, producing SHA-256
  `3613c17b3e1ad76e8490d6dcb659be251f2270e5568fb6ff1e05fe780037083d`. Native Parquet rows are
  deterministically sorted by feature `id`. Its sorted JSON id list, serialized with compact separators,
  `ensure_ascii=False`, and UTF-8, has SHA-256
  `a55f028a344441cfb7e0d3dbad88366ec3834ff7a62135a6f5ab9faf5b0e1393`. The complete native table is
  canonicalized as an object containing the 18 column names in schema order and every row as a positional
  array in table order; UTC datetimes use ISO 8601 `Z`, nested lists preserve their order, and JSON uses
  sorted object keys, compact separators, `ensure_ascii=False`, and UTF-8. Its SHA-256 is
  `46780a69f07e9ed8a7eae343929d81b4c78f2330d6268ee1fdc7de701cd6fe48`. The refresh command recomputes
  this digest from the written Parquet in the same run. The canonical artifacts contain 8,057 stations,
  two products, and 16,114 station-products.

- Switzerland native-table attestation: the orchestrator performed
  `GET https://api.existenz.ch/apiv1/hydro/locations` outside the executor sandbox at
  `2026-08-02T00:14:31Z`, observed 246 stations under `payload`, and verified the supplied complete
  response byte-identical to the replacement `tests/test_data/switzerland_metadata_locations.json`.
  Canonicalization sorts all JSON object keys, serializes the complete response with compact
  separators `(',', ':')` and `ensure_ascii=False`, UTF-8 encodes it, and takes SHA-256, producing
  `7471e85de4f4a6d1e0968a9fe35a962c98729a4bb3b244e0991818f3038ce24a`. The sole integer
  `details.id`, at station `2071`, is intentionally normalized to string so the native Parquet
  column has one scalar dtype. Future Swiss canonical artifacts must be built network-free from
  the committed native table and origin declarations.

- Thailand native-table attestation: the orchestrator performed
  `GET https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_load` outside the executor
  sandbox at `2026-08-02T12:42:03Z`, supplied the complete response, and observed 825
  `waterlevel_data.data` rows with 825 unique integer `station.id` values. Response canonicalization
  uses `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, UTF-8 encoding,
  and SHA-256, producing
  `d42fdac929ddf87f348ed8cd9a6732768fb9775a47fff2bc54f4e0e74ee8bdee`. The native table preserves
  61 lexicographically ordered dotted source columns, widens only integer `station.id` to its exact
  decimal String and mixed numeric columns losslessly, sorts rows lexically by the stored String ID,
  and appends one UTC-microsecond `retrieved_at`. Its full content is canonicalized as an object with
  `columns` in schema order and `rows` as aligned positional lists, rendering `retrieved_at` as RFC
  3339 UTC with exactly six fractional digits and `Z`, then using the same compact sorted-key JSON,
  `ensure_ascii=False`, UTF-8, and SHA-256 procedure. The resulting digest is
  `3e2085ce51e3714d35feb053973c5074a0994278943b51c620c862be1f281cfd`, and the committed table was
  compared with a fresh materialization of the complete supplied response using exact semantic frame
  equality. Station-name language keys were `{en, th}` on 425 rows, `{th}` on 399 rows, and
  `{en, jp, th}` on the sole row with `station.id == 2583`; both agency name maps contained
  `{en, jp, th}` on all 825 rows. Every row met both legacy `tele_waterlevel` and valid-coordinate
  predicates. Comparison with the unchanged 754-row canonical catalogue found 87 currently present
  IDs and 16 no-longer-present IDs, establishing source membership churn and net growth rather than
  a missing filter. `tests/test_data/th_thaiwater_metadata.json` is a four-row verbatim subset and is
  not content-identical to the complete response. The orchestrator also performed
  `GET https://standard.thaiwater.net/docs/การจัดทำมาตรฐานน้ำ-ระยะ/ข้อมูลอ้างอิง-ข้อมูลอ้า/การระบุพิกัดตำแหน่ง/`
  outside the executor sandbox at `2026-08-02T13:51:44Z`; the coordinate-standard page capture is
  607,845 bytes with SHA-256
  `64e4c82a09ad547aeae5dac0493561f89ffd6618c15ac905a92109dd49aa2d04`; its byte-identical committed
  capture is `tests/test_data/th_thaiwater_coordinate_standard.html`. Future Thailand canonical
  artifacts must be built network-free from committed `native.parquet` and origin declarations,
  never from `--live` or a fixture.


- Bosnia native-table attestation: the orchestrator performed
  `GET https://vodostaji.voda.ba/data/internet/layers/20/index.json` outside the executor sandbox at
  `2026-08-02T12:42:03Z`, received 60 entries exactly matching the 60 committed stations, and supplied
  the complete JSON response. Canonicalization uses
  `json.dumps(obj, sort_keys=True, separators=(',',':'), ensure_ascii=False)` encoded as UTF-8 and
  produces SHA-256 `907817ca04d3d5626151d8f57478b90dc22f5503b29b8097106768aca942545f`.
  The response combines station metadata with a volatile timeseries snapshot. The native table excludes
  exactly `L1_label`, `L1_req_timestamp`, `L1_station_longname`, `L1_stationparameter_name`,
  `L1_stationparameter_no`, `L1_timestamp`, `L1_ts_id`, `L1_ts_name`, `L1_ts_precision`,
  `L1_ts_unitsymbol`, `L1_ts_value`, and `L1_web_flow_class`: `L1_ts_value`, `L1_timestamp`, and
  `L1_req_timestamp` change on every fetch, and the `L1_*` group as a whole describes the volatile
  timeseries snapshot rather than station metadata. The reproducible stable proof deletes those twelve
  keys from each object, sorts by `metadata_station_no`, serializes with the same settings, and produces
  SHA-256 `14ab47126fe40f16f23ddc66620fc8ae30910cd812c69806f867a851e659b23d`. All 18
  `metadata_*` fields remain source-named strings, including blank elevation and uninterpreted
  projected and local coordinate fields.

- Bosnia publisher CRS-capture attestation: the orchestrator performed
  `GET https://vodostaji.voda.ba/data/internet/stations/stations.json` outside the executor sandbox at
  `2026-08-02T16:43:18Z`, received 230 station objects with one uniform 24-key keyset, and supplied the
  complete JSON response. Canonicalization uses one
  `json.dumps(obj, sort_keys=True, separators=(',',':'), ensure_ascii=False)` call over the complete
  parsed 230-element document committed as
  `tests/test_data/ba_fhmzbih_crs_evidence_stations.json`, encoded as UTF-8, and produces SHA-256
  `c78bd3b3aee2859eaef3c4373029fe7619a7d8e40b53fa0eab7f989ade3524bc`. The document carries
  `station_latitude`, `station_longitude`, `station_carteasting`, `station_cartnorthing`,
  `station_local_x`, and `station_local_y`, and contains zero horizontal-CRS tokens. Its datum-named
  fields `station_gauge_datum`, `GAUGE_DATUM`, and `GWREF_DATUM` are vertical metre elevations, not
  horizontal coordinate reference systems.

- Switzerland publisher CRS-capture attestation: the declared evidence URL is
  `https://api.existenz.ch/#hydro`. The orchestrator requested `GET https://api.existenz.ch/`
  outside the executor sandbox at `2026-08-03T12:31:42Z`; the final URL was identical, with no
  redirect, and the response was HTTP 200. The response has 15,737 raw bytes and raw SHA-256
  `488b25d24651aafb520d7cf69c1d36ac9f4384fa096b9cab77b44c6b669f82df`; its byte-identical
  committed capture is `tests/test_data/ch_foen_api_docs.html`. The `#hydro` suffix is a page-fragment
  selector and was never sent to the server.

- Czechia publisher CRS-capture attestation: the declared, requested, and final URL was
  `https://opendata.chmi.cz/hydrology/read_me/Popis_kodu_historical.pdf`, with no redirect. The
  orchestrator performed the request outside the executor sandbox at `2026-08-03T12:31:42Z` and
  received HTTP 200. The response has 423,157 raw bytes and raw SHA-256
  `41958b49634d2dc01b51ff72b65d054402628cd154bbcd6b8020def12d88d45a`; its byte-identical
  committed capture is `tests/test_data/cz_chmi_popis_kodu_historical.pdf`.

- Japan publisher CRS-capture attestation: the milestone-14 accepted response used the identical
  declared, requested, and final URL
  `http://www1.river.go.jp/cgi-bin/SiteInfoDetail.exe?ID=301011281104010`. It returned historical
  HTTP 200 at `2026-08-02T19:35:42Z`; the response has 3,208 raw bytes and raw SHA-256
  `81e7269886397975867bf556c8d5b6659bd5f8d7318c4cf062cd0f47419418f9`. Its byte-identical
  committed capture is `tests/test_data/jp_mlit_site_info_detail_301011281104010.html`, and its
  acceptance is bound to the milestone-14 requirement that the body contain the EUC-JP bytes for
  `世界測地系`. A separate attempt at `2026-08-03T12:31:42Z` returned HTTP 403 with a 77-byte
  access-restriction body, so this evidence is non-refetchable; no later success is claimed.

- Japan native-table capture attestation: the
  orchestrator performed the endpoint-expanded 1,024-request capture outside the executor sandbox.
  Its request seed was exactly the sorted unique station ids in
  `jp_mlit/catalogue/stations.parquet` at `origin/main` / `22ff07c`, containing 1,024 ids; the compact
  sorted JSON id list (sorted keys, separators `(",", ":")`, `ensure_ascii=False`, UTF-8) has
  SHA-256 `e7930a7c374c5b3efe1f066eb4ccf511c0c7690c30afc2f7b2583d26d2b6981e`. This is a
  reproducible 1,024-row legacy subset, not MLIT's complete 2,456-station enumeration. Each request
  used `GET http://www1.river.go.jp/cgi-bin/SiteInfoDetail.exe?ID=<station_id>`. Responses are decoded
  with strict EUC-JP, and acceptance requires HTTP 200 plus the EUC-JP bytes for `世界測地系`.
  The accepted-response retrieval window was `2026-08-02T19:35:42Z` through
  `2026-08-02T19:50:44Z`; the manifest campaign itself ended at `2026-08-02T19:50:45Z`.
  Each manifest entry's whole-second UTC instant is authoritative, yielding 902 distinct accepted
  instants; the manifest format carries no sub-second component.
  The truthful arithmetic is 1,024 requested, 1,023 published, and one source-confirmed absence.
  The corresponding unpunctuated count bindings are `requested=1024` and `published=1023`.
  Station `307051287711040` returned HTTP 200 with a 489-byte body lacking the marker and SHA-256
  `2e83eed5a64cf91d9351f2abc28c151dec420a24265dd9db194fd7132bd31faf`; the byte-identical body is
  tracked separately as `tests/test_data/jp_mlit_site_info_detail_rejected_307051287711040.html`.

  The complete manifest object and all reverified response bindings have canonical SHA-256
  `d935586b317cdf234760959c9e97788803bfda9cea2ff6551beaefaeb6e20d21`. Native rows retain the
  deterministic fifteen-column schema order, sort by exact `観測所記号`, carry each accepted
  request's whole-second UTC instant, and preserve source null, empty-string, and non-breaking-space
  states distinctly. The published sorted-id digest is
  `9016935eea6c6c7b3c56ee280a1467f74b4d7b60f2fc10f17e1ed3baa0fb42bd`; the sorted station/whole-second
  timestamp-pair digest is `0f742e2f37bb9c6bfffb7e0d109f8025e5350e6416175c983e79bf8fb8b6fdd0`; and the complete native-frame
  digest is `f3c42f03fc0280c14910dc4203fc8031b9d5cddcc0cc8a6431c3c9268602aec0`. The committed native
  Parquet is a semantic materialization of all 1,023 accepted supplied responses, not of a fixture,
  and was compared with exact frame equality against a fresh complete supplied-response
  materialization.

  Two accepted response bodies are tracked as independent parser witnesses. Station
  `301031281101220` is `tests/test_data/jp_mlit_site_info_detail_accepted_301031281101220.html`,
  3,175 bytes with SHA-256
  `bb9caa28f43a8c94f9c65c4929f6677b85266a4c0140ba2082254361f4954da3`; its `日本測地系`
  cell contains a bare `<BR>`. Station `301011281104310` is
  `tests/test_data/jp_mlit_site_info_detail_accepted_301011281104310.html`, 3,199 bytes with
  SHA-256 `2727f485592f5cbf0fa31538a150c5ca2a6a571d12f224658629c821d27a9dd7`; its `流域面積`
  cell contains an NBSP. Both are byte-identical copies from the accepted supplied capture, and tests
  refresh them through the production parser and compare the result exactly with the committed native
  rows.

  Exactly three previously packaged coordinates diverged from the committed source DMS coordinates:
  `302011282228100` was packaged as `37.424166666666665, 140.52472222222224` versus source
  `37.415277777777774, 140.48333333333332` (about 3.79 km); `302011282218050` was packaged as
  `37.81055555555555, 140.49499999999998` versus source
  `37.81111111111111, 140.4958333333333` (about 96 m); and `308011288805010` was packaged as
  `33.78361111111111, 132.87416666666667` versus source
  `33.78333333333333, 132.8738888888889` (about 40 m).

  `tests/test_data/jp_mlit_metadata.json` is only the exact three-record subset for ids
  `301011281104010`, `303051283310060`, and `309191289913130`, with SHA-256
  `5002cbc510e9dc4946e740286011b0c4d7bb76fe6d115c5fed715816c6144926`; nothing was materialized
  from that fixture. Both `世界測地系` and `日本測地系` remain source vocabulary, the former-system
  pair is never consumed, and no EPSG or datum inference is made. This Japan attestation states nine
  SHA-256 digests; tests hard-code eight of them, while the complete-manifest digest remains an
  attested provenance binding rather than a test literal. Its packaged `crs` is `unknown`, declared
  by the present-tense `crs: NotPublished` Origin with the station-detail page as Evidence.

After writing provider code and tests, run that provider's network-free build from its committed
native table and origins, and commit the resulting canonical artifacts alongside the code.

- France native-table attestation: the orchestrator performed seven paged GETs outside the executor
  sandbox at `2026-08-02T17:32:58Z`, each returning `HTTP 206 Partial Content`:
  `https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?size=1000&page=1&format=json`,
  `https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?size=1000&page=2&format=json`,
  `https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?size=1000&page=3&format=json`,
  `https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?size=1000&page=4&format=json`,
  `https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?size=1000&page=5&format=json`,
  `https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?size=1000&page=6&format=json`, and
  `https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?size=1000&page=7&format=json`.
  Pages returned 1000 × 6 + 454 = 6,454 rows, every page's `count` reported 6454, all 6,454
  non-empty string `code_station` values were unique, and paging terminated on the absence of a
  `next` link. Canonicalization sorts rows by `code_station`, then applies
  `json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, UTF-8 encoded,
  producing SHA-256 `fb3ea87f634554d4d679e5a422c1e5c5df80442f8f3c7a549e4d8bd0fa964c46`.
  Verified twice, by an independent live re-fetch. A fresh seven-page paged fetch was performed and
  its canonical digest compared against the staged capture on disk; the two are byte-identical.

  The orchestrator also performed
  `GET https://hubeau.eaufrance.fr/api/v1/temperature/station?size=2000&format=json` outside the
  executor sandbox at `2026-08-02T17:33:34Z`. The `HTTP 200` response was 1,381,753 bytes and
  contained 869 stations, its `count` reported 869, all IDs were unique, and the single request was
  complete without paging. Canonicalization sorts `data` rows by `code_station`, then uses the same
  `json.dumps` / UTF-8 procedure, producing SHA-256
  `125e4dee1b6ccf3fd17c800f170fc9cd8dc25244091773bb36ff9b61bc89ac2a`.
  Verified twice, by an independent live re-fetch. The capture was re-requested live and its
  canonical digest compared against the staged copy on disk; the two matched.

  The documentation evidence consists of two further orchestrator requests outside the executor.
  `GET https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?code_station=1011000101&format=geojson`
  at `2026-08-02T17:33:42Z` returned `HTTP 200` and 1,924 bytes. Canonicalization uses
  `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, UTF-8, producing
  SHA-256 `51f0259e182d2002c9a2352e2616d7ef20d5ffbdb830da725add3ecf8f52a7b7`.
  Verified twice, by an independent live re-fetch. The capture was re-requested live and its
  canonical digest compared against the staged copy on disk; the two matched.
  `GET https://hubeau.eaufrance.fr/api/v2/hydrometrie/api-docs` at `2026-08-02T17:33:43Z` returned
  `HTTP 200` and 117,460 bytes. Canonicalization: as above. Its SHA-256 is
  `4e668183a03a674e9d12a7a4152781f05167eee43002da188738a173e09c5b02`.
  Verified twice, by an independent live re-fetch. The capture was re-requested live and its
  canonical digest compared against the staged copy on disk; the two matched. Every canonical digest
  was independently reproduced by a fresh live re-fetch outside the executor, and the staged bytes
  were reproduced exactly.

  The committed full JSON bytes in `tests/test_data/fr_hubeau_referentiel_stations_full.json`,
  `tests/test_data/fr_hubeau_temperature_stations_full.json`,
  `tests/test_data/fr_hubeau_geojson_crs_evidence.json`, and
  `tests/test_data/fr_hubeau_openapi_v2.json` are the reviewable captures. The two station captures
  supply native rows; GeoJSON and OpenAPI are documentation evidence only. The canonical catalogue
  contains the complete `7,323 = 6,454 hydrometry + 869 disjoint temperature` station union. The
  `7,289 = 6,420 + 869` result was the superseded pre-m10-s3 shipping state; the hydrometry response
  grew by 34 genuine stations and the retracted 835-row-loss interpretation is false.

  Native materialization sorts by exact `code_station`, preserves both endpoint vocabularies without
  renaming, coalescing, or correction, appends exact `source_endpoint` and endpoint-specific
  UTC-microsecond `retrieved_at`, uses the ordered 73-column schema, and requires exact semantic frame
  comparison against both station captures. The full-frame digest serializes an object containing the
  ordered `columns` and every positional `rows` array; nested list and struct order and values are
  retained, UTC datetimes are RFC 3339 with exactly six fractional digits and `Z`, and JSON uses sorted
  object keys, compact separators, `ensure_ascii=False`, and `allow_nan=False`. Its SHA-256 is
  `f5c3d84a4e6674a1aa5e6b951576edf6bcbdf77867ab0e5c3ffe2f09adbf7322`. All 54 rows where
  `code_projection == 31`, including `H000000201`, remain source-faithful in `native.parquet` despite
  the documented upstream transposition; the pure, network-free canonical build transposes exactly
  those 54 rows and otherwise preserves source coordinates. France's four canonical artifacts are a
  pure function of the committed native material and its two endpoint-specific origin declarations.

### 4.2 Providers not yet migrated

For a provider without both a committed native table and origin declarations (currently the other
two: `br_ana` and `no_nve`), the four canonical packaged catalogue artifacts must be
generated from the live provider API before the provider is committed.


- `tests/test_data/<provider>_metadata_*.json` is a test fixture used for offline tests. It must
  never be used to generate the four canonical packaged catalogue artifacts.
- After writing all provider code and tests, run
  `generate_catalogue.py --live --out src/rivretrieve/_internal/providers/<provider>/catalogue/` to
  produce the four canonical packaged artifacts.

Commit the resulting artifacts alongside the code in both regimes. Regime 4.1 expands as each
provider milestone migrates; this distinction disappears once all thirteen providers have migrated.

Some generators include a provider-specific minimum-station guard that raises `FatalContractError`
when `--live` returns an implausibly small count, catching silent fetch failures or accidental
fixture-backed invocations. The threshold is calibrated per provider (e.g. 10 000 for USGS which has
26 000+ gauges; Lithuania has only 97 stations so no such guard is needed there). Do not copy a
numeric threshold from one provider to another.
