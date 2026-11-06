# NRFA offline catalogue

Deliver reproducible, source-backed offline discovery of UK National River Flow
Archive stations and their advertised flow/stage products. This vision implements
[station catalogue and metadata, #584](https://github.com/RivRetrieve/RivRetrieve/issues/584)
within [the NRFA port, #347](https://github.com/RivRetrieve/RivRetrieve/issues/347).
Completing and verifying the deliverable completes #584. Publishing this vision
does not complete that issue or authorize implementation.

Work belongs on `port/uk-nrfa`. Keep provider implementation and corrections there;
merging the completed port into `main` requires Thiago’s explicit approval through
[final review #597](https://github.com/RivRetrieve/RivRetrieve/issues/597).

## Delivered behavior

Users can discover NRFA stations and advertised products offline, inspect standard
station metadata, and understand that observation retrieval is not implemented yet.
Use the existing catalogue-only provider contract so attempts to retrieve observations
fail explicitly rather than reaching a different provider or implying source absence.

Retain published station identities, including closed stations. Preserve source
coordinates and missing values; do not discard stations because optional metadata is
absent. Use the station-info decimal-degree latitude and longitude directly with
WGS84 (`EPSG:4326`). Do not reproject values that the API already reprojects.

Expose the standard metadata roles: station name, river name, catchment area and
station altitude. Preserve source scalar types, spelling, nulls and supported units.
The documented catchment-area unit is km². Station altitude is generally taken from
the banks of the gauging station, in metres above Ordnance Datum or, in Northern
Ireland, Malin Head. Preserve those datum names without strengthening Ordnance Datum
to a more specific vertical CRS. Station altitude is not stage zero and must not
establish an observation-stage datum.

A per-station datum association must have reviewed evidence. The official numbering
guidance describes six-digit regional identifiers: 0 for mainland Britain, 1 for
surrounding islands and 2 for Ireland. Restore omitted leading zeros for interpreting
that convention, without changing source-facing station identity. Combine this with
the documented Northern Ireland numbering and the UK inventory scope; prefix 2 alone
is not a universal Northern Ireland rule. Unknown or unsupported associations stay
unknown rather than receiving a default.

## Product inventory and bounds

Preserve these ten distinct API products:

- `gdf`, `ndf`, `gmf`, `nmf`: gauged/naturalised daily and monthly flow;
- `gauging-flow`, `gauging-stage`;
- `amax-flow`, `amax-stage`;
- `pot-flow`, `pot-stage`.

Use positively advertised in-scope station/product associations from station-info
`data-summary`. The API documents this as a summary of available time-series types.
Do not fabricate the full station/product cross-product or mark omitted products
unavailable. Describe the catalogue as a snapshot of advertised associations, not
an exhaustive historical archive or a promise of successful retrieval or continuous
observations. Distinct source products remain distinct even where physical facts match.
Establish physical facts and source units from evidence; preserve unknown facts.
Detailed series meaning remains coordinated with #595.

Keep canonical station-product start/end dates unknown for this Effort. Retain exact
native `first`/`last` strings in adopted native inputs and private evidence. Their
precise coverage meaning is undocumented, and the current catalogue holds dates only:
month-only labels and exact timestamps cannot be represented faithfully there. Do not
expand months, truncate timestamps, infer valid-observation coverage, or present this
representation limit as source silence. Stronger bounds and omission semantics remain
for [series meaning #595](https://github.com/RivRetrieve/RivRetrieve/issues/595) and
[retrieval #594](https://github.com/RivRetrieve/RivRetrieve/issues/594).

## Evidence and implementation boundaries

Follow the [provider-port guide](../../docs/maintenance/provider-ports.md),
[evidence guide](../../docs/maintenance/evidence.md) and
[testing guide](../../docs/maintenance/testing.md). Use the existing publication,
station metadata, source-description and provenance contracts. Catalogue-only
registration does not require a speculative observation configuration or fetch/parse
implementation. Exact module layout and reversible build mechanisms remain engineering
choices.

The [continuing private research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/nrfa-source-access.md)
records the permission interpretation and the separate maintainer decision on private
test-response retention. Earlier permission correspondence is already archived.
The original CRS reply is retained in private collection
`nrfa-2026-11-06-crs-correspondence`, registered at archive revision
`fd15877bab32fe6bdd20e60dce3cccaf6e0014a2`, with byte-identical independent retrieval.
See the [pinned research record](https://github.com/RivRetrieve/verification-evidence/blob/fd15877bab32fe6bdd20e60dce3cccaf6e0014a2/research/nrfa-source-access.md).
Keep correspondence, original source bodies and restricted receipts private.

The 6 November 2026 exploratory metadata check found 1,604 unique stations matching
the separate station-ID list, 9,052 in-scope advertised associations, 364 stations
with closure dates and 64 null station altitudes. These observations inform checks;
they are neither fixed acceptance counts nor adopted or certified build inputs.
Retain and adopt exact genuine inputs through the private archive process. New
acquisitions retain their own identities. Reconcile station enumeration and metadata,
verify all adopted mappings and associations, and retain source-supported units,
datum associations and build lineage. Missing mandatory evidence blocks acceptance.

Official references:

- [API help](https://nrfaapps.ceh.ac.uk/nrfa/nrfa-api.html)
- [Locational information](https://nrfa.ceh.ac.uk/data/about-data/gauging-station-information/locational-information)
- [Station numbering](https://nrfa.ceh.ac.uk/data/about-data/gauging-station-information/station-number)
- [Hydrometric areas](https://nrfa.ceh.ac.uk/data/about-data/gauging-station-information/hydrometric-areas)

## Acceptance

- A reproducible build from explicitly selected, verified private inputs produces
  the approved packaged catalogue, station metadata, provenance and descriptor.
- Offline public discovery preserves the adopted station inventory and positively
  advertised in-scope product associations. Closed stations, null metadata and
  distinct products survive publication. Public date bounds remain unknown.
- Metadata tests protect source values, units, WGS84 coordinates and reviewed altitude
  datum associations, including Northern Ireland and closed-station cases.
- Catalogue-only retrieval refusal is verified through existing public contracts.
- Extend existing catalogue/rebuild and distribution checks; run affected
  source-independent tests and applicable full genuine-input checks. Synthetic checks
  alone do not certify source claims. Review package contents for restricted material.
- Explain delivered discovery, snapshot limits, unknown bounds, terms and attribution
  accurately. Leave the full observation-provider documentation to #593.

## Exclusions and later work

No observation retrieval, automatic metadata refresh, richer catchment attributes,
land cover, geology, flow statistics, shared date-bound interface expansion or
cross-provider stitching. Rainfall, numbered bulk peak-flow releases and enquiry-only
records remain outside the agreed port scope. No water-temperature product was found
in the documentation reviewed.

The required ten-gauge CAMELS-GB comparison belongs to [verification #583](https://github.com/RivRetrieve/RivRetrieve/issues/583)
after observation integration. It does not block this catalogue-only increment or
replace genuine catalogue verification. All seven delivery Efforts must finish before
Thiago’s final review; this vision covers only #584.
