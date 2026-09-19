# Drainage-area metadata

`drainage_areas` reads the drainage-area and watershed-size metadata shipped with
RivRetrieve. It works offline with one or many gauges, including selections that
span providers. It does not retrieve observations or require credentials.

```python
import json
import rivretrieve as rr

gauges = rr.find(provider="ca_eccc", product="discharge_daily_mean")
gauge = rr.pick(gauges, station="02GA010")
areas = rr.drainage_areas(gauge)
```

This gauge has two source fields. `DRAINAGE_AREA_GROSS` holds `1035.0` and
`DRAINAGE_AREA_EFFECT` holds null in the packaged snapshot. Selecting additional
products for the same gauge does not repeat its metadata.

## Returned frame

The Polars frame sorts rows by `provider_id`, `station_id`, and `source_field`.
Each source field stays separate. No field is preferred or substituted for another.

| Column | Meaning |
| --- | --- |
| `provider_id`, `station_id` | Gauge identity; station identifiers retain leading zeros. |
| `source_field` | Exact native field name. |
| `source_value` | JSON scalar text, or null. Decode a non-null cell with `json.loads`. |
| `source_dtype` | Native Polars dtype, currently `String` or `Float64`. |
| `source_unit` | An already established unit, otherwise null. Units embedded in field names or values remain unchanged. |
| `state` | Enum: `value`, `source_null`, or `no_metadata`. |

All columns except `state` have Polars `String` dtype. JSON encoding lets strings
and numbers share one column without converting either into the other:

```python
gross = areas.filter(areas["source_field"] == "DRAINAGE_AREA_GROSS")
value = json.loads(gross["source_value"].item())  # float 1035.0
```

A source string such as `633.00 km²` decodes to that exact string, not a number.
Blank strings remain blank strings. Numerical source values retain their numerical
information. There is no unit conversion or common area-kind vocabulary.

- `value`: the source field holds a non-null value.
- `source_null`: the field exists but holds null. Its name, dtype, and any
  established unit remain in the row.
- `no_metadata`: no eligible field is exposed for this gauge. All four source
  columns are null, but the gauge identity remains visible.

Neither absence means zero or establishes that an agency publishes no drainage
area elsewhere. Empty selections return the same schema with no rows.

## Packaged coverage

Coverage follows existing repository evidence. The utility exposes these source
fields, not a harmonized drainage-area dataset or a scientific recommendation.

| Provider | Source fields | Separate units |
| --- | --- | --- |
| `ba_fhmzbih` | `metadata_CATCHMENT_SIZE` | None; formatted source strings retain inline units. |
| `br_ana` | `Area_Drenagem` | None. |
| `ca_eccc` | `DRAINAGE_AREA_GROSS`, `DRAINAGE_AREA_EFFECT` | None. |
| `cz_chmi` | `PLO_STA` | `km²` |
| `fr_hubeau` | `superficie_topo`, `superficie_reelle` | None. |
| `jp_mlit` | `流域面積` | None; source strings retain inline units. |
| `no_nve` | `drainageBasinArea`, `drainageBasinAreaNorway` | `km2` |
| `pl_imgw` | `area` | None. |
| `usgs_nwis` | `drain_area_va`, `contrib_drain_area_va` | `sq mi` for `drain_area_va`; none for `contrib_drain_area_va`. |
| `za_dws` | `Catchment Area km**2` | `km**2` |

`ch_foen`, `lt_lhmt`, and `th_thaiwater` have no eligible field in their current
native tables. They return `no_metadata` rows. France retains both area fields
where they are null, including its hydrometry rows. Norway's lake, reservoir,
regulation, transfer, and remaining-area fields are not drainage-basin size
fields and are excluded.

## Maintaining the packaged projection

The package carries a small projection rather than the complete native tables.
The canonical station catalogue is unchanged. The offline builder uses the
existing station-identity origins, restricts native rows to canonical station
identities, and records absence for providers without an eligible field.

```bash
uv run python scripts/build_drainage_areas.py
uv run python scripts/build_drainage_areas.py --check
```

Run the builder after changing relevant native inputs or field declarations.
The check and tests compare every projected scalar with the native input,
including formatted strings and nulls. No command refreshes a catalogue.

The recorded Polish catalogue description calls its contents "lat/lon, elevation,
and drainage area for all stations". Its seven-column source header has one area
field, `area`, alongside gauge identity, river, elevation, and coordinates. This
repository record establishes eligibility, but not a unit.

Field eligibility is recorded in `AREA_FIELDS` in the builder. Existing evidence
includes the [Czech drainage-area entry](https://github.com/RivRetrieve/RivRetrieve/blob/05b5cf7f16863a254d86073b9a2066b93456f923/docs/milestone-tracker.md), the
[recorded Polish catalogue description](https://github.com/RivRetrieve/RivRetrieve/blob/9b89e3e55154371be8afa293dbd7716948d1431e/docs/milestone-tracker.md),
the retained [French station schema](../tests/test_data/fr_hubeau_temperature_openapi.json),
and the [Norwegian schema](../tests/test_data/no_nve_swagger.json).
[USGS field documentation](provider_ports/usgs_nwis.md) establishes the gross-field
unit, while [Brazil's field notes](provider_ports/br_ana.md) leave its area unit
unstated. Source vocabulary and packaged values establish the explicit
catchment/drainage fields for Bosnia, Canada, Japan, and South Africa.

See the [API reference](reference.md#drainage_areas) for the function contract.
