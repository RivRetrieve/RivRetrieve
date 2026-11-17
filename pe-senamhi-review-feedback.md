# SENAMHI (`pe_senamhi`) final review feedback

Branch `port/pe-senamhi` at `8758174e`, reviewed on 2026-11-06 with an interactive review notebook (`pe_senamhi_review.ipynb`), the source-independent test suite (`63 passed`), and `ty check src`.

The library implementation, offline catalogue, live API retrieval, and storage workflows all work as expected. Before merging into `main`, `docs/providers/pe_senamhi.md` needs a pass to align its table schema, opening example, and user-facing prose with the other implemented provider pages and `docs/AGENTS.md`.

## Works as expected

- **Catalogue and station metadata (`rr.find`, `rr.metadata`):**
  - `rr.find(provider="pe_senamhi")` exposes the 270 hydrological stations (`type="H"`, categories `EHA`, `EHMA`, `HLG`, `HLM`) with selectable series while `rr.metadata` retains all 771 station identities from the packaged catalogue.
  - Both summary and `view="source"` metadata tables work cleanly (`name`, `waterBody`, and `altitude` in `m`).
- **Series discovery and selection (`rr.series`, `rr.pick`):**
  - All 21 native series definitions across the 15 routes (12 PHISIS daily/hourly discharge and stage series + 9 conventional station-archive stage series) are exposed with accurate physical and temporal metadata (`frequency="daily"` / `"hourly"` for PHISIS, `frequency=None` for the monthly archive, `statistic=None`, and `vertical_reference="above_sea_level"` where the source unit is `m.s.n.m`).
  - Narrowing by `quantity`, `frequency`, `vertical_reference`, `variant` (matching `published_id`: `current`, `minimum`, `maximum`, `value`, or archive field names), and `series_id` works as designed.
- **Live retrieval (`rr.fetch`) and source fidelity:**
  - Verified live calls across PHISIS daily (hydrological-year partitions starting 1 September), PHISIS hourly (2-day backward partitions with prefix deduplication across partition boundaries), and monthly station archive (`YYYYMM` calendar-month partitions).
  - Naive timestamps are preserved with `time_zone="unknown"`.
  - Published `null` rows (such as PHISIS daily calendar grids in unpopulated years), empty readings arrays (`OutcomeStatus.EMPTY`), and failed source envelopes (`OutcomeStatus.FAILED` + `source.response_failed`) remain distinct, and partial failures do not discard valid partitions.
  - Provenance informational issues (`provenance.license_not_established`, `provenance.citation_not_established`) are emitted as expected.
- **Export and storage (`rr.write_dataset`, `rr.DatasetStore`):**
  - CF-compliant NetCDF export and incremental store `append` / `update` / `open_dataset` workflows round-trip cleanly.

---

## Documentation changes requested before merge (`docs/providers/pe_senamhi.md`)

### 1. Standardize `## What you can retrieve` table columns and replace internal `Product` IDs

Across the other 13 provider pages (`ch_foen.md`, `br_ana.md`, `fr_hubeau.md`, `lt_lhmt.md`, `pl_imgw.md`, `th_thaiwater.md`, `usgs_nwis.md`, etc.), `## What you can retrieve` uses the standard 6-column user-facing layout (`| Quantity filter | Source field / variant | Frequency | Statistic | Source unit | Returned unit |`) and never exposes RivRetrieve's internal `ProductId` slugs.

In [`docs/providers/pe_senamhi.md`](docs/providers/pe_senamhi.md):
- The **PHISIS** table (lines 94–108) currently uses an 8-column layout that exposes internal product slugs (`phisis_daily_flow`, `phisis_daily_level_above_sea_level`, etc.) and adds a `Vertical reference` column (which is already explained in `### Units and vertical reference`).
- The **Station archive readings** table (lines 131–142) lists internal RivRetrieve product slugs (`monthly_archive_nivel_del_rio_06h`, etc.) under `Product / Source field` instead of SENAMHI's actual published JSON keys (`NIVEL_DEL_RIO_06H`, `NIVEL_DEL_RIO_10H`, `NIVEL_DEL_RIO_14H`, `NIVEL_DEL_RIO_18H`, `NIVEL_DEL_RIO_PROMEDIO`, `N_NIVELAGUA`, `N_NIVELMEDIO`, `N_NIV_INST_00`, `N_NIV_INST_10`), which are the values shown in `rr.series(selection)["published_id"]` and accepted by `rr.pick(..., variant=...)`.

Suggested tables (with a brief note below, as in `fr_hubeau.md`, explaining that these are SENAMHI's published source fields in `published_id` with `variant=None`, and that `rr.pick(..., variant=...)` or `series_id` can be used to select an individual series):

**PHISIS hydrological monitoring:**

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | `current` | Daily | Unknown | m³/s | m³/s |
| `discharge` | `minimum` | Daily | Unknown | m³/s | m³/s |
| `discharge` | `maximum` | Daily | Unknown | m³/s | m³/s |
| `discharge` | `value` | Hourly | Unknown | m³/s | m³/s |
| `stage` | `current` | Daily | Unknown | m, m.s.n.m | m |
| `stage` | `minimum` | Daily | Unknown | m, m.s.n.m | m |
| `stage` | `maximum` | Daily | Unknown | m, m.s.n.m | m |
| `stage` | `value` | Hourly | Unknown | m, m.s.n.m | m |

**Station archive readings:**

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `stage` | `NIVEL_DEL_RIO_06H` | Unknown | Unknown | m | m |
| `stage` | `NIVEL_DEL_RIO_10H` | Unknown | Unknown | m | m |
| `stage` | `NIVEL_DEL_RIO_14H` | Unknown | Unknown | m | m |
| `stage` | `NIVEL_DEL_RIO_18H` | Unknown | Unknown | m | m |
| `stage` | `NIVEL_DEL_RIO_PROMEDIO` | Unknown | Unknown | m | m |
| `stage` | `N_NIVELAGUA` | Unknown | Unknown | m | m |
| `stage` | `N_NIVELMEDIO` | Unknown | Unknown | m | m |
| `stage` | `N_NIV_INST_00` | Unknown | Unknown | m | m |
| `stage` | `N_NIV_INST_10` | Unknown | Unknown | m | m |

### 2. Avoid an opaque 64-character `series_id` hash in the opening example

Lines 23–27 currently use a raw 64-character `series_id` hash in the first code block a user sees:

```python
selection = rr.find(
    provider="pe_senamhi",
    station="212600",
    series_id="fbbf4fa1e5858ded00123418b26c2fd936af128a0ced190b4b063934bb577711",
)
```

Matching the other provider pages, the opening example is much clearer if it selects by `quantity` and `frequency` and narrows to the `current` field with `rr.pick`:

```python
selection = rr.find(
    provider="pe_senamhi",
    station="212600",
    quantity="discharge",
    frequency="daily",
)
selection = rr.pick(selection, variant="current")
```

This produces the exact same 1-series selection and output without requiring the reader to look up a SHA-256 hash first. (Selecting by `series_id` via `rr.series(selection)` can still be mentioned in `## What you can retrieve`.)

### 3. Note cloud/datacenter IP reachability under `## Rate limits` (or access notes)

Per `#603` and `planning/visions/2026-10-30-pe-senamhi-source-scope-and-access.md`, `servicios.senamhi.gob.pe` can time out from some cloud or datacenter IP ranges even when requests succeed from residential or institutional networks. Adding a short sentence in `## Rate limits` will help users troubleshooting connection timeouts on cloud VMs or CI runners.

### 4. Mention the PHISIS automatic-station raw-data notice in `## Time and data status`

Per `planning/visions/2026-11-01-senamhi-provider-documentation.md`, `## Time and data status` should note that PHISIS automatic station views display the notice *"Esta información corresponde a datos crudos registrados por la estación automática."* (without generalizing that label to conventional series).

### 5. Trim maintainer/verification jargon in user-facing prose and complete `## Sources`

Per `docs/AGENTS.md` (*"Do not turn user pages into governance ledgers or internal audit notes"*):
- **Lines 176–177:** Replace *"Future-dated observations and negative values published by SENAMHI are preserved without unsupported correction or invented explanations."* with direct user-facing phrasing (e.g., *"SENAMHI records occasionally contain negative values or future-dated timestamps; RivRetrieve returns these values as published."*).
- **Lines 185–188:** The sentence about visually comparing ten random gauge hydrographs against CAMELS-PE reads like an internal verification note; either drop it from the user guide or move CAMELS-PE to `## Sources` as background context.
- **Lines 218–225 (`## Sources`):** Add the cited agency references from the vision (*Manual de Hidrometría*, SENAMHI 2014, and the `datosabiertos.gob.pe` Hydrometric Water Levels dataset description) and trim the final sentence about *"comparison records, and verification ledgers"* in the private verification archive to match the single-line reference used in other provider pages (such as `ch_foen.md`).
