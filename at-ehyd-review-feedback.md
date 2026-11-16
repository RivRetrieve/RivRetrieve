# Austria: eHYD (`at_ehyd`) final review feedback

Branch `port/at-ehyd` at `47e72037`, reviewed on 2026-11-06 with an interactive review notebook (`at_ehyd_review.ipynb`), visual cross-checks against the live [eHYD portal](https://ehyd.gv.at/), the source-independent test suite (`52 passed`), and `ty check src`.

The library implementation, offline catalogue, live API retrieval across all three endpoint families (`owf`, `pegelBgis`, `pegelLongterm`), and storage workflows all work as expected and match the live eHYD portal. I approve the port for merge once `docs/providers/at_ehyd.md` (and its companion doc test in `tests/test_at_ehyd_documentation.py`) is updated to align its table layout and user-facing style with the other implemented provider pages and `docs/AGENTS.md`.

## Works as expected

- **Catalogue and station metadata (`rr.find`, `rr.metadata`):**
  - `rr.find(provider="at_ehyd")` exposes the 746 river gauges in `EPSG:4326` (744 with selectable series; sediment-only gauges `207480` and `230102` retained without selectable series).
  - Summary and `view="source"` station metadata work cleanly (`name` / `messstelle`, `gewaesser` / `gewasser`, verbatim German-comma `orogr.Einzugsgebiet [km²]` strings, `station_name=null` where historical and telemetry spellings differ across 51 gauges, and `elevation_*=null` / `state="no_metadata"` due to multi-epoch *Pegelnullpunkt* histories).
- **Series discovery and selection (`rr.series`, `rr.pick`):**
  - All 11 river products across the 3 endpoint families (7 validated *Geprüfte Daten* `owf` CSV products + 2 sub-hourly `pegelBgis` telemetry products + 2 current-year daily `pegelLongterm` products) expose accurate physical and temporal facts, including `frequency=None` on station `207340`'s daily (`T,1`) `W-Monatsminima` series.
  - Narrowing by `quantity`, `frequency`, `statistic`, `time_zone`, `vertical_reference`, `variant` (matching `published_id`), and `series_id` works as designed.
- **Live retrieval (`rr.fetch`, `rr.to_utc`) and source fidelity:**
  - Verified live calls and visual hydrograph plots against `ehyd.gv.at` across validated daily/monthly `owf` CSV exports (stations `209486`, `207068`, `207340`, `200352`), rolling sub-hourly `pegelBgis` telemetry (`time_zone="+01:00"` in fixed `MEZ`, converting cleanly via `rr.to_utc` to `+00:00`), and current-year `pegelLongterm` daily series (`current_value` only, with future `null` padding trimmed).
  - Stage conversion (`cm -> m` with `source_unit="cm"` and `vertical_reference="gauge_zero"`), negative stage values below gauge zero (`-2.27 m` at `207068` Linz), and negative monthly mean water temperatures (`-2.8 °C` at `200352` Unterhochsteg) are preserved accurately.
  - Interior `Lücke` lines in `owf` CSVs emit informational `source.gap_marker` issues without fabricating rows, while closing-boundary `Lücke` lines are suppressed cleanly.
- **Export and storage (`rr.write_dataset`, `rr.DatasetStore`):**
  - CF-compliant NetCDF export and incremental store `append` / `update` / `open_dataset` workflows round-trip cleanly.

---

## Documentation changes requested before merge (`docs/providers/at_ehyd.md`)

### 1. Standardize `## What you can retrieve` table columns and replace internal `product_id` slugs

Across the other provider pages (`ch_foen.md`, `fr_hubeau.md`, `lt_lhmt.md`, `pl_imgw.md`, `br_ana.md`, `pe_senamhi.md`, etc.), `## What you can retrieve` uses the standard 6-column user-facing layout (`| Quantity filter | Source field / variant | Frequency | Statistic | Source unit | Returned unit |`), spells out `Minimum` / `Maximum`, and does not expose internal `product_id` routing slugs or parenthetical internal unit codes (`m³/s (\`m3/s\`)`).

In [`docs/providers/at_ehyd.md`](docs/providers/at_ehyd.md) (lines 109–122):
- The current 7-column table (`| Quantity filter | Product (product_id) | Stream | Frequency | Statistic | Source unit | Returned unit |`) exposes internal `product_id` slugs (`pegel_bgis_abfluss`, `pegel_longterm_abfluss`, etc.) that cannot be passed to `rr.find` or `rr.pick`, and adds a `Stream` column when the two streams are already introduced right above the table.
- Splitting into two standard 6-column tables (one for **Validated historical archive (*Geprüfte Daten*)** and one for **Operational telemetry (*Pegel Aktuell*)**) lets the second column show the actual `published_id` values (`owf_abfl_tagesmittel`, ..., for the archive, and `data` / `current_value` for *Pegel Aktuell*) that appear in `rr.series(selection)["published_id"]` and are accepted directly by `rr.pick(..., variant=...)`:

**Validated historical archive (*Geprüfte Daten*):**

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | `owf_abfl_tagesmittel` (`Q-Tagesmittel`) | Daily | Mean | m³/s | m³/s |
| `discharge` | `owf_abfl_monatsminima` (`Q-Monatsminima`) | Monthly | Minimum | m³/s | m³/s |
| `discharge` | `owf_abfl_monatsmaxima` (`Q-Monatsmaxima`) | Monthly | Maximum | m³/s | m³/s |
| `stage` | `owf_wasserst_tagesmittel` (`W-Tagesmittel`) | Daily | Mean | cm | m |
| `stage` | `owf_wasserst_monatsminima` (`W-Monatsminima`) | Monthly (Unknown at `207340`) | Minimum | cm | m |
| `stage` | `owf_wasserst_monatsmaxima` (`W-Monatsmaxima`) | Monthly | Maximum | cm | m |
| `temperature` | `owf_wassertemp_monatsmittel` (`WT-Monatsmittel`) | Monthly | Mean | °C | °C |

**Operational telemetry (*Pegel Aktuell*):**

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | `data` (sub-hourly telemetry) | Unknown | Unknown | m³/s | m³/s |
| `stage` | `data` (sub-hourly telemetry) | Unknown | Unknown | cm, m ü.A | m |
| `discharge` | `current_value` (current-year daily) | Daily | Unknown | m³/s | m³/s |
| `stage` | `current_value` (current-year daily) | Daily | Unknown | cm, m ü.A | m |

*(Note: updating this table will also require a matching adjustment to the table regex assertion in [`tests/test_at_ehyd_documentation.py`](tests/test_at_ehyd_documentation.py) lines 106–129.)*

### 2. Show selecting operational telemetry via `variant` instead of requiring `series_id` hashes

Lines 147–149 currently tell users:

> To retrieve an operational telemetry series without also requesting archive products, pass its `series_id` from `candidates` to `rr.pick(all_discharge, series_id=...)`.

Because `rr.pick(..., variant=...)` matches `published_id`, users do not need a 64-character `series_id` hash to distinguish the two operational telemetry feeds from the archive:
- Sub-hourly telemetry (`pegelBgis`): `rr.pick(all_discharge, variant="data")` (or `rr.pick(all_discharge, time_zone="UTC+01:00")`)
- Current-year daily comparison (`pegelLongterm`): `rr.pick(all_discharge, variant="current_value")`

Documenting `variant="data"` and `variant="current_value"` (with `series_id` mentioned as an alternative) is much friendlier and matches the selection patterns shown in other provider guides.

### 3. Replace internal `product_id` wildcard patterns (`owf_*`, `pegel_bgis_*`, `pegel_longterm_*`) in prose

Throughout `## What you can retrieve`, `## Archive vintage and recent coverage`, and `## Time and data status`, the prose refers to `owf_*`, `pegel_bgis_*`, and `pegel_longterm_*` (~25 occurrences). Because `product_id` is an internal routing key rather than a user filter, the prose will read more naturally and consistently with other provider pages if it refers to the streams by their user-facing names — e.g., **validated archive series (*Geprüfte Daten*)**, **sub-hourly telemetry (*Pegel Aktuell*, `variant="data"`)**, and **current-year daily comparison series (*Pegel Aktuell*, `variant="current_value"`)**.

### 4. Trim internal engine/verification phrasing in `## Time and data status` and `## Sources`

Per `docs/AGENTS.md` (*"Do not turn user pages into governance ledgers or internal audit notes"*):
- **Lines 228–231 & 284–290:** The explanations of internal `result.outcomes` status transitions (`unresolved` vs `empty` vs `failed` on `0`-byte HTTP `200` responses) read like internal engine contract notes. Simplify these bullets to focus on what the user sees in `result.data` and `result.issues` (for example, that post-yearbook dates return no rows because the yearbook export ends at `2023-12-31`, that offline *Pegel Aktuell* gauges return no rows with a `source.inventory_unresolved` warning when requested explicitly, and that empty or malformed `owf` files report an error or warning in `result.issues`).
- **Lines 337–339 (`## Sources`):** Keep the closing lines concise and aligned with the other provider guides (`ch_foen.md`, `fr_hubeau.md`).
