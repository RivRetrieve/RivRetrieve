# HydroPortail catalogue inputs

The catalogue represents the anonymously published native station inventory.
It is not an unrestricted PHyC census. See [COVERAGE.md](COVERAGE.md) for the dated
population reconciliation and the 65 formerly selectable station IDs not published
by the native search. HTTP404 is not evidence of historical observation absence.

## Offline rebuild

From the repository root:

```sh
uv run python maintenance/catalogue/fr_hydroportail/scripts/rebuild.py
```

The script verifies the raw native response against its acquisition receipt,
projects it without copying Hub’Eau metadata, verifies the committed native table
identity, and publishes through the shared catalogue metadata builder. The native
input was committed at `eb2b4fcb3a38875329225b7dbe5f949216c01599`.
The immutable mixed historical ledger remains under
`maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz`.
Only HydroPortail historical acquisitions enter this provider's current
availability lineage. Hub’Eau count-only claims become unchecked HydroPortail
pairs, not positive or absent observations. Failed and empty bounded native
requests retain their exact original request scope and acquisition instant.
Retained historical material references keep their original archive names and
availability limitations; this rebuild does not reacquire unavailable bodies.

`evidence/` holds publisher bytes and acquisition sidecars. SHA-256, byte counts,
UTC retrieval instants, HTTP statuses and exact query parameters describe actual
captures. GeoJSON coordinate order is established by native module 71324 in
`chunk-8529.fdb00780.js.body`; station x/y is used directly, without site-coordinate
substitution or Hub’Eau axis correction. Native labels, status and empty metadata
remain in native.parquet, together with full source station/site JSON.

HydroPortail legal/about material establishes the publication service, not a
blanket reuse licence or every historical measurement author. Provider licence
and citation remain unknown. Hub’Eau's Etalab statement is not transferred.

## New acquisition

Write to a new explicit output directory rather than overwrite a reviewed capture:

```sh
uv run python maintenance/catalogue/fr_hydroportail/scripts/acquire_inventory.py --out PATH
```

The script obtains the source search form and discovers its current opaque site
option values. It requests active, closed and test entities with all published
site types. Preserve and review new query/body receipts, regional consistency
checks, test-filter differences and full-ID reconciliation before adopting a new
snapshot. Do not pin population counts as source completeness invariants.

`reconcile.py` recomputes the dated comparison using this folder's HydroPortail
captures and the independent current Hub’Eau inputs under
`maintenance/catalogue/fr_hubeau/inventory/`. It writes derived comparison reports,
not canonical source metadata. `remaining_missing.py` can acquire individually
missing identity pages while retaining failures separately.
