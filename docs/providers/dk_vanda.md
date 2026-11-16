# Denmark: VandA

[Documentation index](../README.md) · [Usage](../usage.md)

| | |
|---|---|
| Provider | `dk_vanda` |
| Country | Denmark |
| Published by | Danmarks Miljøportal (the Danish Environmental Data Portal), through its VandA hydrometry service |
| Read from | VandA's public API (`vandah.miljoeportal.dk`) |
| Quantities | Discharge, water-level stage (a raw and a DVR90-corrected field) and water temperature |
| Stations in the catalogue | 1,565. Availability depends on station and quantity |
| Station metadata | Station name and drainage area. See [Fields by provider](../station-metadata.md#fields-by-provider) |
| Credentials | None |
| Terms | Creative Commons CC0 1.0 (no attribution required). See [Terms and citation](#terms-and-citation) |
| Agency documentation | [VandA Hydro-API wiki](https://github.com/danmarksmiljoeportal/VanDa/wiki/Hydro-API), [Swagger reference](https://vandah.miljoeportal.dk/api/swagger/index.html) |

RivRetrieve reads VandA's public API. Retrieve one week of discharge at station
`25003918`, Skjern Å at Gjaldbæk Bro:

```python
import rivretrieve as rr

selection = rr.find(provider="dk_vanda", station="25003918", quantity="discharge")

result = rr.fetch(selection, start="2026-11-08", end="2026-11-14T23:59:59", cache="bypass")

preview = result.data.select("time", "time_zone", "value", "unit").head(3)
print(preview.write_csv(), end="")

print(result.data.height)
print([(issue.severity, issue.code) for issue in result.issues])
```

Output:

```text
time,time_zone,value,unit
2026-11-08T00:00:00.000000,+00:00,17.2515,m3/s
2026-11-08T00:10:00.000000,+00:00,17.2126,m3/s
2026-11-08T00:20:00.000000,+00:00,17.2126,m3/s
881
[]
```

The request returned 881 readings in m³/s, about ten minutes apart, for the
seven-day window. The preview shows the first three. The empty issue list means
retrieval reported no problems; it does not establish the quality of the values.
`cache="bypass"` requests VandA's API rather than a local cache. This output was
checked live on 2026-11-15; published values can change, and VandA's native
reading interval is set per station, so a later retrieval or a different station
need not reproduce this exact spacing. See [Usage](../usage.md) for general
selection and result handling.

## Who measures, and who publishes

Danmarks Miljøportal (the Danish Environmental Data Portal) publishes VandA's
station registry and observations. Its own open-data catalogue record states
that this dataset is covered by Miljøportalens "dataansvarsaftale" (data-
responsibility agreement), specifically Annex 2, "Det rene overfladevand"
("clean surface water"). That agreement names the data owners ("Dataejer") as
"Kommunerne, Miljøstyrelsen": Denmark's municipalities and Miljøstyrelsen (the
Danish Environmental Protection Agency). Danmarks Miljøportal is the publisher
that distributes the data on the owners' behalf, not the measuring body itself.

VandA's own station registry additionally lists a station owner and a field
operator for each station (for example, station `25003918` lists Miljøstyrelsen
as owner and DCE, Aarhus University as operator). RivRetrieve's catalogue does
not currently surface these per-station fields.

Station coordinates are RivRetrieve's own reprojection of VandA's native
coordinates (ETRS89 / UTM zone 32N, EPSG:25832) to EPSG:4326. VandA does not
publish latitude and longitude directly.

## What you can retrieve

| Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit |
|---|---|---|---|---|---|
| `discharge` | Vandføring, `result` | Unknown | Unknown | l/s | m³/s |
| `stage` | Vandstand, `result` | Unknown | Unknown | cm | m |
| `stage` | Vandstand, DVR90-corrected, `resultElevationCorrected` | Unknown | Unknown | cm | m |
| `temperature` | Temperaturmåling, `result` | Unknown | Unknown | °C | °C |

RivRetrieve converts discharge from litres per second to cubic metres per second
and stage from centimetres to metres. Water temperature needs no conversion.
VandA publishes no named aggregation for any of these readings, so RivRetrieve
leaves frequency and statistic unknown rather than inferring one from the
reading interval.

Stage is published as two parallel fields for every reading: `result` and
`resultElevationCorrected`. Both describe the same measured water level; they
differ in vertical reference. `resultElevationCorrected` is stated, and
independently confirmed against VandA's own benchmark
("Kotemåling") readings at two stations, to be an elevation above sea level in
the DVR90 vertical datum (Dansk Vertikal Reference 1990, Denmark's national
height system). The raw `result` field is a reading relative to the station's
own local gauge zero; VandA does not state what that gauge zero is referenced
to, and this port found the full published field description and the
examination-type configuration both silent on a datum for it. Its relationship
to sea level, and whether its gauge zero is consistent across stations, are
unestablished by the source.

The catalogue holds 1,565 stations. A snapshot check of recorded availability
(2026-11-14) found numerical discharge values at 294 stations, stage at 1,373,
and water temperature at 66; the remaining stations are catalogued with unknown
availability for that quantity, not confirmed absent. A station being listed
does not guarantee data for every quantity or requested period.

## Series selection

Stage is the one quantity with more than one selectable series: `result` and
`resultElevationCorrected` are both returned under `quantity="stage"`, and
selecting one is required to interpret the vertical reference correctly.
Inspect the candidates before choosing, and select the corrected field
explicitly:

```python
stage = rr.find(provider="dk_vanda", station="25003918", quantity="stage")

candidates = rr.series(stage)
corrected = rr.pick(stage, variant="resultElevationCorrected")

result = rr.fetch(corrected, start="2026-11-14", end="2026-11-14T23:59:59", cache="bypass")
print(result.data.select("time", "value", "unit").head(2).write_csv(float_precision=3), end="")
```

Output:

```text
time,value,unit
2026-11-14T00:00:00.000000,4.335,m
2026-11-14T00:10:00.000000,4.336,m
```

The same station's raw `result` field for the same instants reads `0.626` m and
`0.627` m: a real difference of about 3.7 m, consistent with a fixed benchmark
offset between the station's local gauge zero and the DVR90 elevation, not a
measurement disagreement. Without `variant`, a stage selection covers both
fields; fetching without picking one returns rows for both (278 rows for the
one-day window above, 139 per field), distinguished by the `series_id` column
or by inspecting `candidates` above. See
[Series selection](../usage.md#when-an-agency-publishes-more-than-one-version)
in the usage guide for the general pattern.

## How far back, and how recent

VandA's historical depth is set per station and per quantity; RivRetrieve's
packaged catalogue does not record a first or last available date for
`dk_vanda`, so it cannot tell you a station's depth in advance. Depth varies
widely: this page's example station, `25003918`, has continuous discharge
telemetry back to 1975-01-01. Other stations have telemetry reaching back only
to 2023 or 2025, with no earlier continuous record under any examination type.
A request for a station and period with no published reading returns no rows
for that period; it does not establish that the station has no data at all.

To check a specific station's practical depth before requesting a long
historical window, query VandA's own station endpoint
(`GET https://vandah.miljoeportal.dk/api/stations?stationId=<id>`), which lists
each examination type's first and latest published result directly; this is a
plain, unauthenticated metadata lookup, not an observation request. A single
failed attempt at a genuinely old window is not conclusive either: a request
decades in the past occasionally times out or returns a server error on a
first attempt and succeeds on an immediate retry, which looks like a transient,
cold-query slowdown rather than missing data.

VandA separately tracks manual field gaugings (spot measurements, not a
continuous series) as their own examination type. Some stations with little or
no continuous telemetry history still have decades of field gaugings.
RivRetrieve does not catalogue or retrieve field gaugings as a product; only
continuous telemetry is available through `dk_vanda`.

## Time and data status

VandA publishes every timestamp as a UTC instant. RivRetrieve returns these in
`time`, paired with `time_zone="+00:00"`. Timestamps mark the measurement
instant; readings are point-in-time values, not a stated average over a period.

Water temperature readings can carry a non-null reason code (`reasonSc`) from
VandA's own vocabulary, paired with a free-text `reason`. RivRetrieve preserves
both verbatim in the `dk_vanda.temperature` annotation schema (`Int64` and
`String`, nullable); it does not interpret or rank the code, because VandA's
own published reason-code vocabulary states no textual meaning for any code.
Discharge and stage responses never carry this field.

```python
temp = rr.find(provider="dk_vanda", station="70000277", quantity="temperature")
result = rr.fetch(temp, start="2026-11-08", end="2026-11-08T23:59:59", cache="bypass")
print(rr.annotations(result).select("schema", "name", "dtype").rows())

annotated = result.to_polars(annotations=True)
print(annotated.select("value", "reasonSc", "reason").head(3).rows())
```

Output:

```text
[('dk_vanda.temperature', 'reasonSc', 'Int64'), ('dk_vanda.temperature', 'reason', 'String')]
[(8.3, None, None), (8.3, None, None), (8.2, None, None)]
```

This station and window happen to carry no non-null reason; the columns are
still present and nullable, so a flagged reading elsewhere carries the same
shape without changing it. Checked live on 2026-11-15.

Pass `annotations="reasonSc"` or `annotations=["reasonSc", "reason"]` to
`result.to_polars(...)` or `result.to_pandas(...)` when you only want specific
columns, or call `rr.annotations(result, schema="dk_vanda.temperature")` for
the native schema table. See
[Source annotations](../usage.md#source-annotations) for the general pattern.

A published null remains a row with `value=null`. A period with no published
reading supplies no row. A failed request remains an issue alongside any
successful records. Check [issues](../usage.md#issues) before interpreting an
empty result.

## Terms and citation

Danmarks Miljøportal's own dataset catalogue record states, in its structured
metadata (`dct:license`) and again on the dataset's landing page:

> Licens: Creative Common - CC0 1.0

CC0 1.0 (Creative Commons Zero) dedicates the data to the public domain and
does not require attribution. For traceability, this port's catalogue cites
the publisher as "Danmarks Miljøportal" and the data owners as the
municipalities and Miljøstyrelsen (the Danish Environmental Protection Agency),
matching the dataset's own data-responsibility agreement. Retrieval requires no
credentials.

Separately, Miljøportal's portal-wide terms of use ask that catalogue data
carry the generic sentence "Indeholder data, som benyttes i henhold til
vilkår for brug af danske offentlige data" ("Contains data used under the
terms of use for Danish public data"); it is not specific to this dataset,
and this dataset's own explicit, twice-stated CC0 marking takes precedence.

## Sources

Publisher pages checked on 2026-11-14 and 2026-11-15:

- [VandA Hydro-API wiki](https://github.com/danmarksmiljoeportal/VanDa/wiki/Hydro-API): API documentation.
- [VandA Swagger reference](https://vandah.miljoeportal.dk/api/swagger/index.html): endpoint and field definitions.
- Danmarks Miljøportal's dataset catalogue record (`datavejviser.dk`, JSON-LD, DCAT-AP): publisher, licence and the dataset's own data-responsibility statement.
- Danmarks Miljøportal's dataset landing page (`arealdata.miljoeportal.dk`): licence, data owners and the specific data-responsibility annex, confirmed by the maintainer directly in a browser.
- [Danmarks Miljøportal's terms of use](https://miljoeportal.dk/dataansvar/vilkaar-for-brug/): the portal-wide source-attribution sentence.
- VandA's live station endpoint (`GET /stations?stationId=...`): per-station, per-examination-type first and latest result dates.

The station counts describe the packaged catalogue. The examples were retrieved
live on 2026-11-15. The [private verification archive](https://github.com/RivRetrieve/verification-evidence#readme)
retains commands, source checks, exact output and the limits of these checks.
