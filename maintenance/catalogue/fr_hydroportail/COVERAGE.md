# HydroPortail catalogue scope

The catalogue uses HydroPortail's anonymously published native station inventory.
It does not represent an unrestricted PHyC census. Acquisition includes active,
closed and test entities with all site types published by the search form.
The form's defaults do not define the catalogue population.

## Station identity

Use each full station identifier and the station/site relationship published by
HydroPortail. Do not truncate station identifiers to infer site identifiers or
copy Hub’Eau metadata into missing HydroPortail records. Each publication service
keeps its own acquired inventory and source coordinates.

A station missing from a search response or returning HTTP404 does not establish
station nonexistence, deletion, reuse rights or absence of historical measurements.
Keep source failures distinct from successful empty observation responses. Later
access failures must not rewrite earlier observations or receipts.

## Availability

Catalogue membership alone leaves observation history unknown. Historical
availability comes only from a witness with the same publication service, station,
quantity, selector, request bounds and acquisition date. Hub’Eau count evidence
cannot establish HydroPortail access.

The historical HydroPortail witnesses apply to `raw`. The other supported selectors
remain discoverable without inheriting those raw-history claims. A positive witness
for a bounded request does not establish continuity or whole-history availability.

## Retained verification

The dated population comparisons, native identity-page results, bounded observation
probes and acquisition reports are preserved in the private
[source archive](../../../docs/maintenance/evidence.md). They retain their original
repository-relative identities, including the historical `COVERAGE.md` account.
They are acquisition records, not fixed population requirements for later captures.

See [catalogue maintenance](README.md) to rebuild from exact external inputs or
reproduce a retained reconciliation. Review any new source capture separately
before adopting its station population.
