# Public catalogue coverage and preserved-access account

2026-09-21 source snapshot. All counts are acquisition facts, not acceptance constants.

| Publication source | Stations | Coverage |
|---|---:|---|
| HubEau hydrometry | 6475 | Source count and returned rows agree; next=null; 21 additions and zero removals from old 6454 |
| HubEau temperature | 872 | Source count and returned rows agree; next=null |
| HydroPortail | 6409 | Anonymous national search, active+closed, all five site types including PONCTUEL, test entities included |

HydroPortail returns 9271 sites; only their 6409 nested station identities become station catalogue records. There are 3527 active, 2289 closed and 593 inactive stations. All full station IDs, station labels and explicit station/site relationships match their HubEau counterparts. Source precision remains independent.

## Population differences

The default test-excluding HydroPortail request omitted 20 additional stations. Explicit test=1 retains these existing supported stations. The source labels this control “Inclure les entités d’essai”. One direct identity witness (H312042201) says “Station hydrométrique d’essais Oui”. Search response objects do not themselves publish a test boolean; preserve query/differential evidence rather than inserting an inferred per-station metadata flag.

After including tests, 66 HubEau IDs remain outside native HydroPortail public search. Of these, 65 occur in the old supported catalogue. O811352002 is the single newly acquired HubEau gap. Every one of the 66 native identity-page requests returned HTTP404. There were no network failures, unchecked identities, or authenticated fallbacks. Exact requests/statuses are in `evidence/reconciliation.tar.xz!unmatched-stations.json` and individual `missing-CODE.receipt.json` files. HTTP404 does not establish station nonexistence or absence of past measurements.

Independent regional Mayotte and Dordogne searches exactly match the national subset. The native client uses a single array-returning request and client-side display pagination. A targeted search for site 40510003 retains station 4051000301 but not 4051000302, ruling out a national-only search cap as the explanation for that gap. Source legal/about pages limit grand-public service publication to public reference entities and data. They do not explain why any specific gap is not published. Do not label these records private, deleted, invalid, or historically empty without further evidence.

## Existing availability evidence

The old ledger's 130 instantaneous pairs for the 65 old gaps comprise:
- 116 recent HubEau-count-empty/history-unchecked pairs;
- 10 pairs with preserved failed HydroPortail historical checks;
- 4 positive HubEau observations_tr stage counts for X023000202, X105000302, X200064003 and Y644202001.

No gap pair has a positive HydroPortail historical witness. The four positive counts do not establish HydroPortail access. Retain these original source-scoped evidence facts without transferring the claims to the new HydroPortail provider. `evidence/reconciliation.tar.xz!unmatched-old-availability.json` preserves the complete affected ledger entries.

A bounded historical raw-series probe (2023-06-01, Q and H) for each of 4051000302, A430000201 and P352000101 returned HTTP404 for all six requests. Four further recent raw-H probes target the four positive HubEau-count identities (2026-09-20). All four returned HTTP404. Their exact receipts remain separate from metadata evidence. These probes are source-access evidence only, not an observation census or proof of whole-history absence.

## Implementation implication

Use the independently acquired native HydroPortail inventory, including test entities. Do not populate 66 unavailable native identities by copying HubEau metadata. Preserve all 6475 HubEau hydrometry identities in HubEau. Document the exact current native search/identity access difference and keep the original mixed acquisition ledger as historical evidence, not as current HydroPortail availability. For public native membership, all 6409 stations retain raw-Q and raw-H selectable unknown pairs unless a properly scoped HydroPortail witness exists.

No additional product or variant scope is required. The source has established specific anonymous inventory/identity access differences. If the owner requires old 65 gaps to remain discoverable under HydroPortail despite absent native publication, that requires an explicit outcome decision about independently sourced native identity evidence. It cannot be implemented by a silent copy or an unsupported completeness claim. Failure to access a gap now must not rewrite earlier data or receipts.

## Retained body locations

The repeated identity and bounded-observation HTTP404 bodies are exact members of
`evidence/supporting-captures.tar.xz`. Member names match the adjacent readable
receipt sidecars (`missing-CODE.body`, `gap-observation-*.body`, and
`gap-positive-count-*.body`). The archive changes storage only, not response hashes,
HTTP statuses, request scopes or retrieval times. Verbose reconciliation records
are exact members of `evidence/reconciliation.tar.xz`; [README.md](README.md) gives
the deterministic regeneration command and archive manifest.
