# National preparation measurements

## Behavior and changes

`rr.download("pl_imgw")` replaces the local store with a valid newly acquired
history even when it ends earlier. Removed rows are not carried forward. Incomplete
or ambiguous archive listings, failed transfers and invalid archives still prevent
replacement. Canada's safeguard against an older dated release remains unchanged.

Preparation uses a smaller reconciliation journal, a temporary SQLite table that
checks source-record and emitted-row coverage. Poland expands only the selected
product during each product pass and uses 1024-row sort fetch chunks. An index
maintained during scratch insertion avoids an implicit SQLite sort. Certification
removes one redundant semantic scan, which checks stored values and schema, while
retaining byte checks and complete independent source replay. These changes preserve the shared publication lifecycle.

## Method and exact revisions

Both versions use the same retained publisher inputs selected through the maintained
verification archive. Builds ran serially with network access denied, using retained
publisher originals. They used Python
3.13.14, Polars 1.40.1 and PyArrow 24.0.0 on Darwin 24.6.0 arm64, with 16 logical CPUs.
Machine model and RAM were not recorded. Dependencies were locked at the executable revisions.
Both versions compiled independent input copies named from publisher URL basenames.

- Baseline: [`30ee78e0f4dcb1b57508819894f6d82fbf980d6c`](https://github.com/RivRetrieve/RivRetrieve/commit/30ee78e0f4dcb1b57508819894f6d82fbf980d6c).
- Candidate: [`a906f8b7a1d14a05bc324ee331bc69115b35e7ca`](https://github.com/RivRetrieve/RivRetrieve/commit/a906f8b7a1d14a05bc324ee331bc69115b35e7ca).
- Reviewed archive executable: `53099b6bba902bf875b90d38eb22a6f8fd43994c`.
- Baseline harness SHA256: `04303bca6441142fc3e190354f4fc0f2db6d9d4ad73c0452b708504adb129d93`.
- Candidate harness SHA256: `339276768cb706f0a5a5e6e6c39e2498c9a7e4dd0ea4a40d536e820c420bae4b`.

The baselines are fresh builds. Candidates replace audited prior stores linked to
retained baseline copies. These hardlinks share the same underlying files (inodes). Compilation timers include certification,
publication and cleanup, but exclude setup, working-copy preparation and postcheck
hashes. Observer and extra-root monitoring overhead is unquantified. OS caches were
not purged. Light synthetic checks and two brief, read-only ZIP-directory scans
overlapped the Poland baseline. This was not an isolated benchmark.

## National results

Decimal GB and MB describe bytes. Five-second disk samples can miss short peaks.

| Measure | Poland baseline | Poland candidate | Canada baseline | Canada candidate |
|---|---:|---:|---:|---:|
| Local compilation, seconds | 3,511.349 | 2,722.202 | 2,836.077 | 2,627.485 |
| Observation rows | 59,629,260 | 59,629,260 | 79,811,984 | 79,811,984 |
| Partitions | 228 | 228 | 344 | 344 |
| Final store, MB | 222.986 | 222.986 | 412.932 | 412.932 |
| Sampled managed-file peak, GB | 7.964 | 3.123 | 1.926 | 2.221 |
| Sampled journal peak, GB | 7.395 | 2.324 | 0.241 | 0.123 |
| RSS high-water through compilation, GB | 2.945 | 2.138 | 3.716 | 2.310 |

RSS includes imports, setup and candidate pre-audits. Its final sample precedes the
later baseline-preservation post-audit and comparator. It is not the completed-job
or system-wide peak. Smaller batches do not establish a total memory bound.
The following timings are **inclusive and overlapping; do not add them**.
Compile/write includes decoding, semantic validation and sealing. Source replay
includes decoding and, in the baseline only, the redundant semantic scan.

| Component, seconds | Poland baseline | Poland candidate | Canada baseline | Canada candidate |
|---|---:|---:|---:|---:|
| Independent censuses | 351.945 | 253.106 | 12.450 | 13.527 |
| Sort preparation | 1,714.493 | 1,185.489 | not called | not called |
| Extraction preparation | not called | not called | 4.105 | 4.830 |
| Compile/write including seal | 1,758.083 | 1,456.178 | 1,864.779 | 1,910.649 |
| Source replay | 1,399.013 | 1,010.100 | 952.094 | 696.517 |
| Redundant certification scan | 196.716 | removed | 262.310 | removed |

Poland still makes 6,954 raw decoder entries and 5,220 sort preparations. Smaller
product expansion is protected by tests, not a separately measured national CPU
saving. Canada still extracts four times. Its write phase increased; extraction
remains a small cost. The candidate retains one complete semantic validation and
independent replay. Remaining work is substantial; these timings promise no fixed speedup.

## Disk scope and admission limits

Old data, inputs, output and scratch coexist during replacement; renaming the old
store creates no copy. Canada's higher managed peak includes its old 0.413 GB store.
Poland's sampled active sorts were 393.839/403.218 MB: no sort-space reduction is shown.
The historic 8.587 GB Polish journal is not the comparison baseline; artifact naming differed.
Candidate simultaneous run-plus-originals-plus-baseline peaks were 3.660/3.242 GB
for Poland/Canada by path, or 3.437/2.829 GB after counting each shared underlying file once. These are not
physical APFS allocations. Separate component maxima are not simultaneous totals.
Visible-file sampling misses open, unlinked SQLite spills; physical I/O was not measured.

Admission counts estimated additional growth on actual filesystems, excluding old
stores and inputs already present. Here a source record is one Polish CSV row or
one Canadian monthly table row. Calibration uses 160 bytes/source record for the
journal, a 24-byte/output-row floor, Poland's 80-byte/source-record width reference
and an excess-width term, plus explicit 64 MiB metadata headroom. Width/entropy
probes inform these allowances; they are neither reservations nor guaranteed bounds.
Downloads still buffer a complete response. SQLite caches and concurrent Python/Arrow
buffers remain costs. Native temp accounting assumes the default VFS and unchanged
startup environment. VFS means SQLite's operating-system file backend. Late
environment changes and custom file backends are unsupported.
Windows `GetTempPathW` has source review and synthetic controls, not native Windows
execution evidence. Baseline TMPDIR preceded project imports; startup/site SQLite
initialization was not established. The implementation changes no global temp settings.

## Acquisition replay and fidelity

Strict recorded replays passed: Poland's 943 GETs (76 listings, 867 ZIPs) took 0.209 s;
Canada's 80 final-status HEAD probes and one GET took 0.156 s. Timers include provider
discovery, on-demand retained-body reads and production transfer writes, excluding setup
and identity hashes. Hash prechecks warmed files: these are local replay times, not
network throughput or fresh acquisition. No missing HEAD payload/retry history was invented.
Artifact URL/hash/size/vintage/order and complete response exhaustion matched.

Both national comparisons passed: all stored columns, including original source
fields, matched across every row and partition. Schemas, floating-point bits and
duplicate multiplicity matched in stored order.
Manifests matched except actual build time. Original-seal byte/semantic audits and
frozen input/code/receipt/archive postchecks passed. Baseline bytes, generation,
inode and mtime were preserved; owned ctime changes were recorded. Synthetic tests
protect omissions, substitutions, malformed sources, failed shorter refreshes, late
resource failures and committed cleanup debt. No check infers withdrawal intent or live availability.
