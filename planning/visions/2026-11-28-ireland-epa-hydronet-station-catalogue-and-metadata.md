# Ireland EPA HydroNet: station catalogue and metadata

Establish Step 2 of the `ie_epa` port: a reproducible catalogue builder and
approved packaged catalogue that support offline discovery of the Step 1 scope.
Implementation of this vision completes
[#1106](https://github.com/RivRetrieve/RivRetrieve/issues/1106), Step 2 of
[Program #875](https://github.com/RivRetrieve/RivRetrieve/issues/875). Follow
[Step 2 of the provider-port guide](../../docs/maintenance/provider-ports.md#2-station-catalogue-and-metadata),
the [Program plan](2026-11-27-ireland-epa-hydronet-porting-plan.md) and the
[Step 1 vision](2026-11-27-ireland-epa-hydronet-source-scope-and-access.md).

Work on `port/ie-epa`. Target it with every pull request for this Effort, as the
guide's "Use a dedicated port branch" section and the 2026-11-27 Program comment
on #875 require. Do not merge provider code into `main`.

## Terms

- **Station file list**: the EPA-published
  `stations/{site_no}/{station_no}/index.json` under
  `https://epawebapp.epa.ie/Hydronet/output/internet/`. It repeats the station's
  register fields and lists downloadable files as `_links` entries with
  `station_parameter` (`S`, `Q`), `period_alias` and `href`. The live list also
  includes chart `.png` resources; only `.zip` files matter here.
- **Catalogue**: RivRetrieve's packaged tables. Every availability value in it
  is RivRetrieve's interpretation of EPA material, backed by recorded evidence.
  The EPA publishes no availability field.
- **Product**: a provider-wide series kind. Candidates are water level (`S`) and
  discharge (`Q`) at daily and 15-minute resolution. Step 3
  ([#1100](https://github.com/RivRetrieve/RivRetrieve/issues/1100)) establishes
  their physical meaning, frequency and statistic. Step 2 publishes product rows
  asserting only facts already established; facts Step 3 has not established
  stay `unknown` in the product table rather than being given provisional
  values.
- **Station-product**: one station with one product. Availability is set per
  station-product.

## Inputs and evidence

Build from retained originals only, with no live calls in the build. Follow the
`cl_dga`, `fi_syke` and `ie_opw` builders: an evidence root, a selection and an
input receipt, verifying that the rebuilt native table matches the selected
originals. The `ie_opw` builder
(`src/rivretrieve/_internal/providers/ie_opw/generate_catalogue.py`) exists only
on branch `port/ie-opw`; read it there and do not merge it.

Start from the Step 1 collection `ie_epa-access-2026-11-27-v1` in the private
[verification-evidence](https://github.com/RivRetrieve/verification-evidence)
repository. It holds `stations.json`, `sites.json` and all 3,155 station file
lists. Recapture through the archive's intake process if a fresher snapshot is
needed. Continue the research record `research/ie-epa-source-access.md`; do not
start another.

## Station universe and identity

The universe is the Step 1 rule applied to the selected snapshot:
`RESPONSIBLE_BODY == "Environmental Protection Agency"`, `object_type` exactly
`General;Surface water`, and at least one listed `S` or `Q` `.zip` other than
`Q/complete_gaugings.zip`. The 2026-11-27 snapshot gives 385 stations
(129 active, 215 inactive, 41 suspended). Inactive and suspended stations are
included.

- `station_id` is the native `station_no` string exactly as published. Keep
  leading zeros and letter suffixes: `CAS/34109A` and `CAS/26338A` are in scope.
  It is unique in the register. Do not enforce a five-digit format, unlike
  `ie_opw`.
- Keep `site_no` (the regional folder) as a native field; retrieval paths need
  it.
- `DUB/10047`–`10050` are also in `ie_opw` (branch `port/ie-opw`). Publish them in
  both providers; each provider's documentation points to the other. `DUB/09045`
  hosts no files on HydroNet and stays out for now.

## Coordinates

Map `station_latitude` and `station_longitude` to the catalogue's `latitude`
and `longitude`.

- Label them `EPSG:4326` only when an EPA or data.gov.ie document states the
  reference system of these station coordinates. A projection declared only for
  web-map display layers does not count. Check the HydroNet layer indexes, the
  app configuration and the data.gov.ie record. Otherwise publish `crs`
  `"unknown"` and keep the coordinates.
- Record in the research record, as context only: transforming latitude and
  longitude from WGS84 to Irish Grid (EPSG:29903) reproduces
  `station_carteasting`/`station_cartnorthing` to centimetres at 381 of 385
  stations. `27010`, `03100`, `22011` and `28012` differ by 50–60 m. This does
  not justify the label.
- Do not use `station_local_x`/`station_local_y`. At 14 stations these fields
  hold latitude and longitude rather than grid coordinates, so their meaning is
  inconsistent.

## Availability

Only an explicit EPA statement may make a station-product `unavailable`.
HydroNet makes none, so:

- **`available`**: the station file list includes the matching
  `complete_daymean.zip` or `complete_15min.zip`. A listed file means the EPA
  publishes the series, even if it is empty at capture. Known empty files at
  2026-11-27 are `MON/37016` `Q/complete_daymean` (`#Rows;0`) and `CAS/33008`
  `Q/complete_daymean` (rows without values). Both stations stay in the
  catalogue. Data can return, for example after rating recalibration.
- **`unknown`**: the file list has no file for that product. At 2026-11-27 this
  is 188 station-products: discharge at 88 level-only stations and water level
  at 6 discharge-only stations, each at daily and 15-minute resolution
  (94 station-parameters × 2). The register sometimes contradicts the file
  list: active level-only `ATH/25046` has `DATA_AVAILABLE` "Water Level and
  Flow". The availability reason should say the file list omits the parameter.
- **`unavailable`**: not used.

Every station that has a parameter has both its `complete_daymean` and
`complete_15min` files in the 2026-11-27 snapshot. The rule still applies to
either file alone if a later snapshot differs.

Do not derive availability from `DATA_AVAILABLE`. It disagrees with hosted files
at about 40 in-scope stations. Keep it as a native field.

Record whether the rolling files (`1year_daymean.zip`, `3_months.zip`) are
listed for each station and parameter as native facts. Step 4
([#1102](https://github.com/RivRetrieve/RivRetrieve/issues/1102)) chooses which
files to retrieve. Five active stations list no rolling files: `COR/18009`,
`MON/36031`, `COR/22039`, `COR/22041` and `COR/21001`.

Leave published record start and end dates `None`.

## Descriptive metadata

- **Station name**: `station_name`.
- **Water body name**: `WTO_OBJECT`, as written, including generic values
  (`SPRING`, `STREAM`) and disambiguators (`BLACKWATER [MUNSTER]`). It equals
  `river_name` at every in-scope station.
- **Drainage area**: `CATCHMENT_SIZE` with the inline `km²` unit. Blank values
  are `source_null`. Keep the 13 `0.00 km²` values as written.
- **Elevation**: `no_metadata`. `station_gauge_datum` is a water-level datum
  (`m OD Malin (OSGM02)`, `m OD Malin (OSGM15)`, `m OD (Poolbeg)`, `m (TBM)`);
  Step 3 establishes its meaning.
- **Status**: `station_status` stays native only.

## Native table

Keep a curated set, as `ie_opw` does: identity and region (`station_no`,
`site_no`, `site_name`), `station_latitude`/`station_longitude` and
`station_carteasting`/`station_cartnorthing`, `object_type`, `station_status`,
`RESPONSIBLE_BODY`, `STATION_OWNER`, `TYPE_OF_GAUGING`, `catchment_name`,
`WTO_OBJECT`, `river_name`, `CATCHMENT_SIZE`, `station_gauge_datum`,
`station_gauge_datum_unit`, `DATA_AVAILABLE`, and the listed-file facts above.

Leave out flow percentiles, `LTA_RAINFALL_1961_1990`, web presentation fields
(`Web_Legend`, `Web_Link`), blank groundwater fields and the free-text notes
`ObjectDescription` and `Web_Desc`. They remain in the retained original; Step 3
may consult the notes for datum and suspension history.

## Provider information

Licence CC BY 4.0. Link the
[HydroNet disclaimer](https://epawebapp.epa.ie/Hydronet/output/html/disclaimer.html)
and [FAQ](https://epawebapp.epa.ie/Hydronet/output/html/FAQ.html) from the
catalogue's attribution or provenance metadata, as Step 1 settled.

## Documentation and handoff

Record in the research record and provider documentation:

- that availability comes from the file lists, why listed empty files are
  `available` and why missing files are `unknown`;
- that `unknown` pairs are selectable; Step 4 settles what fetching them
  returns;
- the empty files and the `DATA_AVAILABLE` contradictions;
- the stations excluded by the Step 1 rule: non-EPA stations hosting files
  (`26243`, `06036`, `38010`, `30111`, `18027`, `14049`), lakes, reservoirs and
  springs, spot-only stations, stations with no files, and `DUB/09045`.

Post a safe public summary on #1106. Keep private material out of this
repository and public issues.

Left to the implementing agent: product identifiers, availability-reason
wording, native-table schema details, the `last_catalogue_check` date and the
disclosure review for new field mappings.

Out of scope: physical meaning, datums, timestamps and quality codes (Step 3);
file choice, rolling versus full-history files and empty responses (Step 4);
provider declaration and retrieval (Step 5, [#1104](https://github.com/RivRetrieve/RivRetrieve/issues/1104)).

Step 2 is complete when the packaged catalogue rebuilds from retained evidence,
its checks pass against genuine inputs, and the research record supports every
field mapping and availability claim above.
