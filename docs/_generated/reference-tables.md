## Frame schemas

### Series inspection frame

| Column | Polars dtype |
| --- | --- |
| `provider_id` | `String` |
| `station_id` | `String` |
| `product_id` | `String` |
| `series_id` | `String` |
| `facts_id` | `String` |
| `identity_namespace` | `String` |
| `published_id` | `String` |
| `description` | `String` |
| `identity_origin` | `String` |
| `variant` | `String` |
| `requested_variants` | `List(String)` |
| `requested_series_ids` | `List(String)` |
| `requested_selector_kind` | `String` |
| `requested_selector_value` | `String` |
| `physical_match` | `String` |
| `admission` | `String` |
| `admission_reason` | `String` |
| `source_unit` | `String` |
| `source_unit_state` | `String` |
| `source_unit_evidence` | `List(String)` |
| `normalized_unit` | `String` |
| `identity_evidence` | `List(String)` |
| `unit` | `String` |
| `quantity` | `String` |
| `frequency` | `String` |
| `statistic` | `String` |
| `temporal_support` | `String` |
| `day_definition` | `String` |
| `timestamp_anchor` | `String` |
| `time_zone` | `String` |
| `vertical_reference` | `String` |
| `vertical_datum` | `String` |
| `quantity_state` | `String` |
| `frequency_state` | `String` |
| `statistic_state` | `String` |
| `temporal_support_state` | `String` |
| `day_definition_state` | `String` |
| `timestamp_anchor_state` | `String` |
| `time_zone_state` | `String` |
| `vertical_reference_state` | `String` |
| `vertical_datum_state` | `String` |
| `quantity_evidence` | `List(String)` |
| `frequency_evidence` | `List(String)` |
| `statistic_evidence` | `List(String)` |
| `temporal_support_evidence` | `List(String)` |
| `day_definition_evidence` | `List(String)` |
| `timestamp_anchor_evidence` | `List(String)` |
| `time_zone_evidence` | `List(String)` |
| `vertical_reference_evidence` | `List(String)` |
| `vertical_datum_evidence` | `List(String)` |
| `inventory_ids` | `List(String)` |
| `inventory_scope` | `List(String)` |
| `inventory_windows` | `List(String)` |
| `outcome_windows` | `List(String)` |
| `inventory_vintage` | `List(String)` |
| `inventory_status` | `List(String)` |
| `outcomes` | `List(String)` |
| `outcome_reasons` | `List(String)` |

Identity and facts are separate. Nullable facts carry explicit evidence states; admission and inventory are not completeness scores. Use to_bundle for lossless exports.

### Station metadata summary

| Column | Polars dtype |
| --- | --- |
| `provider_id` | `String` |
| `station_id` | `String` |
| `station_name` | `String` |
| `latitude` | `Float64` |
| `longitude` | `Float64` |
| `crs` | `String` |
| `water_body_name_field` | `List(String)` |
| `water_body_name_value` | `List(String)` |
| `drainage_area_field` | `List(String)` |
| `drainage_area_value` | `List(String)` |
| `drainage_area_unit` | `List(String)` |
| `elevation_field` | `List(String)` |
| `elevation_value` | `List(String)` |
| `elevation_unit` | `List(String)` |
| `elevation_datum` | `List(String)` |

### Source metadata frame

| Column | Polars dtype |
| --- | --- |
| `provider_id` | `String` |
| `station_id` | `String` |
| `source_field` | `String` |
| `source_scope` | `String` |
| `source_value` | `String` |
| `source_dtype` | `String` |
| `source_unit` | `String` |
| `state` | `Enum(categories=['value', 'source_null', 'no_metadata'])` |
| `attribute_role` | `Enum(categories=['station_name', 'water_body_name', 'drainage_area', 'elevation'])` |
| `support_fact` | `String` |
| `source_datum` | `String` |
| `source_datum_field` | `String` |
| `source_datum_dtype` | `String` |
| `datum_support_fact` | `String` |

See `metadata` above and [station metadata](station-metadata.md) for name alternatives, JSON decoding and absence states.

### Observation frame

| Column | Polars dtype |
| --- | --- |
| `time` | `Datetime(time_unit='us', time_zone=None)` |
| `time_zone` | `String` |
| `station_id` | `String` |
| `product_id` | `String` |
| `series_id` | `String` |
| `facts_id` | `String` |
| `quantity` | `String` |
| `source_unit` | `String` |
| `unit` | `String` |
| `value` | `Float64` |

Only value is nullable. Time precision can vary while remaining Datetime. The zone belongs to each row, not the timestamp dtype. See `ObservationResult` above for units and meanings.


## Shipped software capabilities

The table uses the built-in manifest and declarations, not source probes. Credential names are requirements, not a readiness or successful-access test. Bulk retrieval needs explicit `download()` consent before a store exists.

Counts describe packaged inventory accounting only. They do not establish countrywide completeness, continuous history or present-day source access. Pair counts describe access routes, not concrete source-series counts or admission. See the [provider handoff](index.md#river-data-and-where-to-find-them) for ownership and coverage qualifications.

| Provider | Observation kind | Required credential variables | Stations | Available pairs | Unknown pairs | Unavailable pairs |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `ba_fhmzbih` | live | none | 60 | 132 | 48 | 0 |
| `br_ana` | live | `ANA_IDENTIFICADOR`, `ANA_SENHA` | 17914 | 6 | 107478 | 0 |
| `ca_eccc` | bulk store | none | 8057 | 0 | 16114 | 0 |
| `ch_foen` | live | none | 246 | 0 | 738 | 0 |
| `cz_chmi` | live | none | 831 | 0 | 4155 | 0 |
| `fr_hubeau` | live | none | 7347 | 15283 | 5014 | 0 |
| `fr_hydroportail` | live | none | 6409 | 59 | 12759 | 0 |
| `jp_mlit` | live | none | 1023 | 0 | 4092 | 0 |
| `lt_lhmt` | live | none | 97 | 0 | 194 | 0 |
| `no_nve` | live | `NVE_API_KEY` | 4902 | 14847 | 0 | 29271 |
| `pl_imgw` | bulk store | none | 1301 | 0 | 3903 | 0 |
| `th_thaiwater` | live | none | 825 | 1096 | 554 | 0 |
| `usgs_nwis` | live | none | 26258 | 58421 | 0 | 99127 |
| `za_dws` | catalogue-only | none | 2905 | 0 | 8715 | 0 |

### Packaged access coordinates

Access coordinates and declared units come from products.parquet. These are internal routes, not public physical filters or scientific authority. A provider listing a route does not imply that every station offers it. Use physical filters in `find` and inspect `series` for admission, units and facts. A product route does not select a preferred source variant.

| Provider | Product | Canonical unit |
| --- | --- | --- |
| `ba_fhmzbih` | `discharge_reported` | `m3/s` |
| `ba_fhmzbih` | `stage_reported` | `m` |
| `ba_fhmzbih` | `water_temperature_reported` | `degC` |
| `br_ana` | `discharge_daily_mean_bruto` | `m3/s` |
| `br_ana` | `discharge_daily_mean_consistido` | `m3/s` |
| `br_ana` | `discharge_instantaneous` | `m3/s` |
| `br_ana` | `stage_daily_mean_bruto` | `m` |
| `br_ana` | `stage_daily_mean_consistido` | `m` |
| `br_ana` | `stage_instantaneous` | `m` |
| `ca_eccc` | `discharge_daily_mean` | `m3/s` |
| `ca_eccc` | `stage_daily_mean` | `m` |
| `ch_foen` | `discharge_reported` | `m3/s` |
| `ch_foen` | `stage_reported` | `m` |
| `ch_foen` | `water_temperature_reported` | `degC` |
| `cz_chmi` | `discharge_daily_mean` | `m3/s` |
| `cz_chmi` | `discharge_hourly_mean` | `m3/s` |
| `cz_chmi` | `stage_daily_mean` | `m` |
| `cz_chmi` | `stage_hourly_mean` | `m` |
| `cz_chmi` | `water_temperature_daily_mean` | `degC` |
| `fr_hubeau` | `discharge_daily_max` | `m3/s` |
| `fr_hubeau` | `discharge_daily_mean` | `m3/s` |
| `fr_hubeau` | `stage_daily_max` | `m` |
| `fr_hubeau` | `water_temperature_reported` | `degC` |
| `fr_hydroportail` | `discharge_instantaneous` | `m3/s` |
| `fr_hydroportail` | `stage_instantaneous` | `m` |
| `jp_mlit` | `discharge_daily` | `m3/s` |
| `jp_mlit` | `discharge_hourly` | `m3/s` |
| `jp_mlit` | `stage_daily` | `m` |
| `jp_mlit` | `stage_hourly` | `m` |
| `lt_lhmt` | `discharge_daily_mean` | `m3/s` |
| `lt_lhmt` | `stage_daily_mean` | `m` |
| `no_nve` | `discharge_daily_mean` | `m3/s` |
| `no_nve` | `discharge_hourly_mean` | `m3/s` |
| `no_nve` | `discharge_instantaneous` | `m3/s` |
| `no_nve` | `stage_daily_mean` | `m` |
| `no_nve` | `stage_hourly_mean` | `m` |
| `no_nve` | `stage_instantaneous` | `m` |
| `no_nve` | `water_temperature_daily_mean` | `degC` |
| `no_nve` | `water_temperature_hourly_mean` | `degC` |
| `no_nve` | `water_temperature_instantaneous` | `degC` |
| `pl_imgw` | `discharge_daily` | `m3/s` |
| `pl_imgw` | `stage_daily` | `m` |
| `pl_imgw` | `water_temperature_daily` | `degC` |
| `th_thaiwater` | `discharge_reported` | `m3/s` |
| `th_thaiwater` | `stage_reported` | `m` |
| `usgs_nwis` | `discharge_daily_mean` | `m3/s` |
| `usgs_nwis` | `discharge_instantaneous` | `m3/s` |
| `usgs_nwis` | `stage_daily_max` | `m` |
| `usgs_nwis` | `stage_daily_mean` | `m` |
| `usgs_nwis` | `stage_daily_min` | `m` |
| `usgs_nwis` | `stage_instantaneous` | `m` |
| `za_dws` | `discharge_daily_mean` | `m3/s` |
| `za_dws` | `discharge_instantaneous` | `m3/s` |
| `za_dws` | `stage_instantaneous` | `m` |
