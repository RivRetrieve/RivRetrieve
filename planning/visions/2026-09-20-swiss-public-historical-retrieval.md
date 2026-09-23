# Swiss public historical retrieval

## Outcome and scope

Address [bug #305](https://github.com/RivRetrieve/RivRetrieve/issues/305): historical Swiss observations available from Existenz must be reachable through ordinary public RivRetrieve retrieval. Users must not need an account, personal credentials, a manually copied public token, or internal transport APIs. RivRetrieve must handle Existenz’s published shared read-only archive authentication internally.

This is standalone software work. It is not an Effort under a Program. The user paused their documentation review after discovering this defect. Leave [PR #289](https://github.com/RivRetrieve/RivRetrieve/pull/289) open and unchanged. Do not edit its branch, rewrite its page, merge it, or resume its review. The user will return to the documentation agent separately after the bug is fixed. Leave `planning/visions/2026-09-20-swiss-provider-documentation-review.md` unchanged as well.

Publishing this vision does not authorize starting implementation. The implementation handoff covers the bug and directly necessary verification, not the Swiss documentation review or unrelated provider cleanup.

## Confirmed problem

At investigated main commit `431699b8ecca55e8fcb013b04fd17a0a22f014a5`, public `rr.fetch` constructs a bare `HttpClient` for Switzerland. The Swiss declaration has no required credentials or credential bindings. Both the provider fetch function and its window-declaration selection choose Flux only when the supplied transport can authenticate the archive endpoint. Requested age does not select a route. Consequently, public historical retrieval always reaches the recent-only REST service instead of the archive.

Existenz’s published source documentation describes a 32-day REST horizon and an InfluxDB archive at `https://influx.konzept.space/api/v2/query`, with organization `api.existenz.ch`, bucket `existenzApi`, and a shared read-only token. No personal credential setup is required, but archive HTTP authentication is required. Recheck the published access arrangement during implementation without exposing token values.

The actual public reproduction reported in #305 was:

```python
import rivretrieve as rr

selection = rr.find(provider="ch_foen", station="2018", quantity="discharge")
result = rr.fetch(selection, start="2024-01-01", end="2024-01-31", receipts=True)
print(result.data.height)
print(result.issues)
print(result.provenance.calls_made)
```

It returned zero rows with `source.unsupported_series`, reason `Swiss REST response lacks payload object`. The REST response was HTTP 200 with `payload: []`. This is not the earlier HTTP 500/FatalContractError report in PR #289. A read-only replay through actual public credential resolution and client construction reproduced the REST route and issue; only the low-level HTTP sending boundary was intercepted.

A direct archive query using the published read-only access returned five January 2024 `flow` observations. During this discovery, those exact captured CSV bytes passed through the real Swiss parser successfully. It returned the five values `108.045, 108.045, 108.182, 108.32, 108.045` at January 1 UTC labels `00:00, 00:40, 00:50, 01:00, 01:10`, with source unit `m3/s`. The absent `flow_ls` field remained unresolved. This establishes basic parsing of that capture only. Its limited single-field query is not the production padded, multi-field request and proves neither full January coverage nor all archive response forms.

## Access and behavior constraints

Resolve source access and authentication at explicit composition boundaries. Lower-level provider operations must consume resolved dependencies, not discover application state or circumvent shared transport protections.

The user settled internal token management, not a specific provisioning mechanism. Choose whether to bundle the published token or acquire it automatically using source evidence, reliability, token-change behavior, and maintenance costs. Do not make users manage it. Do not introduce a general credential-management system or new public route controls solely for this defect. Record the choice and evidence in implementation delivery, not a new ADR.

Keep authentication restricted to the intended archive origin. Preserve the existing credential authority, redirect protections, and redaction behavior. Do not expose token values through URLs, query parameters, Flux bodies, representations, logs, exceptions, provenance, receipts, or exported bundles. If automatic acquisition reads a credential-bearing source document, do not retain that document as an ordinary observation receipt.

Preserve recent Swiss retrieval. Do not assume archive-only access has identical recent freshness or field coverage without evidence. The exact route-selection mechanism is an engineering decision, but it must make supported historical windows reachable and must agree with the engine’s route-specific window rendering. If date-dependent routing is used, account for padded fetch bounds and windows crossing the REST horizon.

The engine continues to own padding, rendering, and clipping. REST uses inclusive stops; Flux uses exclusive stops. Preserve the public closed requested interval, including its final eligible observation. Do not shift rendered bounds independently inside the provider.

Retain source failures and their reasons alongside independent successful results. An authentication or archive failure must not silently fall back to historical REST and become apparent missing data. Keep malformed source responses distinct from valid empty results and from fatal internal contract violations. Repair directly encountered parser or boundary defects needed for the real archive path if evidence establishes them; do not expand into speculative parser redesign.

Preserve source field identities, units, and unknowns. In particular, `flow` and `flow_ls` remain distinct; litres per second convert to cubic metres per second. Catalogue candidates do not prove field availability. Absent `flow_ls` must not become an invented observation or successful empty acquisition. Do not infer frequency, temporal support, statistics, vertical references, or complete station/window coverage.

## Acceptance evidence

Follow regression-before-fix: add a test that fails on existing production code before changing that code, then make the same test pass.

The primary regression must call public `rr.find` and `rr.fetch`, optionally narrowing with `rr.pick(..., variant="flow")`, while preserving the real provider declaration, credential resolution, transport construction, and route/window planning. Intercept only the actual HTTP boundary. Instrument and assert the chosen route so the old implementation demonstrably enters historical REST. Do not patch the client factory to return an already-authenticated transport, which bypasses this bug.

Replay real source response bytes with truthful request matching. The existing five-row limited archive capture may prove parsing, but it must not masquerade as an exact recording of the different production query. Acquire suitable production-request evidence as needed. Assert archive POST, organization and Flux bounds, correct scoped authentication, returned values and timestamps, units, final clipping, and faithful observation receipts. Use library-specific frame assertions.

Cover recent retrieval, relevant boundary windows, authentication failure reporting, and token non-disclosure. Verify the public historical call without personal credential configuration. An unrestricted discharge selection must preserve successful `flow` rows alongside unresolved field availability where the response warrants it.

Execute the actual historical example through public RivRetrieve against the live source after the repair. Check the complete production response through parsing, conversion, clipping, and assembly. Report observed rows and fields without claiming complete month coverage. Distinguish live results from recordings. If upstream availability prevents live verification, report the blocker and retained evidence rather than declaring end-to-end live success.

Run the relevant regressions and repository checks using `uv` exclusively. Follow project instructions for formatting, linting, and type checking (`uv run ty check src`). Deliver concise failing-before/passing-after evidence, source-access verification, remaining limitations, and the implementation PR reference so the user can separately resume PR #289.

## Repository and evidence anchors

Recheck these against the implementation checkout:

- `src/rivretrieve/_internal/discovery.py`: public composition, `_resolve_credentials`, `_credentialed_transport`.
- `src/rivretrieve/_internal/transport.py`: authentication capability, credential binding and protection.
- `src/rivretrieve/_internal/providers/ch_foen/{declaration,config,fetch,parse}.py`: route selection, source windows, request construction, decoding.
- `docs/architecture.md`: composition boundaries, engine-owned windows, source failure isolation, provenance.
- `tests/test_ch_foen_fetch.py`, `tests/test_ch_foen_parse.py`, `tests/test_ch_foen_public.py`, and `tests/test_source_field_public.py`.

Existing Flux tests inject authenticated transports. `tests/test_source_field_public.py` also replaces the public client factory with one returning an authenticated transport. These tests do not establish ordinary public archive reachability.

Local investigation evidence is under `.worktrees/evidence/swiss-provider-documentation-review/`: public scripts/logs, historical and recent REST bodies, redacted source documentation, archive metadata, and `public-archive-response.csv`. These files may not exist in another checkout. Issue #305 preserves the reproduction and source-access findings; acquire safe source recordings if needed. Do not commit credential-bearing artifacts or treat local captures as current live verification.
