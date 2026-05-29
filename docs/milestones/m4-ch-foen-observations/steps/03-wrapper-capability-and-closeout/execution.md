# 03-wrapper-capability-and-closeout Execution

## 1. What Landed

- `src/rivretrieve/_internal/discovery.py` - added `_provider_lookup = provider` after `provider(...)` and `observations(...)` as a delegation-only free function.
- **Atomic public-surface checkpoint:** `src/rivretrieve/__init__.py` and `tests/test_package.py` re-exported `observations` and expanded T119/T120 together.
- `tests/test_observations_wrapper.py` - added spy delegation, required-keyword negative controls, and default `on_issue` forwarding tests.
- `tests/test_ch_foen_observations.py` - added fixture-backed `rr.observations(provider="ch_foen", stations=["2206"], ...)` smoke coverage.
- `src/rivretrieve/_internal/providers/ch_foen/generate_catalogue.py` and `src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json` - updated `bulk_observations` to the descriptive M4 value and regenerated only `provider.json`.
- `tests/test_ch_foen_generate_catalogue.py`, `tests/test_ch_foen_capabilities.py`, and `tests/test_internal_catalogue_schemas.py` - added generator-side, write-path, loader/runtime, schema, and intra-JSON drift coverage for the capability string.
- `docs/provider_ports/ch_foen.md` - populated observation retrieval, annotation schema, issues, token handling, schema divergence, and pain-point sections with D10 legacy citations.
- `docs/milestones/m4-ch-foen-observations/REPORT.md` - wrote the M4 closeout report and M4 -> M5 handoff.

## 2. Test Count Delta and Negative-Control Results

- Start of step: 416 tests.
- End before version bump: 426 tests.
- Delta: +10 tests.
- T119 expanded by adding `observations` to the exact package-root public set.
- T120 expanded by removing `observations` from the deferred-name list while keeping `ObservationResult`, `ObservationRequest`, `ObservationProvenance`, `AnnotationSchema`, `AnnotationTable`, `RawPayload`, `Issue`, `CatalogResult`, and provider internals absent.
- Offline-import test: passing.
- Network-bypass sentinel `test_ch_foen_observation_client_default_transport_is_not_used_in_tests`: passing.
- Token-literal-absence test: passing.
- Delegation spy tests: passing, including exact kwarg forwarding and default `on_issue="warn"`.
- Real wrapper smoke: passing with station `2206`, 144 rows, `0.014..0.015` m3/s, `flow_ls` fallback, native `L/s`, converted `m3/s`.

## 3. Delegation Purity Audit

`src/rivretrieve/_internal/discovery.py:43-59`:

- Lines 43-51 define a keyword-only signature and default only `on_issue="warn"`.
- Line 52 calls `_provider_lookup(provider)`, preserving the existing lazy registration behavior through the original `provider()` implementation.
- Lines 53-59 return `provider_handle.observations(...)` with exact forwarded kwargs.

No wrapper validation, normalization, defaulting beyond `on_issue="warn"`, type coercion, issue routing, result construction, copying, or transformation was added.

## 4. Capability Declaration Outcome

- Before: `bulk_observations == "false"`.
- After: `bulk_observations == "true: 366-day window decomposition with stitched N x M station-product requests; partial failures reported as recoverable issues"`.
- Intra-JSON parsed comparison against `git show HEAD:src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json`: changed keys were exactly `{"bulk_observations"}`; the key set stayed identical.
- Artifact diff check: only `src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json` changed under the catalogue artifact directory.
- Generator-side tests: passing through `tests/test_ch_foen_generate_catalogue.py`.
- Loader-side test: passing through `tests/test_ch_foen_capabilities.py`.

## 5. Docs Population Summary

Added or populated these sections in `docs/provider_ports/ch_foen.md`:

- `Observation Retrieval`
- `Annotation Schema`
- `Issues`
- `Token Handling`
- `Schema Divergence from Legacy Wide-Form Output`
- `Pain Points`

Legacy citations use `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python` at `cd9b030` and cover `docs/fetchers/switzerland.rst`, `examples/test_switzerland_fetcher.py`, and load-bearing `rivretrieve/switzerland.py` line ranges. The stale M3 empty-annotation note was replaced with the M4 non-empty annotation-schema summary. Divergence from legacy wide-form pandas output is documented as intentional.

## 6. REPORT.md Write-Up Summary

`REPORT.md` contains the required nine sections: steps executed, public API shipped, internal types introduced, runtime dependencies, test delta and negative controls, discoveries, M4 -> M5 handoff, escalations, and ready-for-M5.

REPORT §7 includes all mandatory spot-checks: final `bulk_observations` value, new `observations` symbol plus T119/T120 baseline, D7/D9 cross-M4 firing status, and D10 legacy-citation method.

## 7. Tactical Fixes

- Added a permanent intra-JSON drift test that allows no changed keys outside `bulk_observations`; after the closeout commit, the same test remains useful even when `HEAD` already contains the new value.
- Kept wrapper annotation imports under `TYPE_CHECKING` so `import rivretrieve` does not pull observation internals at runtime because of type hints.

## 8. New Discoveries

No D11+ discovery was found or appended.

`L_D7_probe` did not fire: no Pydantic model with `extra="allow"` was added or changed.

`L_D9_probe` did not fire: step 03 does not walk provider JSON; the one JSON comparison uses concrete parsed dicts for `provider.json` drift checking.

## 9. M4 -> M5 Handoff Confirmation

REPORT §7 includes the M5 handoff facts for station-map work: packaged/offline station catalogue shape, coordinate availability, nullable elevation/drainage fields, observation timezone annotation pattern, schema-divergence boundary, token isolation, final `bulk_observations`, public-surface baseline, D7/D9 status, and D10 method.
