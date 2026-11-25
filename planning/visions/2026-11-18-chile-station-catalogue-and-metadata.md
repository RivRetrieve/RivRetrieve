# Chile station catalogue and metadata

Deliver reproducible offline station discovery for the selected direct DGA historical
`cl_dga` scope. A user must be able to identify a station, see supported source
metadata, and distinguish its published historical products without mistaking an
active-station listing for observation availability.

This vision implements [Effort #736](https://github.com/RivRetrieve/RivRetrieve/issues/736)
in [Program #734](https://github.com/RivRetrieve/RivRetrieve/issues/734).
Successful delivery completes #736 only. Publishing this vision does not complete
the Effort or authorize delivery of the later provider steps.

## Scope and catalogue membership

Follow step 2 of the [provider-port guide](../../docs/maintenance/provider-ports.md).
The source remains DGA's national `caudal_diario_historico.zip` and
`caudal_medio_mensual_historico.zip` on `https://mapas2.mop.gob.cl/`, selected in
[Step 1](2026-11-18-chile-source-scope-and-access.md).

Include stations evidenced in the selected historical ZIPs. Use other DGA station
sources to establish and enrich their metadata, not to add stations without records
in the selected products. The inspected daily and monthly files each contained the
same 784 eight-digit codes. This is a snapshot finding, not a fixed catalogue size
or a promise about future publications. Establish station-product associations
from the relevant product evidence; listing a station does not promise continuous
records or values for every requested period.

Preserve leading zeros and establish reproducible links between station codes and
observation records. Reconcile the ZIP inventory with the embedded `mapas2` station
JSON and DGA's `Informe Nacional` workbook. The Step 1 counts are leads to verify:
126 ZIP-backed gauges were absent from the map's fluviometric subset, while 111
active fluviometric workbook codes were absent from the historical ZIPs. Neither
source is an interchangeable inventory of historical availability.

## Faithful metadata

Publish source facts using the existing catalogue and station-metadata contracts.
Formatting and evidenced normalization are allowed; adding hydrological
interpretation is not. Establish mappings, units, source precedence where sources
differ, and the evidence for each adopted field. Do not silently choose a plausible
value when the sources conflict.

- Preserve identifiers and source names. Check-digit forms in supporting tables
  must be reconciled explicitly with the eight-digit observation codes.
- Establish coordinates and their encoding before normalization. Keep horizontal
  CRS and vertical datum unknown unless source evidence establishes them. The
  workbook's `Datum` values of 18 and 19 are UTM zone integers, not datum names.
- Do not publish inspected `ALTITUD=0` placeholders as established zero-metre
  elevations. Keep unsupported elevation unknown and preserve source evidence.
- Missing optional metadata must not remove a station with an established
  observation link. Do not infer missing facts from station names or nearby gauges.

The implementing agent chooses the builder structure and supported field mappings
from the evidence. Use the shared catalogue publication path rather than a separate
Chile-specific publication system.

## Data rights and maintainer decision

The maintainer approved faithful station metadata publication subject to the
source's terms, without hydrological interpretation. Apply the repository's
existing [data-rights policy](../../README.md#data-rights) and
[station-metadata policy](../../docs/station-metadata.md#data-rights): MIT covers
RivRetrieve code, not provider data, including packaged catalogues and metadata.

This supersedes Step 1's mistaken premise that packaging DGA station metadata
would place it under MIT and therefore required approval to relicense it. Do not
introduce a new blanket approval requirement on that premise. Ordinary evidence,
field-disclosure and artifact review still apply. Maintainer approval does not
grant rights on DGA's behalf or establish a dataset-specific open licence.

Keep `ProviderInfoCatalog.license = None` while a dataset-specific licence remains
unestablished. Preserve DGA/MOP attribution and references to the source and
[MOP terms](https://www.mop.gob.cl/condiciones-de-uso/). The recorded terms permit
non-commercial reproduction with clear citation; commercial reuse may require
written permission. Do not replace this with an unconditional claim that all Chile
data can never be used commercially. Do not infer downstream permission from
RivRetrieve's own non-commercial purpose.

Step 7 owns the full user-facing explanation of these conditions and their
uncertainty. Step 2 must preserve the terms and attribution in its catalogue
handoff so packaging does not imply MIT rights over source data. Existing Poland,
Thailand and Lithuania provider documentation demonstrates this separation of
software licensing and provider conditions; it does not establish Chile's rights.
If new evidence contradicts the adopted publication basis, report the specific
conflict rather than silently broadening permission.

## Evidence and delivery

Continue the existing private research record `research/cl-dga-source-access.md`
in `verification-evidence`; do not create a parallel research history. Start from
collection `cl_dga-access-2026-11-18-v1` and follow the
[evidence guide](../../docs/maintenance/evidence.md) for exact input selection,
reviewed revisions, retained material, and source certification. The national daily
ZIP was fingerprinted but not retained in that initial collection. Obtain any
missing genuine inputs through the existing archive process before making claims
that require them; an authored inventory summary is not a retained source body.
Keep controlled material and correspondence private.

Deliver:

- A reproducible catalogue builder and reviewed packaged artifacts using the
  shared provider, product, station, station-product and metadata publication path.
- Evidence-backed station/observation links, supported field mappings, inventory
  reconciliation, and explicit coverage and metadata limits.
- Focused source-independent tests for the changed behavior and applicable full
  genuine-input catalogue checks. Follow the testing and evidence guides; missing
  mandatory evidence blocks acceptance rather than becoming a skipped success.
- A safe handoff to Steps 3–7 explaining remaining source unknowns, terms and
  attribution. This work does not resolve daily statistic or time support, build
  retrieval, add operational telemetry, or perform the final CAMELS-CL comparison.

Update Program #734 and the #736 discussion with the agreed rights correction and
vision link, preserving the historical record and explicitly superseding the old
MIT-packaging premise. Keep Step 2 open until its deliverables and verification are
complete. Carry the correction into the continuing private research record during
execution so later steps do not reinstate the mistaken gate. Give Step 7 the terms
handoff; do not complete Step 7 here.

Implementation and corrections remain on `port/cl-dga`. The Program's final review
by @thiagovmdon and explicit approval before merging the port to `main` remain
unchanged. Leave unchosen implementation details to the implementing agent.
