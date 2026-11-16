# Final Review Feedback: Finland SYKE (`fi_syke`, Effort #760)

## Overall Assessment

The **`fi_syke`** provider port (Finnish Environment Institute / *Suomen ympäristökeskus*, SYKE, Open Hydrology OData API `Hydrologiarajapinta` v1.1) is well-architected, faithful to source evidence, and passes all logic, retrieval, public-surface, documentation, and type checks (`29 passed`, `ty check src` clean).

However, live end-to-end testing during the review uncovered **one functional bug in `catalogue_series.py` / `catalogue/source_series.json`** (where `water_temperature_reported` is given `quantity="water_temperature"` instead of `"temperature"`, causing `rr.find(provider="fi_syke", quantity="temperature")` and `rr.pick(..., quantity="temperature")` to return 0 series) and **a few documentation/catalogue alignment items** in `docs/providers/fi_syke.md` that should be resolved before merging `port/fi-syke` into `main`.

### What Works as Expected

- **Offline Catalogue (`stations.parquet`, `products.parquet`, `station_products.parquet`)**:
  - Packaged snapshot (`catalogue_version="2026-11-07"`) contains **2,543 stations** across **3 products**:
    - `discharge_reported` (`Virtaama`, `Suure_Id=2`, source unit `m3/s` -> `m3/s`): `711` stations with `availability="available"`.
    - `stage_reported` (`Vedenkorkeus`, `Suure_Id=1`, source unit `cm` -> `m`): `1,753` stations with `availability="available"`.
    - `water_temperature_reported` (`LampoPintavesi`, `Suure_Id=4`, source unit `°C` -> `degC`): `79` stations with `availability="available"`.
  - Planar coordinates (`KoordErTmIta`, `KoordErTmPohj` in `EPSG:3067` / ETRS-TM35FIN) are accurately projected to geographic ETRS89 (`EPSG:4258`) for `2,540` stations (`latitude` `59.95°N–69.91°N`, `longitude` `19.63°E–31.15°E`), while the `3` stations with missing coordinates in `Paikka` (`1636`, `2533`, `3522`) are preserved with `latitude=None`, `longitude=None`.
  - Station metadata (`rr.metadata(provider="fi_syke")`) exposes `station_name` (`Nimi`), `river_name` (`VesalNimi` sub-basin name), and `basin_name` (`PaaVesalNimi` main drainage basin name), and `rr.metadata(provider="fi_syke", view="source")` preserves all **31** raw `Paikka` attributes.
  - Open-data licence (`CC BY 4.0`) and attribution terms from SYKE's service pages (`avoin-tieto`, `hydrologiset-havaintotiedot`) are established in `rr.describe("fi_syke")` and `result.provenance`.
- **Live Observation Retrieval (`fetch.py`, `parse.py`, `series.py`, `origins.py`, `config.py`)**:
  - Queries `https://rajapinnat.ymparisto.fi/api/Hydrologiarajapinta/1.1/odata/{Virtaama|Vedenkorkeus|LampoPintavesi}` with `$filter=Paikka_Id eq {int} and Aika ge datetime'...' and Aika le datetime'...'` and `$orderby=Aika asc`, intentionally omitting `$top` so SYKE's server-driven pagination emits `odata.nextLink` (`$skiptoken`) across 500-row pages (`MAX_PAGES = 200`).
  - **Live worked example (`894` `Ruskeakoski` on `Jänisjoki`, `2020-01-01` to `2020-01-07`)**: Returns all 7 daily discharge rows (`16.73` to `29.93 m3/s`) with `OutcomeStatus.SUCCESS`, matching `docs/providers/fi_syke.md`.
  - **Live multi-page pagination (`894` `Ruskeakoski`, `1959-01-01` to `1961-12-31`)**: Automatically follows `odata.nextLink` across **3 HTTP 200 pages** (`500 + 500 + 96` rows) and returns all `1,096` daily rows in ascending timestamp order.
  - **Live recent 2026 observations (`894` `Ruskeakoski`, `2026-01-01` to `2026-04-15`)**: Returns `105` daily rows (`7.44` to `20.42 m3/s`).
  - **Live stage conversion (`cm -> m`, `vertical_reference="above_sea_level"`, `vertical_datum=None`)**: Verified on `2471` (`Luksuan pato`, `244.50–244.52 m`) and `1721` (`Melajärvi`, `109.88–110.05 m`), with `source_unit="cm"` and `unit="m"`.
  - **Live water temperature retrieval (`1685` `Säkylän Pyhäjärvi`, `2023-06-01` to `2023-08-31`)**: Returns `91` daily rows (`14.5` to `21.6 degC`) with `source_unit="°C"` and `unit="degC"`.
  - **Quality/processing flag preservation (`Lippu_id`)**: Non-null `Lippu_id` values emit `warning` issues (`code="source.flag_code"`) with `flag_code` details while preserving the numeric observation value.
  - **Time zone & UTC conversion**: Preserves `time_zone="unknown"` (`source_silent`) and raises `FatalContractError` on `rr.to_utc(result)`.
  - **Downstream integration**: `rr.to_bundle` / `rr.from_bundle`, `rr.write_dataset` / `rr.open_dataset`, `rr.DatasetStore` (`append`, `update`, `open_dataset`), `cache` modes (`"bypass"`, `"refresh"`, `"reuse"`), and `receipts=True` all pass end-to-end.

---

## Code, Catalogue & Documentation Issues to Fix Before Merging

### 1. Bug (Fixed in PR [#786](https://github.com/RivRetrieve/RivRetrieve/pull/786)): `catalogue_series.py` set `quantity="water_temperature"` instead of `"temperature"`, breaking `rr.find(provider="fi_syke", quantity="temperature")`

- **Status**: Fixed in PR [#786](https://github.com/RivRetrieve/RivRetrieve/pull/786) (`fix/fi-syke-catalogue-series-quantity` -> `port/fi-syke`).
- **Where**:
  - `src/rivretrieve/_internal/providers/fi_syke/catalogue_series.py` (lines 37–48)
  - `src/rivretrieve/_internal/providers/fi_syke/catalogue/source_series.json`
- **Issue**:
  - In `catalogue_series.py`, `describe_catalogue_series()` reads `quantity = row["observed_property"]` directly from `products.parquet`, where `observed_property` is `"water_temperature"`. Consequently, `catalogue/source_series.json` records `"quantity": {"value": "water_temperature", "state": "known", ...}` (and `"normalized_unit": null`).
  - By contrast, `src/rivretrieve/_internal/providers/fi_syke/series.py` (lines 60–67) defines `observed_property="water_temperature"` and `quantity="temperature"` (with `normalized_unit="degC"`), matching `QUERY_VOCABULARIES["quantity"] = ("discharge", "stage", "temperature")` in `src/rivretrieve/_internal/selection.py` and other providers with water temperature (such as `ba_fhmzbih`).
  - Because `selection.py` filters `PhysicalFacts.quantity.value == "temperature"`, calling:
    ```python
    rr.find(provider="fi_syke", quantity="temperature")
    rr.pick(rr.find(provider="fi_syke"), quantity="temperature")
    ```
    returns **0 matched series** (`empty_reason.code == "unresolved_inventory"`), and calling `rr.find(provider="fi_syke", quantity="water_temperature")` raises `ValueError: Unsupported quantity filter 'water_temperature'. Supported values: 'discharge', 'stage', 'temperature'`.
  - Additionally, before `rr.fetch()`, `rr.series(sel)` reports `quantity="water_temperature"` and `unit="°C"`, whereas after `rr.fetch()`, `rr.series(result)` reports `quantity="temperature"` and `unit="degC"`.
- **Suggested Fix**:
  - In `catalogue_series.py`, use `PRODUCTS_BY_ID[product].quantity` (`"temperature"`) and `PRODUCTS_BY_ID[product].normalized_unit` (`"m3/s"`, `"m"`, `"degC"`) from `series.py` (or map `"water_temperature"` to `"temperature"`), regenerate `catalogue/source_series.json`, and add a regression assertion in `tests/test_fi_syke_public.py` verifying that `rr.find(provider="fi_syke", quantity="temperature")` returns matching series.

---

### 2. Contradiction in `docs/providers/fi_syke.md` (Fixed in PR [#788](https://github.com/RivRetrieve/RivRetrieve/pull/788)): Prose Claims `frequency` Is Unknown While Code and Table Declare `frequency="daily"`

- **Status**: Fixed in PR [#788](https://github.com/RivRetrieve/RivRetrieve/pull/788) (`docs/fi-syke-final-review` -> `port/fi-syke`).
- **Where**:
  - `docs/providers/fi_syke.md` (lines 55 and 91–92 vs lines 82–86)
- **Issue**:
  - Both `series.py` (line 144) and `catalogue_series.py` (line 50) declare `frequency=known("daily", _PAIKKA_EVIDENCE)`, `products.parquet` sets `frequency="daily"`, and the table in `docs/providers/fi_syke.md` (lines 82–86) correctly lists `Frequency = Daily` and `Statistic = Unknown`.
  - However, two sentences in `docs/providers/fi_syke.md` state that `frequency` is unknown (left over from adapting `docs/providers/ba_fhmzbih.md`):
    1. Line 55: *"Each row carries a timestamp in `time`, the value in `value`, and the series metadata columns; `fi_syke` does not publish a time zone or aggregation statistic in the observation payload, so `time_zone` is `unknown` and the request did not restrict by `statistic` or `frequency`."*
    2. Lines 91–92: *"The `Virtaama`, `Vedenkorkeus`, and `LampoPintavesi` endpoints return timestamped values (`Aika`, `Arvo`) without stating whether each row is a daily mean, an instantaneous reading, or another aggregation, so RivRetrieve leaves frequency and statistic unknown rather than guessing from the roughly daily spacing of the values."*
- **Suggested Fix**:
  - Update line 55 and lines 91–92 in `docs/providers/fi_syke.md` to state that `frequency` is `"daily"` (established from SYKE's `Paikka` / service metadata, so `frequency="daily"` can be used in `rr.find` and `rr.pick`), while `statistic`, `temporal_support`, `day_definition`, `timestamp_anchor`, and `time_zone` remain `unknown`.

---

### 3. `station_products.parquet` Availability (`"unknown"` vs `"unavailable"`) Contradicts `docs/providers/fi_syke.md`'s One-Quantity-Per-Station Statement (Fixed in PR [#788](https://github.com/RivRetrieve/RivRetrieve/pull/788))

- **Status**: Fixed in PR [#788](https://github.com/RivRetrieve/RivRetrieve/pull/788) (`docs/fi-syke-final-review` -> `port/fi-syke`).
- **Where**:
  - `src/rivretrieve/_internal/providers/fi_syke/generate_catalogue.py` (lines 228–250)
  - `docs/providers/fi_syke.md` (lines 75–78 and 101–104)
- **Issue**:
  - In SYKE's `Paikka` table, `Paikka_Id` is a **per-quantity** identifier (`Suure_Id=1` for `Vedenkorkeus`, `Suure_Id=2` for `Virtaama`, `Suure_Id=4` for `LampoPintavesi`).
  - `docs/providers/fi_syke.md` states:
    - Lines 75–78: *"A station publishes at most one of the three admitted quantities: a river gauge with both discharge and stage readings appears as two separate stations in the catalogue, one per quantity, not one station with two available products."*
    - Lines 101–103: *"The catalogue lists each station under exactly one of these three quantities, because the source itself associates one quantity with each station identifier."*
  - However, `build_station_products()` in `generate_catalogue.py` sets `availability="unknown"` (rather than `"unavailable"`) for the 2 non-witnessed products at each `Paikka_Id` (`5,086` rows). Because RivRetrieve's selection engine includes all `(station_id, product_id)` pairs where `availability != "unavailable"`, calling:
    - `rr.find(provider="fi_syke")` selects **7,629 series** (`2,543 × 3`) rather than `2,543` series;
    - `rr.find(provider="fi_syke", quantity="discharge")` selects **all 2,543 stations** (including the `1,753` stage-only and `79` temperature-only `Paikka_Id`s); and
    - `rr.find(provider="fi_syke", station="894")` selects **all 3 products** (`discharge_reported`, `stage_reported`, `water_temperature_reported`) for station `"894"` unless the caller also specifies `quantity="discharge"`.
- **Suggested Fix**:
  - Either mark non-matching products for a `Paikka_Id` as `"unavailable"` in `station_products.parquet` if `Paikka.Suure_Id` is authoritative for each `Paikka_Id`, **or** update `docs/providers/fi_syke.md` to explain that non-witnessed quantities at a `Paikka_Id` have `availability="unknown"` (so users should always pass `quantity=...` or `product=...` when selecting a `Paikka_Id`).

---

### 4. Minor Documentation Clarifications in `docs/providers/fi_syke.md` (Fixed in PR [#788](https://github.com/RivRetrieve/RivRetrieve/pull/788))

- **Status**: Fixed in PR [#788](https://github.com/RivRetrieve/RivRetrieve/pull/788) (`docs/fi-syke-final-review` -> `port/fi-syke`).
- **Per-site stage datum corrections (`VedenkTasoTieto`)**:
  - `docs/providers/fi_syke.md` (lines 94–99) explains that SYKE uses `N2000` or `N60` (`vertical_datum=None`) and that coastal stage readings can be negative. Per the Step 1 scope vision (`planning/visions/2026-11-07-fi-syke-source-scope-and-access.md`), it is also worth noting that SYKE publishes a per-station datum correction table (`VedenkTasoTieto`, providing `Tasokorjaus` offsets across `N43`, `NN`, `N60`, `N2000`, and `LN` for 1,623 of the 1,753 stage stations) which RivRetrieve does not apply because `Vedenkorkeus` rows do not identify which datum each reading is recorded in; users comparing absolute stage elevations across stations should consult `VedenkTasoTieto`.
- **Excluded SYKE `Hydrologiarajapinta` tables**:
  - Mention in `docs/providers/fi_syke.md` (under *Limitations*) that SYKE's `Hydrologiarajapinta` also publishes depth-specific water-temperature profiles (`LampoLuotaus`, `Suure_Id=12`) and catchment runoff per unit area (`Valuma`, `Suure_Id=3`, in `l/s/km2`), which are excluded from `fi_syke`.
- **Table column header (`Source field / variant`)**:
  - In `docs/providers/fi_syke.md` (lines 82–86), the first column is titled `Source field / variant` with values `Virtaama`, `Vedenkorkeus`, and `LampoPintavesi`. In `rr.series()`, `variant` and `published_id` are `null` (`None`) for all `fi_syke` series (`Virtaama` etc. are OData entity set names stored in `products.parquet["native_id"]`), so `rr.pick(selection, variant="Virtaama")` matches 0 series. Renaming that column header to `Source entity set` (or `OData entity set`) avoids implying that `variant=` filters on those names.
