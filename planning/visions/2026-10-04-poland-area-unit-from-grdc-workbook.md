# Poland area unit from the GRDC workbook

Poland's existing drainage-area values should carry their source-supported unit,
square kilometres, in both `rr.metadata(selection, view="source")` and the aligned
lists returned by `rr.metadata(selection)`. The values themselves must not change.
This is a focused evidence and catalogue correction following the metadata work
discussed in [#484](https://github.com/RivRetrieve/RivRetrieve/issues/484) and
[#490](https://github.com/RivRetrieve/RivRetrieve/issues/490).

## Evidence and current behaviour

At public repository revision `4d43cf5e6fa8e20c90307d5eb54cb666ac32af08`, Poland's
`STATION_METADATA_FIELDS` in
`src/rivretrieve/_internal/providers/pl_imgw/origins.py` maps `area` to
`drainage_area` without a unit. The metadata API already supports per-field units
and source-support links. No new API shape is needed.

The owner supplied `Metadata_GRDC_30.10.2025.xlsx` for this correction. Inspection
found the explicit header `Catchment area (square kilometre)`. Its bytes match the
workbook identity already published in Poland's acquisition provenance:

- SHA-256: `dfab6ea7de80fb1570f4a8dded8743ed7c7dcb4eb67fe75e2c0e02e9b964b7bf`.
- Size: 116,301 bytes.

The provenance describes this workbook as later GRDC corroboration of the
recovered station table. It does not establish that this workbook was the original
acquisition behind the historical import. Preserve that distinction.

Discovery inspected the private archive at revision
`ecf8d210cb209021cc27e228f4582fadf3ee16ac`. Its station-metadata review preserves the
existing Polish area field with an unknown unit and does not approve additional
GRDC name or elevation fields. The checked Poland-associated collection manifests
did not identify this exact workbook or the previously fingerprinted forwarded
email. Recheck current archive state before intake to avoid duplicate retention.
A public fingerprint alone does not mean that the corresponding bytes are archived.

## Settled scope

Retain the exact workbook in the private `RivRetrieve/verification-evidence`
archive, using an existing exact retained member if one is found. Preserve its
original bytes and record its actual role and known acquisition limitations.
Select it explicitly as evidence for the area-unit claim; archive membership alone
does not adopt a source claim into a catalogue.

Verify that the workbook's identified area column corresponds to the existing
Polish `area` values and station identities across the relevant catalogue coverage.
Do not establish a field-wide unit from one matching example. Retain the explicit
source wording and bind the resulting unit claim to the workbook evidence through
the existing metadata support and catalogue provenance mechanisms. Choose the unit
representation consistently with the repository's source-fidelity conventions.
No numerical conversion is required.

Update the private review and source checks, public declarations, packaged Polish
metadata and associated provenance as needed for this claim. Keep ordinary user
documentation concise and accurate. Do not redesign the metadata framework or
broaden this work to other providers.

The following must remain unchanged:

- Existing area scalar values and their types, source field name and source scope.
- Nulls, placeholders, absent-row states and station coverage.
- Coordinates, CRS, observation behaviour and the metadata API shape.
- All other metadata fields and their publication decisions.

Do not add elevation, station names, water-body names or any other workbook field.
Retaining the complete original workbook privately does not approve those fields
for publication.

## Email and disclosure boundary

The owner has no email to supply and explicitly requested proceeding with the
Excel file alone. Recovering correspondence is out of scope and is not an added
prerequisite for this area-unit correction. Do not invent receipt dates, permission
wording or original-email verification. Keep the existing historical verification
record distinct from the evidence newly retained and checked for this work.

The owner authorized private retention of this workbook and this narrowly scoped
metadata correction. The workbook establishes the unit; it is not proof of broader
redistribution permission. Keep the workbook, private records and detailed evidence
outputs out of the public repository, logs, test fixtures and distributions.
Publish only the approved metadata and safe provenance references. Follow
`docs/maintenance/evidence.md` and the private archive's intake and verification
rules without expanding the permission claim.

## Acceptance

- The exact workbook is retained and independently retrievable through a pinned
  private archive selection, with its digest, role and limitations recorded.
- Genuine-input checks establish the header's meaning and its mapping to the
  existing Polish area field across the relevant coverage. A mismatch is reported
  and investigated, not repaired by silently replacing catalogue values.
- Source metadata exposes the established square-kilometre unit on the existing
  area rows. Summary metadata carries the same unit beside the same field and
  value, with aligned lists and unchanged state semantics.
- Before-and-after comparison proves that area values, identities, coverage and
  all unrelated metadata remain unchanged. Necessary support and provenance
  additions are expected.
- Focused source-independent regressions detect a missing or unsupported unit and
  disagreement between the source and summary views. Applicable full genuine-input
  checks run against explicitly reviewed public and private code revisions and
  verified inputs. Missing mandatory inputs are reported as blocked, never replaced
  by synthetic evidence or silently skipped checks.
- Approved rebuilt products work offline without private-archive credentials.
  Distribution review confirms that no workbook or private correspondence is
  packaged.

Implementation may change both repositories, but should remain proportional to
this single-field correction. This vision authorizes no new hydrological product
or broader metadata adoption.
