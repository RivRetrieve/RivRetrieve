# Transport boundaries and reliable tests

RivRetrieve should handle malformed requests consistently, send only explicitly configured credentials, and distinguish source failures from software defects. Its tests should prove those behaviors without depending on a contributor's credentials, proxies, cache, working-directory configuration, or the current date.

A failing malformed-URL test exposed more than a missing exception conversion. Investigation found environment-sensitive tests and an authentication boundary that ordinary injected-sender tests do not exercise. Improve these specific weaknesses across the affected suite, not just the original failing case. Preserve useful existing coverage rather than rewriting the suite.

## Confirmed outcomes

- Malformed URLs become terminal invalid-request transport failures before network access. They do not retry. Preserve the existing one-attempt accounting and useful failure evidence. Do not catch arbitrary `ValueError` around all sender execution to achieve this.
- Authentication comes exclusively from RivRetrieve's explicit credential configuration. Ambient `.netrc` authentication must neither add credentials to ordinary requests nor replace configured authorization. Preserve proxy and certificate-environment support; disabling all Requests environment handling is not an acceptable shortcut.
- Unexpected programming errors remain fatal during authenticated execution, with sanitized diagnostics that cannot expose credential-bearing exceptions, traceback locals, or values. Recognized transport failures retain their existing supported-failure and partial-result behavior. Plain HTTP execution must continue propagating unrelated programming errors.
- Tests own inputs unrelated to their named promise. Deliberate configuration tests still exercise real environment and dotenv precedence with synthetic inputs. Shared setup must not hide malformed inputs, bypass validation, or override temporary stores selected by individual tests.
- Existing assertions prove measurement attachment to time and series, requested receipt presence, and named no-network/no-retry guarantees. Date-sensitive expectations use authored dates rather than a moving clock.

These outcomes were confirmed with the maintainer. Reversible implementation mechanisms remain open.

## Investigation evidence

The investigation began at local revision `43242356df25662a0f0acd5b54b2a3c742a8932c`. Publication targets `main`; its fetched revision was `f419b7395801ea7f05293c779b00187255b0f380`. Recheck affected code on the implementation revision rather than assuming these observations certify later changes.

The project environment used Python 3.13.14, Requests 2.34.2, and urllib3 2.8.0. No dependencies, runtime constants, or repository code were changed during investigation.

### Reproduced failures

1. `uv run pytest --logic-only tests/test_http_retry_network.py -q` produced **49 passed, 1 failed**. The failing case was `test_invalid_request_is_terminal_before_network_access[http://[invalid]`.
2. Running its two invalid-request parameters with `NETRC` pointing to a nonexistent temporary file produced **2 passed**. Pointing it to an empty temporary file produced **1 passed, 1 failed**. Requests calls `get_netrc_auth` before normal prepared-request URL validation. If a netrc file exists, `urllib.parse.urlparse` raises plain `ValueError("Invalid IPv6 URL")`; `HttpClient.send` catches Requests, timeout, and connection exceptions, not plain `ValueError`. File presence is sufficient; credential contents are irrelevant to this failure.
3. `tests/test_fetch.py::test_fetch_routes_only_selected_sparse_series` passed with `RIVRETRIEVE_CACHE_DIR` absent and failed with that variable deliberately empty, under the same fresh temporary working directory. The test uses synthetic stages but inherits configuration unrelated to routing. Rejecting an empty runtime cache setting is correct; this observation calls for test isolation, not weakened production validation.
4. `tests/test_http_retry_storage.py::test_recovered_archive_keeps_earlier_success_and_writes_only_complete_bytes[fixed]` passed with `NO_PROXY=127.0.0.1` and failed with empty `NO_PROXY` and synthetic `HTTP_PROXY=unsupported-proxy://127.0.0.1:1`. Both runs used an explicit absent temporary NETRC. The unsupported proxy scheme required no external proxy access. Unlike the network test module, this loopback module lacks proxy bypass setup.
5. A no-network experiment used real `requests.Session.prepare_request` and a temporary netrc entry for `synthetic.invalid` with fake credentials. Preparation added Authorization to an ordinary request and replaced a supplied fake Bearer header. Only boolean outcomes were reported. This is normal Requests behavior, but conflicts with RivRetrieve's explicit credential authority and evidence model. It does not establish an actual credential leak. FOEN declares Authorization, and the authentication exchange supplies Authorization for acquired tokens, so the affected boundary is used by production providers.

Source-independent collection succeeded: **3,739 selected, 1,582 deselected**. The evidence-selection and evidence-configuration modules passed **29 tests**. No complete suite baseline or retained-input acceptance was performed during this investigation. These counts are observations, not fixed acceptance counts.

### Code-review findings

- `_send_with_requests` in `src/rivretrieve/_internal/transport.py` uses Requests' ambient authentication behavior. `ExecutedRequestEvidence` is assembled before Requests prepares the actual request. Injected-sender assertions alone cannot detect introduced or replaced authorization.
- Credential execution in `transport.py` and `authentication.py` converts unexpected exceptions into supported failures, except for explicitly recognized fatal contract errors. Existing secret-sanitization tests intentionally expect this behavior for examples such as RuntimeError. Changing fatality therefore requires revising those expectations while preserving their secrecy guarantees.
- The invalid-request integration test checks reason, attempt count, and sleeps, but not its claimed absence of network access or invalid-request category. Keep real preparation and strengthen the existing expectations rather than replacing Requests with a fake sender.
- Public routing and registered-store tests can inherit cache environment variables and cwd `.env`. `_resolve_store_root` gives those settings precedence over registered stores. Examples include `tests/test_fetch.py` and `tests/test_bulk_series_outcomes.py`. A global cache-directory override would defeat the latter fixtures rather than isolate them.
- `tests/test_no_nve_public_routes.py` compares values without timestamps, and its `all(...)` receipt checks can pass with an empty receipt collection. `tests/test_public_representative_source_series.py` sorts nonnull values in the three-version example without checking which version owns each value or null. Strengthen existing expectations using independent source fields and explicit identity/time/value associations.
- The default-end and future-end tests in `tests/test_fetch.py` read `date.today()` around execution. Pin their relevant date inputs; no suite-wide clock replacement is required.

The written testing guide already prescribes independent expectations, meaningful association checks, and isolated inputs. The problem is uneven application, not a need for a new testing philosophy. Real wire-fault tests, storage rollback tests, and catalogue-fixture mutation/detachment tests are strong. Review did not establish a general overmocking problem or shared catalogue-validation bypass.

## Implementation scope and constraints

Fix the real Requests boundary and authenticated error semantics. Extend the relevant real-adapter and sanitization tests so they can detect the original defects. Preserve credential authority, redirect restrictions, secret-response handling, source-failure identity, and request/attempt evidence.

Use synthetic missing, empty, and populated netrc inputs where they prove distinct behavior. Verify authentication through real request preparation, and an assembled sender check where needed to connect prepared headers to RivRetrieve's evidence. Do not merely clear netrc in tests and declare the library fixed. Keep unrelated sender-error propagation covered.

Improve affected shared fixtures and analogous callers rather than applying isolated patches to one test. Own proxy/netrc settings in real loopback tests. Isolate public API configuration without replacing the behavior that configuration tests are meant to exercise. Repository-relative fixture paths mean a blanket working-directory change is not automatically safe. Tests must not consume the contributor's dotenv, credentials, or observation stores.

A source-independent selection is not itself a network sandbox. Establish safe execution that prevents accidental publisher traffic while retaining intentional loopback tests. Prefer existing test mechanisms and small shared fixtures; do not introduce a second test coordinator or broad patching that masks product behavior.

Strengthen NVE row/receipt expectations and the named date-sensitive tests. Investigate analogous cases when evidence indicates the same defect, but do not turn this into speculative exhaustive testing or cosmetic cleanup. Redundant regex/prose assertions found in review are lower-priority cleanup opportunities only when they overlap changed coverage; they do not justify a separate rewrite.

Do not change retry policy constants, provider hydrological interpretations, publisher request limits, or source data to make tests pass. Do not add hosted CI. Keep private source evidence and credentials out of public artifacts. No new public configuration surface is required by this vision.

## Acceptance

Work in small test-first increments following the repository testing and evidence guides. Existing failing tests may serve as regression controls when they reach the intended defect. Demonstrate that new or strengthened expectations detect the claimed failure; avoid assertions calculated from the same implementation under test.

Acceptance must establish:

- Both missing and existing synthetic netrc cases produce the intended malformed-request result without network access or retries.
- Ambient synthetic authentication cannot add or replace credentials, and recorded credential evidence agrees with execution. Explicit credentials still work; proxy and certificate configuration remain supported.
- Unexpected authenticated execution errors are fatal and sanitized; supported source failures still retain their identity and partial results. Unrelated plain-client programming exceptions propagate.
- Affected tests behave consistently under deliberately varied synthetic cache, dotenv, proxy, netrc, and date inputs as applicable. Their default setup does not consult contributor secrets or stores.
- NVE expectations detect timestamp/series misattachment, including null placement, and missing receipts.
- Affected checks, the full source-independent suite, formatting/lint, and `uv run ty check src` pass on the delivered revision. Explain any optional skips; do not present them as executed coverage. Use temporary cache/store roots without overriding fixture-selected stores.
- Changed retained-source expectations pass against genuine inputs selected through the existing private archive procedure. Missing mandatory inputs block acceptance; synthetic substitutes do not certify those expectations. No governing source changes are intended, but any such change triggers the applicable full checks.

Record exact revisions, commands, results, and limitations. Review the scope of any large diff and remove changes without a demonstrated need.

## Update PR #549 only after verification

[PR #549](https://github.com/RivRetrieve/RivRetrieve/pull/549), `fix: bound HydroPortail requests and verify chunk assembly`, currently states that its full logic suite is red because the malformed-URL transport case also fails on untouched target `f419b739`. Its historical results are not superseded merely because this vision is published or a focused test passes.

After the fixes are delivered, incorporate them into the PR's then-current revision through the normal safe workflow and run the applicable checks there, including its full source-independent suite and affected HydroPortail checks. Only after successful verification update the stale limitation and check results in the PR body. State the newly verified revision and results; keep historical evidence only where useful and clearly labeled. If checks remain red or mandatory verification is unavailable, retain an accurate limitation instead.

Preserve Freddy's authorship, publisher-observation limits, related issue references and no-auto-close safeguards, retained-replay limitations where still applicable, and the PR's draft/review-only status. This task does not authorize marking that contribution ready, merging PR #549, or claiming its unrelated timeout/503 issues are solved. Re-read its current body before editing so concurrent changes are preserved.

This is a standalone vision. Publication authorizes no implementation or PR #549 text change by itself.
