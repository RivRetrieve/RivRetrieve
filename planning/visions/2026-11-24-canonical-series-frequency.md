# Canonical series frequency

A researcher looking for stage readings every four hours should be able to find INA's four-hourly product with `rr.find(frequency="PT4H")`. Today the query vocabulary has five entries. INA documents this cadence, but the catalogue leaves it unknown because the vocabulary cannot express it. Replace the allowlist with a `Frequency` domain type so any source-established cadence in the supported grammar can be inspected and selected without adding a core constant. Completing both parts of this vision completes [discussion #992](https://github.com/RivRetrieve/RivRetrieve/issues/992).

## The frequency contract

Use one parser for known provider frequencies and public frequency predicates. Both `rr.find()` and `rr.pick()` accept ISO 8601 duration strings in the subset below. Reject legacy aliases such as `daily`, Python and pandas timedelta objects, zero or negative durations, fractional spellings, and combinations across families. Accept positive durations with whole-number components that reduce exactly to a single unit within their family.

| Family | Example inputs | Canonical spelling |
| --- | --- | --- |
| Elapsed hours, minutes, seconds | `PT60M`, `PT1H` | `PT1H` |
| Elapsed hours, minutes, seconds | `PT1H30M`, `PT90M` | `PT90M` |
| Calendar weeks and days | `P7D`, `P1W` | `P1W` |
| Calendar weeks and days | `P1W2D`, `P9D` | `P9D` |
| Calendar years and months | `P12M`, `P1Y` | `P1Y` |
| Calendar years and months | `P1Y6M`, `P18M` | `P18M` |

Use the largest single unit in the family that represents the value exactly. Preserve the distinction between `P1D` and `PT24H`, `P1W` and `PT168H`, and `P1Y` and `P365D`. A weekly filter matches every starting weekday. A yearly filter matches every reporting-year start month. Frequency describes how often the series reports. Its value alone establishes neither the period summarized by an observation nor its timestamp anchor. Changes to `temporal_support` are outside this vision.

Canonicalize before matching or intersecting predicates and before computing a physical-fact record's content-derived `facts_id`. Equivalent frequency spellings must produce the same selection and, with all other facts and evidence equal, the same identifier. Serialize a known frequency using its canonical string wherever the frequency is exposed. Preserve the evidence and the distinct states for source silence and unestablished cadence. The concrete Python representation and any conversion helpers are implementation choices.

## Part 1 — Core engine and INA

Carry the type through physical facts, catalogue construction, query validation, selection, and inspection. Update the daily and monthly clipping checks to recognize their canonical calendar frequencies. Exercise the first review end to end with Argentina's INA catalogue:

- Four-hourly stage (`Hm4h`) is selectable with `PT4H` and retains its unknown statistic.
- Weekly mean stage (`Hms`) is selectable with `P1W` or `P7D` and retains its mean statistic.
- Variable-interval instantaneous readings retain their evidence state. Their observed timestamps do not establish a regular cadence.
- A known frequency copied from `rr.series()` works in either public filter and selects the same series under the same remaining constraints.

Use a second provider in this review if it exercises a materially different integration path. The INA guide describes the underlying products and the current vocabulary limitation. [INA series semantics](../../docs/providers/ar_ina.md)

## Part 2 — All providers and the release

Check every provider on the target branch. Migrate the remaining frequency declarations, shared catalogue transformations, and generated products that encode the old vocabulary. Preserve source-native product identifiers and evidence. Verify that each affected packaged catalogue agrees with its generator and that equivalent queries match the same products after loading from disk. Apply the repository's evidence requirements to changed source claims. [Verification evidence guide](../../docs/maintenance/evidence.md)

Carry canonical strings through inspection frames, packaged and exported catalogues, store and bundle metadata, and the station explorer's generated Python filters. Replacing a stored frequency such as `daily` with `P1D` changes the content-derived identifier used to join observations to facts. Bump the accumulated and compiled observation store formats and the export bundle format in the same release. Verify joins on newly written artifacts and the existing format-refusal behavior for retired versions.

Update public examples, provider documentation, generated reference tables and their generator to explain the grammar. Document the replacement spellings for existing filters and identify the stores and bundles users must rebuild or re-export.

Review the core and INA example first so that findings can inform the remaining migrations. Land both parts together on `main`. The release is complete when the same frequency copied from any published surface works as a filter across providers.
