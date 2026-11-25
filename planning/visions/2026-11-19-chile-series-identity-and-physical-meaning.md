# Chile series identity and physical meaning

Establish defensible source identities and physical facts for the two selected
DGA historical discharge products. Users must be able to distinguish the products
without receiving unsupported claims about daily averaging, time zones or source
quality.

This is Step 3, [issue #740](https://github.com/RivRetrieve/RivRetrieve/issues/740),
of [Chile Program #734](https://github.com/RivRetrieve/RivRetrieve/issues/734).
Executing and verifying this vision completes #740 only. Publishing this document
leaves the issue open and does not deliver the provider integration.
Work remains on `port/cl-dga`; merging the completed port to `main` requires the
Program's final review by @thiagovmdon.

## Established scope

Use the direct DGA historical national exports at `https://mapas2.mop.gob.cl/`:
`caudal_diario_historico.zip` and `caudal_medio_mensual_historico.zip`.
Step 1 selected these for eventual `BulkStore` access. Step 2 delivered their
offline catalogue through #909. The inspected 784-station count describes a
snapshot, not an invariant for future publications.

Preserve these separate products and source identities:

| Product | Published value field | Quantity and native unit | Established frequency and statistic |
| --- | --- | --- | --- |
| `discharge_daily` | `Caudal_diario` | discharge, `m3/s` | daily; statistic unknown |
| `discharge_monthly_mean` | `Caudal_Medio_mensual` | discharge, `m3/s` | monthly; mean |

Daily `statistic`, `temporal_support`, `time_zone` and `day_definition` remain
unknown (`not_established`) unless source evidence establishes them for this
export. Monthly mean terminology does not itself establish exact temporal
support, time zone or timestamp anchor. Keep each fact independent and preserve
unestablished facts as unknown. Neither CR2's daily-mean description nor another
DGA interface's instantaneous indicator defines these exports.

Preserve genuine zero discharge separately from missing values and absent dates
or months. Do not fill gaps, invent values, collapse separate series or interpret
unpublished quality/status as approved or provisional. Preserve source statuses
if established; do not rank them or infer them from numeric values.

## Work and evidence

Follow Step 3 of `docs/maintenance/provider-ports.md`. Continue the private record
`research/cl-dga-source-access.md` in
[RivRetrieve/verification-evidence](https://github.com/RivRetrieve/verification-evidence)
rather than creating a parallel research history. Earlier findings are leads and
handoffs, not a substitute for the applicable source checks.

- Verify quantity, units, product identities and station-to-series distinctions
  against genuine source inputs. Look for parallel records and real exceptions
  to proposed mappings, including conflicting identities or units.
- Establish the native time fields, including monthly `Año`/`Mes`, and distinguish
  source date or month labels from observation instants. Document a faithful
  representation and any shared-engine limitation without assigning an invented
  time zone, day boundary or averaging interval. Do not claim a synthetic
  timestamp anchor is a source fact.
- Check missing-value encodings, zero values, exceptional numeric values,
  duplicate records and any published row statuses. An inspected snapshot with
  no negative or empty values does not define a universal missing-value rule.
- Make a targeted search for stronger official documentation about unresolved
  semantics. Record what was checked and which claims remain unknown. An agency
  answer is not a prerequisite where the library can represent the uncertainty
  honestly. Obtain authorization before sending correspondence.

If quantity, unit or valid conversion cannot be established for an affected
series, expose that limitation rather than admit guessed physical facts.
Distinguish missing source knowledge from a shared-engine representation gap;
report any gap that prevents faithful representation for the later integration.

## Build on the existing definitions

`src/rivretrieve/_internal/providers/cl_dga/series.py` already defines both products
through `SeriesMapping`, with separate namespaces
`cl_dga.mapas2.caudal_diario` and `cl_dga.mapas2.caudal_medio_mensual`. Preserve the actual existing namespaces and
published IDs unless evidence requires a correction.
`catalogue_series.py` uses these definitions for catalogue descriptions.

Use `provider_series.py` and `source_series.py` as the shared contracts for
`SourceIdentity`, `PhysicalFacts`, admission and physical filters. Established
discharge and `m3/s` permit numeric admission even when temporal facts are unknown.
Unknown facts must not satisfy filters requiring known values. Extend or correct
the existing definitions only where this investigation requires it; do not
introduce another source of truth or change production code solely to create a
deliverable. Date/month label representation is an evidence-backed handoff here;
full acquisition and observation compilation belong to later steps.

## Completion evidence and boundaries

Completion requires supported mappings for both products, a record of checked
exceptions and explicit unresolved facts, and a clear handoff for native time
labels and value/status handling. Keep catalogue descriptions and any changed
mapping definitions consistent. Explain what later parsing must preserve.

Follow `docs/maintenance/evidence.md` and the private archive's current intake and
verification process. Retain original inputs and supporting references privately.
Review exact code revisions before running against private evidence. Run the
applicable full checks when governing claims, source bindings, verifiers or
collections change. Missing mandatory evidence is a blocker; synthetic tests or
research prose cannot replace it. For changed library behavior, use focused
test-first coverage and run affected source-independent checks with `uv` according
to `docs/maintenance/testing.md`. Report what each check establishes and any limits.

Acquisition rules, streaming, download failures and date-window retrieval behavior
remain in #735. Full `BulkStore` integration remains in #741. The complete provider
verification and mandatory ten-basin CAMELS-CL comparison remain in #742; full
user-facing provider documentation remains in #737. This step neither expands to
operational telemetry, stage or temperature nor adopts CR2 conventions such as
`minFrac` or midnight UTC.

Preserve the Step 2 rights correction: software MIT licensing does not relicense
provider data or packaged metadata. Keep DGA/MOP attribution and source terms,
with `license = None` while a dataset-specific licence is unestablished. Do not
publish controlled material in code, issues, logs or artifacts. Source permission
is not established by maintainer approval.
