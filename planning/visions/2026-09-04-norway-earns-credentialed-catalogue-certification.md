# Norway earns credentialed catalogue certification

Program: https://github.com/RivRetrieve/RivRetrieve/issues/6
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/90

## Outcome

`no_nve` becomes a fully certified and publicly selectable built-in provider. Its catalogue is no longer an explicit empty withholding: a credentialed acquisition establishes a committed native table, acquisition provenance, complete origin declarations, and populated packaged catalogue artefacts that a credential-free checkout can rebuild and verify offline.

This closes the catalogue half of Norway. Its `LiveStages` observation adapter and recorded product proofs already exist. Once this effort lands, a user with `NVE_API_KEY` can select Norwegian station-product series and fetch them through the ordinary public surface.

The original ticket grouped Norway and Brazil because both catalogue endpoints require credentials. Discovery narrowed this effort to Norway so available NVE access can produce a usable provider without waiting weeks for ANA access. Brazil remains explicitly withheld and moves to a separate catalogue-certification Effort. Existing Effort #213 continues to own Brazil's observation token exchange and observation recordings; it does not become the catalogue effort by implication.

## The assurance boundary

A single authorized maintainer may make the credentialed NVE catalogue capture. Authentication restricts access to the request; it does not turn the published station response into a secret. The repository must state this human capture boundary rather than imply that every reviewer independently contacted NVE.

The durable, secret-free acquisition record identifies:

- the exact non-secret requests for both `Stations?Active=1` and `Stations?Active=0`;
- the UTC retrieval instant for each response, or one campaign instant if the acquisition is atomic;
- the complete response bytes, retained as audit evidence outside the wheel;
- raw response digests and byte sizes;
- response-row, accepted-row, and distinct-station counts, including overlap between the active and inactive sets;
- deterministic canonicalization and ordering rules;
- the committed native-table identity and semantic digest; and
- an exact semantic-frame comparison between a fresh materialization of the retained responses and the committed native table.

A reviewer does not need an NVE credential. Independent review verifies request completeness, secret absence, response and native-table identity, deterministic materialization, acquisition-provenance closure, canonical build reproducibility, and origin declarations offline. A later credentialed fetch is a refresh or corroboration, not a prerequisite for accepting the first capture.

`NVE_API_KEY` may exist only at the composition root and in the outgoing `X-API-Key` request header scoped to `https://hydapi.nve.no`. The value must not enter a command line, source response recording, native table, provenance, receipt, issue, warning, exception, log, generated artefact, or provider display. The established credential contract remains unchanged: the process environment takes precedence over `./.env`, and `.env.example` names the required variable without containing a value.

## Native truth before canonical facts

Credentialed refresh and credential-free build have distinct authority. Refresh obtains and records NVE's station response in the source's vocabulary. Build receives only the committed native table and origin declarations, performs no network access, and produces the canonical catalogue.

The native acquisition preserves the complete source structure and values needed to audit the result. It does not silently discard malformed rows, duplicate identities, missing coordinates, or malformed `seriesList` members. An incomplete request set, unexpected response shape, unexplained duplicate, or unaccounted row loss refuses the refresh. Any deliberate row withholding is explicit acquisition provenance, not an absent row whose reason must be guessed.

Historical counts of 4,889 stations and 44,001 station-product rows are comparison evidence, not acceptance thresholds. The certified population is what the complete attested acquisition publishes at its recorded instant.

Station-product availability follows exact NVE `seriesList` parameter and resolution pairs. A published matching pair establishes availability. A well-formed complete list without a matching pair can establish unavailability. Missing or malformed source structure cannot be converted into an assertion that NVE publishes no series. No product, unit, statistic, coordinate reference system, or availability is inferred from the country, the legacy canonical artefacts, or the retired implementation.

Every canonical station column has one complete origin declaration under ADR 0012's existing forms. The real build passes the origin gate. Removing any declaration, naming a native column that was not acquired, failing to propagate a native value, emitting a different documented constant, or making an unevidenced not-published claim fails loudly.

## Certification and distribution

`no_nve` joins `ORIGIN_GATE_ENROLLED_PROVIDERS` only in the same valid repository state that contains its committed native table, complete declarations, acquisition provenance, populated catalogue artefacts, and executable proofs. There is no partially certified state inside the enrolled provider.

The enrolment boundary remains separate from the built-in provider manifest after Norway joins. It records which providers have been audited rather than which providers ship. `br_ana` therefore remains registered, withheld, and outside the gate, and any future built-in remains uncertified until explicitly audited.

The native table is a repository build input. The retained acquisition responses are materialization audit evidence, not canonical-build inputs. Neither ships in the wheel. The wheel contains the populated canonical catalogue and the acquisition-provenance identity required to trace its available facts. This follows Effort #51's delivered wheel contract and supersedes ADR 0013's stale statement that native tables ship in wheels; this effort must not restore that obsolete consequence.

## Evidence of success

A fresh checkout with no NVE credential can demonstrate all of the following:

1. The retained response bytes match the acquisition record's sizes and digests, and the complete expected NVE request set is present.
2. Fresh native-table materialization from those responses is semantically identical to the committed native table.
3. The canonical catalogue rebuild is network-free and byte-identical to the committed packaged artefacts, apart from any already documented non-semantic build timestamp treatment.
4. The real origin gate accepts every declared canonical station column and rejects each declaration when removed or contradicted.
5. Acquisition provenance binds every available packaged fact to NVE and its recorded acquisition, with no unexplained fact or row.
6. Public discovery exposes populated Norwegian products and stations. `find` can select a real Norwegian station-product edge instead of returning `no_catalogue_edge`.
7. The existing observation path becomes reachable through the public selection surface for a user who supplies `NVE_API_KEY`.
8. Secret-sentinel tests prove that credential values cannot reach any durable or user-visible output.
9. The built wheel contains no native table, retained source response, `.env`, credential, or other catalogue build input.
10. Brazil remains explicitly withheld and unselectable, with no accidental legacy catalogue facts restored.

Completeness and secrecy tests exercise the real acquisition and packaging boundaries. They do not substitute a small fixture for the full source response or prove leakage safety only through a mocked proxy.

## Boundaries

This effort does not:

- change credential precedence, add a secret store, or automate API-key acquisition;
- require credentials for offline build, review, installation, catalogue browsing, or selection;
- implement or change Brazil's catalogue acquisition;
- implement Brazil's observation token exchange or recordings owned by Effort #213;
- change Norway's already delivered observation semantics or recordings;
- introduce a new provider kind or fold origin certification into provider registration;
- establish a recurring live refresh, drift monitor, or scheduled credentialed CI job;
- treat historical generated catalogues as native source evidence; or
- expose native tables or credentialed response recordings through the public API or wheel.

A separate Program Effort must apply the same credentialed-acquisition assurance to Brazil when ANA access becomes available. That future work reuses the existing credential mechanism rather than reimplementing it.
