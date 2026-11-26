# Netherlands Rijkswaterstaat (`nl_rws`) — series identity and physical meaning

Complete [Effort #1050](https://github.com/RivRetrieve/RivRetrieve/issues/1050)
by establishing the runtime `SourceIdentity`, `PhysicalFacts`, unit admission,
missing-value handling, and declared `AnnotationSchema` definitions for the
Netherlands hydrometric provider (`nl_rws`) on branch `port/nl-rws`. Verified
completion of this vision completes `#1050`; publishing this vision alone does
not.

This Effort builds on completed Step 1
([#1048](https://github.com/RivRetrieve/RivRetrieve/issues/1048),
[`2026-11-25-nl-rws-source-scope-and-access.md`](2026-11-25-nl-rws-source-scope-and-access.md)),
completed Step 2
([#1049](https://github.com/RivRetrieve/RivRetrieve/issues/1049),
[`2026-11-25-nl-rws-station-catalogue-and-metadata.md`](2026-11-25-nl-rws-station-catalogue-and-metadata.md)),
coordination issue [#355](https://github.com/RivRetrieve/RivRetrieve/issues/355),
and the continuing private research record `research/nl-rws-source-access.md`
plus retained collection `nl_rws-access-2026-11-25-v1` (release `458265071`)
in `RivRetrieve/verification-evidence`. Follow
[provider-port step 3](../../docs/maintenance/provider-ports.md). Keep all
work on `port/nl-rws` — never merge into `main` before final review
[#1055](https://github.com/RivRetrieve/RivRetrieve/issues/1055) is approved.

## Outcome

Implement runtime-safe series-identity and source-annotation modules under
`src/rivretrieve/_internal/providers/nl_rws/`:

- `src/rivretrieve/_internal/providers/nl_rws/series.py` — runtime series
  identity (`SourceIdentity`, `SourceSeries`, `PhysicalFacts`), missing-value
  classification, and product/unit admission helpers shared cleanly with
  `catalogue_series.py` (never importing `generate_catalogue.py`, respecting
  `tests/test_provider_architecture_contracts.py`).
- `src/rivretrieve/_internal/providers/nl_rws/annotations.py` — declared
  `AnnotationSchema` definition for `nl_rws` observation qualifiers.
- Focused source-independent tests in `tests/test_nl_rws_series.py` (and/or
  `tests/test_nl_rws_annotations.py`).

Step 3 does not implement HTTP fetching/chunking (`fetch.py`), full driver
parsing/integration (`parse.py` / `declaration.py`), or `BUILTIN_PROVIDER_IDS`
registration; those belong to Steps 4–5 (`#1051`–`#1052`).

## Settled decisions

### 1. Parallel series identity (`SourceSeries.variant`)

- For any `(station_id, product_id)` among the 10 admitted `OW` `meting`
  products (`Groepering = ""`, `WaardeBewerkingsMethode` in `{"NVT", "GEM24H"}`),
  identify each distinct measured stream in `WaarnemingenLijst` by
  **`variant = WaardeBepalingsMethode.Code`** (for example `"other:F216"`,
  `"other:F230"`, `"other:F006"`, `"other:F007"`, `"NVT"`).
- Never collapse parallel `WaardeBepalingsMethode` series (such as Lobith
  unchecked `other:F216` and checked `other:F230` 10-minute discharge series)
  into one series, and never fabricate daily means from `NVT` readings.
- Reject or ignore non-`meting` (`verwachting`, `astronomisch`), non-`OW`,
  non-empty `Groepering`, and unadmitted `WaardeBewerkingsMethode` series
  rather than misclassifying them into an admitted product.

### 2. Physical facts, units, vertical references, and time

- **Quantities and native units (all 10 products pass `admission()`):**
  - `Q` `m3/s` → canonical `m3/s`
  - `Q` `m3/d` → canonical `m3/s` (`÷ 86,400`)
  - `WATHTE` `cm` → canonical `m` (`÷ 100`)
  - `T` `oC` (normalized `degC`) → canonical `degC`
- **Vertical references on `WATHTE` (kept distinct, never collapsed):**
  - `NAP`, `MSL`, and `TAW`: `vertical_reference = known("above_sea_level", ...)`
    and `vertical_datum = known(<code_here>, ...)`.
  - `PLAATSLR` (*t.o.v. plaatselijk referentievlak*): `vertical_datum = known("PLAATSLR", ...)`
    and `vertical_reference = not_established` (local reference plane; do not
    classify as `above_sea_level` or `gauge_zero` without official proof).
- **Frequency, statistic, and temporal support:**
  - `GEM24H` (*Etmaalgemiddelde*): `frequency = known("P1D", ...)`,
    `statistic = known("mean", ...)`; `temporal_support`, `day_definition`, and
    `timestamp_anchor` remain `not_established` (do not infer day-end or
    day-start anchor from `00:00:00+01:00`).
  - `NVT`: `frequency`, `statistic`, `temporal_support`, `day_definition`, and
    `timestamp_anchor` remain `not_established` at the product level because
    `NVT` spans both 10-minute and daily `m3/d` series and method-specific
    averaging windows.
- **Time zone and clipping axis:**
  - Confirmed live across the 2020-03-29 spring DST transition
    (`12_obs_dst_lobith_2020_03_29_meting.json`): DDAPI 2.0 stamps observations
    with explicit fixed ISO-8601 `+01:00` offsets (no jump to `+02:00`).
  - Derive/validate `time_zone` from the explicit offset on `Tijdstip` (e.g.
    `known("+01:00", ...)` when all offsets match `+01:00`) and use
    `ClippingAxis.SOURCE_TIMESTAMP`.

### 3. Declared source annotations (`nl_rws.observation`)

- Declare **one observation-scoped schema** (`schema_id = "nl_rws.observation"`,
  `provider_id = "nl_rws"`, `scope = AnnotationScope.OBSERVATION`) with exactly
  two `String` fields:
  1. `statuswaarde` — Rijkswaterstaat observation validation status
     (`"Ongecontroleerd"`, `"Gecontroleerd"`, `"Definitief"`, etc.).
  2. `kwaliteitswaardecode` — Aquo/RWS observation quality code (`"00"`,
     `"25"`, `"99"`, etc.).
- Both fields must carry non-placeholder descriptions and verified official
  `http`/`https` `reference_url` links (Rijkswaterstaat / Aquo documentation)
  passing `AnnotationSchema` validation.
- **Explicitly excluded from annotations:** Do not declare
  `opdrachtgevende_instantie`, `bemonsteringshoogte`, `referentievlak`, or
  series-level description annotations (`nl_rws.series`).
- Never interpret `statuswaarde` or `kwaliteitswaardecode` as a quality
  ranking, never create synthetic `SourceSeries.variant` splits solely for
  annotation changes, and never emit per-row informational quality-code issues.

### 4. Missing-value sentinel handling (`9.99999e+37` / `Kwaliteitswaardecode = "99"`)

- Empirical verification across all 211,262 rows of the 2-year Lobith discharge
  response (`17_obs_window_cap_test_2yr.json`) confirmed an exact 1-to-1
  correspondence: all 435 rows with `Kwaliteitswaardecode = "99"` carry
  `Waarde_Numeriek = 9.99999e+37` (`Waarde_Alfanumeriek = ".999999E+38"`), while
  all 210,827 `"00"` rows carry normal physical readings.
- Classify any row with `Kwaliteitswaardecode == "99"` or
  `Waarde_Numeriek == 9.99999e+37` (or `Waarde_Numeriek is None`) as a
  **published missing slot**:
  - Canonical observation value becomes `null` (never letting `9.99999e+37`
    leak as a numeric measurement).
  - Observation annotation table retains the slot with `measured = False`,
    preserving `statuswaarde` and `kwaliteitswaardecode` (e.g. `"99"`).
- Never drop missing-value rows silently, and never treat valid `0.0` or
  negative readings (such as low/negative coastal or polder `WATHTE` in `cm`
  or `0.0 °C` water temperature) as missing.
- **Downstream documentation requirement (`#1054`):** Step 7 user
  documentation (`docs/providers/nl_rws.md`) must explicitly document this
  missing-value / `Kwaliteitswaardecode = "99"` (`9.99999e+37`) behavior and
  the `statuswaarde` / `kwaliteitswaardecode` observation annotations.

## Evidence of completion

1. `src/rivretrieve/_internal/providers/nl_rws/series.py` and
   `src/rivretrieve/_internal/providers/nl_rws/annotations.py` implemented on
   `port/nl-rws` (with `catalogue_series.py` sharing `PRODUCT_DEFINITIONS`
   cleanly and no runtime import of `generate_catalogue.py`).
2. Focused source-independent tests verifying:
   - All 10 admitted products pass `admission()` with exact canonical units
     (`m3/s`, `m`, `degC`) and distinct vertical datums (`NAP`, `PLAATSLR`,
     `MSL`, `TAW`).
   - Parallel `WaardeBepalingsMethode` series (`other:F216` vs `other:F230`,
     `other:F006` `GEM24H`) resolve to distinct `SourceSeries` identities with
     `variant = WaardeBepalingsMethode.Code`.
   - `Kwaliteitswaardecode == "99"` and `9.99999e+37` classify as published
     missing slots (`null` value + `measured = False` annotation slot), while
     `0.0` and negative stage/temperature values remain measured.
   - `nl_rws.observation` `AnnotationSchema` validates cleanly with exactly
     `statuswaarde` and `kwaliteitswaardecode` and valid official `reference_url`s.
   - Fixed `+01:00` offset parsing and `ClippingAxis.SOURCE_TIMESTAMP`.
3. `ruff format --check`, `ruff check`, `ty check src`, and affected tests
   (including `tests/test_nl_rws_*.py` and `tests/test_provider_architecture_contracts.py`)
   pass on `port/nl-rws`.
4. Independent review completed, PR merged into `port/nl-rws` (never `main`),
   and completion summary posted when closing `#1050`.
