# Czech provider documentation verification

Checked on 2026-09-28 (UTC) for [PR #295](https://github.com/RivRetrieve/RivRetrieve/pull/295)
and the [standalone vision](../../../planning/visions/2026-09-28-czech-provider-documentation-review.md).
This record distinguishes live source checks, offline catalogue inspection and
recorded tests. No production code or catalogue artifacts changed.

## Tested revision and environment

- Implementation and catalogue revision: `46028d1441a958cccb9a2863fda1f8c68fc09d6e`.
  This merges target `main` at `a9e9e1d96fa1d8403e1654e2553c7ae12f2b238a`
  into Thiago's existing branch at `604cbc0cba227ff085b1b42bdf1d572bb5609196`.
- The page and these evidence files were the only uncommitted changes during
  final checks. The PR preserves both histories, with no rewritten commits.
- CPython 3.13.8; project dependencies and commands run through `uv`.
- Checkout: `.worktrees/visions/czech-provider-documentation-review` below the
  repository. No other checkout was created for implementation.
- Initial setup failed before importing RivRetrieve because the inherited
  external `/private/tmp/pce-uv-cache` lacked a cached wheel's `WHEEL` file.
  A fresh worktree-local cache resolved this environment failure:
  `export UV_CACHE_DIR="$PWD/.uv-cache"`.

Run commands below from the checkout root.

## Live public example

```bash
uv run python docs/verification/czech-provider/example.py
```

[`example.py`](example.py) is exactly the provider page's sole Python block,
executed in a fresh session in its documented order. The final run on
2026-09-28 returned the exact [`example-output.txt`](example-output.txt): seven
daily discharge rows, first three values 1.7, 1.54 and 1.5 m³/s, UTC labels,
and `issues=()`. It used `cache="bypass"`, not recordings or a local cache.
The first successful live execution took 11.87 seconds including environment
setup; the final run took 4.40 seconds.

The original station was retained. The one-week window gives a readable preview
instead of an uninspected annual result. This change does not avoid a known
failure. No library or verification-support defect was identified.

A separate live GET of
`https://opendata.chmi.cz/hydrology/historical/data/daily/H_0-203-1-180100_DQ_2020.json`
returned HTTP 200 at `2026-09-28T14:06:52.758603+00:00`. Its QD entry has native
unit `M3_S`, header `DT,VAL`, 366 rows, and first entries
`["2020-01-01T00:00:00Z", 1.7]`, `["2020-01-02T00:00:00Z", 1.54]`,
`["2020-01-03T00:00:00Z", 1.5]`. HD is also present; TD is absent in this
particular file. This is additional source evidence, not a second public-API
example or a claim that all quantities exist at this station.

## Offline catalogue inspection

```bash
uv run python docs/verification/czech-provider/inspect_catalogue.py
```

[`catalogue-output.txt`](catalogue-output.txt) records 831 locations and 4,155
series candidates. The five combinations are discharge/stage daily and hourly
means, and daily mean temperature. The public `inventory_status` is
`["incomplete"]`; the page makes no claim that catalogued candidates establish
observations. The packaged native table identifies the example station as
`VD České Údolí`, stream `Radbuza`, matching the freshly fetched source metadata.
Two preliminary one-off inspection attempts used the wrong selection attribute
and then assumed a frame instead of a tuple. Correcting that inspection code to
`len(selection.locations)` required no library changes.

## Authoritative source checks

```bash
uv run python docs/verification/czech-provider/check_sources.py
```

The script downloads source documents below the ignored `source-checks/` folder
and extracts the historical dataset PDF with `pypdf`.
[`source-checks.log`](source-checks.log) records dates, URLs, final URLs and
HTTP statuses from the successful run. All eight requests returned HTTP 200
without credentials. [`source-evidence.md`](source-evidence.md) retains
quotations, unofficial translations and an independent source review, including
the historical code description and daily/hourly directory checks.

Source SHA-256 digests for that implementation check:

| Download | SHA-256 |
|---|---|
| `institution.txt` | `cea754b850f8da0261bcad54e82c9430d73deca95fcce27240bb054f3adacdfd` |
| `open-data.txt` | `ebd6cbe1cf138aab25ace3fb7534eeb5a6586cedbf213b7fede277acd3c86fc6` |
| `annual.txt` | `f051c2c8abb9a4ef4f0fbe0064626870e44246302e78d380a9f12f8b5ceaf607` |
| `hydrology.txt` | `bf5f8ce792dcc8f0652078ecdc03cbdce3d944fdd9f53de193ab4fa34fd99fcc` |
| `description.pdf` | `2fdcbc852ec519cae906445c88c243afdf1cc02d8676413a328fa9522d11c895` |
| `meta2.txt` | `b72883dbaa8407b4a514ae4aeec807350222b67298da16a089ed6299d553fafc` |
| `meta1.txt` | `82b3af59057137af2be8dbe6ea666371d45577478faee84441bd799ffe992264` |
| `terms.txt` | `50ffc08e39632feaaceb5d3e329ad39017333e942aa0aca536fd719e147760c8` |

The page's physical interpretation is also checked against
`src/rivretrieve/_internal/providers/cz_chmi/config.py`, `fetch.py` and `parse.py`:
annual historical DQ/HQ routes, source means, cm-to-m conversion, UTC labels,
unknown daily averaging boundaries and hourly interval anchoring. The parser
accepts `DT,VAL` without inventing quality flags. The independent source check
found no stronger published temporal or finality guarantee.

## Recorded tests and documentation checks

```bash
uv run pytest -q tests/test_cz_chmi_observations.py tests/test_chmi_source_boundary_isolation.py tests/test_cz_chmi_hourly_semantics_regression.py tests/test_cz_chmi_boundary_probe.py
uv run --with rdflib pytest -q tests/test_documentation.py tests/test_supporting_documentation.py tests/test_reference_contracts.py
uv run python scripts/generate_reference.py --check
```

- [Focused tests](focused-tests.txt): **48 passed in 8.35s**. Existing coverage
  checks annual coalescing, source means, units, conversion, nulls, public routing,
  exact receipts, hourly semantics and source-failure isolation. These replay
  recorded evidence; they do not establish current source availability.
- [Documentation tests](documentation-tests.txt): **28 passed in 7.34s**,
  with one existing rdflib `ConjunctiveGraph` deprecation warning.
- [Reference check](reference-check.txt): **Reference is current.**
- No new tests or expensive combinations were added. New coverage runtime impact
  is zero. The checks above reuse established focused coverage.
- `uv run ruff check docs/verification/czech-provider/*.py` and
  `uv run ruff format --check docs/verification/czech-provider/*.py` passed.
- `git diff --check` passed. The complete diff against target `main` keeps every
  provider index link and changes no production file.

## Limits and review gate

The live example establishes only the requested station, quantity and week at
that retrieval time. The returned empty issue tuple is not a scientific quality
assessment. Published values and availability can change.

Neither the station catalogue nor a directory listing establishes continuous
coverage, station-specific earliest dates, availability of every series, complete
latest-year observations, historical finality or averaging boundaries. The page
therefore makes no fixed-year cutoff claim. CHMI's explicit institutional duties
do not prove that CHMI alone operates every published station. Citation guidance
is practical advice, not a publisher-specified template.

No required source check was blocked. The graphical hydrology guide was not
used because text extraction did not expose its substantive content. Tests were
focused, not a full repository suite. Independent review and human review of
PR #295 remain required. This work does not approve or merge that PR.

## Follow-up after user feedback, 2026-09-28

The user reviewed the page and requested clearer annual-file/station wording and
a roadmap pointer. The follow-up explains daily versus hourly files, states that
a quantity may be absent (TD is absent in the checked 2020 example file), and
links existing [#294](https://github.com/RivRetrieve/RivRetrieve/issues/294).
A [dated clarification](https://github.com/RivRetrieve/RivRetrieve/issues/294#issuecomment-5872834287)
preserves that issue's historical evidence while requiring source-defined
semantics for future mappings. No duplicate issue or production change.

The page's Python block remains byte-for-byte equal to the tested `example.py`;
its request and displayed output are unchanged. The following checks passed
again after the prose edits:

```bash
uv run --with rdflib pytest -q tests/test_documentation.py tests/test_supporting_documentation.py tests/test_reference_contracts.py
uv run python scripts/generate_reference.py --check
git diff --check
```

The user then explicitly authorized completion and merge without further human
gates, superseding the earlier restriction. The
[PR authorization record](https://github.com/RivRetrieve/RivRetrieve/pull/295#issuecomment-5872842211)
retains the exact instruction. Final independent re-review and repository checks
still precede merge by the root implementing agent. The original vision and
verification record above retain their historical context.
