# Streamline `AGENTS.md`

## Outcome

Reduce RivRetrieve's root `AGENTS.md` from a project history and provenance register to a concise set of universal working instructions. It should contain the shared working guidance used by `../pyplate/AGENTS.md` and one short paragraph that explains what RivRetrieve is.

The change matters because instructions loaded for every task should be brief, stable, and generally applicable. Provider acquisition campaigns, catalogue attestations, temporary migration states, and architectural explanations should remain discoverable without consuming the instruction file.

## Target instruction file

Use the version of `../pyplate/AGENTS.md` present on the target branch as the universal baseline. Preserve RivRetrieve's actual package description in place of pyplate's placeholder, but compress it to one short paragraph. That paragraph should state the essential promise and boundary: RivRetrieve provides faithful, traceable river-gauge access through one consistent shape; it harmonises objective identity and physics while leaving source judgement uninterpreted.

Adopt pyplate's current synchronized doctrine block, including its explicit four-rule list and synchronization markers. The remaining universal sections should continue to cover the `uv` environment, design doctrine, and complex-data testing guidance.

Do not retain extra RivRetrieve-specific operating rules in `AGENTS.md`, even as a condensed provider or catalogue section. In particular, the file must not contain provider-specific instructions, acquisition attestations, request URLs, retrieval timestamps, row counts, digests, coordinate comparisons, temporary enrolment status, catalogue campaign history, fixture provenance, or observation-recording policy.

## Relocation and information ownership

Removing material from `AGENTS.md` must not make current evidence or active decisions untraceable.

- Provider-specific material belongs in a dedicated provider space. The repository already has `docs/provider_ports/<provider>.md`; these documents, or a more clearly separated per-provider provenance area if warranted by the content, should own each provider's source details and attestations.
- Cross-provider architectural decisions belong in ADRs or focused design documentation. ADR 0012 and ADR 0013 already establish catalogue origins and committed-native catalogue builds. ADR 0024 already establishes real recorded observation fixtures and exact replay behavior. Link or extend the authoritative document instead of duplicating its rules.
- Current machine-verifiable facts should remain authoritative in catalogue provenance records, manifests, generator declarations, and tests where those representations already exist. Markdown should preserve rationale and evidence that cannot be recovered from them.
- Other still-active conventions that do not belong in the universal baseline need an appropriate focused developer or design document.
- Obsolete narrative, superseded intermediate interpretations, and duplicated historical explanation may be removed. Substantive evidence needed to audit a current provider or shipped artefact must be retained outside `AGENTS.md`.

The implementing agent should classify the existing material rather than move the entire large section verbatim into one new catch-all document. Provider facts should be distributed to their provider owners, shared decisions should point to their architectural owner, and duplication should be eliminated.

## Repository facts

At discovery time, RivRetrieve's `AGENTS.md` was approximately 61 KB while pyplate's was approximately 3.9 KB. The first four RivRetrieve sections already largely matched pyplate. Almost all excess content was in the packaged-catalogue section, followed by a shorter observation-recording section.

The current file contained 51 unique SHA-256 values that were not duplicated in Markdown under `docs/`. Their absence elsewhere does not prove that all are still required, because some may already be represented in structured provenance or tests. It does mean the migration must check each substantive attestation before deleting its only human-readable record.

Existing destinations include:

- `CONTEXT.md`, which is a glossary and must remain limited to terminology;
- `docs/adr/`, for accepted architectural decisions;
- `docs/provider_ports/`, for provider-specific source, mapping, and port information;
- provider catalogue `provenance.json`, committed native tables, manifests, fixtures, and tests, for machine-verifiable evidence.

## Evidence of completion

The work is complete when:

1. Root `AGENTS.md` is comparable in scope and size to `../pyplate/AGENTS.md`.
2. It contains only the universal baseline and one short RivRetrieve introduction paragraph.
3. It follows pyplate's synchronized doctrine form rather than retaining local drift.
4. Searching `AGENTS.md` finds no provider-by-provider attestations, provenance hashes, capture histories, or temporary catalogue regimes.
5. Every active shared rule removed from `AGENTS.md` has an authoritative home in an ADR or focused document.
6. Every substantive provider-specific fact needed for current traceability has a dedicated provider or structured provenance home.
7. Existing references remain valid, and documentation checks and the normal repository test suite pass.

## Exclusions

This work does not change provider behavior, catalogue contents, observation behavior, provenance semantics, or accepted architecture. It reorganizes documentation and removes obsolete duplication. It must not use the cleanup as a reason to reopen provider decisions or regenerate catalogue artifacts.
