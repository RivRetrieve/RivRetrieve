# Source-faithful metadata presentation

Related requests: [#484](https://github.com/RivRetrieve/RivRetrieve/issues/484) and
[#490](https://github.com/RivRetrieve/RivRetrieve/issues/490).
Foundation: [#430](https://github.com/RivRetrieve/RivRetrieve/issues/430).

## Outcome

Make station metadata easy to discover, inspect and join to observations through
`rr.metadata(selection)`. Implement Thiago's information **and presentation**:
one row per station, with aligned lists that keep every supported field beside
its value. The source view remains the detailed reference. Sending users to the
long source table instead of providing the proposed summary does not satisfy this
vision. Neither does replacing the aligned columns with nested records, an opaque
object, a preferred scalar or a different public interface.

Multiple area fields, a river and a lake name, or elevations of different reference
points are separate source facts. They must not compete for one cell or disappear
because they differ. The public presentation is a requirement, not a reversible
implementation suggestion. This work is intended to satisfy both related requests.
Publishing this vision alone does not deliver either request.

This is the comprehensive metadata redesign, across all 14 providers. Research,
source acquisition, semantic support, publication review, architecture, packaged
products and documentation are in scope. Do not choose a minimal patch or defer
providers merely because their evidence is harder to establish. There are no
backward-compatibility requirements; remove replaced machinery rather than retain
aliases or parallel legacy paths. Comprehensive coverage does not require a
universal framework for hypothetical metadata roles.

## Public presentation

Keep `rr.metadata(selection)` and `rr.metadata(selection, view="source")` as the
two views. Both remain offline and require neither observations nor archive
credentials. The summary has one row per selected `(provider_id, station_id)`,
regardless of selected series count. Identifiers remain strings, including leading
zeros. Preserve the current canonical `latitude`, `longitude` and `crs` together,
including unknowns, independently of saved selection geometry. Metadata remains
available for gauges excluded by observation admission or map eligibility.

The summary exposes these columns in addition to identity and geometry:

| Columns | Presentation |
| --- | --- |
| `station_name`, `station_name_alternatives` | Keep the existing scalar name and Boolean alternatives rule. |
| `water_body_name_field`, `water_body_name_value` | Aligned lists of native field names and ordinary, decoded name strings. |
| `drainage_area_field`, `drainage_area_value`, `drainage_area_unit` | Aligned lists of native field names, exact JSON scalar text and established units. |
| `elevation_field`, `elevation_value`, `elevation_unit`, `elevation_datum` | Aligned lists of native field names, exact JSON scalar text, established units and published datum names or codes. |

All list columns have Polars `List(String)` dtype with nullable cells and nullable
entries where applicable. A numeric source value and a source string that looks
numeric remain distinguishable through JSON decoding. Preserve strings with inline
units as strings. Do not add JSON quotation marks around summary water-body names:
Thiago's readable name presentation is deliberate. Field names, units and datum
labels or codes are strings, not JSON-encoded display text.

For every list-based role:

- Position *i* across the role's columns refers to the same source field. List
  lengths always agree. Sort by exact source field name; order carries no preference.
- Keep all exposed fields. Preserve source-null entries, empty strings, whitespace,
  source placeholders and zero values. Do not trim strings or interpret `ND` as null.
- Equal values from different source fields remain separate entries. Norway's
  `lakeName` and `riverName` both survive when both contain `Mår`.
- When no field is exposed for a station and role, all that role's list cells are
  null. This differs from lists containing named fields whose values are all null.
- Units and datums attach to individual entries. Unknown units or datums remain
  null. Do not infer units, prefer a field, convert quantities or shift datums.

The owner explicitly chose preservation of blank and null water-body fields over
#490's proposed blank-name filtering. Consequently, a Norwegian station with a
blank `lakeName` still lists that field beside `riverName`. This is the agreed
exception to that issue's illustrative output. Reconcile examples with this rule;
do not silently restore the issue's filtering proposal.

Rename the role `river_name` to `water_body_name` in the source and summary
contracts. Remove `river_name` and `river_name_alternatives` from the summary.
Retain both Norwegian fields and the other providers' supported water-body fields.
Do not split the role into river and lake or treat their names as alternatives.

Keep `station_name` unchanged: exactly one distinct nonblank supported name yields
a scalar; multiple distinct nonblank names yield null with the alternatives flag
true. Do not broaden station-name presentation for hypothetical future fields.

Use one `elevation` role. Preserve each field's source definition rather than
classifying ambiguous values as exclusively station altitude or gauge zero.
USGS's “gage/land surface” wording must not be narrowed by inference. Explain
station altitude, ground level and gauge-zero distinctions in the functionality
page. Preserve published datum codes, including France's codes, rather than
substituting expanded labels. Labels may be explained in prose with support.
No water-surface elevation computation, datum transformation or plausibility-based
cleanup belongs in this work.

## Source model and provider research

The architecture separates reviewed source facts from their presentation. Build
an approved, traceable source projection; derive the summary's aligned lists from
it. Do not maintain independently authored summary values or calculate datum
associations only in the summary. The source view must carry elevation's datum
and support its association with the value, whether the datum comes from a native
field or a separately documented declaration. Leave reversible internal carrier
and implementation choices to the implementing agent.

Preserve exact scalar values, native dtypes, source vocabulary, support links and
`value`, `source_null`, `no_metadata` distinctions. A blank string remains a source
value. An unexposed field does not establish that the agency publishes none.
Missing or invalid packaged metadata is an error, not an absence row. Empty
selections retain the chosen view's schema.

Review all 14 providers: `ba_fhmzbih`, `br_ana`, `ca_eccc`, `ch_foen`, `cz_chmi`,
`fr_hubeau`, `fr_hydroportail`, `jp_mlit`, `lt_lhmt`, `no_nve`, `pl_imgw`,
`th_thaiwater`, `usgs_nwis` and `za_dws`. Investigate the requested roles, field
meanings, units, datum applicability and publication basis with the same standard.
Use existing retained inputs and acquire additional source evidence where needed.
Do not limit the work to already approved columns or the four elevation providers
labelled “phase 1” in #484. Record supported inclusions and unresolved gaps for
every provider; do not promise every provider has every attribute.

Research leads from #484 include USGS `alt_va` / `alt_datum_cd`, NVE `masl`,
Hub'Eau `altitude_ref_alti_station` / `code_systeme_alti_site` and `altitude`,
IMGW `gauge_altitude`, MLIT `零点高`, ANA `Altitude`, ThaiWater
`station.ground_level`, and Bosnia `metadata_station_elevation`. They are leads,
not accepted source claims. Investigate the other providers rather than assuming
absence from their current packaged projections.

Area-unit research includes USGS `contrib_drain_area_va` and Poland `area`, but is
not limited to those two fields. Retain existing values while establishing units
through reviewed source evidence. Establish that a definition or datum applies
to the actual adopted field and station scope. One matching Polish station value
is not proof that a separate publication's datum applies to the whole inventory.

Keep catchment hypsometry, warning thresholds, bank levels and standalone stage
datums outside these requested roles. A water-level datum without a station
elevation is not an elevation value. New metadata does not authorize unrelated
changes to observation physics, availability claims or canonical station geometry.

Follow `docs/maintenance/evidence.md` and the private archive's reviewed procedures.
Retain exact originals and acquisition identities separately from materialised
inputs and authored interpretations. New acquisitions cannot retroactively supply
missing historical originals. Each new mapping requires semantic support and a
publication basis; existing metadata permission is not a blanket approval of new
fields. Review code revisions before private-evidence execution and review
products for disclosure before adoption. Keep private material, credentials and
controlled outputs out of public repositories, logs, caches and distributions.
Missing mandatory evidence blocks the affected acceptance claim. Never weaken a
check, invent a source definition or conceal a gap to reach coverage targets.

## Repository starting point

Source inspected at `e49e9027c2015d14c6417830a6f62ac2cb2cf819`:

- `src/rivretrieve/_internal/discovery.py::metadata` composes packaged input reads
  and the two projections.
- `_internal/station_metadata.py` owns runtime schemas, validation and summary
  projection. It currently treats every non-area role as a string name. Elevation
  requires explicit role handling rather than retaining that assumption.
- `_internal/catalogues/station_metadata.py` owns `MetadataField` declarations and
  native projection. It has no datum carrier today.
- Provider `origins.py` declarations and `_internal/catalogues/publication.py`
  connect mappings to native inputs, authored revisions and support facts.
- Every provider's packaged role column is a closed Polars Enum. Every gauge must
  have each role, including absence rows. Renaming a role and adding elevation
  therefore require compatible metadata products for **all 14 providers**, not
  just the six providers with existing water-body mappings. Update associated
  evidence, support-fact references and descriptors consistently. Do not rewrite
  canonical `stations.parquet` merely to add summary attributes.

Extend the existing contracts and tests rather than add parallel machinery.
Relevant coverage includes `tests/test_station_metadata.py`,
`tests/test_station_metadata_areas.py`, `tests/test_station_metadata_packaging.py`
and `tests/test_catalogue_origin_certification.py`.

## Documentation as part of delivery

Write one coherent functionality page at `docs/station-metadata.md`. Update
necessary API docstrings, links and stale descriptions elsewhere, without creating
competing guides. Read `docs/AGENTS.md` and existing pages before writing. Useful
examples already inspected for this vision are `docs/usage.md`,
`docs/providers/no_nve.md` and `docs/providers/ca_eccc.md`.

Write explicit, unambiguous explanations that LLMs can use correctly, in simple
language that humans can read. Follow the hydrology audience and prose rules in
`docs/AGENTS.md`. Explain current functionality, source meanings and how to use
the result. Avoid migration narratives and unnecessary implementation detail.

Every code snippet must serve a concrete purpose and must be tested. Show the
actual verified output unless the snippet only presents the API. An API-only
snippet is exempt from displaying output, not from verification. Do not add
snippets that merely repeat prose. Explain what each useful example demonstrates.
Use small, readable outputs rather than unwieldy full-width tables.

Demonstrate Thiago's actual workflow: inspect the station summary, understand
multiple fields and missing entries, explode aligned columns together, and select
a particular field by its native name. Include representative area, water-body
and elevation cases, and explain JSON decoding where useful. Establish outputs
against accepted products; do not copy speculative issue examples as tested facts.
Explain that elevations can describe different reference points and that metadata
availability does not prove observation availability.

## Acceptance

Delivery must demonstrate both source fidelity and Thiago's public presentation:

1. The specified columns, list dtypes, alignment, ordering and readable-name versus
   JSON-quantity representation are exercised through the public API. No preferred
   value, conflicting-name suppression or substitute interface is introduced.
2. Tests distinguish missing roles, null fields, blanks, equal values in different
   fields and unequal values. They preserve formatted strings, inline units,
   leading whitespace, `ND`, zeros and unusually large source elevations.
3. Mixed-provider selections, duplicate series, empty selections, catalogue-only
   gauges, canonical geometry and fatal packaged-contract failures remain covered.
   Summary entries agree with their source rows, units and datums.
4. Every provider has a reviewed outcome for the requested metadata. New fields,
   units and datums have exact support and publication review; unresolved evidence
   or publication limits are explicit. Applicable full genuine-input checks pass
   before affected products are accepted. Preserve distinctions between native
   rebuilds, source-body verification and live observations.
5. Regenerated metadata, evidence and descriptors agree. Installed wheel and sdist
   checks demonstrate offline access and exclude private/native evidence. Run
   affected source-independent tests and the broader checks required by changed
   boundaries, following `docs/maintenance/testing.md`.
6. The functionality page and API documentation describe the delivered contract.
   Every snippet is tested and every behavioral example shows checked output.
   Review the final presentation against #484, #490 and the explicit decisions
   above, not merely against a test suite derived from the implementation.

Do not report implementation acceptance from this vision's publication or from
source-only inspection. Research uncertainty concerns what publishers establish;
it is not permission to redesign the agreed presentation or quietly omit hard
providers. Report genuine blockers precisely.
