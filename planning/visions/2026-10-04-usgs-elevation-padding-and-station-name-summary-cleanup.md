# USGS elevation padding and station name summary cleanup

Deliver the reported metadata presentation improvements in
[#505](https://github.com/RivRetrieve/RivRetrieve/issues/505) and
[#509](https://github.com/RivRetrieve/RivRetrieve/issues/509).
Implementation is complete only when the changes are verified, merged, and both
issues have delivery comments and are closed. Publishing this vision leaves them
open and does not authorize starting implementation automatically.

RivRetrieve harmonises axes and units without harmonising scientific interpretation.
Small, explicit presentation rules can improve usability while the source view
preserves the original facts. Keep this work limited to the reported issues.

## USGS elevation text

In the summary returned by `rr.metadata(selection)`, remove leading padding from
recognised numeric strings in USGS `alt_va`. For station `07374000`, the elevation
entry currently decodes to the string `" 0.00"`; it must decode to `"0.00"`.
The `elevation_value` list still contains JSON-encoded string text, not a JSON
number. Preserve signs, decimal spelling and trailing zeros. Do not convert the
value to a numeric scalar, change its physical reference point or assess whether
zero is plausible.

Keep the exact original value and dtype in `view="source"`. Preserve units,
datums, field ordering and list alignment. Preserve nulls, empty strings,
whitespace-only values, placeholders and qualified or unrecognised text. The
cleanup must recognise the complete numeric text rather than extract a number
from arbitrary surrounding text. Limit the change to USGS `alt_va`; other fields
and providers remain unchanged. This is not general whitespace normalisation.

## Station-name summary

Remove the `station_name_alternatives` column from the summary, including its
empty-selection schema. Keep the scalar `station_name` and its existing rule:

- One distinct nonblank supported name yields that exact name.
- No nonblank name yields null.
- Several distinct nonblank names yield null.

Equal names from separate fields still count as one distinct name. Blank names do
not populate the scalar. Preserve spelling, language and surrounding spaces in
nonblank names. All approved name fields remain unchanged in the source view.

The summary will no longer distinguish a missing name from multiple distinct
names. This is an accepted trade-off; users can inspect the source view. Do not
replace the removed flag with another column, choose the first source row, or add
an English-first preference. Revisit preferred-name presentation when approved
metadata actually requires multiple station names. Remove the column directly;
no deprecated alias or parallel compatibility path is required.

The public-API audit at `3f42f137df9873095b573243b2a4de539d7e8b77`
found 77,020 gauges, no true alternatives flags and at most one exposed station-name
field per gauge. Removing only the flag must therefore leave every current scalar
station name unchanged. Synthetic coverage still needs to protect the multiple-name
rule; the current catalogue does not exercise it.

ThaiWater has multilingual fields in retained native schemas, but no station-name
field is currently approved and exposed through either metadata view. Selecting a
language does not grant publication permission. Do not expose these fields, expand
source research or change publication decisions in this work. The source view
contains approved metadata, not every raw field held upstream.

## Relationship to delivered and concurrent work

The [source-faithful metadata vision](2026-10-04-source-faithful-metadata-presentation.md)
was delivered in PR #498 for #484 and #490. This vision supersedes its requirements
to keep the station-name alternatives flag and preserve leading whitespace in the
USGS summary elevation field only. Keep its aligned-list presentation for water-body
names, areas and elevations, including blank and null entries and separate fields
with equal values.

PR #508 delivered the [inline-unit presentation vision](2026-10-04-separate-inline-metadata-units-without-changing-source-values.md)
for Japan, Bosnia and Switzerland. Preserve that behavior and its exact source
values. Do not broaden its numeric-text cleanup or change units and datums.

Poland PR #507 implements the separate [area-unit vision](2026-10-04-poland-area-unit-from-grdc-workbook.md).
Do not absorb, overwrite or merge that work as part of this change. This vision
adds no fields, units, datum associations or source bindings. Observation behavior,
canonical geometry, names and water-body presentation remain unchanged except for
the explicitly removed summary flag.

## Implementation context and verification

`src/rivretrieve/_internal/station_metadata.py` owns the summary schema, validated
source projection and quantity presentation. Its scalar station-name selection
already implements the rule above. `src/rivretrieve/_internal/discovery.py` owns
public composition and the metadata docstring. Extend existing behavior rather
than introduce a general metadata-normalisation or preferred-name framework.

Use the simplest sufficient coverage in `tests/test_station_metadata.py`,
`tests/test_station_metadata_areas.py`, `tests/test_station_metadata_packaging.py`
and related existing contracts. Acceptance must demonstrate:

- The public USGS example returns cleaned JSON-string text with unchanged source
  value, scalar type, unit and datum. Leading padding changes; numeric spelling
  does not. Strings already without padding remain unchanged.
- Nulls, blanks, placeholders, qualified text and non-string source scalars remain
  unchanged. Non-target quantity fields and the PR #508 examples retain their
  existing behavior.
- The summary has no alternatives column, even for empty selections. Existing
  packaged station names remain identical. Synthetic equal, conflicting, blank
  and space-bearing names exercise the retained scalar rule and source fidelity.
- The two views remain offline. Mixed-provider selections, one-row-per-gauge
  behavior and aligned lists remain intact. Installed-distribution coverage checks
  the changed public presentation without exposing private material.

Follow `docs/maintenance/testing.md` and run affected source-independent tests
and broader checks appropriate to the shared public schema. Follow
`docs/maintenance/evidence.md` if implementation changes governing claims, source
bindings or packaged products. Such changes require applicable full checks against
reviewed genuine inputs; unavailable mandatory evidence is a blocker, not a reason
to weaken checks. A presentation-only change does not itself require new source
research or catalogue regeneration.

Update `docs/station-metadata.md`, relevant API docstrings and stale architecture
or reference descriptions. Describe current behavior plainly, including the
remaining null-name ambiguity and the exact-source versus cleaned-summary distinction.
Follow `docs/AGENTS.md`. Show concise, tested USGS output and remove documentation
that promises the alternatives flag. Do not turn user documentation into a migration
history or evidence ledger.

## Delivery and issue closure

The implementation must satisfy both #505 and #509. After verification and merge,
leave a short delivery comment on each issue linking the actual implementation PR
and describing its delivered change. Close each issue if still open, then verify
both comments and final issue states. If merge closes an issue automatically, still
leave the delivery comment. Do not report either issue delivered when its acceptance
is incomplete.

The documentation PR for this vision uses neutral issue references and leaves
both issues open. Vision publication is a handoff, not delivery of their fixes.
