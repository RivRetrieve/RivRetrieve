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

## Columns at a glance

The summary has one row per gauge and these columns, in this order.

| Column | Type | What it holds |
| --- | --- | --- |
| `provider_id` | `String` | The provider the gauge belongs to, such as `usgs_nwis`. |
| `station_id` | `String` | The station identifier. It stays a string so leading zeros survive. |
| `station_name` | `String` | The one distinct nonblank name the source supports. Null when there is none. |
| `latitude` | `Float64` | Latitude from the packaged station catalogue, unchanged. |
| `longitude` | `Float64` | Longitude from the packaged station catalogue, unchanged. |
| `crs` | `String` | The coordinate reference system of the coordinates, such as `EPSG:4269`. The text `unknown` when the catalogue does not state it. |
| `water_body_name_field` | `List(String)` | Native field names that hold a water-body name, such as `riverName`. |
| `water_body_name_value` | `List(String)` | The names themselves, in the same order as the field list. |
| `drainage_area_field` | `List(String)` | Native field names that hold a drainage area. |
| `drainage_area_value` | `List(String)` | The areas as JSON text. Decode each entry with `json.loads`. |
| `drainage_area_unit` | `List(String)` | The unit of each area, such as `km2` or `sq mi`. Null when unknown. |
| `elevation_field` | `List(String)` | Native field names that hold an elevation. |
| `elevation_value` | `List(String)` | The elevations as JSON text. Decode each entry with `json.loads`. |
| `elevation_unit` | `List(String)` | The unit of each elevation, such as `feet`. Null when unknown. |
| `elevation_datum` | `List(String)` | The published datum label or code of each elevation, such as `NAVD88`. Null when none is published. A blank source value stays blank. |

In each group of list columns, entry *i* of every list describes the same source
field. A gauge with no field for a group has null list cells. Each part below
explains these columns. `rr.metadata(selection, view="source")` returns a different
table with one row per source attribute, described in
[Inspect source attributes and scope](#inspect-source-attributes-and-scope).

## Read the station summary

`provider_id` and `station_id` identify each gauge. Station identifiers remain
strings, including leading zeros. `latitude`, `longitude` and `crs` come together
from the current packaged canonical station catalogue, independently of locations
saved in a selection. Unknown coordinates and CRS remain unknown.

`station_name` is the one distinct nonblank supported name, when one exists.
It is null when no nonblank name exists or several distinct nonblank names exist.
Use the source view to distinguish these cases. Equal names from separate fields
count as one name. Blank names do not populate this scalar, but remain in the
source view. Spelling, language and surrounding spaces are not normalised.

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
field with another field's value or unit. RivRetrieve does not say which area to use,
and the order of the list does not rank them. Select a particular field by its native
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
type. It does not turn numeric text into a number or interpret a placeholder as
missing data.

For Japan's `流域面積` and `零点高`, Bosnia's `metadata_CATCHMENT_SIZE`, and
Switzerland's `Catchment size` and `Station altitude`, the summary separates a
recognised numeric string from its explicit unit. It preserves numeric spelling,
including signs, trailing zeros and thousands separators. The unit remains in
its source spelling, such as `km2` or `km²`.

```python
japan = rr.find(provider="jp_mlit", station="301011281104010")
area = rr.metadata(japan).row(0, named=True)

print(area["drainage_area_value"], area["drainage_area_unit"])
# ['"142.00"'] ['km2']

numeric_text = json.loads(area["drainage_area_value"][0])
print(repr(numeric_text))
# '142.00'
```

Numeric text still needs user parsing for arithmetic. For example, a Japanese
value `1,719.00km2` becomes the JSON string `"1,719.00"`, not the number `1719.0`.
Blanks, nulls, placeholders and qualified text such as `T.P. +1.230 m` stay
unchanged. Japan and Bosnia receive a unit only when the individual value can be
separated unambiguously. Existing independently supported units remain attached
even when a value cannot be separated.

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

The Canadian station `05AA003` from the drainage-area example above has no water-body
name field, so its list cells are null:

```python
print(row["water_body_name_field"], row["water_body_name_value"])
# None None
```

The following Norwegian station has four drainage-area fields, but the source gives
null for all four. The fields and their unit are kept; only the values are null:

```python
missing_areas = rr.metadata(rr.pick(norway, station="16.28.0")).row(0, named=True)
print(missing_areas["drainage_area_field"])
# ['drainageBasinArea', 'drainageBasinAreaNorway', 'transferAreaIn', 'transferAreaOut']
print(missing_areas["drainage_area_value"])
# [None, None, None, None]
print(missing_areas["drainage_area_unit"])
# ['km2', 'km2', 'km2', 'km2']
```

The first case has null list cells. The second keeps the named entries and their
alignment. Neither case supplies a numeric area or establishes source silence.

## Interpret elevations

For USGS `alt_va`, the summary removes leading spaces, tabs and nonbreaking spaces
from complete numeric strings. Signs, decimal spelling and trailing zeros remain
unchanged. Nulls, blanks, placeholders and qualified or unrecognised text remain
unchanged. This rule does not apply to other fields.

```python
usgs = rr.find(provider="usgs_nwis", station="07374000")
elevation = rr.metadata(usgs).row(0, named=True)

print(elevation["elevation_field"], elevation["elevation_value"])
# ['alt_va'] ['"0.00"']
print(elevation["elevation_unit"], elevation["elevation_datum"])
# ['feet'] ['NAVD88']
print(repr(json.loads(elevation["elevation_value"][0])))
# '0.00'

source = rr.metadata(usgs, view="source").filter(pl.col("source_field") == "alt_va")
print(repr(json.loads(source["source_value"].item())))
# ' 0.00'
```

The decoded summary value remains a string. The source view retains its exact
padding and `String` dtype. Removing padding does not assess whether zero is
plausible or change the elevation's physical reference point, unit or datum.

The Swiss source publishes station altitude as a string that includes units.
The summary separates the numeric text from `m a.s.l.` and retains the supported
datum:

```python
swiss = rr.find(provider="ch_foen", station="2004")
altitude = rr.metadata(swiss).row(0, named=True)

print(altitude["elevation_field"])
# ['Station altitude']
print(altitude["elevation_value"])
# ['"432"']
print(altitude["elevation_unit"], altitude["elevation_datum"])
# ['m'] ['LN02']
print(json.loads(altitude["elevation_value"][0]))
# 432
```

Decoding restores the string `"432"`, not the number `432`. The source view still
returns `"432 m a.s.l."` when decoded. Separating this suffix does not change the
published datum association.

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
Source quantity values also retain their complete original text, including any
inline units and leading padding. For example, Japan's area above decodes to
`142.00km2` in the source view. Source and summary units agree entry by entry.

| Column | Meaning |
| --- | --- |
| `provider_id`, `station_id` | Gauge identity. |
| `source_field` | Exact native field name. |
| `source_scope` | Source context where needed to distinguish fields, otherwise null. |
| `source_value` | JSON scalar text, or null. Decode non-null cells with `json.loads`. |
| `source_dtype` | Native scalar type, such as `String` or `Float64`. |
| `source_unit` | Established unit, otherwise null. |
| `state` | Enum: `value`, `source_null` or `no_metadata`. |
| `attribute_role` | Enum: `station_name`, `water_body_name`, `drainage_area` or `elevation`. |
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
