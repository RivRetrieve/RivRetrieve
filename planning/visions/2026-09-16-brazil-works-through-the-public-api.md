# Brazil works through the public API

Related issue: https://github.com/RivRetrieve/RivRetrieve/issues/213

## Outcome

Brazil's ANA provider is usable end to end through RivRetrieve's normal public API: a caller can discover evidenced station/product selections, supply their own credentials, retrieve observations, and inspect faithful values and provenance in the same shape as other providers. Catalogue certification and observation retrieval are one contained outcome, not separate tickets. Merely implementing an adapter while all Brazil stations remain withheld is not delivery.

This work does not plan a release, publish a package, or change the eleven-provider first-release commitment. It does not wait for release planning. The existing Brazil follow-up issue is #213; its former observation-only boundary is superseded by this confirmed end-to-end scope. Historical decisions and evidence remain preserved rather than relabelled as delivered.

## Starting evidence

At main `078ed1a`, `br_ana/declaration.py` declares `CatalogueOnly` and requires `ANA_IDENTIFICADOR` and `ANA_SENHA`. The generator retains deferred catalogue acquisition provenance. Norway's completed certification is not Brazil's certification. Existing Brazil product definitions and legacy payloads are leads to investigate, not proof of published products or station availability.

The shared `CredentialExchangeTransport` and `ExchangeSpec.ana()` exist in `src/rivretrieve/_internal/authentication.py`, with authentication tests. The ANA specification currently names the GET token endpoint at `https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/OAUth/v1`, the `items.tokenautenticacao` token field, and source-scoped bearer authentication. This is reusable infrastructure, not an already-operational Brazil integration: the current public composition root wires direct header credentials, and Brazil remains catalogue-only. Reuse and complete the shared authentication path rather than adding a second provider-owned credential system.

ANA confirmed account registration and directed the user to `https://www.ana.gov.br/hidrowebservice/swagger-ui.html#/`, with the tutorial under Documentation. Password reset is at `https://www.snirh.gov.br/hidrotelemetria/Login2.aspx`. Registration confirms account issuance, not a successful token exchange or observation request. Verify actual behavior against official documentation and real responses during implementation. Do not copy the registration email, account identifier, password, or tokens into repository evidence.

## Catalogue and public access

Acquire ANA's station inventory with traceable source identity and acquisition records. Build the canonical catalogue from the native table, establish per-column origins, and enroll Brazil in the existing origin-certification guarantees. Preserve source vocabulary and unestablished facts without inferring source silence. Reproduce the resulting catalogue offline from admissible retained inputs under the repository's established distribution boundaries.

Expose evidenced station/product relationships through the existing selection and fetch surface. Account for the acquired inventory and explain withheld or inaccessible records; do not substitute a handpicked demonstration catalogue for national-source support. A station's presence alone does not prove every product is available, and one empty request does not prove a product never exists. Retain the repository's distinction between available, unavailable, unknown and withheld evidence. Do not invent a universal station count or promise that every station supplies every measurement.

Update Brazil's acquisition provenance and Croissant descriptor with the catalogue. Preserve already-established ANA source terms and citation evidence where valid; surface the source's words without interpreting permissions. Native tables, private acquisition inputs and credentials must respect existing package-exclusion rules.

## Observations

Implement Brazil as an authenticated `LiveStages` provider on the shared engine. Cover the daily columnar and telemetric endpoint families wherever real evidence establishes their published products. Discharge is central; retain other existing candidate measurements only when their identity, units, statistics, semantics and source responses are established. Do not synthesize daily means or other products the source does not publish.

Investigate documented request limits, including the recorded lead that telemetric requests are capped at 30 days. Declare product-specific window behavior using the existing engine vocabulary. The engine owns padding, splitting, rendering, clipping, unit conversion and result assembly. Provider code contributes source request construction, decoding and declarations, not private window arithmetic.

Return the established five-column observation frame, provenance, issues and opt-in receipts. Preserve native wall-clock time and source-established zones; do not infer zones from geography or promote a fixed offset to an IANA zone. Apply existing daily-label and requested-window semantics. Preserve the distinction between per-series source failures and fatal contract violations. Reuse existing cache behavior without inventing a Brazil-specific store.

## Credentials

Ship a tracked `.env.example` containing empty `ANA_IDENTIFICADOR` and `ANA_SENHA` placeholders, clear registration instructions, and ANA documentation and reset links. Keep any other supported provider placeholders. Actual values belong in the user's ignored local `.env` or process environment. Process environment values take precedence, as the current public credential resolver specifies; `.env` is read from the working directory, not silently copied into worktrees or packaged artifacts. ANA's identifier is not the account email address.

Read secrets only at composition roots and pass narrow credential inputs into the shared transport. Missing or rejected credentials must fail through the established safe interfaces. Bearer tokens and exchange credentials must not appear in logs, reprs, exceptions, requests saved as recordings, receipts, provenance, fixtures, PRs, or documentation. Verify refresh, expiry, origin scoping and redirect refusal on the actual integration path. Token-exchange responses must never become public observation recordings. Do not reconstruct credentials from chat history; use credentials provisioned locally by the owner and rotate any previously exposed password before live use.

A clarification to `.env.example` is currently an uncommitted change in the canonical working copy. Preserve that user-requested change; the implementation must reconcile it with the template requirement rather than discard it. Vision publication includes only this vision, not that unrelated working-copy edit.

## Evidence of completion

- Normal public discovery and selection expose Brazil's certified catalogue, and representative supported selections retrieve real ANA observations through the public fetch path.
- Every claimed provider-product has admissible, credential-free real source recordings and an independently authored boundary probe. The expectation author must not see the port implementation or its output; the three count/first/last literals are grounded in the recording and official documentation. Invented legacy payloads never establish expectations.
- Real recordings and executable tests cover daily and telemetric request boundaries as applicable, including capped-window splitting and the source's actual stop convention. Authentication tests establish that secrets cannot escape on success or failure.
- Catalogue origin, acquisition provenance, descriptor, reproducibility and packaging checks pass. Public selectability and observation support agree; documentation does not claim products or availability that evidence does not establish.
- Repository-native tests, lint and type checks pass. For bugs discovered during integration, add a test proving the actual failing path before changing production behavior.
- User documentation explains Brazil access, credentials, supported products and evidenced limitations. The retired `reference/legacy_observations/br_ana` subtree is removed only after its useful evidence is retained and its replacement is verified.

A registered account alone, a successful token exchange alone, a catalogue-only declaration, or an adapter reachable only through internal test construction does not satisfy this outcome.

## Boundaries and implementation authority

Follow `AGENTS.md`, `CONTEXT.md`, existing ADRs and source-evidence rules. Keep production names and modules about stable domain responsibilities, not the ticket number. Resolve reversible implementation mechanics from the repository and official sources. If ANA evidence contradicts an existing assumption, correct the assumption with recorded evidence rather than silently guessing. Escalate material changes to the promised outcome or inability to establish usable Brazil access.

No South Africa work, unrelated provider redesign, live station-discovery API, license interpretation, release publication, or automated account acquisition is included. Vision publication does not start implementation. Existing source behavior, access restrictions and missing evidence are risks to investigate, not reasons to claim completion without the public end-to-end result.
