# SENAMHI offline station catalogue

Deliver reproducible offline station discovery for Peru's SENAMHI provider,
`pe_senamhi`, under [Effort #604](https://github.com/RivRetrieve/RivRetrieve/issues/604)
and [Program #534](https://github.com/RivRetrieve/RivRetrieve/issues/534).
Completing and verifying this catalogue completes #604. Publishing this vision
alone does not complete the Effort or authorize the full provider integration.

Work targets `port/pe-senamhi`; keep `main` unchanged until the Program's final
review permits merging. Follow [provider-port step 2](../../docs/maintenance/provider-ports.md),
the [evidence process](../../docs/maintenance/evidence.md), and the established
[source-and-access scope](2026-10-30-pe-senamhi-source-scope-and-access.md).
The Swiss offline catalogue is the delivery precedent: useful discovery with
explicit limits, followed by separate series-meaning and retrieval work.

## Discovery outcome

Users can select established hydrological station identities offline and inspect
source-backed metadata and catalogue candidates. A listed station does not
promise observations for every product or requested period. Preserve known
associations and unknown availability using the existing catalogue contracts;
do not restrict discovery to stations with successful observation samples.

Build from explicitly selected retained originals without network access. Use
the existing catalogue schemas, publication path and provenance contracts rather
than introducing a provider-specific publication framework. Register only the
catalogue capability needed for offline discovery; observation retrieval remains
outside this Effort.

The 2026-10-31 investigation identified 771 hydrological registry identities and
142 PHISIS monitoring stations. These are snapshot expectations to verify against
the selected inputs, not permanent constants. Include hydrological categories
found under the source's meteorological type label where evidenced. Do not drop
closed or paused stations merely because of their operational condition.

## Identity and metadata

Preserve Freddy's [catalogue handoff decisions](https://github.com/RivRetrieve/RivRetrieve/issues/604#issuecomment-6542299050):

- Use registry `stationId` and matching PHISIS `code` as canonical identities.
  Never auto-alias `legacyStationId`: its values collide with other primary IDs.
  Published `automaticCode` and `conventionalCode` links are relationships, not
  authority to merge stations or observations.
- Use the national station registry for coordinates, elevation, operational
  condition, subtype/category and administrative codes. Enrich matching stations
  with PHISIS detail `waterBody` and `waterBodyType`. Do not propagate metadata
  through unproven aliases or invent river names for stations without them.
- Publish supported descriptive metadata through the shared metadata machinery.
  Preserve source vocabulary and unknowns; do not infer normalized operational
  judgement from codes. Missing optional metadata does not block independent rows.
- Station elevation is explicitly bound by the publisher frontend to metres above
  sea level. This does not establish a named vertical datum. Generic WGS84 help
  was not an explicit station-registry CRS declaration. Certify any adopted CRS
  from applicable evidence or retain `unknown`; do not cite generic help as a
  station-specific declaration.

Derived offline station metadata and product/association tables have maintainer
disclosure approval, subject to mandatory SENAMHI attribution in
`ProviderInfoCatalog.citation` and `STATION_METADATA_NOTICE`. Review the actual
published artifacts. Raw observations and restricted acquisition receipts must
remain private.

## Product associations and limits

Keep PHISIS monitoring and the monthly station archive distinct. Do not equate
their water-level series. Retain source identities and units needed for later
series mapping without claiming statistics, time zones or temporal support that
have not been established.

The bounded investigation checked every monitoring station-variable pair at
DAILY and HOURLY resolution, every selected station's monthly-period route, and
the latest published month where periods were returned. This is sufficient for
the step-2 catalogue; a complete historical month-by-month scan is not required.
It does not establish an exhaustive historical product inventory.

Account for these witnessed cases:

- PHISIS has 101 discharge and 63 water-level station-variable pairs. Daily
  samples contain published values for all pairs. Five hourly windows are empty
  but explicitly identify the requested station, resolution, variable and unit.
  Preserve recognized hourly associations without claiming populated history.
- PHISIS level units distinguish 46 `m` from 17 `m.s.n.m` pairs. Station `levelType`
  contradicts observation units at 15 stations. Use response units for the
  physical distinction, without inferring a named datum from `m.s.n.m`.
- Of 771 period requests, 259 returned nonempty lists, two returned successful
  empty lists and 510 failed with a station-deactivated/no-data message. Those
  failures include 59 stations labelled functioning. Preserve failure identity
  and reason in the evidence; neither status nor failed requests establish
  historical observation absence.
- Of 259 latest-month samples, 258 publish water-level fields. ILAVE's latest and
  immediately preceding sampled months publish only meteorological fields. Keep
  its PHISIS products; archive water-level availability remains unestablished.
- Monthly water-level fields include conventional `NIVEL_DEL_RIO_06H`, `10H`,
  `14H`, `18H`, `PROMEDIO`, automatic `N_NIVELAGUA`, and additional
  `N_NIVELMEDIO`, `N_NIV_INST_00`, `N_NIV_INST_10` fields. Preserve distinct source
  fields and their evidence. Do not silently omit them or map them to equivalent
  series without support. Precise meanings and temporal support belong to #605.
  Rainfall and other meteorological observations remain outside scope.
- Four latest monthly responses publish December 2026 dates and non-null values,
  later than the October acquisition. Preserve originals without correction.
  Do not publish sampled dates or listed periods as verified record boundaries.
  Carry the anomaly into series-meaning and retrieval research.

## Evidence and reproducibility

Continue the existing private
[research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/pe-senamhi-source-access.md).
Retain Freddy's work and append the new findings, including the CRS qualification.
The earlier collection `pe_senamhi-access-2026-10-30-v1` remains its own acquisition;
new responses must not replace it under that identity.

The completed local campaign retained 1,524 independent original-body/receipt
pairs, including failed responses, three publisher frontend assets and an earlier
ILAVE month. Local byte-size and SHA-256 checks passed, and request-start spacing
was at least 1.05 seconds. These checks establish capture integrity, not archive
acceptance or source certification. Obtain the restricted local recovery material from the maintainer handoff
before intake; it is not yet an approved portable archive input. Missing access
to that capture blocks its adoption rather than authorizing fabricated replacements.

Review and ingest the new capture through the private archive's existing process.
Preserve request identities, exact bytes, failures and limitations. Select exact
retained inputs and reviewed code revisions for the build and certification.
Update the private record before treating the new research as durable evidence.
No public package, issue or test output may include restricted bodies or receipts.
Any necessary additional source requests remain bounded and at most one per
second; do not depend on live service access in CI.

Implement the reproducible catalogue transformation and focused behavior tests.
Extend shared catalogue rebuild and evidence contracts, including private
source-certification checks where needed. Verify metadata joins, unknown
availability, identity separation and the named exceptions above at the simplest
sufficient level. Verify offline discovery, deterministic rebuilding, provenance,
attribution and distribution contents. Review candidate products before copying
approved artifacts into the provider's catalogue directory.

## Completion and downstream handoff

Complete #604 only after the source-backed catalogue is built, independently
reviewed and verified against genuine retained inputs. Run affected
source-independent tests and the applicable full genuine-input checks. Missing
mandatory evidence is blocked, not a passing or skipped check. Record exact
revisions, selected collections, checks and remaining limitations.

The fresh implementing agent may choose reversible builder and test details.
It must not broaden this work into observation fetch/parse implementation or full
provider acceptance. Hand off additional field semantics, physical distinctions,
time conventions and date anomalies to [#605](https://github.com/RivRetrieve/RivRetrieve/issues/605),
and request-window, completeness and source-failure behavior to
[#606](https://github.com/RivRetrieve/RivRetrieve/issues/606).
Keep later integration and final review Efforts open.
