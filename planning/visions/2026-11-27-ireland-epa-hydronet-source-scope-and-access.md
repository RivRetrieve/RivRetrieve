# Ireland EPA HydroNet: source, scope and access

Establish Step 1 of the `ie_epa` port: who publishes EPA HydroNet data, which
stations and products RivRetrieve will cover, how they are reached and under
what terms. Later Efforts build the catalogue, physical meanings and retrieval
on this boundary. Implementation of this vision completes
[#1101](https://github.com/RivRetrieve/RivRetrieve/issues/1101), Step 1 of
[Program #875](https://github.com/RivRetrieve/RivRetrieve/issues/875). Follow
[Step 1 of the provider-port guide](../../docs/maintenance/provider-ports.md#1-source-scope-and-access)
and the [Program plan](2026-11-27-ireland-epa-hydronet-porting-plan.md).

The research in #875 is an exploratory lead. A live recheck on 2026-11-27
confirmed much of it but contradicted several claims, noted below. Recheck
anything this vision relies on when capturing evidence.

## Source and access

EPA HydroNet is a static KISTERS WISKI Web Public export under
`https://epawebapp.epa.ie/Hydronet/output/internet/`. On 2026-11-27:

- `stations/stations.json` listed 3,155 register stations with 44 fields,
  including `site_no`, `station_no`, `object_type`, `RESPONSIBLE_BODY`,
  `STATION_OWNER`, `station_status`, `DATA_AVAILABLE` and `Web_Link`.
- `stations/sites.json` listed 8 regional folders: `ATH`, `CAS`, `COR`, `DUB`,
  `KIK`, `LIM`, `MON` and `NI`. #875 says 7.
- Each station manifest, `stations/{site_no}/{station_no}/index.json`, lists its
  hosted `.zip` files. Manifests returned `200` even for stations without files
  and carry `Last-Modified` and `ETag` headers.
- Access was anonymous. The host had no `robots.txt` (`404`) and no stated rate
  limits or automated-access rules were found. Keep requests at about one per
  second.
- The FAQ says telemetry is uploaded every six hours.

Treat `LiveStages` without credentials as the working access kind and confirm it
while establishing the provider declaration facts. The provider identifier is
`ie_epa`.

## Terms and attribution

The licence pages are under `/Hydronet/output/html/`, not the paths given in #875:

- [Disclaimer](https://epawebapp.epa.ie/Hydronet/output/html/disclaimer.html):
  "This data is open data and is licensed under a Creative Commons Attribution
  4.0 International License (CC BY 4.0)." It also requires users to make third
  parties who receive the data "fully aware of the notes, warnings and
  conditions of use".
- [FAQ](https://epawebapp.epa.ie/Hydronet/output/html/FAQ.html): describes the
  data and quality codes; it states no licence.
- [data.gov.ie `water-levels-and-flow`](https://data.gov.ie/dataset/water-levels-and-flow):
  `CC-BY-4.0`, and "The sites are owned by Local Authorities and operated by the EPA."

The licence wording has no explicit exclusion for stations run by other
agencies; #875 inferred one. The agency boundary below makes that question moot.

Settled: do not contact the EPA. The published CC BY 4.0 statement suffices.
Meet the pass-on condition by linking the disclaimer and FAQ from the provider
page and from the catalogue's provenance or attribution metadata, as other
providers do.

## Station scope

`ie_epa` covers EPA-run river and stream gauges.

- **Agency boundary.** Include stations where `RESPONSIBLE_BODY` is
  `Environmental Protection Agency`. HydroNet also hosts files for a few
  stations run by other agencies, contradicting #875. The recheck found
  `26243`, `06036`, `38010` and `18027` (OPW) and `30111` (Teagasc, owned by
  Mayo County Council). Exclude them and record the exclusion. Only 49
  non-EPA stations were sampled, so check every non-EPA manifest during Step 1
  to make the list of exclusions complete.
- **Hosted files.** Determine availability from manifest `.zip` links, not from
  `RESPONSIBLE_BODY` or the free-text `DATA_AVAILABLE` field. A station is in
  scope only when it hosts at least one in-scope `S` or `Q` file (see Products).
  Spot-only stations and stations without files have nothing to retrieve and
  are not included.
- **Shared with OPW.** The `ie_opw` port is not yet on `main`; see
  [#354](https://github.com/RivRetrieve/RivRetrieve/issues/354), branch
  `port/ie-opw` and `docs/providers/ie_opw.md` there. It retains five
  EPA-numbered gauges: `09045` and the Dún Laoghaire-Rathdown gauges
  `10047`–`10050`. HydroNet lists all five as EPA-responsible. Include them in
  `ie_epa` when they host in-scope files. Each provider's documentation should
  point to the other.
- **Water bodies.** Include rivers and streams. Exclude lakes and reservoirs
  (42 EPA stations, `object_type` `General;Surface water;Lake or Reservoir`) and
  springs (`General;Surface water;Spring`: `DUB/14100`, `ATH/26332` and
  `KIK/16025`). Lake and reservoir exclusions follow `ie_opw`, `at_ehyd` and
  `co_ideam`. Spring exclusions follow `at_ehyd` and the Slovenia port
  ([#1033](https://github.com/RivRetrieve/RivRetrieve/issues/1033)).
  Groundwater, NI stations and other agencies' redirect entries are out of scope.
- **Station status.** Include inactive and suspended stations that host files.

Record the lake, reservoir and spring exclusion in the private research record
as a scope question to revisit. Previous ports excluded standing water as a
river-focused convention without a recorded rationale. The
[USGS review](https://github.com/RivRetrieve/RivRetrieve/issues/629) includes
lakes and reservoirs. A later cross-provider decision may bring them back.

## Products

Candidate products are water level (`S`) and discharge (`Q`) at daily and
15-minute resolution. HydroNet publishes `complete_daymean`, `complete_15min`,
`1year_daymean` and `3_months` files for each. No surface-water temperature or
other parameter was found.

Exclude spot gaugings (`Q/complete_gaugings.zip`) at both spot-only and
continuous stations. About 1,169 EPA surface-water stations are listed as spot
measurements only. Some records reach back to 1978, and gaugings carry their own
codes (`Good`, `Fair`, `Poor`). Document that they exist, and record them as an
open scope question for all providers rather than a decision for this port.

User documentation should state the excluded lakes, reservoirs, springs and
spot gaugings briefly, as the `ie_opw` and `at_ehyd` pages do.

Later Efforts own these questions:

- **Step 2** establishes the exact station universe and file availability from
  manifests, applying the classification above. It also handles anomalies: an
  active station without rolling files and level-only stations hosting `Q`
  files.
- **Step 3** establishes relative versus absolute levels, historical datums,
  timestamps, DST and quality-code annotations.
- **Step 4** chooses between full-history and rolling files and handles empty
  files such as `#Rows;0`.

## Evidence and handoff

No `ie_epa` research record existed in the private
[verification-evidence](https://github.com/RivRetrieve/verification-evidence)
repository on 2026-11-27. Start one; the Ireland OPW source-access record is a
useful model. Capture small genuine originals through the archive's intake
process:

- `stations.json`, `sites.json` and the licence pages
- the data.gov.ie record
- representative manifests and `.zip` files, including every boundary case named
  above

Captures from the 2026-11-27 recheck were local and provisional. Recapture
originals through intake; do not archive those files.

Record the settled decisions, the contradictions with #875 and the open scope
questions. Post a safe public summary on #1101 and mark tracker
[#870](https://github.com/RivRetrieve/RivRetrieve/issues/870) as in progress when
work starts. Keep private material out of public issues and this repository.

Step 1 is complete when the research record and retained evidence support every
scope, access and terms claim above, or record any correction. Stop at the Step 1
handoff; do not begin Steps 2–7.
