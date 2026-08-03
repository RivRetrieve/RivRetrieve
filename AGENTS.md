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

### 4.1 Providers with a committed native table and origins

For a provider with both a committed native table and origin declarations (currently `ba_fhmzbih`,
`ca_eccc`, `ch_foen`, `cz_chmi`, `lt_lhmt`, `usgs_nwis`, and `za_dws`), the four canonical packaged
catalogue artifacts (`catalogue/provider.json`, `catalogue/products.parquet`,
`catalogue/stations.parquet`, and
`catalogue/station_products.parquet`) are a pure, network-free function of that committed table and
the provider's origins. Generating the canonical artifacts from a live API is forbidden because it
would reintroduce the nondeterminism the pure build removes. In particular, future USGS canonical
generation must use its committed `native.parquet`, never `--live` or supplied RDB payloads.

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
  parsed 230-element document, encoded as UTF-8, and produces SHA-256
  `c78bd3b3aee2859eaef3c4373029fe7619a7d8e40b53fa0eab7f989ade3524bc`. The document carries
  `station_latitude`, `station_longitude`, `station_carteasting`, `station_cartnorthing`,
  `station_local_x`, and `station_local_y`, and contains zero horizontal-CRS tokens. Its datum-named
  fields `station_gauge_datum`, `GAUGE_DATUM`, and `GWREF_DATUM` are vertical metre elevations, not
  horizontal coordinate reference systems.

After writing provider code and tests, run that provider's network-free build from its committed
native table and origins, and commit the resulting canonical artifacts alongside the code.

### 4.2 Providers not yet migrated

For a provider without both a committed native table and origin declarations (currently the other
six: `br_ana`, `fr_hubeau`, `jp_mlit`, `no_nve`, `pl_imgw`, and `th_thaiwater`), the four canonical
packaged catalogue artifacts must be generated from the live provider API before the provider is
committed.

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
