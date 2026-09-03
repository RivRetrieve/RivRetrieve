# RivRetrieve Product Dictionary

This file is the authoritative dictionary of canonical RivRetrieve product IDs. [ADR 0010](adr/0010-a-declaration-is-keyed-by-product.md) defines how provider declarations are keyed to products.

Product IDs are stable user-facing labels. They are not parseable mini-grammars. Code must rely on the structured fields in each entry.

Providers may use a canonical product ID only when their native product matches the entry closely enough. If a native product does not fit, the provider should expose a provider-specific product ID and document the semantics in provider product metadata.

## Entry Fields

Each canonical product entry defines:

```text
product_id
observed_property
frequency
statistic
period_type
period_anchor
unit
derived
derivation_method
description
notes
```

Initial V1 canonical observed properties:

```text
discharge
stage
water_temperature
```

Precipitation, catchment rainfall, meteorological variables, and non-river products are out of V1 canonical scope. Provider ports may propose future additions when concrete provider evidence justifies expanding the vocabulary.

Initial V1 semantic vocabulary:

```text
frequency:      irregular | 5min | 10min | 15min | 30min | hourly | daily | monthly | annual | provider_defined | unknown
statistic:      instantaneous | mean | sum | min | max | provider_defined | unknown
period_type:    instant | interval | unknown
period_anchor:  instant | start | end | midpoint | provider_defined | unknown
```

Use `unknown` when source temporal support is not established. This value corresponds to `UnknownTemporalSupport` in the shared observation engine and prevents providers from claiming instant or interval support without evidence.

## Canonical Products

### discharge_instantaneous

```text
observed_property: discharge
frequency: irregular
statistic: instantaneous
period_type: instant
period_anchor: instant
unit: m3/s
derived: false
derivation_method: none
description: Instantaneous or irregular discharge observations in cubic meters per second.
notes: Provider quality, provisional status, and source API belong in annotations or provenance, not in the product ID.
```

### discharge_daily_mean

```text
observed_property: discharge
frequency: daily
statistic: mean
period_type: interval
period_anchor: start | end | midpoint | provider_defined
unit: m3/s
derived: false
derivation_method: none
description: Daily mean discharge in cubic meters per second.
notes: The provider must document period anchoring when known. A provider-native daily mean and a RivRetrieve-derived daily mean are different products unless derivation semantics are explicitly defined.
```

### discharge_hourly_mean

```text
observed_property: discharge
frequency: hourly
statistic: mean
period_type: interval
period_anchor: start | end | midpoint | provider_defined | unknown
unit: m3/s
derived: false
derivation_method: none
description: Hourly mean discharge in cubic meters per second.
notes: The source interval anchoring must remain unknown when the publisher does not establish it.
```

### discharge_daily_min

```text
observed_property: discharge
frequency: daily
statistic: min
period_type: interval
period_anchor: start | end | midpoint | provider_defined
unit: m3/s
derived: false
derivation_method: none
description: Daily minimum discharge in cubic meters per second.
notes: Use only when the native product is a daily minimum over a defined daily period.
```

### discharge_daily_max

```text
observed_property: discharge
frequency: daily
statistic: max
period_type: interval
period_anchor: start | end | midpoint | provider_defined
unit: m3/s
derived: false
derivation_method: none
description: Daily maximum discharge in cubic meters per second.
notes: Use only when the native product is a daily maximum over a defined daily period.
```

### stage_instantaneous

```text
observed_property: stage
frequency: irregular
statistic: instantaneous
period_type: instant
period_anchor: instant
unit: m
derived: false
derivation_method: none
description: Instantaneous or irregular water level/stage observations in meters.
notes: Provider datum, gauge reference, or source-specific level semantics must be preserved in product metadata or annotations where available.
```

### stage_daily_mean

```text
observed_property: stage
frequency: daily
statistic: mean
period_type: interval
period_anchor: start | end | midpoint | provider_defined
unit: m
derived: false
derivation_method: none
description: Daily mean water level/stage in meters.
notes: Provider datum or reference-level semantics must not be hidden.
```

### stage_hourly_mean

```text
observed_property: stage
frequency: hourly
statistic: mean
period_type: interval
period_anchor: start | end | midpoint | provider_defined | unknown
unit: m
derived: false
derivation_method: none
description: Hourly mean water level/stage in meters.
notes: The source interval anchoring must remain unknown when the publisher does not establish it.
```

### stage_daily_min

```text
observed_property: stage
frequency: daily
statistic: min
period_type: interval
period_anchor: start | end | midpoint | provider_defined
unit: m
derived: false
derivation_method: none
description: Daily minimum water level/stage in meters.
notes: Use only when the native product is a daily minimum over a defined daily period.
```

### stage_daily_max

```text
observed_property: stage
frequency: daily
statistic: max
period_type: interval
period_anchor: start | end | midpoint | provider_defined
unit: m
derived: false
derivation_method: none
description: Daily maximum water level/stage in meters.
notes: Use only when the native product is a daily maximum over a defined daily period.
```

### water_temperature_instantaneous

```text
observed_property: water_temperature
frequency: irregular
statistic: instantaneous
period_type: instant
period_anchor: instant
unit: degC
derived: false
derivation_method: none
description: Instantaneous or irregular water temperature observations in degrees Celsius.
notes: Sensor depth or measurement context should be preserved in provider metadata or annotations when available.
```

### water_temperature_daily_mean

```text
observed_property: water_temperature
frequency: daily
statistic: mean
period_type: interval
period_anchor: start | end | midpoint | provider_defined
unit: degC
derived: false
derivation_method: none
description: Daily mean water temperature in degrees Celsius.
notes: Use only when the native product is a daily mean over a defined daily period.
```

### water_temperature_hourly_mean

```text
observed_property: water_temperature
frequency: hourly
statistic: mean
period_type: interval
period_anchor: start | end | midpoint | provider_defined | unknown
unit: degC
derived: false
derivation_method: none
description: Hourly mean water temperature in degrees Celsius.
notes: The source interval anchoring must remain unknown when the publisher does not establish it. Added for the no_nve port: NVE HydAPI publishes a water-temperature series at resolution 60 whose method is Mean.
```

## Provider-specific products

### jp_mlit: stage_hourly, stage_daily, discharge_hourly, discharge_daily

```text
provider: jp_mlit
observed_property: stage | discharge
frequency: hourly | daily
statistic: unknown
period_type: interval
period_anchor: unknown
unit: m | m3/s
derived: false
derivation_method: none
description: MLIT KIND 2/3/6/7 observations whose source tables establish cadence and quantity but not a mean statistic or interval anchor.
notes: These IDs must not be replaced by the canonical *_mean products without new publisher evidence.
```

## Proposed Changes

Provider ports may propose additions or revisions here when a native product does not match the existing dictionary. Additions should include the full entry fields and a short note about which provider forced the addition.
