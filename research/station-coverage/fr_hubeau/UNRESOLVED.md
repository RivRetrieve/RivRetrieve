# fr_hubeau — accounted limits and remaining delivery work

The Effort #225 vision settles the former route, survey and attribution-scope questions.
Nicolas owns remaining verification, implementation and acceptance. Do not restart a
research correction cycle or a survey to remove legitimate unknown states.

## 1. History unchecked — accounted, no survey required

6,604 recent-empty pairs have no historical check: 1,976 in-service and 4,628
out-of-service pairs. Whether another window has values is not established. They
remain selectable with unknown availability. Two empty windows would not establish
whole-history absence either. No further acquisition is required for accounting.

## 2. Failed historical checks — accounted, not empty

The governing partition retains 96 earlier failures and adds `J783301020` Q:
1–8 June 2026 HTTP 500, 1–8 June 2023 empty. The final total is **97 failures**
and **524 two-window empties**. A failure does not explain its cause or establish
absence. Do not retry these pairs to make the ledger look complete. Future user
requests still return measurements, valid emptiness or explicit source issues.

## 3. Station-own discharge — settled

A station selection returns its own Q via `/stationhydro/ajax/{code_station}/series`.
The complete private `1232000101` response verifies the station-Q route for 1 June
2026. Site access and activation calendars are outside scope. The old numerical
site/station comparison is an unsupported derived anecdote without full comparison
bodies; it is not the basis for this settled choice.

## 4. Organisation-name gaps — disclosed, not an expansion blocker

1,023 hydrometry stations are absent from `sa:StationHydro`; another 65 have blank
`NomIntervenant`. The original checks found neither closure nor station type explains
all gaps. No responsible measurement producer is inferred from these gaps. A new
Sandre/Hub'Eau enquiry is not a prerequisite under the official-publication scope.

## 5. Publication established; dataset-author citation remains unresolved

`NomIntervenant` names an organisation without a measurement role.
`ProducteurDuJeu` names a station-referential dataset producer, not the author of all
historical measurements. Official documents establish SCV's HydroPortail/PHyC role
and distinguish the Vigicrues network and external producers; Hub'Eau terms name OFB,
SCV and BRGM editors. The old three-station “producing SIE body” provenance claim
must be corrected during implementation, without inventing original producers.

The source requires: “L'utilisateur de ces données doit néanmoins veiller à citer l'auteur des Jeux de données.” The dataset-author question remains unresolved; a
publisher label does not satisfy it by itself. Preserve exact terms and citation words.
No new original-producer inquiry is required before expansion, and no licence or
redistribution conclusion follows from these publication facts.

## 6. Full-body evidence and publication boundary

The governing private corpus supplies full primary count bodies, retained empty/error
bodies and exact replacement numerical witnesses. It does not recover discarded old
positive bodies. **59 precise old historical totals are retired**, replaced by one-day
witnesses with their own URLs and acquisition dates. Old site/station comparisons
remain historical unsupported derived anecdotes, not certified governing facts.

Use `inventory/governing_evidence.json.xz` and
`inventory/retired_historical_totals.json`. Private verification is explicit:
`scripts/verify_governing_evidence.py --evidence-root PATH`. Public deterministic
ledger checks are not source certification. Arrange an authorised private handoff if
bodies are absent; do not substitute hashes or automatically rerun acquisition scripts.

Keep the private corpus outside distributed artifacts. The old research scanner is
not a project-wide ban on measurement values. Existing genuine-recording conventions
remain in force. Publication of minimal test recordings needs reviewed approval;
this document supplies no broad legal permission or prohibition.

## 7. Source facts not established by this research

- **Per-station product availability.** Neither referential declares it; `grandeur_hydro` is the
  constant `Q` for all 9,284 sites and `date_premiere_donnee_dispo_site` is empty for all.
- **Timezone of the daily and temperature products.** No captured source establishes one.
- **Published record bounds.** Counts establish that observations exist, not the span they cover.
- **Rate limits.** No rate-limit statement was established in the inspected/captured
  evidence. Absent `X-RateLimit` or `Retry-After` headers and the inspected OpenAPI
  specification do not establish that no limit exists or that none is published elsewhere.

---

## 8. The hard-coded HydroPortail identity map — REPORTED, NO DECISION NEEDED

`fetch.py` holds `_HYDROPORTAIL_IDENTITIES` with one entry and raises for any other station. The
mapping is published as `code_site` for every hydrometry station and matches for `Y251002001`.
Remove this sample-only gate during implementation and validate station-own Q.
Production code is out of scope for these research edits. See `ROUTE_DECISIONS.md` §3.
