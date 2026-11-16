# NRFA series identity and physical meaning

Deliver evidence-backed, tested series definitions for the ten NRFA flow and
stage products. These definitions must preserve published identities and physical
meaning so later retrieval can use them without guessing or collapsing distinct
records.

This vision delivers [#595](https://github.com/RivRetrieve/RivRetrieve/issues/595).
Complete that issue only after implementing and verifying these definitions.
Publishing this document does not complete it. Provider coordination is
[#347](https://github.com/RivRetrieve/RivRetrieve/issues/347); shared UK context is
[#582](https://github.com/RivRetrieve/RivRetrieve/issues/582).

## Delivery boundary

Work on `port/uk-nrfa`. The existing offline catalogue remains available and
observation retrieval remains explicitly unavailable. This is a code-and-evidence
deliverable, not only a research report.

The scope is the current NRFA API publication of:

- `gdf` and `ndf`: gauged and naturalised daily flow;
- `gmf` and `nmf`: gauged and naturalised monthly flow;
- `gauging-flow` and `gauging-stage`: check-gauging products;
- `amax-flow` and `amax-stage`: annual-maximum products;
- `pot-flow` and `pot-stage`: peaks-over-threshold products.

Keep all ten distinct. Current publication means the archive served at retrieval
time, not real-time observations. Do not derive missing products, stitch records
to EA, or add rainfall, water temperature, numbered bulk releases or enquiry-only
records. Retrieval behavior belongs to #594, end-to-end integration to #590,
complete provider verification to #583 and user documentation to #593. Keep
interface documentation accurate within this change. Thiago's final approval in
#597 remains necessary before the provider merges into `main`.

## Establish source definitions

Use the existing separation between source identity and physical facts. Establish
quantity, native unit, statistic, frequency, time information and vertical
reference only where source evidence supports them. Preserve unknown facts with
the appropriate evidence state. Distinguish unfinished research from source
silence. Existing catalogue associations do not establish continuous records or
nonempty observations in a requested window; canonical catalogue bounds remain
unknown unless a separately justified change is required within this scope.

The catalogue currently supplies quantity and unit mappings: flow in m3/s and
stage in m. Verify response-specific definitions and exceptions rather than
assuming every response inherits every catalogue fact. Naturalised flow remains
distinct from gauged flow. Monthly products are published series, not instructions
to aggregate daily values locally.

AMAX flow is selected over an October–September water year. The selection period
is not the duration of the measurement. POT contains selected events above a
threshold, and check gaugings have their own measurement context. Source metadata
such as `PT15M`, `PT1S` or `Maximum` must not silently become an unsupported averaging
duration, regular sampling claim or independent maximum-stage selection rule.
Keep the source vocabulary available where it cannot safely become a canonical
physical fact.

## Time labels and filtering

Use the existing label-selection contract. Keep the label used to locate a value
separate from the interval that value describes. Do not introduce month-overlap
selection or compute a partial-month mean.

Genuine monthly responses use `YYYY-MM` labels and publish monthly mean metadata.
A documented nominal timestamp, such as the first day at midnight, can carry that
label through the current datetime-based engine while the original source month
string remains available. Such a convention does not establish a physical
interval start, an instantaneous measurement or clock precision published by the
source. Verify the chosen mapping through conversion, output, clipping and
serialization; keep source-backed physical facts independent of the carrier.

For that month-start convention, a January 1–31 request includes January's mean;
a January 15–31 request does not. Explain this behavior and preserve the original
month label. Do not adopt an unsupported UTC instant merely to fill the carrier.
The API documentation's UTC statement and the precision of individual labels
require separate consideration.

NRFA describes the ordinary daily water day as 09:00 to the following morning,
with calendar-day exceptions. Establish applicability before asserting a uniform
day definition. Peak documentation uses midnight for unknown times in some
contexts, but captured JSON midnight labels alone do not identify which events
have unknown time. Preserve labels; do not silently shift dates or classify every
midnight as unknown.

## Stage references

Preserve stage relative to the source gauge reference, with native units and
supported conversion. Unknown historical datum does not prevent retaining stage
in metres. Station altitude is not gauge zero and must not be added to stage to
manufacture absolute elevation.

Research dated datum applicability and the relationship between gauging, AMAX and
POT stage products. Preserve unresolved references rather than assuming a common
datum across products or historical periods. The combined AM file provides
context for paired stage/flow records; it does not by itself prove a universal
selection relationship for separate JSON products.

## Flags, missing values and rejection metadata

Use the shared annotation design delivered by
[#809](https://github.com/RivRetrieve/RivRetrieve/issues/809). Establish the
source fields, their types, meanings, applicability and supporting official
references needed by later parsing. Do not implement a provider-only annotation
mechanism or enable observation retrieval here.

Keep source flags, published nulls or missing markers, absent rows and failed
requests distinct. Do not rank quality, discard flagged values, turn rejection
periods into invented daily flags, or filter observations by source judgement.
Every shipped annotation definition needs a verified field description and
source reference, following the shared documentation contract.

Captured station-info metadata contains rejected AMAX year lists of integers and
rejected-period lists of strings, including null metadata. Existing typed series
annotations can preserve such lists. Establish which series they describe before
attaching them; do not copy station-level metadata indiscriminately to all ten
products. Preserve native year labels, period strings, relationships and
null/empty distinctions without inferring endpoint inclusivity or year encoding.
A whole published metadata snapshot must not be mistaken for a request-window
excerpt when designing later refresh behavior.

Official documentation distinguishes rejection of an AMAX water year from
rejection of POTs during an unrepresentative period. Incomplete records and
rejected records are not interchangeable. Keep source decisions, not a locally
recreated rejection algorithm. Exact API field applicability, year encoding and
period endpoint semantics remain research questions; they are not demonstrated
engine limitations.

## Evidence and verification

Follow the [provider-port guide](../../docs/maintenance/provider-ports.md),
[testing guide](../../docs/maintenance/testing.md) and
[evidence guide](../../docs/maintenance/evidence.md). Continue the existing
[private NRFA research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/nrfa-source-access.md).
Keep original responses, correspondence and detailed evidence private.

Discovery on 16 November 2026 obtained bounded monthly, daily, peak and rejection
metadata examples. These new captures were local private originals with receipts,
not admitted archive collections or source certification. Locate and admit them
through the established archive process if available; otherwise make a new
bounded acquisition under its own identity. Do not claim that private storage or
synthetic checks replace retained-source verification. The sampled daily values
were unflagged; a genuine flag-bearing observation remains outstanding.

At main revision `acfb68dad2c8b13553bc5731b51356fde43defc6`, 180 existing narrow
source-independent tests passed during discovery. Additional synthetic checks
preserved nominal month labels and original strings through public output and
bundles, and native series lists through output, bundles, offline store reuse and
selection narrowing. These were separate diagnostic paths, not an integrated
NRFA adapter. They establish feasibility, not source meaning. Fully clipped
observation annotations currently lose their schema, so explicit annotation-name
selection can raise on an empty result; account for existing behavior rather
than assuming empty results retain every annotation column.

The port was catalogue-only at `93b4cbd823e20ad376e0143f4faad20b425542f2` during
discovery and predates the shared annotation work. Reconcile the necessary shared
contracts on the port branch before relying on them. Do not treat its older
checkout as evidence that current `main` lacks a capability, and do not merge the
provider into `main` as part of this work.

Completion requires:

- Reusable, tested definitions covering all ten product identities, with supported
  physical facts and explicit unknowns.
- Source-backed mappings and genuine examples sufficient to defend adopted
  claims, including flag and missing-value handling where definitions are adopted.
- Focused tests that detect identity collapse, unsupported physical inference,
  loss of source labels or annotations, and confusion between stage and altitude.
  Extend existing shared contracts instead of building another framework.
- Relevant source-independent checks and required genuine-source checks completed
  against reviewed revisions, with unresolved limitations recorded honestly.
- Offline catalogue behavior preserved and observation retrieval still unavailable.

If required evidence cannot be obtained, report the affected definition as
blocked rather than fabricate a fact or silently reduce the ten-product scope.
Unknown optional physical facts can remain unknown where the contracts support
them. A blocked required definition prevents claiming full completion.

## Shared-engine changes require demonstrated need

Build with the current design first. The absence of a specialized month type or
interval table is not proof of a limitation. If a required behavior cannot be
preserved, identify a genuine source example, demonstrate the failure against
the current shared contracts, and explain why existing representations do not
suffice. Flag that result and open a dedicated issue before treating redesign as
part of the NRFA work. No shared-engine limitation was established during this
discussion.

Leave module layout and other reversible implementation details to the implementing
agent. This vision authorizes the definitions work when implementation is
explicitly invoked; publication alone does not start it.
