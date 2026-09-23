# Canada provider verification

## Scope and revision

This is documentation verification, not a production-code change.
Revision `6da9b64` merges original PR #274 (`c909dbf`) with main `5469884`.
Only documentation and focused documentation tests change after that merge.
The original author commits remain in the existing branch.

## Fresh national acquisition

`acquisition.json` records the successful public `rr.download("ca_eccc")`
execution, edition, source URL, SHA-256, timing and compiled footprint.
The complete national July 17, 2026 ZIP was freshly acquired on September 22;
compilation and certification completed successfully. This was not a fixture,
old-store read, monkeypatched download or recorded-response replay.
The public compiler removes publisher artifacts after successful certification.

From the checkout, the executed commands were:

```bash
UV_CACHE_DIR="$PWD/.uv-cache" RIVRETRIEVE_CACHE_DIR="$PWD/.evidence/canada-2026-09-23/cache" uv run python -u .evidence/canada-2026-09-23/acquire.py
RIVRETRIEVE_CACHE_DIR="$PWD/.evidence/canada-2026-09-23/missing-cache" uv run python -u .evidence/canada-2026-09-23/isolated_conditions.py
uv run python -u .evidence/canada-2026-09-23/retrieve_available.py
uv run python -u .evidence/canada-2026-09-23/final_snippets.py
```

For the last two commands, the process environment retained the first command's
`RIVRETRIEVE_CACHE_DIR` and checkout-local `UV_CACHE_DIR`.
The scripts here preserve the commands' inputs; full execution logs and the
compiled store remain in the checkout's `.evidence/canada-2026-09-23/`.
The 57 MB acquisition log contains full manifest object representations;
`acquisition.json` is its concise transcription, not a second acquisition.

Before acquisition, available disk was 323,697,803,264 bytes and physical RAM
was 68,719,476,736 bytes. These are host resources, not minimum requirements.
Public download and compilation took 3,585.31 seconds. The resulting store
occupies 412,848,037 bytes. Peak disk and RAM usage were not measured.
The publisher listing independently shows the compressed ZIP as 266M;
an exact transferred-byte count was not retained. No 1 GB estimate is asserted.
An inherited uv package cache initially had a missing wheel file. Setup was
retried with checkout-local `UV_CACHE_DIR` before project execution.

## Local retrieval from that acquisition

The main page retains station `05OG008`. The original year 2000 has no rows
for that station in the freshly certified store. `diagnose_empty.py` and its
log retain that inspection; selection and compiled series/facts identities
agree. This is absent data, not a confirmed retrieval defect. A new historical
week, March 1–7, 1991, returns seven rows with no issues. A short example does
not establish continuous station history or national availability.

`retrieve_available.py` used the public API with receipts and compared bypass
and reuse using `polars.testing.assert_frame_equal`. `retrieval.log` retains a
concise extract: seven values, the ten public columns, no issues, identical
reuse, and the local edition. The public result has no quality column.
The preserved full local receipt log shows native `FLOW_SYMBOL` fields in the
store excerpt; this does not make those symbols canonical quality flags.

`final_snippets.py` executes the exact final retrieval and status blocks in
order, using the already prepared national store. The preparation block uses
the same public download call as `acquire.py`; the national transfer was not
needlessly repeated. `final_snippets.log` is the exact displayed output.

## Isolated conditions and catalogue

`isolated_conditions.py` and its log confirm 8,057 packaged station locations
and one daily mean discharge candidate at `05OG008`. The separate missing
cache returns zero rows with `bulk.store_missing`, and no source calls.
`cache="refresh"` raises `FatalContractError` and directs explicit `download`.
No existing user cache was read, modified or cleared. Two initial author
mistakes accessing selection locations were corrected before the successful
probe; they were not library defects.

The declarations and compiler establish daily mean discharge and stage, their
units, unknown time zone/day definition, native symbol retention and monthly
cell unpivoting. The catalogue's source facts leave vertical reference and
record dates unestablished. These code facts do not establish publisher terms.

## Authoritative publisher evidence

`sources/INDEX.json` identifies fresh HTTP checks, URLs, status, retrieval times,
byte counts and SHA-256 hashes. The selected raw response bodies are retained.
`source-claims.md` distinguishes institutional, time, status and legal claims.
The full researcher directory remains at repository-root
`.worktrees/visions/canada-source-evidence/`; broad searches and unused bodies
are deliberately not committed. References to auxiliary PDF/release evidence
in that matrix refer to this full retained directory.

The official historical dataset record links the SQL archive and names OGL.
ECCC's separate server licence is not treated as identical or given invented
precedence. MDB-specific citation wording is not relabelled as SQLite wording.
These publisher-page checks are distinct from the actual fresh archive download.

## Focused validation and remaining gates

`tests/test_canada_documentation.py` checks snippet syntax/current selection,
packaged count, evidence hashes and the index link. These are authored offline
checks, not live acquisition evidence. Missing-store tests exercise isolation
with test doubles. Validation results are retained in `tests.log`.
Independent review and Nicolas's explicit feedback are required before delivery
is complete. PR #274 must not be approved or merged by the implementing agent.

Validation: 15 focused tests passed; 42 existing documentation/reference tests
passed (one upstream rdflib deprecation warning). Ruff check and format check
passed for the new test. `git diff --check` passed.
