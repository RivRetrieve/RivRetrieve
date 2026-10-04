# Separate inline metadata units without changing source values

Deliver the related metadata cleanup requested in
[#502](https://github.com/RivRetrieve/RivRetrieve/issues/502),
[#503](https://github.com/RivRetrieve/RivRetrieve/issues/503) and
[#504](https://github.com/RivRetrieve/RivRetrieve/issues/504) together.
Japan, Bosnia and Switzerland publish quantity strings that contain units.
The station summary should separate the numeric text from those explicit units,
while the source view remains an exact reference for the original values.

This is a focused change to the presentation agreed for #484 and #490 in
[the metadata vision](2026-10-04-source-faithful-metadata-presentation.md).
It deliberately supersedes that vision's requirement to preserve inline units
inside summary quantity values for the fields below. It retains the aligned-list
interface and source-fidelity guarantees. Reading an explicit unit from a value
does not authorize guessing units or interpreting source judgement.

## Agreed output

Keep `rr.metadata(selection)` and `rr.metadata(selection, view="source")` offline.
Keep the existing columns, list alignment, field ordering and per-field meanings.
Summary quantity columns remain `List(String)` containing JSON scalar text.
For a source string with a recognised number and unit, return the numeric portion
as a JSON-encoded **string**, not a JSON number or a floating-point conversion.

These are the intended summary list entries, shown as Python representations:

| Provider and station | Field | Value entry | Unit entry | Datum entry |
| --- | --- | --- | --- | --- |
| Japan `301011281104010` | `流域面積` | `'"142.00"'` | `'km2'` | Not applicable |
| Japan `301011281104010` | `零点高` | `'"0.000"'` | `'m'` | `None` |
| Bosnia `4024` | `metadata_CATCHMENT_SIZE` | `'"1600.00"'` | `'km²'` | Not applicable |
| Switzerland `2004` | `Catchment size` | `'"713"'` | `'km2'` | Not applicable |
| Switzerland `2004` | `Station altitude` | `'"432"'` | `'m'` | `'LN02'` |

For example, `json.loads` of the first value entry returns the string `142.00`.
Preserve the numeric spelling, including trailing zeros, signs and thousands
separators. A Japanese value `1,719.00km2` becomes the JSON string `"1,719.00"`,
not the numeric scalar `1719.0`. Separating the unit and its surrounding separator
text does not authorize general whitespace or spelling normalisation.

Keep each original `source_value` and `source_dtype` unchanged in the source view.
For example, Japan's source value still decodes to `142.00km2`, and Switzerland's
source altitude still decodes to `432 m a.s.l.`. Preserve source scopes, field
names, state distinctions, support links and datum associations.

Expose the supported units consistently in source and summary views. Japan and
Bosnia need units read from each recognised value, rather than a field-wide unit
that would also populate blank entries. Preserve `km2` versus `km²`; no unit
normalisation or numerical conversion is requested. Swiss unit and datum
associations already exist and remain unchanged. Removing `m a.s.l.` from the
Swiss summary value does not infer or change its datum.

Preserve every field and its list position, including nulls, blanks, whitespace-only
values, placeholders and zero values. Do not interpret zero as missing or remove
implausible elevations. Text that cannot be separated unambiguously remains
unchanged; do not partially strip qualifiers, fabricate units or replace it with
null. Unknown units remain unknown unless the existing source evidence establishes
them independently. Keep existing supported unit associations even when a value
cannot be separated. Missing roles and named null-valued fields remain distinct.

## Repository evidence and implementation boundary

Discovery reproduced all three issue examples through the public API and inspected
the packaged metadata. Japan has 981 nonblank area strings with `km2` and 1,009
nonblank elevation strings with `m`. Of those area strings, 252 contain thousands
separators. Bosnia has 50 nonblank area strings with `km²` and no exposed elevation.
Switzerland has 237 populated entries for each requested field. These counts are
starting-point observations, not authority to discard other stations or states.

`src/rivretrieve/_internal/station_metadata.py` validates source scalars and builds
the aligned summary. It currently copies quantity values and units unchanged.
`src/rivretrieve/_internal/catalogues/station_metadata.py` owns native projection
and `MetadataField` declarations. Current unit declarations are field-wide;
row-level extraction must fit the reviewed source projection and validation rather
than silently supplying inconsistent summary-only units. Keep raw scalar validation
and native round-trip guarantees intact. Choose the smallest suitable implementation;
this work does not require a new universal metadata framework.

Tests currently require inline preservation in both source and summary. Retain the
source assertions and revise only the intended summary expectations. Inspect
`tests/test_station_metadata.py`, `tests/test_station_metadata_areas.py` and related
packaging and declaration contracts. Synthetic cases include qualified text such
as `T.P. +1.230 m`; do not treat arbitrary text surrounding a number as disposable.

Keep scope to these providers' named fields and the shared behavior necessary to
support them. Other providers' quantity representations, station and water-body
names, observation behavior, canonical geometry and publication decisions remain
unchanged. There is no all-provider numeric-type redesign or new preferred field.
The [Poland area-unit correction](2026-10-04-poland-area-unit-from-grdc-workbook.md)
is separate work: its unit comes from workbook evidence and its values stay unchanged.
Do not absorb or overwrite that concurrent change.

## Verification and documentation

Follow `docs/maintenance/evidence.md` for changed unit mappings and source bindings.
Use reviewed revisions and exact genuine inputs for applicable full checks. Record
support for per-value unit extraction and update affected packaged products,
provenance and descriptors where required. Keep controlled material private.
Missing mandatory evidence blocks the affected acceptance claim; synthetic tests
or inspection of derived packaged values do not replace original-source checks.
No new metadata fields or broader source permissions are authorized.

Acceptance must demonstrate:

- The public API returns the table's intended values, units and datum, with unchanged
  source values and types. Source and summary units agree entry by entry.
- Numeric formatting survives, including Japanese thousands separators and zero
  elevation text. `json.loads` restores strings for cleaned source-string values.
- Blanks, whitespace, nulls, placeholders, unrecognised or qualified strings and
  missing roles retain their meanings and positions. No unit is inferred from a
  neighbouring row or assigned merely because another row has one.
- All non-target fields and providers remain unchanged. Swiss unit and datum
  associations, field ordering and list alignment remain unchanged.
- Affected source-independent regressions and applicable genuine-input checks pass.
  Rebuilt products remain usable offline, with no private material in distributions.

Update `docs/station-metadata.md` and applicable API docstrings to describe the
current distinction between cleaned summary text and exact source values. Show
concise, tested examples, including the JSON-string representation. Explain that
numeric text still requires user parsing for arithmetic. Follow `docs/AGENTS.md`;
do not turn the user documentation into a migration narrative or evidence ledger.

## Delivery and issue follow-up

After implementation is verified and its PR is merged, leave a short comment on
**each** of #502, #503 and #504 linking the actual implementation PR and stating
that the requested cleanup was delivered there. For example: “Implemented in
PR #<number>: metadata values and explicit units are now separated in the summary;
original source values remain available in the source view.” Then close each issue
if it is still open, and verify the comments and final issue states. If merge
already closed an issue automatically, still leave the short delivery comment.
Do not report an issue delivered if its acceptance is incomplete.

The documentation PR publishing this vision must leave all three issues open.
Publication is a handoff, not implementation acceptance, and does not authorize
starting implementation automatically.
