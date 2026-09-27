# Evidenced baseline access: France, Bosnia and Thailand

The French counts below describe the historical combined catalogue. Current
`fr_hubeau` and `fr_hydroportail` have independent source inventories; see the
[current native coverage account](../../maintenance/catalogue/fr_hydroportail/COVERAGE.md).

Measured target: `120b2792294011308a06d31c7bb3a55134865b74` (schema 3).
Sample-before target: `b68a38eaca4a4460eaad0ed271ef746e04a245d0`.
The accepted evidence destination and the measured final selection agree. This is
coverage accounting, not independent release acceptance.

## Before and measured after

Counts concern selectable station/product pairs, not continuous records or every
gauge in a country. The original committed native inventories define this scope.

| Provider | Before stations / pairs | Measured after stations / pairs | Positive evidence | Unknown availability |
| --- | ---: | ---: | ---: | ---: |
| `fr_hubeau` | 3 / 6 | 7,323 / 33,139 | 20,966 | 12,173 |
| `ba_fhmzbih` | 2 / 3 | 60 / 180 | 132 | 48 |
| `th_thaiwater` | 1 / 2 | 825 / 1,650 | 1,096 | 554 |
| Total | 6 / 11 | 8,208 / 34,969 | 22,194 | 12,775 |

Unknown availability remains selectable. It is not unsupported, permanently absent,
or an unestablished acquisition. A future fetch can return measurements, valid
emptiness, or an explicit source issue. Positive evidence is not a promise for every
row or requested period. Published record bounds and continuity are not inferred.

## Evidence and limits

### France

The disjoint populations are 6,454 hydrometry stations with five hydrometric products
and 869 temperature stations with temperature only. Unknown reasons are 4,948
publisher whole-record count zeros at acquisition, 524 two-window empties, 97 failed
historical checks, and 6,604 recent-empty pairs with history unchecked. Historical
failures are not emptiness. `J783301020` Q's June 2026 HTTP 500 remains a failed check.
Fifty-nine old precise historical totals are retired; replacement one-day numerical
witnesses do not certify those older totals. No repeat survey is implied.

Selected instantaneous discharge is the station's own Q, never a duplicated shared
site series. The published station/site mapping is not derived by truncation. Actual
series units, not display preferences, control conversion. HydroPortail supplies
historical instantaneous access without a claimed freshness advantage. Hub'Eau daily
and temperature products remain source-published products, without local aggregation.
HydroPortail publishes UTC; daily and temperature zones remain unknown.

SCV's HydroPortail/PHyC role and Hub'Eau's OFB/SCV/BRGM editors establish official
publication. `NomIntervenant` does not identify a measurement-production role;
`ProducteurDuJeu` describes station-referential dataset production. Neither establishes
all historical measurers. The source says: “L'utilisateur de ces données doit néanmoins
veiller à citer l'auteur des Jeux de données.” A publisher label does not settle that
dataset-author citation question. Source terms remain uninterpreted.

### Bosnia

All 60 baseline stations have numerical Q/H evidence; 12 have numerical WT evidence.
The other 48 WT workbooks match station, parameter and unit but contain zero data rows.
Measurement cells, not `#Rows`, establish numerical evidence. Timestamped blank cells
remain source records, not numerical measurements. Preserve string ID `2101-B` and
route through the source metadata's exact `site_no`.

Configured yearly workbooks are rolling access. The known monthly example is not an
archive or an exhaustive list of source periods. Each acquisition's actual observed
span belongs to that capture; an old requested window may clip to no rows. Failed
guessed filenames do not prove that no longer-history method exists. Workbook zones
and temporal support remain unknown. Retained workbook XML repeats the unknown-zone
wall-clock label `2025-10-26T02:00`; the `2010` Q workbook has two different values
at that label. This is a source fact, not evidence of a timezone, offset, DST rule or
runtime failure. Existing engine duplicate handling is unchanged. Annual source row
counts must not be presented as final engine output counts. The mixed-blank boundary
probe covers May 22–24 separately from that repeated-label case.

AVP Sava is the evidenced issuer; `ba_fhmzbih`
remains the public key. Further upstream measurement responsibility is not inferred.
The extra 39 surveyed stations, EPP layers and other station-document objects are
outside the original baseline, not unexplained baseline exclusions.

### Thailand

The baseline includes the 25 IDs absent from a later snapshot. It does not incorporate
605 newly observed IDs. Graph responses establish both fields' meanings and per-pair
availability: 813 stage and 283 discharge positives; 12 stage and 542 discharge unknown.
The governing tested windows contain seven or 91 inclusive dates. These research
windows do not restrict ordinary future user requests.

The engine plans at most 365 inclusive calendar dates per SOURCE request after adding
two days at each end of the requested window. A 365-date user request can need multiple
sub-windows. There is no separate 361-date public restriction, provider-side padding,
or provider splitting. Each source call receives its own bounds. This is a conservative
working size, not a proven source maximum or universal leap-year rule. The leap-containing
null grid proves honoured bounds, not historical measurements. Padding and final
clipping explain the prior two-day comparison, not an unstable source floor. Public
bypass, reuse/remainder and refresh must respect the same source bounds before cache
coverage is recorded. Wall-clock zone and temporal support remain unknown; Bangkok,
daily aggregates and source-published record bounds are not inferred.

Per-station supplying agencies remain distinct from HII's platform role. These bindings
do not identify every original producer or historical sensor operator.

## Representation migration and material footprint

The intermediate expanded target `6f0edf6` used schema 2. Its France provenance and
inline descriptor occupied 157,487,091 bytes. Schema 3 stores evidence once as five
typed Parquet relations and a strict header. The descriptor describes those relations
rather than expanding the national graph. France now occupies **4,028,560 bytes** for header, five relations and descriptor;
the descriptor alone is **42,905 bytes**. Final exact sizes and hashes are in the
[machine account](evidenced_coverage.json), including the intermediate baseline.
Native and four canonical files remain byte-identical across this migration.

This is an explicit metadata migration, not RDF-isomorphic compression. `find` and
`fetch` signatures and observation tables are unchanged. Nested acquisition metadata
now uses `CatalogueEvidence.header` and five Polars relations, without old nested
aliases. `describe` returns the bounded profile-3 JSON-LD. Strict v2 file/build inputs
normalize to the new carrier. See [profile 3](../catalogue-evidence.md).

The intermediate eager-loader measurements were 989,364,224 bytes peak RSS for a
three-pair USGS selection and 1,357,758,464 bytes for France selection/description on
macOS. These describe the superseded representation, not current performance.
The migration's bounded fresh-process probes reported 566,689,792 bytes for USGS
find, 597,442,560 for France find, and 595,935,232 for France find plus describe.
These [migration measurements](https://github.com/RivRetrieve/RivRetrieve/pull/237)
are environment-specific observations, not performance guarantees. Atomic
registration still validates all 13 headers and 65 evidence tables. The cost is not
limited to France requests, and no memory budget compliance is claimed. Metadata
lineage is not the controlled private measurement corpus.

## Reproduction and accounting

The [JSON account](evidenced_coverage.json) pins every original native inventory,
governing ledger and packaged artifact by path, byte count and SHA-256. Exact pair
keys locate each ledger record, including its actual source request, acquisition
instant, material reference and digest. It records per-product availability, reason,
source and acquisition-date partitions. Pair-acquisition edge counts can exceed
pair counts because France has multiple historical acquisitions per pair; Thai
products share their station response. Dates are deliberately mixed.

France governing acquisitions are September 11–13, 2026. Bosnia has three pairs
from September 2, three from September 7, 48 from September 9 and 126 from September
13. Thailand reuses 12 September 11 responses (24 pairs) and has 813 September 13
responses (1,626 pairs). Exact per-capture Bosnia spans and Thai seven/91-date
windows are in the JSON and ledgers. The original native inventories were captured
August 2, 2026, not at these later observation acquisitions.

Measured checks compare all native IDs, ledger pairs, table pairs and ordinary
`find` selections as actual sets, not only totals. Missing/extra sets are empty;
all 11 old selectable pairs survive; no baseline exclusion is unexplained.
Availability locators cover every pair, including unknown. Every governing
acquisition's source binding, request, instant, material size and hash matches the
normalized relations. Fresh offline builds reproduce all eleven generated files
per provider byte-for-byte. Build outputs and caches are not source evidence.

From a source checkout with its uv environment available, run these offline builds.
The output directories are disposable and are not the private evidence corpus.

```sh
uv run python -m rivretrieve._internal.providers.fr_hubeau.generate_catalogue \
  --native src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet \
  --availability-ledger maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz \
  --out .worktrees/coverage-build/fr_hubeau
uv run python -m rivretrieve._internal.providers.ba_fhmzbih.generate_catalogue \
  --native src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet \
  --workbook-access-ledger maintenance/catalogue/ba_fhmzbih/inventory/baseline_workbook_access.json \
  --out .worktrees/coverage-build/ba_fhmzbih
uv run python -m rivretrieve._internal.providers.th_thaiwater.generate_catalogue \
  --native src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet \
  --availability-evidence maintenance/catalogue/th_thaiwater/inventory/governing_station_product_evidence.csv \
  --out .worktrees/coverage-build/th_thaiwater
```

Use [profile 3's offline joins and selected-closure recipe](../catalogue-evidence.md#offline-python-and-polars-inspection)
to inspect a pair's evidence. Public deterministic ledger/binding closure is not
private source-body certification. The checks reported here do not rerun that
certification or claim that missing bytes can be verified from hashes. The accepted
research records independent controlled-body verification separately. Its corpus
requires an authorised handoff and must not trigger automatic reacquisition.

See the retained verifier interfaces and source-body requirements:
[France](../../maintenance/catalogue/fr_hubeau/README.md),
[Bosnia](../../maintenance/catalogue/ba_fhmzbih/README.md), and
[Thailand](../../maintenance/catalogue/th_thaiwater/README.md).
The [Bosnia source expectation note](../../tests/test_data/ba_fhmzbih_public_source_expectations.md)
documents the repeated unknown-zone timestamps and narrow mixed-blank probe.

The account validation also ran:

```sh
uv run pytest tests/test_selection.py tests/test_catalogue_evidence_representation.py tests/test_catalogue_evidence_graph.py -q
```

Result: 27 passed, six rdflib deprecation warnings (65.52 s). This targeted result
is separate from the root-owned integrated suite and release acceptance.
