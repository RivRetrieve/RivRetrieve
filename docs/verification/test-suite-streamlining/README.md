# Test-suite streamlining verification

Historical review completed on September 28, 2026, for the
[streamlining vision](../../../planning/visions/2026-09-27-comprehensive-test-suite-streamlining.md).
This records one delivery. It is not an ongoing per-test reporting requirement.
The contributor rule is in [AGENTS.md](../../../AGENTS.md#contributing-tests).

## Outcome and scope

The full default suite decreased from **3,879.97 s (64m 40s)** to **2,153.63 s (35m 54s)**,
a **44.5% reduction**. Both runs passed. Production code, `pyproject.toml` and `uv.lock`
are identical between them. No new skips or opt-in suites were added.

The review covered all 253 test files on `c8e87616816fa132e54d99af6a7adbacb52e24bc`,
including the merged Lithuania shared-acquisition repair. The [inventory](inventory.csv)
accounts for every file and its guarantee: 185 retained unchanged, 64 changed, four
consolidated into other coverage, and three new isolation-test files. The resulting
suite has 252 test files. These are file counts, not collected cases.

Reviewed areas include all providers and source formats, public discovery/retrieval,
engine contracts, catalogue generation/evidence, native stores/cache, transport and
credentials, exports, documentation, installed packaging and maintenance tools.
Each removal was mapped to retained assertions. Cheap/static checks were reviewed
alongside expensive replay cases. [File timings](timings.csv) record remaining costs.

Implementation PRs: [#397](https://github.com/RivRetrieve/RivRetrieve/pull/397),
[#398](https://github.com/RivRetrieve/RivRetrieve/pull/398), and
[#399](https://github.com/RivRetrieve/RivRetrieve/pull/399).
The final integration adds the reviewed provider/documentation fixture adoption and this record.

## What changed, and where guarantees now live

| Guarantee / layer | Actual authored change | Retained coverage and transfer |
| --- | --- | --- |
| Public behavior using packaged catalogue inputs | Explicit test-only validated-input pool, with content fingerprints and detached deep copies; 37 audited modules and 30 additional test functions opt in; the README page opts in conditionally. | Registry clearing remains per test. Real manifest composition, declarations, environment/cache/credential resolution and handles remain fresh. Custom loaders retain precedence. Real loading, corruption, unrelated-member atomic refusal and national generation stay outside the pool. New isolation tests exercise changed bytes despite same size/mtime, semantic corruption, missing/symlinked inputs and nested/frame mutation. |
| Provider numeric parsing and failure integration | USGS measurement/sentinel duplication consolidated; selected exhaustive public matrices moved to actual parsers. | All 19 USGS invalid representations remain at the actual parser with healthy sibling identity/value and failure reason. Three public invalid classes retain all issue policies, exact receipts, reacquisition and coverage exclusion. Eight successful representations remain public/cache cases, including -1, signed zero, large finite, negative sentinel-looking value and null; each now bundle-round-trips. |
| HydroPortail and HubEau source semantics | All 48 malformed empty-envelope combinations moved to real HydroPortail parse; public Q/H invalid-selector witnesses added. HubEau public numeric policy/value multiplication reduced. French JSON parser coverage added alongside a smaller public matrix. | All 16 HydroPortail real station/quantity/variant replays remain. All eight live numeric mutations remain at real parsers; public overflow retains all policies and zero/finite/null integration remains. All 15 French route/cell parser combinations remain; nine original/null/missing public routes plus three daily sibling cases remain, including five-page temperature integration. |
| Read-only national catalogue projections | Japan and HubEau repeated unchanged builds now feed detached test projections. Two duplicate catalogue readability bodies combined. | Every original projection assertion remains; changed input, malformed source, date/origin, CLI and full artifact regeneration paths still use real fresh builders. New mutation controls cover nested metadata and in-place Polars changes. Exact Japan mathematical docstring wording test removed without changing docstrings. |
| Core model and discovery behavior | Removed unused issue-policy parametrization from 13 model tests; removed m1/m5 smoke files. | Every malformed model field/value remains. Real fatal-policy interactions remain at public/driver boundaries. Focused discovery already proves sorted providers, product vocabulary and unknown-provider refusal. Stronger Polars/Pandas adapter checks remain in observation tests; four absent wide-helper assertions moved there. |
| National catalogue origin certification | Combined positive origin and CRS sweeps over the same 15 provider/partition builds. | All original assertions run on the same real full outputs. Negative real builders, offline composition-root rebuilds and exact artifact comparisons remain. No cached mutation builder or reduced national sample was introduced. |
| Compiled observations | Native-value assertion merged into the compile-state expected frame, deleting one repeated compile/read test. Streaming schema-order mutation corrected to preserve all other fields. | Null, blank, finite native value, absence, source quality and identity remain. The corrected mutation now isolates order and proves unchanged values/types after reversing that permutation. Every transaction failure phase and the 65,537-row Arrow-boundary witness remains. |
| Installed distributions | Ordinary direct-wheel/sdist-derived-wheel build/install setup shared across three packaging files. Builds reduce from nine to five, including both independent contaminated sentinel builds. | All verification bodies remain: installed origin outside the repository, both distribution routes, offline discovery, exact archive bytes, packaged relation/RDF/closure proofs, drainage states, input/secret exclusion and both sentinel builds. Fresh verifier process, temporary working directory and HOME remain. New two-route verifier isolation tests add environment/network/bytecode and cross-verifier state controls without extra builds. |
| Executable documentation | README replay assertions transferred into actual page execution; handwritten quickstart duplicate, callable AST scan and duplicate output-presence checks removed; link/syntax page sets unified. | Real README/usage/provider/supporting/CAMELS examples remain. Exact rows/schema/series/units/receipts/issues transfer to README execution. Output contracts run for executed blocks; empty pages are refused. CAMELS keeps its independent full-year numeric oracle. Generated-reference freshness and model-field/enum completeness remain separate. No provider page, public docstring or generated reference was changed. |
| Transport recording and architecture | Fake-sender recorder tests use coherent virtual monotonic/UTC time. Constructor keyword-order and syntax-specific provider-census scan removed. | Real HttpClient orchestration, source recording, credentials/redaction and versions remain; transport pacing tests remain. Dependency ownership, input identity, empty default scope, network bans, role inventory and adversarial architectural controls remain. |

### Deliberate ancillary coverage change

Installed tests now install the built RivRetrieve wheel offline with `--no-deps`, exposing the current project dependency directories through plain `.pth` paths without executing editable project `.pth` files. They still verify the installed distribution, resources and offline behavior. They no longer verify fresh dependency resolution/install from the network. This explicit boundary change removes network variability; it is not presented as preserved fresh-install coverage. Shared installations are read-only by test usage, not filesystem permissions, so the new process-state checks and reversed consumer run matter.

### Production behavior remained unchanged

The three streamlining diffs contain no `src/` changes. Production registration still validates the full manifest atomically; no production path cache, lazy provider registration, parser shortcut or validation bypass was introduced. Measured pool acceleration applies only to enrolled tests. It does not promise faster cold public discovery for users. The branch includes upstream Lithuania behavior from PR391, but does not count that repair as this work's optimization.

## What stayed, including expensive checks

- Public selection, physical scope, explicit partial selectors, identity/fact segments, conversion, units, temporal unknowns, fatal internal contracts, source-failure isolation, native cache coverage/vintage, receipt provenance and bundles remain default offline coverage.
- Every provider retains recorded acquisition and source-specific parsing/identity guarantees. Source format differences are not replaced with a generic numeric parser. Boundary probes retain exact requests, attested bytes and source-checkable counts/labels. The recording corpus was not rewritten.
- Catalogue acquisition/evidence retains independent lineage, header/relations, foreign keys, canonical bindings, source vocabulary, withholding versus silence, closure and full regeneration checks. Drainage metadata preserves published scalar representation, units only where established, and null/blank/no-metadata distinctions independently of numeric admission or map coordinates.
- Store conformance's independent oracle and production validation remain separate. Materialized and streamed certification keep different read-back paths. Precommit restoration, postcommit cleanup authority, source-unit completeness, undeclared columns, malformed artifacts, symlink safety and recovery remain distinct cases.
- The exact Poland annual archive compile remains in the default suite. Bulk malformed numeric representation, actual provider compilation, public explicit-download recovery, native receipt and two-provider shared-reader tests were not narrowed beyond the one native-value transfer.
- Real import isolation, installed resource verification, provider extensibility, script/source-evidence verification, descriptor/reference contracts and optional mapping/geographic behavior remain. No new skip or opt-in expensive suite was introduced by these slices.

### Protected Lithuania integration

The final-target supplement records one physical request per declared station/month, exact recorded values and shared receipts, independent station/month/product failures, padding-only 404 distinction, incomplete inventory versus explicit reuse, mixed cache eligibility, held values/vintage on failed refresh and independent successful-month replacement. It also records distinct same-URL attempts, full retry history in provenance/cache/outcomes, immutable transport evidence and credential-safe retention. These tests and related driver, engine, Swiss provenance and Thaiwater boundary updates are retained unchanged by cleanup. Lithuania-containing documentation cases remain unenrolled. Poland/Lithuania provider pages and API accuracy work are untouched.

## Recommendations not implemented

The review considered broader production evidence-validation optimization, arbitrary-path caching, more national-build reuse, smaller negative native fixtures, bulk numeric batching, map fixture narrowing, receipt/shared-reader catalogue setup reuse, consent/reader/certification consolidation, broader static-check simplification and shorter loopback shutdown polling. These are not delivered changes in the captured diffs. The production proposals lacked a justified measured user-facing change in scope. Many narrow tests were already cheap or protected different failure stages. The final adoption includes 14 core modules, 14 provider modules, nine documentation modules, 30 additional functions in mixed modules, and the README parameter through an explicit conditional fixture request. Real loader, registration and corruption tests remain outside that adoption.

This distinction is intentional: review completeness does not require deleting a test from every file. No coverage-loss claim is based solely on similar names, passing counts or reduced runtime.


## Measurements and validation

### Comparable full-suite runs

| Measurement | Before | After |
| --- | ---: | ---: |
| Revision | `c8e8761` | `2c992e2` |
| Collected cases | 4,703 | 4,533 |
| Passed / skipped | 4,700 / 3 | 4,530 / 3 |
| Warnings | 78 | 78 |
| Total pytest time | 3,879.97 s | 2,153.63 s |
| Summed setup | 451.925 s | 53.331 s |
| Summed call | 3,409.416 s | 2,085.247 s |
| Summed teardown | 12.329 s | 8.138 s |

Environment: macOS 15.7.3 ARM64, CPython 3.13.8, uv 0.12.1, pytest 9.1.0.
Both worktrees used `uv sync --all-extras --dev` and the same lockfile. The declared
build backend was cached before both runs. Tests ran serially, without coverage or
parallel workers. Other coordinated test/build jobs were idle during each run.
Each run used a fresh Python process. Filesystem and uv caches were warm; no OS-cold
claim is made. The test input pool starts empty in each pytest session.

Commands from each worktree, with `PYTHONPATH` pointing to the directory containing
[phase_timing.py](phase_timing.py) and `RR_TIMING_LOG` naming that run's JSONL output:

```text
uv run pytest -p phase_timing --durations=0 --junitxml=<run>.xml
```

The plugin only records pytest phase reports; it does not filter tests or alter execution.
Elapsed pytest time includes collection and reporting, so phase sums are slightly smaller.
The two controlled runs establish this local comparison, not a hardware-independent runtime
promise. Unchanged-file phase totals were about 1% slower in the after-run, consistent with
small run-to-run noise rather than a general machine speedup.

The 170-case reduction comes from the documented consolidations and added isolation checks.
It is not the main source of the speedup. The 42 files changed only to reuse catalogue inputs
retained their cases and assertions; their combined phase time fell from 1,082.0 s to 342.8 s.
Files combining assertion consolidation with fixture reuse fell from 956.8 s to 155.2 s;
those effects are not claimed as independently measured. Packaging reuses three ordinary
builds while retaining two separate contaminated builds. No production performance gain is claimed.

Three existing skips remain: two coverage-map checks require optional `geopandas`, and the
Thaiwater governing-evidence acceptance check requires controlled private source bodies.
The 78 warnings comprise 20 source-workbook missing-default-style warnings and 58 RDFLib
`ConjunctiveGraph` deprecation warnings. They were not suppressed.

An earlier exploratory run on `565d391` took 3,951.75 s and had four packaging failures
because its new offline cache lacked `uv-build`. Those four passed after preparing the
backend. That run also predates PR #391 and is **not** the reported comparison above.

### Test-support measurement

Three repeats on `c8e8761`, in an exclusive measurement slot, compared real loading with
the test pool. Imports were preloaded. Each public call used a fresh registry; exact
selection, frame and normalized-evidence equality was checked outside the timing.

| Operation (median) | Real loader | First pool use | Warm pool |
| --- | ---: | ---: | ---: |
| All artifact loads | 2.576 s | 3.185 s | 0.505 s |
| Fresh manifest registration | 3.167 s | not measured separately | 0.497 s |
| USGS daily find | 3.183 s | 4.009 s | 0.707 s |
| HydroPortail variant find | 3.157 s | 3.936 s | 0.512 s |

First use is slower; repeated test inputs benefit. Deepcopy alone takes a median 0.498 s.
A traced warm borrow retained about 81.6 MB and peaked at about 104.6 MB of Python allocations;
this does not fully describe Arrow buffers. Same-size/same-mtime changed inputs triggered
real revalidation. These measurements concern test support, not library changes.

### Correctness and review

- Full after-suite: 4,530 passed, three existing skips, 78 warnings.
- Integrated reverse-order run: 134 passed, including public fixture consumers, real declaration
  and corrupt-artifact refusals, and pool mutation/invalidation tests.
- README fixture activation plus isolation checks: 12 passed. Setup tracing confirms the
  conditional fixture runs for the README page; Lithuania-containing usage cases remain unpooled.
- Core slice: 175 enrolled/isolation cases passed; earlier focused checks covered national
  certification, real registration, malformed artifacts, model contracts and both store paths.
- Provider slice: 601 passed in reversed node order, including the unchanged upstream Lithuania
  and transport-attempt regressions. Collection then exposed a removed test-helper import in
  HubEau publication scope; the repair calls the real full builder and all four scope tests passed.
- Packaging/contracts: 172 focused cases passed; reverse packaging-consumer/isolation run passed
  11 cases. Both installed distribution routes and both contaminated sentinel builds remain.
- `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`,
  `uv run ty check src`, `uv run python scripts/generate_reference.py --check`, and
  `git diff --check` passed on the integrated test tree.
- Independent reviewers read every slice's full diff and validation evidence. A separate
  whole-vision review checked the integrated diff, enrollment and coverage transfers.

The committed CSV files preserve the file-level review and timing totals. Detailed run logs,
JUnit XML, phase JSONL, measurement script/data and review notes are retained locally under
`.worktrees/evidence/test-suite-streamlining/`; regenerable build output is not delivery evidence.

### Slowest remaining files

| Test file | After phase time | Reason retained |
| --- | ---: | --- |
| `test_lt_lhmt_shared_acquisition.py` | 154.7 s | Protected new shared-call/cache/retry integration |
| `test_pl_imgw_annual.py` | 96.7 s | Exact annual archive compilation |
| `test_catalogue_origin_certification.py` | 91.5 s | Real national builders and refusal gates |
| `test_lt_lhmt_monthly_isolation.py` | 84.7 s | Independent month failures and held cache values |
| `test_source_field_boundaries.py` | 68.4 s | Source-specific identity/physics boundaries |
| `test_documentation_examples.py` | 63.4 s | Actual page execution; mixed Lithuania cases remain unpooled |

## Residual costs and risks

Full national evidence validation/regeneration, annual compilation, installed RDF/evidence
proofs and protected acquisition tests remain deliberate costs. Detached copies still cost
CPU and memory. Future fixture enrollment needs a boundary audit so it cannot mask loading
or corruption checks. Public witnesses remain alongside parser matrices to catch policy,
sibling, cache and receipt interactions. Shared installations are read-only by convention;
future verifiers must not mutate them. No production optimization or blanket fixture rule
was introduced.
