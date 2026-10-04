# Station metadata

`rr.metadata(selection)` returns one row per selected gauge, with its station name,
canonical geometry, and source-supported water-body names, drainage areas and
elevations. It reads packaged files offline. It does not retrieve observations or
require archive credentials.

```python
import rivretrieve as rr

selection = rr.find(provider="ca_eccc", quantity="discharge")
metadata = rr.metadata(selection)
```

Selections can span providers. Selecting several series at one gauge does not
repeat its metadata row. Metadata remains available for catalogue-only gauges and
for gauges excluded from observation admission or map display. A listed station
or metadata value does not guarantee observations for a quantity or period.

## Read the station summary

`provider_id` and `station_id` identify each gauge. Station identifiers remain
strings, including leading zeros. `latitude`, `longitude` and `crs` come together
from the current packaged canonical station catalogue, independently of locations
saved in a selection. Unknown coordinates and CRS remain unknown.

`station_name` is the one distinct nonblank supported name, when one exists. If
several distinct nonblank names exist, it is null and `station_name_alternatives`
is true. Blank names do not populate this scalar, but remain in the source view.
Spelling, language and surrounding spaces are not normalised.

The other attributes use aligned lists:

| Role | Aligned columns | Value representation |
| --- | --- | --- |
| Water-body name | `water_body_name_field`, `water_body_name_value` | Native field names and ordinary name strings. |
| Drainage area | `drainage_area_field`, `drainage_area_value`, `drainage_area_unit` | Native field names, JSON scalar text and established units. |
| Elevation | `elevation_field`, `elevation_value`, `elevation_unit`, `elevation_datum` | Native field names, JSON scalar text, established units and published datum labels or codes. |

These columns have Polars `List(String)` dtype. Within a role, position *i* in each
list describes the same source field. List lengths agree. Fields sort by their
exact names, with source scope breaking ties. This order does not select a
preferred field.

Every exposed field remains in the lists. Equal values from different fields stay
separate. Empty strings, whitespace, source placeholders such as `ND`, and zeros
are preserved. A null value remains an entry beside its field name. Unknown units
and datums remain null beside the corresponding value.

If no field is exposed for a gauge and role, all of that role's list cells are
null. This differs from a list of named fields whose values are all null. Neither
case means zero or establishes that an agency publishes no metadata elsewhere.
Available fields depend on source meaning, retained evidence and publication
permission.

## Work with multiple fields

### Drainage areas

Area fields can describe different parts of a catchment. Norway's `transferAreaIn`
and `transferAreaOut` describe transferred catchment portions, not alternative
estimates of total drainage area. Keep these meanings separate.

Canada's effective and gross drainage areas remain separate. This station's two
values are numeric source scalars, stored as JSON text:

```python
import json
import polars as pl

canada = rr.find(provider="ca_eccc", station="05AA003", quantity="discharge")
summary = rr.metadata(canada)
row = summary.row(0, named=True)

print(row["drainage_area_field"])
# ['DRAINAGE_AREA_EFFECT', 'DRAINAGE_AREA_GROSS']
print(row["drainage_area_value"])
# ['1129.0', '1130.0']
print(row["drainage_area_unit"])
# ['km2', 'km2']
```

Explode a role's aligned columns together. Exploding them separately can pair a
field with another field's value or unit. Select a particular field by its native
name rather than taking the first entry:

```python
area_columns = ["drainage_area_field", "drainage_area_value", "drainage_area_unit"]
areas = summary.select("station_id", *area_columns).explode(area_columns)

for entry in areas.select(*area_columns).iter_rows():
    print(entry)
# ('DRAINAGE_AREA_EFFECT', '1129.0', 'km2')
# ('DRAINAGE_AREA_GROSS', '1130.0', 'km2')

gross = areas.filter(pl.col("drainage_area_field") == "DRAINAGE_AREA_GROSS")
print(json.loads(gross["drainage_area_value"].item()))
# 1130.0
```

Quantity values use JSON scalar text so that a number and a source string that
looks numeric remain distinguishable. `json.loads` restores that source scalar
type. It does not extract a number from a string containing units or interpret a
placeholder as missing data.

### Water-body names

Water-body names are already decoded strings. Norway's lake, reservoir and river
fields remain separate, including blanks and equal names. Selecting without a
quantity filter also includes gauges whose listed series are not discharge:

```python
norway = rr.find(provider="no_nve")
water = rr.metadata(rr.pick(norway, station=["1.198.0", "16.24.0"]))

for entry in water.select(
    "station_id", "water_body_name_field", "water_body_name_value"
).iter_rows():
    print(entry)
# ('1.198.0', ['lakeName', 'reservoirName', 'riverName'], ['', '', 'Riserelva'])
# ('16.24.0', ['lakeName', 'reservoirName', 'riverName'], ['Mår', 'MÅRVATN', 'Mår'])
```

`Mår` occurs twice because it belongs to two different fields. `MÅRVATN` retains
its source spelling. Blank names are not removed.

### Missing fields and source-null values

The Canadian station above has no exposed water-body name field. The following
Norwegian station has four exposed area fields, but all four values are null:

```python
print(row["water_body_name_field"], row["water_body_name_value"])
# None None

missing_areas = rr.metadata(rr.pick(norway, station="16.28.0")).row(0, named=True)
print(missing_areas["drainage_area_field"])
# ['drainageBasinArea', 'drainageBasinAreaNorway', 'transferAreaIn', 'transferAreaOut']
print(missing_areas["drainage_area_value"])
# [None, None, None, None]
```

The first case has null list cells. The second keeps the named entries and their
alignment. Neither case supplies a numeric area or establishes source silence.

## Interpret elevations

The Swiss source publishes station altitude as a string that includes units.
The summary retains that string's JSON encoding and the supported datum:

```python
swiss = rr.find(provider="ch_foen", station="2004")
altitude = rr.metadata(swiss).row(0, named=True)

print(altitude["elevation_field"])
# ['Station altitude']
print(altitude["elevation_value"])
# ['"432 m a.s.l."']
print(altitude["elevation_unit"], altitude["elevation_datum"])
# ['m'] ['LN02']
print(json.loads(altitude["elevation_value"][0]))
# 432 m a.s.l.
```

Decoding restores a string, not the number `432`. The separate unit and datum
columns do not change its source representation.

Elevations can describe different physical reference points. Station altitude
can locate the station, ground level can describe the ground surface, and gauge
zero is the reference level from which a gauge measures water level. The agency's
field definition determines the meaning. Some definitions remain broader, such
as USGS's gage/land-surface wording.

RivRetrieve preserves each field separately under one elevation role. It does not
choose a reference point, convert quantities, shift datums or remove implausible
values. A published datum code remains a code; it is not replaced by an expanded
label. A datum defined in source documentation can be attached without a separate
native datum field. A standalone water-level datum does not create an elevation
value.

Fields can refer to different source snapshots or physical points. Station
metadata does not establish which reference level applies to historical water-level
observations. Do not compute water-surface elevation by adding a water level to an
arbitrary elevation entry.

## Inspect source attributes and scope

`rr.metadata(selection, view="source")` returns the supported attributes behind
the summary. It keeps each field, its scalar type, its state and its support links.
It also distinguishes source contexts when the same field name appears in more
than one place. For example, Hub'Eau station and site records can both publish
`libelle_cours_eau`. Both values remain in the summary without renaming or merging
the fields; `source_scope` distinguishes them in the source view.

Use both the field name and its scope when the field name alone is ambiguous.
This selects the site's water-body name rather than the station's separate field:

```python
french = rr.find(provider="fr_hubeau", station="1011000101")
source = rr.metadata(french, view="source")
site_name = source.filter(
    (pl.col("source_scope") == "hydrometrie/referentiel/sites")
    & (pl.col("source_field") == "libelle_cours_eau")
)

print(json.loads(site_name["source_value"].item()))
# Grande Rivière à Goyaves
```

Unlike summary water-body names, source-view strings retain JSON encoding.

| Column | Meaning |
| --- | --- |
| `provider_id`, `station_id` | Gauge identity. |
| `attribute_role` | Enum: `station_name`, `water_body_name`, `drainage_area` or `elevation`. |
| `source_field` | Exact native field name. |
| `source_scope` | Source context where needed to distinguish fields, otherwise null. |
| `source_value` | JSON scalar text, or null. Decode non-null cells with `json.loads`. |
| `source_dtype` | Native scalar type, such as `String` or `Float64`. |
| `source_unit` | Established unit, otherwise null. |
| `state` | Enum: `value`, `source_null` or `no_metadata`. |
| `support_fact` | Stable fact name in the provider's packaged catalogue evidence. |
| `source_datum` | Published datum label or code as plain text, otherwise null. |
| `source_datum_field`, `source_datum_dtype` | Native datum field and type, when the datum comes from a native field. |
| `datum_support_fact` | Evidence for the datum's association with this elevation field. |

All columns except the two Enums have Polars String dtype. Datum codes retain
their native string or integer type through `source_datum_dtype`. A datum supplied
by a documented declaration has no native datum field or dtype.

- `value`: the field holds a non-null value, including a blank string.
- `source_null`: the field holds null. Its field name, dtype and established
  associations remain present.
- `no_metadata`: no field is exposed for this gauge and role. Source attributes
  and support links are null.

Every selected gauge has source rows for all four roles, including `no_metadata`
rows where needed. Empty selections retain their view's schema. Missing or invalid
packaged metadata raises an error rather than becoming an absence row.

## Data rights

Each provider's catalogue carries approved metadata and evidence. Support facts
connect values, definitions and datum associations to their adopted inputs without
exposing archived source bodies. Rebuilds require verified inputs and reviewed
mappings; see the [evidence guide](maintenance/evidence.md).

Packaged metadata remains subject to the source provider's terms. RivRetrieve's
MIT licence applies to its code. Follow the attribution and reuse conditions on
the [provider pages](README.md#providers). `rr.describe(provider)` reads the
packaged catalogue descriptor offline; metadata notices appear in its
`station_metadata` record set.

- [LHMT's terms](providers/lt_lhmt.md#terms-and-citation) require source attribution
  and apply CC BY-SA 4.0 unless stated otherwise. Adaptations must follow the licence's share-alike conditions.
- [MLIT's terms](providers/jp_mlit.md#terms-and-citation) explain PDL1.0 and its
  exceptions, citation with the consultation date, and notices for processing
  and the responsible party.

See the [API reference](reference.md#metadata) for the function contract.
