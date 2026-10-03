# Station metadata

`metadata` returns a station table or the source attributes behind it. Both views
read packaged files offline. They accept selections spanning providers and do not
retrieve observations or require archive credentials.

```python
import rivretrieve as rr

selection = rr.find(provider="ca_eccc", quantity="discharge")

stations = rr.metadata(selection)
print(stations)

source = rr.metadata(selection, view="source")
print(source)
```

## Station table

The default view has one row per selected gauge. `provider_id` and `station_id`
identify the gauge; station identifiers remain strings, including leading zeros.
Selecting several series for a gauge does not repeat its row.

`station_name` and `river_name` contain verbatim source-supported names. A name
appears only when there is exactly one distinct nonblank name for that role.
Whitespace-only strings remain in the source view but do not populate the summary.
Different spellings, languages and surrounding spaces are not normalised. If more
than one distinct nonblank name exists, the summary name is null and
`station_name_alternatives` or `river_name_alternatives` is true. These Boolean
columns distinguish alternatives from a role with no usable name.

`latitude`, `longitude` and `crs` preserve geometry from the current packaged
canonical station catalogue together, independently of locations saved in a selection.
Unknown coordinates or CRS stay unknown. RivRetrieve does not infer a CRS from a
map display. Geometry is limited to the selected gauges. Metadata remains
available when observation admission or map eligibility excludes a gauge.

Names require a reviewed source mapping and permission to publish them. A missing
name does not establish that the agency publishes none. RivRetrieve does not
extract a river from a station label or substitute a basin name.

## Source attributes

The source view preserves each supported attribute separately. Drainage-area
fields appear here rather than as one apparently standard area in the summary.

| Column | Meaning |
| --- | --- |
| `provider_id`, `station_id` | Gauge identity. |
| `attribute_role` | Enum: `station_name`, `river_name`, or `drainage_area`. |
| `source_field` | Exact native field name. |
| `source_value` | JSON scalar text, or null. Decode non-null cells with `json.loads`. |
| `source_dtype` | Native dtype. |
| `source_unit` | An already established unit, otherwise null. |
| `state` | Enum: `value`, `source_null`, or `no_metadata`. |
| `support_fact` | Stable fact name in the provider's packaged catalogue evidence, otherwise null for `no_metadata`. |

All columns except the two Enums have Polars String dtype. Rows sort by provider,
station, role, source field, source value and support fact. JSON encoding retains
the original scalar type:

```python
import json

areas = source.filter(source["attribute_role"] == "drainage_area")
values = [json.loads(value) for value in areas["source_value"] if value is not None]
```

A string such as `633.00 km²` decodes to that exact string. Blank strings, inline
units and numeric values are preserved. Distinct area meanings stay separate.
RivRetrieve does not choose a preferred area, infer a unit or convert these values.

- `value`: the field holds a non-null value, including a blank string.
- `source_null`: the field holds null. Its field name, dtype, established unit
  and support fact remain in the row.
- `no_metadata`: no field is exposed for this gauge and role. The four source
  columns and support fact are null.

Neither absence means zero or establishes that an agency publishes no metadata
elsewhere. Each selected gauge has source rows for all three roles, including
explicit `no_metadata` rows where needed. Empty selections retain their view's
schema. Metadata does not establish that observations exist for a requested period.

## Packaged evidence

Each provider's catalogue carries `station_metadata.parquet` beside its evidence.
The projection contains approved fields, not complete native tables. Stable support
fact names connect source values to catalogue evidence without exposing archived
source bodies. Rebuilds require explicit verified inputs and reviewed mappings;
see the [evidence guide](maintenance/evidence.md). Missing or invalid packaged
metadata raises an error rather than becoming an absence row.

See the [API reference](reference.md#metadata) for the function contract.
