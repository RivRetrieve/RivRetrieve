# 03-wrapper-capability-and-closeout — Adversarial Critique

## Verdict

**SEND BACK TO PLANNER.**

There is exactly one Major: the delegation body shown in §3 is broken Python (parameter `provider` shadows the module-level `provider` function, so `provider(provider)` resolves to `str("ch_foen")`), and the plan's proposed fix ("use a non-shadowing local name if needed, e.g. `provider_handle = provider(provider)`") doesn't address the shadow at all — it only renames the unused result. Because this collision is the entire mechanical core of the wrapper, executors deserve an unambiguous idiom in the plan rather than discovering the bug at test time. Minors (REPORT §7 gaps; the `[2206]` int-vs-str fixture identifier in test 5; D7/D9 firing-status omission) can be folded if the Major is rewritten.

## Major findings

### M1. `§3 delegation body shadows the module-level `provider` callable

§3 shows the delegation body as:

```python
return provider(provider).observations(
    stations=stations,
    products=products,
    start=start,
    end=end,
    on_issue=on_issue,
)
```

The wrapper has a keyword-only parameter `provider: str`. Inside the function body, Python LEGB resolves `provider` to the parameter (the `str` "ch_foen"), not to the module-level `provider()` function defined a few lines above in `src/rivretrieve/_internal/discovery.py:27`. The call `provider(provider)` therefore evaluates to `str("ch_foen") == "ch_foen"`, and the subsequent `.observations(...)` raises `AttributeError`.

The plan acknowledges the collision with: "Use a non-shadowing local name if needed, e.g. `provider_handle = provider(provider)`, so the parameter name does not obscure the existing `provider()` function." This is incorrect — assigning the result to `provider_handle` does not undo the parameter's shadow over `provider` on the right-hand side; both names still resolve to the parameter.

Workable idioms the planner must pick from (and pin in §3, not leave to the executor):

- Bind a module-private alias *after* the function definitions: `_provider_lookup = provider`, then `provider_handle = _provider_lookup(provider)`.
- Use `_registry.get(provider)` directly, mirroring `provider()` (and explicitly calling `_ensure_default_providers_registered()` first to preserve the lazy default registration semantics).
- House the wrapper in a new sibling module (e.g. `src/rivretrieve/_internal/observations_wrapper.py`) that imports `provider` from `_internal.discovery` and so does not shadow it.

This is a Major because (a) the literal §3 code is wrong, (b) the plan's own attempted workaround doesn't compile to the intended semantics, and (c) the choice between the three idioms is *plan-level*, not tactical — option 2 in particular re-implements lazy registration outside `provider()`, which is exactly the kind of "is this allowed to drift?" call the executor should not be making alone.

Note: the architecture.md / tracker signature commits the public keyword to `provider`, so renaming the parameter is *not* an option.

## Minor findings

### m1. Smoke test 5 passes `stations=[2206]` (int) where the contract demands `str | Sequence[str]`

§5 test 5 reads:

> call `rr.observations(provider="ch_foen", stations=[2206], products=["discharge_instantaneous"], start="2025-01-01", end="2025-01-01", on_issue="ignore")`

The wrapper signature in §2 declares `stations: str | Sequence[str]`. `[2206]` is `Sequence[int]`. M2 `ObservationRequest.from_inputs(...)` normalizes ints to strings in some implementations, but the contract is documented as `str | Sequence[str]`, and the *spy* tests in §5 test 1/3/4 test exact-kwarg forwarding — so the integer would be forwarded into request normalization unchanged. Either the legacy gauge id is consistently a string (`"2206"`, matching `examples/test_switzerland_fetcher.py:9` `gauge_id = "2016"`) or step 02 deliberately accepts ints; the plan must pin one and use it consistently in test 5 and any spec-shape table in §3. Most likely fix: `stations=["2206"]`.

### m2. REPORT §7 question-8 recommendation omits four spot-check items from the brief

Plan §7 question 8 enumerates: station catalogue shape, latitude/longitude/elevation/drainage nullability, `resolved_timezone` annotation, schema divergence, token isolation, D6 path shadowing. The brief's L_report_handoff_coverage spot-check list also requires:

- The revised `bulk_observations` final value (M5 V1 conformance closeout pins capability flags).
- The new package-root symbol `observations` and the T119/T120 update (M5's conformance closeout test inventory builds on the M4 public surface).
- `L_D7_probe` / `L_D9_probe` firing status across M4 — plan §3 declares both do not fire for step 03, but the cross-M4 verdict (step 01/02 also did not fire per step 02 execution.md §8) is the load-bearing fact for whether D7/D9 stay one-offs or get promoted in M5.
- D10 outcome (legacy-checkout citation method): if M5 also consults legacy code for `map_stations`, the same `git -C .../thirdparty/RivRetrieve-Python show cd9b030:<path>` idiom applies.

None of these are scope-bearing for *step 03 itself*, but missing them would push the question into M5 scope discussion. Minor.

### m3. §6 step 4 regeneration command lacks pre-regen verification

§6 step 4 instructs the executor to run `generate_catalogue` with `--catalogue-date 2026-05-28` (matching the current artifact's `catalogue_version`). It does not instruct the executor to first compute the current artifact hash (or `git show HEAD:.../provider.json`) and assert the *only* diff after regeneration is the `bulk_observations` value. Plan §5 test 14 covers this via `git diff --stat`, but `git diff --stat` only reports file-level changes — it would not catch a within-`provider.json` drift in another field. The stronger check is `jq -S` round-trip or a byte-by-byte assert that only the `bulk_observations` key value differs. Minor because §9 stopping condition does say "Stop if regenerating catalogue artifacts changes anything outside `provider.json` and an explicit version-stamp field", but that condition is about file paths, not intra-JSON drift.

## Nits

### n1. The `"true: ..."` prefix in the capability string is slightly awkward

The proposed `bulk_observations` value is:

```
true: 366-day window decomposition with stitched N x M station-product requests; partial failures reported as recoverable issues
```

The `pl.Utf8` column is just a string, so prefixing with `true: ` is harmless but mixes boolean semantics with a free-form description. Alternatives: drop the `true: ` prefix, or use just `"true"` (boolean-shaped Utf8) and document the mechanics in `docs/provider_ports/ch_foen.md` instead. Not load-bearing — the schema accepts the proposed value as-is.

### n2. Test 15 ("REPORT presence/structure test is not required; verify manually") is fine but inconsistent with the rest of §5

Other capability/wrapper tests are concrete `pytest` cases. Test 15 is a manual structural check. Either drop it from the §5 numbered list (since it isn't a test) or move it to §6 step 6 as part of the REPORT authoring instruction. Nit.

### n3. §6 step 1 phrasing "as annotations only as needed" risks executor confusion

§6 step 1 says: "Use existing imports for `Sequence`, `OnIssue`, and `ObservationResult` as annotations only as needed." The existing `discovery.py` does not import `Sequence`, `OnIssue`, or `ObservationResult` (verified via `Read`). They will need to be *added* as imports. With `from __future__ import annotations` already on line 1 of discovery.py, the annotation imports are not strictly required at runtime, but they must still appear as either `TYPE_CHECKING` imports or unconditional imports. The plan should say "add" rather than "use existing." Nit.

## Lens-by-lens summary

- **L1 (scope completeness):** ✅ — wrapper, T119/T120 expansion, capability decision, provider-port docs population, REPORT, and patch bump all covered against the tracker M4 §3 exit criteria.
- **L2 (scope over-reach):** ✅ — no retrieval/transform/parsing module is touched; no new annotations; no broadening of product vocabulary; no reach into M5.
- **L3 (citation verification, generic):** ✅ — spot-checked `switzerland.py:22-29`, `:43`, `:44-81`, `:97-110`, `:175-188`, `:190-218`, `:220-241`, `:251-261`, `:263-269`, `:290-297`, `:348-352` via `git -C /Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python show cd9b030:rivretrieve/switzerland.py`; all match. `examples/test_switzerland_fetcher.py:9-20` and `docs/fetchers/switzerland.rst:1-5` both verified.
- **L4 (test coverage adequacy):** ⚠️ — delegation spy, required-kwarg negatives, default forwarding, real-ch_foen smoke (transport-injected, not mocked), T119/T120 expansion, offline-import re-verify, generator-side and loader-side capability tests, schema test, artifact-drift check are all enumerated. Smoke test fixture identifier (`[2206]`) is questionable; see m1.
- **L5 (error handling completeness):** ✅ — §4 enumerates only bubbling exceptions; explicitly forbids wrapper-side catch/re-route/transformation/`apply_on_issue`.
- **L6 (open question rigor):** ✅ — every §7 question has a recommendation grounded in architecture.md, tracker, or step 02 execution.md.
- **L7 (deferral hygiene):** ✅ — `rr.map_stations()`, additional annotations, product vocabulary expansion, shared backend-policy, wide-form pandas, explicit `__all__`, live catalogue flags, token reclassification are all legitimate deferrals.
- **L8 (implementation order):** ✅ — §6 explicitly identifies the atomic checkpoint of `__init__.py` re-export + T119/T120; intermediate states keep tests green.
- **L9 (stopping conditions adequacy):** ✅ — §9 covers wrapper-purity, vocabulary breach, artifact drift, network, lazy-import contract, citation-evidence floor, REPORT §7 omissions.
- **L10 (architecture commitment compliance):** ✅ — lazy-import contract preserved; capability flag honest; wrapper-as-pure-delegation; no architecture §9/§14/§16/§17 amendment requested.
- **L11 (speculative abstraction):** ✅ — no wrapper request model, no wrapper result model, no wrapper-specific error type, no shared backend-policy abstraction.
- **L_two_channel:** ✅ — §4 explicitly documents that the wrapper does not catch, does not call `apply_on_issue`, does not reroute issues, does not transform fatals.
- **L_inherited_patterns:** ✅ — no public type promotion beyond M2; lazy-import contract intact; capability flag honest; D8 generator-side test required for the new value (tests 10/11).
- **L_legacy_citation_fidelity:** ✅ — every cited legacy range names the `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python` checkout @ `cd9b030` path (D10-compliant), and content matches at the spot-checked ranges.
- **L_vocabulary_boundary:** ✅ — no new product ID, no new annotation ID, no new `ProviderInfoCatalog` column.
- **L_offline_invariant_explicit:** ✅ — wrapper lives in `_internal.discovery` next to the other free functions; no `_internal.providers.ch_foen` import at module-load time; lazy registration via existing `provider()` (modulo the M1 shadow bug above).
- **L_asymmetric_encoding_round_trip:** ✅ — D8 generator-side and write-path tests are pinned in §5 tests 10/11.
- **L_D7_probe:** NA — no Pydantic model with `extra="allow"` is added.
- **L_D9_probe:** NA — no JSON walk; capability artifact load uses concrete dict checks.
- **L_delegation_purity:** ❌ — Intent is delegation-only and §4 explicitly forbids validation/normalization/transformation, but the §3 code example is mechanically broken (see M1) and therefore does not yet demonstrate pure delegation. After M1 is resolved the lens flips to ✅.
- **L_capability_descriptiveness:** ✅ — proposed value captures 366-day window decomposition, N×M cross-product, recoverable partial-failure issues; matches step 02 execution.md §1 (retrieval N×M, stitching, transport-injected client) and §3 (recoverable per-call failures routed as Issues). §7 Q4 justification cites step 02 execution.md §9 ("now behaviorally true"). The `true: ` prefix is a nit (see n1).
- **L_provider_json_regen:** ✅ — §6 step 4 pins date `2026-05-28` (same as committed artifact's `catalogue_version`, verified via `Read`), only `bulk_observations` should diff; §5 test 14 and §9 add stopping conditions. Strengthen with intra-JSON byte check per m3.
- **L_docs_observation_coverage:** ✅ — every M4 exit-criterion section is enumerated: Observation Retrieval, Annotation Schema, Issues, Token Handling (final), Schema Divergence, Pain Points; plus explicit replacement of the stale M3 "annotation schemas are empty" note (currently at `docs/provider_ports/ch_foen.md:45`).
- **L_report_handoff_coverage:** ⚠️ — six of ten brief-mandated spot-checks present; four omissions (see m2): `bulk_observations` final value, the new `observations` symbol and T119/T120 update, D7/D9 cross-M4 firing status, D10 outcome.

## Adversarial probes attempted

1. **Read step 02 execution.md §1 and §3** to compare against the plan's proposed `bulk_observations` value. Confirmed: 366-day windows, N×M cross-product, partial-failure-as-recoverable-issue all hold in the implementation. The proposed descriptive string is honest. ✅
2. **Read current `provider.json`** (`src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json:1`): `bulk_observations` currently `"false"`, `catalogue_version` `2026-05-28`. Confirmed §6 step 4's `--catalogue-date 2026-05-28` would not bump the version-stamp column. ✅
3. **Read existing `_internal.discovery.py`** to verify the wrapper's proposed home matches the M1 step 03 free-function pattern. Confirmed: `providers`, `provider`, `provider_info`, `stations`, `products`, `product_info` all live there. Plan §2 location decision is correct. ✅ While reading I noticed the parameter-shadow bug in §3's code block (see M1).
4. **Read `tests/test_package.py`** for the actual T119/T120 implementations. Confirmed: current expected set is `{ProviderHandle, product_info, products, provider, provider_info, providers, stations}`, deferred list contains `"observations"`. Plan §2 diff is coherent (adds `observations` to T119, removes `observations` from T120). The plan's claim that T120 forbids `ObservationResult, ObservationRequest, ObservationProvenance, AnnotationSchema, AnnotationTable, RawPayload, Issue, CatalogResult` matches the deferred-name list in `tests/test_package.py:27-57`. ✅
5. **Verified every legacy line range cited in §7 Q7** by `git -C /Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python show cd9b030:<path> | sed -n '<a>,<b>p'`:
   - `switzerland.py:22-29` — supported variables docstring ✅
   - `switzerland.py:43` — `MAX_WINDOW_DAYS = 366` ✅
   - `switzerland.py:44-81` — `VARIABLE_MAP` table ✅
   - `switzerland.py:97-110` — `_split_windows` ✅
   - `switzerland.py:175-188` — `_build_flux_query` ✅
   - `switzerland.py:190-218` — `_download_data` (headers, per-window POST) ✅
   - `switzerland.py:220-241` — `_parse_timeseries_payload` (tz conversion via `tz_localize(None)`) ✅
   - `switzerland.py:251-261` — `_apply_parameter_preference` ✅
   - `switzerland.py:263-269` — `_convert_units` (`flow_ls` / 1000) ✅
   - `switzerland.py:290-297` — daily aggregation block ✅
   - `switzerland.py:348-352` — instant filtering ✅
   - `examples/test_switzerland_fetcher.py:9-20` — gauge `2016`, daily discharge/temperature ✅
   - `docs/fetchers/switzerland.rst:1-5` — automodule stub ✅
   All citations name the legacy-checkout path explicitly per D10.
6. **Read M3 REPORT §7** to compare handoff style. The M3 §7 is a 6-item surprises-and-candidates list (annotation schemas, token classification, observation placeholder, D8 serialization carry-over, D7/D9 applicability, capability flags). M4 plan's §7 Q8 recommendation parallels several but misses D7/D9 cross-M4 firing status and D10 outcome propagation (see m2).
7. **Read `handle.py:46-54`** to verify the wrapper signature matches the provider handle. Confirmed: provider-handle `observations` is `(self, *, stations, products, start, end, on_issue="warn")`. The wrapper's keyword set is the same modulo the added `provider: str`. ✅
8. **Probed shadow risk** by reading `_internal.discovery.py:27` (`def provider(provider_id: str) -> ProviderHandle`) and comparing to the proposed §3 body. Discovered M1 above.
