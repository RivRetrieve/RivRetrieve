# Traceable catalogues and station metadata

Program: https://github.com/RivRetrieve/RivRetrieve/issues/427
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/430

## Outcome

Maintainers can trace catalogue claims and exposed station metadata through
recorded declarations or executable transformations to exact archived support.
Users can inspect station metadata through one simple offline API. The metadata
feature exercises the same traceability design as the existing catalogue products;
it is part of this Effort, not a separate delivery.

The owner explicitly included the station and river name request in
[issue #267](https://github.com/RivRetrieve/RivRetrieve/issues/267). Its older
inventory is background, not verified current coverage. New provider research is
completely out of scope. Use retained material and existing established knowledge.
Do not acquire new source material, add providers, investigate new endpoints, or
try to eliminate metadata or historical evidence gaps.

Flag significant metadata, coverage or evidence gaps encountered during this work
in GitHub issues. Search existing issues first and reuse a matching issue rather
than creating a duplicate. Otherwise open a focused follow-up with the affected
scope, observed limitation, safe supporting references, and remaining uncertainty.
For example, [#263](https://github.com/RivRetrieve/RivRetrieve/issues/263) already
tracks French catchment area on an uncaptured referential; #265 and #294 are other
coverage follow-ups. Their historical claims are not renewed verification.
Do not report every ordinary source null as a new gap or infer that an agency
publishes no metadata from a missing packaged field. Recording a gap does not
authorise investigation or repair in this Effort. An existing limitation can remain
a documented follow-up; missing mandatory acceptance inputs still block acceptance,
and major bugs follow the stop rule below.

## Metadata experience

```python
import rivretrieve as rr

selection = rr.find(provider="ca_eccc", quantity="discharge")

metadata = rr.metadata(selection)
print(metadata)

source_metadata = rr.metadata(selection, view="source")
print(source_metadata)
```

Both calls return ordinary Polars frames and read approved packaged metadata.
They do not fetch observations, contact providers, or require archive credentials.
They accept selections spanning providers. Each gauge is identified by provider
and station ID; identifiers retain leading zeros. Multiple selected series do not
multiply the gauge's summary row or repeat its source attributes.

The default view has one row per selected gauge. Its ordinary scalar columns
include `provider_id`, `station_id`, `station_name`, `river_name`, `latitude`,
`longitude`, and `crs`. Coordinates and CRS travel together. Preserve the
catalogue's established coordinate representation and explicit unknowns; do not
label every coordinate WGS84 or borrow a map display's assumptions.

Use verbatim, source-supported names for the station and river or water-body role.
An unambiguous source-designated name may populate the summary. When alternatives
cannot be reduced without an arbitrary language or semantic preference, leave the
summary name unset and make the existence of alternatives visible. Preserve
alternatives in the source view. Do not infer a river from a station label,
transliterate names, treat a basin name as a river name, or silently equate a site
with a station. Exact presentation of the alternatives indicator is a reversible
design detail; it must be discoverable from the summary and documented.

The source view is a supported attribute table, not a dump of entire native tables.
It exposes station identity, attribute role, exact source field, source value,
native dtype, established unit where applicable, and an explicit value/absence
state. It preserves name alternatives and all currently exposed drainage-area
fields. Safe support references must let maintainers trace exposed values without
publishing restricted source bodies. Choose the reference representation within
the existing provenance design.

Drainage areas appear in the source view, not as a single apparent standard area
in the default view. Preserve the current `drainage_areas` information contract:

- Distinct fields and area meanings remain separate. Do not select a preferred
  gross, effective, contributing, topographic, or other area.
- Preserve original strings and numbers, native dtype, blank strings and inline
  units. The existing JSON-scalar representation is an available lossless carrier;
  users must be able to recover the original scalar type and value.
- Retain an already established unit; otherwise keep it unknown. Do not infer,
  parse into a preferred number, or convert areas into a common unit.
- Preserve `value`, `source_null`, and `no_metadata` distinctions. A source-null
  field retains its identity, dtype and established unit. No exposed field does
  not mean that the agency publishes none elsewhere. Neither absence means zero.

Empty selections retain stable schemas. Metadata scope follows the selected gauge
identities, independently of numeric observation admission or map eligibility.
Do not broaden a selection by enumerating all retained location evidence.
Metadata does not establish that observations are available for a station.

Once superseded, remove the public `rr.drainage_areas` function and export, its
replaced machinery, and its maintained documentation. Replace its examples and
references with the unified API. No compatibility wrapper, deprecation period,
or migration guide is wanted. Preserve relevant historical records as history.
Do not add separate public functions for each attribute.

Keep the initial metadata scope to identity, names, coordinates/CRS, existing area
fields and the source context needed to interpret them. Elevation, operating
status, additional area acquisition, and a universal metadata framework are not
part of this outcome.

## Catalogue and archive responsibilities

Refactor the existing catalogue and provenance contracts across all 14 providers.
The shared archive and unified test access delivered by #428 and #429 are the
foundation. Reuse their access and integrity contract; do not introduce a second
archive manager or consumer inventory.

Keep these roles distinct: original source bodies, native materialisations,
reviewed ledgers, authored origin/product/physical-fact declarations, executable
transformations, and packaged products. A native table with retrieval timestamps
is not original response bytes. Human or agent interpretation is recorded
authorship, not an automatic source fact or a reproducible agent acquisition.
Persist accepted interpretations so builds never require rerunning an agent.

A maintainer must be able to inspect the support for an authored declaration and
identify the executable code and revision used for an automated transformation.
Select exact input versions and declaration/build revisions explicitly. Providers
can advance independently and collections can serve multiple providers. Do not
force a global archive version. Adding archived bytes must not silently adopt
them into a catalogue; code changes may change a product without new acquisitions.

Retain offline native-plus-declarations reproducibility. Preserve existing
original-to-native and complete source-body checks separately where available.
A derived-input rebuild must never certify that missing originals were retained
or checked. Keep recovered-input limits, authored unknowns, reviewed ledger limits,
provider request scopes, and existing evidence gaps explicit.

Preserve historical acquisition identities and original bytes while replacing
obsolete path bindings and implicit source-checkout assumptions. Regenerate
serialized provenance, descriptors and affected identities consistently. Approved
catalogue products and safe provenance remain packaged and usable offline.

Existing source claims must not change incidentally. The explicitly approved
addition is the faithful exposure of names and station metadata from retained
inputs. New field mappings need genuine-input validation and a disclosure review;
source availability alone does not establish redistribution permission.

## Current implementation to build on

These are code-inspection findings, not renewed source verification:

- `catalogues/schemas.py` already defines canonical station identity, latitude,
  longitude and CRS. Names need a reviewed projection from retained inputs.
- `selection.py::_station_keys` selects provider/station identities from matching
  known series. Retained `locations` can be broader than the selected scope.
- `discovery.py::drainage_areas`, `_internal/drainage_areas.py`, and
  `scripts/build_drainage_areas.py` implement the existing offline source-field
  projection. Preserve its information while replacing its specialised API.
- Provider `generate_catalogue.py` entry points and the adapter in
  `tests/test_catalogue_origin_certification.py` already compose explicit native
  and other reviewed inputs. `scripts/build_source_descriptions.py` takes an
  evidence root. Do not redesign them as if no offline build exists.
- `acquisition_provenance.py` still models historical repository paths and native
  Git identities. Their historical meaning must survive the move to current
  archive locators. Transformation records need inspectable executable lineage,
  beyond a transformation name and kind.
- `catalogues/publication.py::build_catalogue_metadata` and
  `catalogues/evidence.py` already normalise and validate linked evidence,
  descriptions, claims and descriptors. Adapt these coherently rather than
  introducing a parallel provenance system.

Retain provider-specific build limits documented in the Effort and maintenance
notes. Modern USGS metadata remains necessary beyond the legacy native table.
Bosnia, historical France and ThaiWater retain their governing checks and reviewed
ledgers; ledger agreement alone is not full source-body certification. Current
Hub'Eau and historical France inputs are distinct. HydroPortail witnesses do not
establish other request scopes. Brazil's additional retained support remains
digest-bound. Japan's supplied scope is not national discovery. Recovered Polish
lineage does not establish missing original-byte identity. Other providers keep
their established availability unknowns and catalogue-only limits.

## Evidence of completion

Users can print a clean station table and retrieve source attributes through the
same function, for single-provider and mixed-provider selections. The source
view retains existing area values and states exactly, preserves supported name
alternatives, and exposes no invented names, units, area preference or CRS.
The default view does not hide unresolved alternatives. Neither view needs
observations or archive access at runtime.

Maintainers can follow representative authored declarations and automated
transformations to exact retained inputs and code revisions, and rebuild applicable
catalogue products using explicit input selection. All 14 provider build paths
must retain their supported claims and limits, not just the metadata examples.
The accepted build must distinguish native/derived rebuilds, recording replay,
complete governing source-body checks and any live observations.

Run the applicable full checks against genuine retained inputs for changed source
bindings, mappings, governing claims, verifiers or collections. Use the established
private coordinator and reviewed code requirements. Preserve full-positive
prerequisites before relevant negative regressions. Missing mandatory material is
blocked, never silently skipped or replaced by synthetic or reconstructed originals.
Source-independent tests remain a separate form of evidence. Reuse existing
coverage where it protects the same behavior; add focused checks for the new API,
source-fidelity boundaries and traceability guarantees.

Review packaged metadata, descriptors, documentation and distribution outputs for
restricted disclosure. Keep credentials, source bodies and detailed controlled
output out of public repositories, logs, caches, CI artifacts and distributions.
Existing GitHub permissions are sufficient for archive work; no added access tiers
or routine owner-managed download workflow is wanted. Pinned identities detect
changed archive assets; this Effort adds no independent backup guarantee.

Maintained documentation describes the resulting API and archive-backed build
workflow directly. Remove replaced implementations within this Effort, rather
than deferring them to #431. #431 retains the broader final integration and
publication-boundary review. Do not rewrite Git history or change visibility.

Follow the Effort's stop rule: fix and validate small, clear bugs directly. For a
major bug, stop implementation, open a `bug` issue assigned to `CooperBigFoot`,
and wait for repair and explicit permission to resume. This does not authorise
incidental source-claim changes, weakened checks or disclosure.
