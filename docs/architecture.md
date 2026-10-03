# Architecture

RivRetrieve gives river-gauge observations a common access path while preserving
what their publishers establish. It harmonises identity, units and established
physical representations. Scientific quality, the meaning of source quality codes
and suitability for a study remain outside that responsibility. Matching quantities
and units alone do not establish scientific comparability.

The [usage guide](usage.md) explains selection and retrieval. The
[API reference](reference.md) specifies individual interfaces.

## Physical facts and published identity

Quantity, frequency, statistic, temporal support and vertical reference are separate
facts. Establishing discharge and its unit does not establish a daily mean or a time
zone. Admission requires a known quantity, source unit and dimensionally valid
conversion; other facts can remain unknown. This permits useful retrieval without
inventing meaning. An explicit physical predicate matches only established matching
facts.

Published identity is separate from physical description. Several source series can
share the same physical facts. RivRetrieve preserves each matching supported identity
rather than choosing a preferred series or inferring a quality ranking. Physical-fact
segments describe changes or distinctions within a series without losing its identity.

Discovery reads packaged catalogues offline. A selection records physical constraints,
source-identity restrictions and acquired catalogue evidence. An unrestricted selection
retains the intent to include all matches, including identities discovered during
retrieval. The packaged snapshot therefore supports discovery without claiming an
exhaustive historical inventory.

## Shared engine and source responsibilities

Public composition resolves configuration, credentials, paths and resources. Lower-level
operations receive the dependencies they need. This keeps application state out of
parsing and physical conversion.

Providers declare source facts and implement source-specific access. An explicit
provider manifest distinguishes live services, compiled bulk sources and catalogue-only
sources. Live providers fetch bytes and parse native rows. Bulk providers download and
compile publisher artifacts for the shared store reader. Catalogue-only providers
support discovery and refuse observation retrieval.

The shared engine owns request planning, window arithmetic, unit conversion, clipping
and assembly. Providers consume its rendered request bounds without shifting them.
Keeping these operations shared prevents providers from developing incompatible
interpretations of the same request.

The stages preserve distinct responsibilities:

- **Fetch** supplies immutable bytes and their source-call origins.
- **Parse** establishes native rows, series definitions, scoped inventories, outcomes
  and issues from source responses.
- **Convert** validates rows, applies declared unit conversions and clips to the
  requested window.
- **Assemble** combines observations with the information needed to interpret and
  trace them, including outcomes without rows.

Typed contracts and runtime validation check the boundaries between these stages.
A fetch window must contain its requested window; converted rows must remain within
the requested bounds. Contract violations raise because invalid stage output cannot
form a valid result.

## Time and incomplete results

Native wall-clock timestamps travel with their established time-zone information.
Unknown zones remain unknown. A midnight label does not establish daily temporal
support, and coordinates do not establish a station's time zone. Daily calendar
clipping and timestamp clipping follow the established physical facts. Conversion to
UTC is a separate operation with its own information requirements.

A null value, an absent row, a successful empty answer and a failed request carry
different meanings. Outcomes retain the requested scope and reason even when no
concrete series identity can be established. Source failures remain attached to partial
results so independent series and independently exhaustive intervals can still return.
Caller issue policy controls reporting, not classification or retention. Provider-defined
empty responses wholly within request padding can remain in provenance without a
requested-data warning; other failures remain diagnostic.

Results retain one provider identity, license and citation. Multi-provider retrieval
returns separate results because station identifiers can overlap and source terms must
remain attributable.

## Native storage and traceability

Stores retain native values and native wall-clock labels. Live retrieval and store
reads use the same conversion stage, which avoids double conversion and keeps physical
interpretation consistent. Compiled stores preserve declared source columns and value
states from publisher artifacts. Accumulated stores retain parsed observations and the
evidence needed to decide whether a later request can reuse them.

Reuse requires both knowledge of the matching series and successful interval coverage.
The decision is made per station and access route. An uncovered route is reacquired
while another can be served locally. Coverage is separate from observation density:
a successful empty answer can cover an interval, while a rolling snapshot can establish
only the rows it contains. Failed reacquisition retains held successful observations at
their original retrieval time alongside the new diagnostics. Storage details, revisions
and replacement rules belong to the [observation-store contract](design/observation-store-layout.md).

Provenance identifies source calls independently of optional receipt retention.
Publisher receipts preserve bytes at the parse boundary. Store-excerpt receipts encode
selected stored rows and cannot reconstruct discarded publisher content. This distinction
makes the available evidence explicit without promising reproducibility from a checksum
or URL alone. Credential transport restricts supplied secrets to declared source origins;
receipt origins exclude request headers.

## Catalogue evidence and station metadata

Catalogue builds check canonical columns against declared origins and acquisition evidence.
Canonical station columns describe identity and geometry, not harmonised names, river labels, or quality judgements.
Native tables are verified archive inputs supplied to catalogue builds. They are not a public wheel API.
`metadata` reads a packaged projection of approved station names, river names and
drainage-area fields at provider-station grain. Its summary preserves canonical
geometry and shows unresolved name alternatives. Its source view preserves source
vocabulary, exact scalar values, null and no-metadata states, and stable support
fact references. See [station metadata](station-metadata.md) for interpretation.
`describe` reads the packaged Croissant descriptor offline.
The current evidence representation uses a typed header and five normalized relations, with explicit resolution of individual fact lineage.

## Evidence and verification

Source-independent tests check shared contracts and failure behavior. Source-backed
tests replay genuine inputs through the transport boundary and refuse unmatched
requests. These checks establish behavior against retained evidence, not current
service availability. The [testing guide](maintenance/testing.md) explains the test
strategy; the [evidence guide](maintenance/evidence.md) governs genuine-input checks.
