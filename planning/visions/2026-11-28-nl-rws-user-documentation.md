# Vision: Netherlands (`nl_rws`) User Documentation (Step 7)

- **Effort:** [#1054](https://github.com/RivRetrieve/RivRetrieve/issues/1054) (this vision completes `#1054` when implemented and merged into `port/nl-rws`)
- **Coordination:** [#355](https://github.com/RivRetrieve/RivRetrieve/issues/355) (tracker [#870](https://github.com/RivRetrieve/RivRetrieve/issues/870))
- **Target branch:** `port/nl-rws` (never merge `port/nl-rws` into `main` until Step 8 [#1055](https://github.com/RivRetrieve/RivRetrieve/issues/1055) is approved)
- **Depends on:**
  - Step 1 ([#1048](https://github.com/RivRetrieve/RivRetrieve/issues/1048)): `planning/visions/2026-11-25-nl-rws-source-scope-and-access.md`
  - Step 2 ([#1049](https://github.com/RivRetrieve/RivRetrieve/issues/1049)): `planning/visions/2026-11-25-nl-rws-station-catalogue-and-metadata.md`
  - Step 3 ([#1050](https://github.com/RivRetrieve/RivRetrieve/issues/1050)): `planning/visions/2026-11-26-nl-rws-series-identity-and-physical-meaning.md`
  - Step 4 ([#1051](https://github.com/RivRetrieve/RivRetrieve/issues/1051)): `planning/visions/2026-11-26-nl-rws-retrieval-behavior.md`
  - Step 5 ([#1052](https://github.com/RivRetrieve/RivRetrieve/issues/1052)): `planning/visions/2026-11-27-nl-rws-provider-integration.md`
  - Step 6 ([#1053](https://github.com/RivRetrieve/RivRetrieve/issues/1053)): `planning/visions/2026-11-27-nl-rws-verification.md`

## Goal

Publish accurate, hydrology-readable user documentation for the Netherlands Rijkswaterstaat (`nl_rws`) provider, register it across the MkDocs site and station metadata index, regenerate the documentation artifacts (`docs/_generated/reference-tables.md` and `docs/assets/coverage-map.png`), and verify the practical example live against Rijkswaterstaat DDAPI 2.0.

## Scope and Settled Decisions

### 1. New provider page: `docs/providers/nl_rws.md`

Write `docs/providers/nl_rws.md` following `docs/AGENTS.md` and `docs/maintenance/provider-ports.md` (Step 7), using `docs/providers/fi_syke.md` as a structural reference:

- **Audience and style:**
  - Educated hydrology reader with basic Python; avoid internal software architecture jargon.
  - **No em dashes (`—`) anywhere in prose.** Use commas, parentheses, sentence breaks, or connecting words instead.
  - State observed coverage, limits, and caveats honestly; never imply continuous coverage across the full period of record.
- **Overview and scope:**
  - Data publisher: Rijkswaterstaat Waterwebservices DDAPI 2.0 (`https://ddapi20-waterwebservices.rijkswaterstaat.nl`), open surface-water (`OW`) measured observations (`ProcesType = "meting"`, `Groepering = ""`) only.
  - Explicitly excluded: forecasts (`verwachting`), astronomical tides (`astronomisch`), and tidal extremes (`GETETBRKD2` / `GETETM2`).
  - Packaged catalogue: 1,706 stations in `EPSG:4258` (`Naam` as station name), zero credentials or API keys required.
- **"What you can retrieve" table:**
  - Must use the exact 6-column header required by `docs/maintenance/provider-ports.md`:
    `| Quantity filter | Source field / \`variant\` | Frequency | Statistic | Source unit | Returned unit |`
  - List all 10 admitted products accurately (using the public `Quantity filter` values `discharge`, `stage`, and `temperature`):
    1. `discharge` — `discharge_m3s_nvt` (`Q`, `m3/s`, `NVT`, `NVT`): frequency unknown, statistic unknown, `m3/s` -> `m3/s`.
    2. `discharge` — `discharge_m3s_gem24h` (`Q`, `m3/s`, `NVT`, `GEM24H`): daily (`P1D`), mean, `m3/s` -> `m3/s`.
    3. `discharge` — `discharge_m3d_nvt` (`Q`, `m3/d`, `NVT`, `NVT`): frequency unknown, statistic unknown, `m3/d` -> `m3/s`.
    4. `stage` — `stage_nap_nvt` (`WATHTE`, `cm`, `NAP`, `NVT`): frequency unknown, statistic unknown, `cm` -> `m` (above sea level, NAP).
    5. `stage` — `stage_nap_gem24h` (`WATHTE`, `cm`, `NAP`, `GEM24H`): daily (`P1D`), mean, `cm` -> `m` (above sea level, NAP).
    6. `stage` — `stage_plaatslr_nvt` (`WATHTE`, `cm`, `PLAATSLR`, `NVT`): frequency unknown, statistic unknown, `cm` -> `m` (local reference `PLAATSLR`, vertical reference category unestablished).
    7. `stage` — `stage_msl_nvt` (`WATHTE`, `cm`, `MSL`, `NVT`): frequency unknown, statistic unknown, `cm` -> `m` (above sea level, MSL).
    8. `stage` — `stage_taw_nvt` (`WATHTE`, `cm`, `TAW`, `NVT`): frequency unknown, statistic unknown, `cm` -> `m` (above sea level, TAW).
    9. `temperature` — `water_temperature_nvt` (`T`, `oC`, `NVT`, `NVT`): frequency unknown, statistic unknown, `oC` -> `degC`.
    10. `temperature` — `water_temperature_gem24h` (`T`, `oC`, `NVT`, `GEM24H`): daily (`P1D`), mean, `oC` -> `degC`.
- **Series behavior, time zones, and caveats:**
  - **Parallel measurement methods (`variant`):** Rijkswaterstaat can publish multiple `WaardeBepalingsMethode` codes for the same station and product (for example `other:F216` and `other:F230` at Lobith). RivRetrieve keeps each method as its own series rather than merging them, so users should inspect `variant` when selecting or comparing series.
  - **`NVT` vs `GEM24H` and historical depth:** `GEM24H` provides 24-hour daily means (and extends into historical decades at major gauges), whereas `NVT` carries the unaggregated series (cadence and statistic unestablished in the catalogue; high-frequency modern series at many gauges, and daily historical records at some gauges such as Lobith back to 1901). Explicitly note the unestablished semantics: `NVT` cadence/statistic, `GEM24H` day anchor, and `PLAATSLR` vertical-reference category.
  - **Fixed `+01:00` timestamps:** DDAPI 2.0 reports timestamps with a fixed `+01:00` offset year-round, including across daylight-saving transitions, with no DST jump.
  - **Quality annotations and missing-value sentinel (explicit requirement):**
    - Document the `nl_rws.observation` annotation schema and its two fields: `statuswaarde` (publisher validation status, e.g. `Ongecontroleerd`, `Gecontroleerd`, `Definitief`) and `kwaliteitswaardecode` (Aquo quality code, e.g. `"00"` normal, `"25"` qualified, `"99"` missing).
    - Explicitly explain that Rijkswaterstaat encodes missing observations using `Kwaliteitswaardecode = "99"` and/or a numeric sentinel (`9.99999e+37`, or `.999999E+38` in alphanumeric payloads). RivRetrieve converts these sentinel observations to `null` in `value` (never dropping the row and never leaking `9.99999e+37` into numeric values) while preserving the `nl_rws.observation` annotation on the timestamp.
- **Live-verified practical example:**
  - Use **Lobith (`lobith.bovenrijn.tolkamer`)** for the runnable Python example (discovery + retrieval using the public `rivretrieve` API).
  - Run the exact snippet live against Rijkswaterstaat DDAPI 2.0 during implementation, record the actual output (trimmed cleanly for readability if needed) and the date checked, and ensure the prose does not claim continuous coverage.
- **Terms of use and attribution:**
  - State the open-data license (Public Domain Mark 1.0 / CC0 1.0) and recommended attribution: `"Bron: Rijkswaterstaat – Waterwebservices"`.

### 2. Navigation, index, metadata, and generated assets

- `mkdocs.yml`: add `Netherlands (Rijkswaterstaat): providers/nl_rws.md` alphabetically under the Providers nav section (between Lithuania and Norway).
- `docs/README.md`: add `- [Netherlands: Rijkswaterstaat](providers/nl_rws.md)` alphabetically in the provider list.
- `docs/station-metadata.md`: add the `nl_rws` row alphabetically:
  `| [\`nl_rws\`](providers/nl_rws.md) | \`Naam\` | — | — | — |`
  (preserving the table's existing `—` placeholder convention for empty cells).
- `docs/_generated/reference-tables.md`: regenerate via `uv run python scripts/generate_reference.py` (required because `nl_rws` is registered in `BUILTIN_PROVIDER_IDS` and `docs/hooks.py` checks `scripts/generate_reference.py --check` during build).
- `docs/assets/coverage-map.png`: regenerate via `uv run python docs/scripts/coverage_map.py --out docs/assets/coverage-map.png` so the published coverage map reflects `nl_rws`.

## Out of Scope

- Runtime code or catalogue changes in `src/rivretrieve/` (already verified in Steps 2–6).
- Merging `port/nl-rws` into `main` (reserved for Step 8 [#1055](https://github.com/RivRetrieve/RivRetrieve/issues/1055)).
- Editing `docs/maintenance/provider-ports.md` (handled separately in PR [#1097](https://github.com/RivRetrieve/RivRetrieve/pull/1097)).

## Externally Observable Evidence of Success

1. `docs/providers/nl_rws.md`, `mkdocs.yml`, `docs/README.md`, `docs/station-metadata.md`, `docs/_generated/reference-tables.md`, and regenerated `docs/assets/coverage-map.png` are committed on a feature branch and merged into `port/nl-rws` after independent review.
2. The Lobith (`lobith.bovenrijn.tolkamer`) example in `docs/providers/nl_rws.md` has been executed live during Step 7 implementation and its documented output matches the live response (with check date noted).
3. `docs/providers/nl_rws.md` contains zero em dashes (`—`) in prose, includes the exact required 6-column `"What you can retrieve"` header covering all 10 products, and clearly documents `nl_rws.observation` (`statuswaarde`, `kwaliteitswaardecode`) and `Kwaliteitswaardecode = "99"` / `9.99999e+37` -> `null` handling.
4. Automated checks pass on the PR branch:
   - `pytest tests/test_reference_contracts.py tests/test_coverage_map.py tests/test_documentation.py` (including `mkdocs build --strict`).
   - `ruff check` on any touched Python files (none expected).
5. [#1054](https://github.com/RivRetrieve/RivRetrieve/issues/1054) is closed only after the Step 7 implementation PR is merged into `port/nl-rws`.
