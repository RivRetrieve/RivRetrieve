# Mapped live-provider evidence and conformance

This account covers the enrolled MLIT, CHMI, LHMT and ThaiWater routes. The source
recordings are unchanged. Negative derivatives in tests are labelled as such and
are not evidence that an unrecorded response exists.

## Published facts and access limits

| Source | Established facts | Unknowns and scope |
|---|---|---|
| MLIT KIND 2/3/6/7 | Exact HTML titles/units and DAT labels establish stage m or discharge m³/s and hourly/daily labels. | Statistic, interval support, interval anchor, day definition, zone and vertical reference remain unknown. `KAWABOU=NO` is retained exactly; its meaning/effect is not established. |
| CHMI DQ: HD/QD/TD; HQ: HH/QH | The exact `meta2.json` dictionary defines all five as means with CM/cm, M3_S/m³/s, or 0C/°C. Recorded timestamps explicitly carry Z. | Interval anchoring, day definition and vertical reference are unknown. Repeated enrolled codes have no established block identity; they return identified unsupported outcomes without selecting a block. |
| LHMT historical waterLevel/waterDischarge | Full API documentation defines daily means in cm/m³/s and UTC dates. | Exact day definition, interval anchor and stage reference remain unknown. Measured observations use another route, fields and timestamp semantics; they are not enrolled as alternatives. |
| ThaiWater tele_waterlevel value/discharge | Official application binds the route to stage m MSL and discharge m³/s. Stage has a published above-sea-level reference. | No named vertical datum, temporal support or source zone is established. Canal inside/outside fields and forecasts are different routes, not enrolled alternatives. |

MLIT evidence: `tests/test_data/jp_mlit_*_2023_{html,dat}.recording.json`, eight
exact responses acquired on 2026-09-02. The terms capture
`jp_mlit_terms_licence_euc_jp.html` describes tentative/final **cells**, not
coexisting method series. A present endpoint check returned an explicit access
restriction against acquisition using tools. No further automated acquisition
was attempted. This access limit prevents resolving `KAWABOU` here; it is not
classified as harmless or exhaustive.

CHMI evidence: `tests/test_data/cz_meta2.json`, publisher
<https://opendata.chmi.cz/hydrology/historical/metadata/meta2.json>, acquired
2026-09-02T14:47:26.717737Z, SHA-256
`b72883dbaa8407b4a514ae4aeec807350222b67298da16a089ed6299d553fafc`.
The retained code-definition PDF defines TSCON_ID as an indicator of the
hydrological quantity. Annual recordings have HD/QD/TD once with 365 cells each,
and HH/QH once with 8,760 cells each. QNEX/QNEY are separately defined monthly
products including/excluding PZV influence; this does not establish alternatives
of the enrolled daily/hourly products or authorize new products.

LHMT evidence: `tests/test_data/lt_lhmt_terms_licence.html`, the **full** publisher
API document <https://api.meteo.lt/>, acquired 2026-08-21T08:27:13Z, SHA-256
`bf8f893026a8c744136818d47da37e8c7b231b891c74c85e0f6192ac4a8d8645`.
The historical section says `Vidurkis per parą` for both fields and identifies
`observationDateUtc` as a UTC date. These documentation facts now bind to that
capture, not the station-list acquisition. The measured route describes
waterLevel/waterTemperature and observationTimeUtc instead.

ThaiWater evidence: `tests/test_data/th_thaiwater_official_app.chunk-2026-09-02.js`,
<https://www.thaiwater.net/dist/js/app.chunk.js>, acquired
2026-09-02T16:24:05.191409Z, SHA-256
`c5aeb29ff02c604ec186a1eea56bbfa770091dee6953e3d497722e1fe8632ec8`.
The tele_waterlevel components bind `value` to `ระดับน้ำ (ม.รทก)` / `Water Level
(m MSL)` and `discharge` to `(ม.3/วิ.)` / `(m3/second)`. A frontend display offset
is not a source-time-zone definition. Separate `station_type=canal` components
label `value`/`value_out` inside/outside. All six retained enrolled graph
recordings have null value_out; this is scoped negative evidence, not a promise
about every response.

## Public behavior and retained evidence

`tests/test_mapped_provider_fidelity.py` replays every enrolled route through
`find` and `fetch`. It checks exact physical-fact equality, content identities,
explicit unknowns, complete result bundles, publisher receipts, native-unit
conversion once across reuse, and subset refresh without sibling erasure.
Unrestricted reuse reacquires when inventory remains incomplete. An explicit
series-ID restriction can reuse successful coverage without claiming exhaustive
source inventory. A date-only midnight representation does not establish an
interval anchor.

`tests/test_jp_mlit_html_outcomes.py` exercises source HTML defects and explicit
no-data marker derivatives through actual transport. Valid HTML remains a
prerequisite, not a spurious empty observation outcome. Unsupported source
responses retain their identity and successful siblings; invalid internal tags
remain fatal. The unused maintainer live-collection compatibility seam is removed;
offline supplied-capture and native-table rebuilding remain authoritative.

`tests/test_provider_semantic_lineage.py` checks exact publisher definitions and
their governing acquisitions. Existing source-parser, boundary, catalogue and
acquisition tests remain meaningful scientific regressions.

The Thai catalogue retains 825 baseline stations and 1,650 governed pairs:
1,096 available and 554 unknown. Full private verification reads the original
controlled corpus with an explicit evidence root and checks every body/receipt.
The corpus is not included here; public ledger agreement is not a substitute for
that check. See `maintenance/catalogue/th_thaiwater/README.md`. The genuine full
verifier and private adversarial tests were executed during this delivery.

All four source inventories remain incomplete. A supported singleton is not proof
that no other publisher series exists. No quality ranking, preferred alternative,
new source route, automatic legacy-store migration or inferred datum is added.

## Regression proof

Before repair, the actual public mapped workflow produced seven failing tests:
four catalogue/result fact mismatches, MLIT unsupported interval support, Thai
omitted sea-level reference, and fabricated daily interval anchors. Those same
tests pass after explicit mapping facts and rebuilt catalogues. Separate real
boundary regressions demonstrated missing explicit mappings falling back to
product tables, explicit withholding being bypassed, and generic daily labels
being classified as anchors. Product projection tests caught independently
maintained `provider_defined` anchors before removing the duplicated scientific
declarations. Temporal vocabulary projection preserves `instantaneous` for
physical predicates and `instant` only in the existing product-table enum.

MLIT malformed/no-data derivatives failed on the original public transport path,
not a mocked parser result. CHMI/LHMT lineage tests failed against actual acquired
fact bindings before being moved to their retained publisher documents.
`tests/test_catalogue_evidence.py` still checks the complete original ordered
assertions after separately validating only the intentional lineage repairs.
No publisher bytes or native station table were changed for these repairs.
