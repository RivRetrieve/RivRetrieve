# Bosnia provider documentation verification

Historical output files and `source-evidence.md` are archived with their original
bytes under the `docs/verification/bosnia-provider/` member paths. Links labelled
“archived” below name those retained members. Select and retrieve them through the
[verification guide](../../maintenance/evidence.md); they are not in-tree inputs.

Checked on 2026-09-28 (UTC) for [PR #296](https://github.com/RivRetrieve/RivRetrieve/pull/296)
and the [standalone vision](../../../planning/visions/2026-09-28-bosnia-provider-documentation-review.md).
This record separates fresh live checks, offline catalogue inspection and recorded
source tests. No production code or catalogue artifact changed.

## Current input and output locations

The commands and file locations below record the historical verification run.
Retained outputs and source material belong in the private
[source archive](https://github.com/RivRetrieve/verification-evidence).
Follow [verification evidence](../../maintenance/evidence.md) to select and
retrieve exact inputs outside the checkout. Current script invocations require
these explicit locations:

```sh
uv run python docs/verification/bosnia-provider/inspect_catalogue.py \
  --native "$RIVRETRIEVE_TEST_EVIDENCE_ROOT/src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet"

uv run python docs/verification/bosnia-provider/check_sources.py \
  --source-requests "$RIVRETRIEVE_TEST_EVIDENCE_ROOT/docs/verification/bosnia-provider/source-requests.json" \
  --out /path/to/external-output/authoritative

uv run python docs/verification/bosnia-provider/check_workbooks.py \
  --out /path/to/external-output/workbooks
```

The last two commands acquire fresh source bytes. They do not reproduce the
historical acquisitions. Keep their stdout, stderr and downloaded bodies outside
the checkout. The recorded tests also require `RIVRETRIEVE_TEST_EVIDENCE_ROOT`.

## Tested revision and environment

- Implementation and catalogue revision: `c52581617c3a3074ce990cfafe289c129689f7c4`.
  This merges target `main` at `a74d508` into Thiago's original branch commit
  `6f08a0b`, preserving both histories. The only conflict was the provider list;
  the resolution keeps Bosnia and every current provider link.
- Documentation and supporting evidence were the only uncommitted changes during
  verification. These changes do not modify provider behavior.
- CPython 3.13.8. Project commands used `uv` from the checkout root.
- Only implementation checkout created:
  `.worktrees/visions/bosnia-provider-documentation-review`.
  Independent source research used an evidence directory, not another checkout.
- Initial environment setup failed before importing RivRetrieve because the
  inherited `/private/tmp/pce-uv-cache` lacked a wheel's `WHEEL` file. A fresh
  worktree-local cache resolved this environment failure:
  `export UV_CACHE_DIR="$PWD/.uv-cache"`.

## Exact live public example

```bash
uv run python docs/verification/bosnia-provider/example.py > docs/verification/bosnia-provider/example-output.txt 2> docs/verification/bosnia-provider/example-stderr.txt
```

[`example.py`](example.py) is exactly the provider page's sole Python block,
executed in a fresh session in the documented order. It uses `cache="bypass"`.
`example-output.txt` (archived) retains the exact displayed output:
69 discharge rows at station `2310`, HS Ključ on the Sana, for September 1–3,
2026. The first row is a published blank; source timestamps are naive and
returned with `time_zone="unknown"`. Source unit `m³/s` becomes returned unit
`m3/s` without changing the values.

The two informational issues report that RivRetrieve has not established the
licence and citation. They are not failed observation requests or measurement
quality flags. The first final-form run took 4.70 seconds.
`example-stderr.txt` (archived) records openpyxl's warning that the
publisher workbook has no default style. It is separate from RivRetrieve's
returned issues and did not prevent reading the timestamp/value cells.

The original station was retained. A three-day window gives a readable example
of source values, blanks and absent rows; it does not avoid any demonstrated
code failure. No code defect was found, and no production repair or workaround
was made. The fixed window will eventually roll out of the source files.

## Independent live workbook inspection and quantity checks

```bash
uv run python docs/verification/bosnia-provider/check_workbooks.py > docs/verification/bosnia-provider/workbook-output.txt 2>&1
uv run python docs/verification/bosnia-provider/check_quantities.py > docs/verification/bosnia-provider/quantity-output.txt 2>&1
```

The workbook script fetches layer-20 metadata, resolves its published group for
each station and downloads source bytes directly. It uses openpyxl independently
of RivRetrieve's parser. `workbook-output.txt` (archived) records URLs,
UTC access instants, HTTP statuses, SHA-256 digests, exact headers, full row counts,
blank counts and first/last timestamps. All four requests returned HTTP 200.
Raw workbooks, metadata and this run's records are retained in the private source archive.

| Fresh workbook | Source header | Full rows | Blank values | First label | Last label |
|---|---|---:|---:|---|---|
| `2310/Q/Q_1Y.xlsx` | Proticaj, m³/s | 7,975 | 96 | 2025-09-29 00:00 | 2026-09-28 19:00 |
| `2310/H/H_1Y.xlsx` | Vodostaj, cm | 7,902 | 0 | 2025-09-29 00:00 | 2026-09-28 18:00 |
| `4110/WT/Tvode_1Y.xlsx` | Temperatura vode, °C | 1,371 | 0 | 2025-09-29 00:00 | 2025-11-30 01:00 |

The discharge source has exactly 69 rows in the example window, six blank
values, and no September 1 midnight row. Its first three timestamp/value pairs
match the public preview, including the source's floating-point value
`3.9330000000000003`. The stage workbook has 63 rows in that window. The
water-temperature workbook has no rows there; it is an example of stale,
shorter availability despite a yearly filename. These checks establish sample
spans, not continuous coverage, a universal one-year minimum or a refresh schedule.

`quantity-output.txt` (archived) retains additional fresh public-API
checks, each with cache bypass:

- Discharge `2310`, September 1–3, 2026: 69 rows, six nulls, `m³/s` to `m3/s`.
- Stage `2310`, same window: 63 rows, no nulls, `cm` to `m`, first value
  `-5 cm` becomes `-0.05 m`. A negative stage does not establish a datum.
- Temperature `4110`, October 1–3, 2025: 72 rows, no nulls, `°C` to `degC`,
  first value 6.5. This window was chosen from the freshly inspected source span.

All three return unknown time zones and only the same two informational
provenance issues. The temperature check does not claim September 2026 availability.
These are supporting checks, not extra snippets on the reader page.

## Offline catalogue and implementation evidence

```bash
uv run python docs/verification/bosnia-provider/inspect_catalogue.py > docs/verification/bosnia-provider/catalogue-output.txt 2>&1
```

`catalogue-output.txt` (archived) establishes 60 locations and 180
selectable series candidates: all three quantities at every station. The packaged
availability table records discharge and stage as available at 60 each; water
temperature is available at 12 and unknown at 48. These are acquisition-time
conclusions, not a live survey of every station or guarantees for a period.
The public inventories are incomplete. Frequency and statistic remain unknown.
The native metadata identifies `2310` as HS Ključ on the Sana, matching fresh
layer-20 metadata.

Code inspected at the tested revision:

- `src/rivretrieve/_internal/providers/ba_fhmzbih/config.py`: source Q, H and WT
  workbook routes, source parameters/units, unknown time zone and temporal support.
- `fetch.py`: live group routing from layer 20, then complete yearly workbooks.
- `parse.py`: exact workbook station/parameter/unit headers, unknown time zone,
  retained blanks, source-structure validation and no quality-flag inference.
- `generate_catalogue.py` and `origins.py`: station/product availability conclusions
  from recorded acquisitions, rather than current-period promises.
- Shared conversion and architecture contracts establish harmonised units and
  closed timestamp-window clipping. Unknown temporal support does not become
  an instantaneous reading or hourly mean.

## Authoritative institutional and terms evidence

An independent source researcher fetched 12 official URLs on 2026-09-28; all
returned HTTP 200. `source-requests.json` (archived) retains exact
access timestamps, final URLs and response digests. `source-evidence.md` (archived)
contains claim-to-source references, exact quotations, explicitly unofficial
translations and scope limits. The implementation agent also re-fetched those
URLs through the project environment:

```bash
uv run python docs/verification/bosnia-provider/check_sources.py > docs/verification/bosnia-provider/source-checks.log 2>&1
```

`source-checks.log` (archived) records that second acquisition. Source
HTML is retained in the private source archive; the archived
extracts and request manifests retain the substantive evidence.

The main corrections to the original claims are:

- AVP Sava's jurisdiction is the Black Sea drainage area **within the Federation
  of Bosnia and Herzegovina**, not all of Bosnia and Herzegovina. Institutional
  monitoring duties do not establish ownership or the operator of every station.
- FHMZBiH links readers to AVP Sava's information system. The provider identifier's
  mapping to AVP workbooks is established by current code and live request URLs;
  no historical explanation for the identifier is invented.
- The Impressum's exact informational/not-official quotation is verified. It does
  not say provisional, quality controlled or approved.
- The Impressum does not state a reuse licence or citation format. AVP Sava's
  main site carries an “All rights reserved” notice. The page therefore makes
  no claim of unrestricted reuse or an exhaustive absence of terms elsewhere.

## Recorded tests and documentation checks

```bash
uv run pytest -q tests/test_ba_fr_public.py tests/test_ba_fhmzbih_recorded_public.py tests/test_source_field_boundaries.py
uv run --with rdflib pytest -q tests/test_documentation.py tests/test_supporting_documentation.py tests/test_reference_contracts.py
uv run python scripts/generate_reference.py --check
uv run ruff check docs/verification/bosnia-provider/*.py
uv run ruff format --check docs/verification/bosnia-provider/*.py
git diff --check
```

- Focused tests (archived): **38 passed in 81.76s**, eight existing
  openpyxl style warnings. Existing tests protect public routing, exact identities,
  units, clipping, receipts, blank rows, empty temperature, malformed headers,
  timestamp validation and source-failure isolation. Some tests also cover France.
  Recorded inputs and authored corruption controls do not prove live availability.
- Documentation tests (archived): **28 passed in 8.20s**, with
  one existing rdflib `ConjunctiveGraph` deprecation warning.
- Reference check (archived): **Reference is current.**
- No new tests or expensive combinations were added. New test runtime impact is
  zero. The checks reuse established focused coverage.
- Ruff lint and format checks passed for all five supporting Python scripts.
  `git diff --check` passed. The final page Python block and displayed output
  were compared exactly with the executed script and captured stdout.
- Final reruns of the example, catalogue inspection, workbook inspection and
  supporting quantity checks passed together in 16.38 seconds.

## Limits and human review

Live verification covers the named stations, quantities and windows only.
The source can change values, have gaps, return blanks or cease to serve data.
A short successful request does not establish full historical continuity or
scientific quality. No time zone, averaging interval, station ownership or reuse
permission was inferred. No outage blocked these checks.

The work updates the existing PR and preserves Thiago's authorship and the
provider index. Independent review of `72263349fb8e1321ee5d6305de4b572f7a6e9aee`
found no actionable issues and reproduced the live example, catalogue inspection,
quantity checks and 38 focused tests (83.91 seconds). The reviewer did not re-fetch
all institutional pages or rerun the documentation suite.

The original human review gate was satisfied on 2026-09-28. After reviewing the
page, the user explicitly authorised finishing and merging without another human
gate. Their feedback led to two separately tracked follow-ups:
[#406](https://github.com/RivRetrieve/RivRetrieve/issues/406) for geographical
coverage and AVP naming with compatibility, and
[#407](https://github.com/RivRetrieve/RivRetrieve/issues/407) for archive access.
The page links these roadmap items without promising current support. No example,
production code or catalogue changed in this follow-up. The documentation suite
was rerun: 28 tests passed in 7.29 seconds. The generated reference remained current,
and `git diff --check` passed.
