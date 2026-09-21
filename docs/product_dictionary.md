# Physical products and source series

Use physical filters to describe the observations you need. Product IDs identify
provider access routes in catalogues and returned rows. Do not parse an ID to infer
its physical meaning or use it to choose between separately published series.
The structured facts shown by `rr.series` describe that meaning.

## Physical facts

The public `quantity` vocabulary is `discharge`, `stage`, and `temperature`.
Supported output units are respectively `m3/s`, `m`, and `degC`. A series needs an
established source unit and a dimensionally valid conversion before numeric rows
can be returned. `source_unit` keeps the publisher's spelling; `unit` describes
the converted value.

The other physical filters can be known independently:

| Filter | Meaning |
| --- | --- |
| `frequency` | Established frequency, such as `daily` or `hourly`. |
| `statistic` | Published statistic, such as `mean`, `min`, `max`, or `instantaneous`. |
| `temporal_support` | Whether the value describes an `instant` or an `interval`. |
| `day_definition` | The source's definition of a daily period. |
| `timestamp_anchor` | What the time label identifies within that period. |
| `time_zone` | Established time-zone meaning. |
| `vertical_reference`, `vertical_datum` | Published reference for water levels. |

A known fact has a value and evidence. `source_silent` means the source does not
publish the fact; `not_established` means its meaning has not been established.
Neither unknown state matches an explicit physical filter. A midnight label does
not establish the day's boundaries. An update every ten minutes does not establish
a ten-minute average, and an instantaneous statistic does not establish an irregular
frequency.

## Inspect before narrowing

This offline example inspects a Swiss gauge. Its discharge quantity and unit are
established, but its temporal meaning is not. It is included in a broad discharge
selection, not a selection that requires daily means.

```python
import rivretrieve as rr

broad = rr.find(provider="ch_foen", station="2004", quantity="discharge")
facts = rr.series(broad)

daily = rr.pick(broad, frequency="daily", statistic="mean")
daily_facts = rr.series(daily)
```

The [usage guide](usage.md) shows retrieval and the returned values. The generated
[provider capabilities](reference.md#shipped-software-capabilities) list all enrolled
providers and their declared routes. The [API reference](reference.md#series)
explains the inspection columns.

## Reading product labels

The following labels summarize routes, not universal definitions overriding source
facts. The `PhysicalFacts` attached to a source series remain the precise account.

| Product label or family | Meaning and limits |
| --- | --- |
| `discharge_daily_mean`, `stage_daily_mean`, `water_temperature_daily_mean` | Source-published daily means, not means computed by RivRetrieve. Day definition and timestamp anchoring may still be unknown. |
| `discharge_hourly_mean`, `stage_hourly_mean`, `water_temperature_hourly_mean` | Established hourly means. Frequency does not establish the interval anchor. |
| `discharge_daily_min`, `discharge_daily_max`, `stage_daily_min`, `stage_daily_max` | Source-published daily extrema. A station need not expose every listed route. |
| `discharge_instantaneous`, `stage_instantaneous`, `water_temperature_instantaneous` | Instantaneous observations where established. Do not infer frequency from this suffix. |
| `discharge_reported`, `stage_reported`, `water_temperature_reported` | Reported values with source-specific facts; the suffix establishes no temporal support. |
| Japan's `stage_hourly`, `stage_daily`, `discharge_hourly`, `discharge_daily` | Frequency and quantity are known; statistic and interval anchor are not established. |
| Poland's `discharge_daily`, `stage_daily`, `water_temperature_daily` | Daily values; an archive-wide mean statistic is not established. |

## Separately published identities

Two series can have the same physical facts. Brazil's daily-mean discharge and
stage routes each retain Bruto (raw) and Consistido (quality-checked by ANA).
RivRetrieve returns both when they match, without selecting a preferred series.
USGS methods and Norwegian versions also retain their own published identities;
they are not a common quality classification.

`series_id` distinguishes a source series. `facts_id` identifies a physical-fact
segment within it. A source identity does not establish scientific
interchangeability, and provider-specific observation quality flags are not added
to harmonised rows. No unsupported product is calculated from other observations.

For implementation details, see [architecture](architecture.md) and the generated
[PhysicalFacts contract](reference.md#physicalfacts).
