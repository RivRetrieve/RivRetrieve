# Effort 17 Canada HYDAT national certification

**Certification status: CERTIFIED**

This is a sanitized operational record. The source archive, generated store, runner, and full logs are external evidence and are not committed. This record does not claim that the 278,852,677-byte official response is replayable from a fresh clone. The committed compact fixture separately proves the compiler boundary on a checksum-pinned derived input.

## Certified runtime

- Code commit: `cc06fcfd1276cf7be297c4208fd4ad308da771f1`
- Git tree: `0906212ab65428fc204108349d4247e764db33e6`
- Runner SHA-256: `9d3e1f564d16978c791b5107bcd0d604925abbbe510f0cff7c8396f23dcf6e50`
- Explicit dependency closure: 33 files, canonical closure SHA-256 `b981feed6e2489db1369bdfe775e0571f7b959594ccaafe1bff22c172e4e8800`
- `pyproject.toml` SHA-256: `e12b6b09ceed5669978ea70fd99cc88f45c42041805f14b84b3332efe6b0dd72`
- `uv.lock` SHA-256: `3a2523f8d2471b4e2d771009b47688ce67a33fa8f7e8150896c34b23660a33e7`
- `.python-version` SHA-256: `02e735b3dfe1c32833eb550b7ff8ffa17f5f2bc3fa1e7bae61a8f5a3883ce398`
- Environment: Python 3.13.8 on macOS 15.7.3 arm64; the operational log binds the complete installed-package manifest without retaining a local executable path here.

The later record-only commit changes the PR head only. It does not change the certified runtime closure. No runtime result is attributed to the record-only commit.

## v7 relationship

V7 remains valid historical operational evidence for exact head `78cde3408df5cd9143b0f66b342f5b1bbbc405b1`. V8 supersedes it only as the current exact-head operational evidence for `cc06fcfd1276cf7be297c4208fd4ad308da771f1`.

The two ordered 33-file closures differ only in `src/rivretrieve/_internal/discovery.py`: v7 used 10,033 bytes with SHA-256 `1acb7ab6961872c469d3d5d77cd5f034e0168b6ac6b63ac4d7a8181dc9335120`; v8 uses 10,158 bytes with SHA-256 `a3c1cd900f0eebb698f52228f89dc5909f8e0013cad258b3bd3054d70861ef47`. The change expands the `clear_cache()` docstring. Executable behavior is unchanged. V8 therefore closes exact-head identity after a documentation-only closure change; it does not correct a v7 output defect.

## Evidence-split disposition

The accepted evidence has three distinct roles: (1) this checksum-bound external operational certification covers the exact official national archive, (2) the committed checksum-pinned derived fixture covers deterministic compiler mechanics, and (3) committed official OGC/CSV recordings independently corroborate selected publisher facts. The recordings and fixture were not inputs to the national compiler. Together these parts do not make the national response fresh-clone replayable.

## Official input

- Requested and final URL: `https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/Hydat_sqlite3_20260717.zip`
- HTTP status: 200
- HTTP response date: `Wed, 02 Sep 2026 15:12:53 GMT`
- Original UTC retrieval instant: `2026-09-02T15:17:12.591855Z`
- Last-Modified: `Mon, 20 Jul 2026 17:51:26 GMT`
- ETag: `"109ef445-6570e8e22909f"`
- MIME type: `application/zip`
- Size: 278,852,677 bytes
- SHA-256: `b05eb121a547ca4a179a27aa47c354089fd902e93e5dc1e4a5416fc4641eb298`
- Source vintage: `2026-07-17`
- ZIP integrity: clean, with one `Hydat.sqlite3` member
- Member identity: 1,296,893,952 bytes; SHA-256 `9185ea30301229ed90675dc82d71efe4b294d6f0227241e219d4c26d212ef517`; CRC32 `d2f99a9a`

The precise retrieval instant comes from the original repository attestation. The runner reused the retained checksum-pinned response. It did not perform or claim a second network retrieval.

## Independent source census and compilation

| Source table | Monthly records | Calendar contributions | `SUM(NO_DAYS)` | Output product |
|---|---:|---:|---:|---|
| `DLY_FLOWS` | 1,779,871 | 54,219,307 | 54,219,307 | `discharge_daily_mean` |
| `DLY_LEVELS` | 840,225 | 25,592,677 | 25,592,657 | `stage_daily_mean` |
| Total | 2,620,096 | 79,811,984 | 79,811,964 | both products |

The independently computed calendar-contribution census matched the source-closure and product-total gates exactly. Stage uses 25,592,677 calendar cells rather than `SUM(NO_DAYS)` 25,592,657 because four `07HF001` rows differ: 2013-02 records 25 versus 28 days, 2013-03 records 20 versus 31, 2014-04 records 26 versus 30, and 2014-05 records 29 versus 31. Published values occur after `NO_DAYS` in the March 2013 and May 2014 rows. `NO_DAYS` is retained without reinterpretation and is not used as a terminal-day bound. No populated value or symbol occurs after the valid calendar month.

- Physical SQLite schema: 73 `DLY_FLOWS` columns and 74 `DLY_LEVELS` columns
- Source-schema fingerprint: `sha256:a860def22e2f9c3a1ad673a7b7b8a0cb32928cef340f67a316e168456718e2fd`
- Schema gate: all 147 ordered qualified names and declared types matched `HYDAT_SOURCE_SCHEMAS` and the manifest; 68 columns are reconstructible and 79 are retained, with no missing, extra, reordered, duplicated, or type-mismatched disposition
- Provider: `ca_eccc`
- Store format version: 2
- Compiler version: `0.1.49`
- Build/start: `2026-09-03T08:04:47.593276+00:00`
- Finish: `2026-09-03T08:33:28.391984+00:00`
- Body compile interval: 1,720.798708 seconds
- Timed interval: 1,941.02 seconds real; 2,036.08 user; 303.08 system
- Maximum resident set size: 1,391,198,208 bytes
- Total rows: 79,811,984
- Product totals: 54,219,307 discharge; 25,592,677 stage
- Partitions: 344, comprising 167 contiguous discharge years 1860-2026 and 177 contiguous stage years 1850-2026
- Output files: 345, comprising 344 Parquet files and one manifest
- Output bytes: 373,468,647
- Manifest SHA-256: `5da9f33f5b42fed700355a5effbc35fa8656f0e91f8c6fcc6c3751ea496b5d4c`
- Store tree SHA-256: `27a4daa227a3be9f2b9c83268841ebdd8268295ca926e44fa0dbc3b2edf3c573`
- Tree algorithm: one SHA-256 stream over each file in sorted relative-path order as relative-path UTF-8 bytes, one NUL byte, then exact file bytes

A fresh store validation passed. Every independent Parquet footer row count matched its manifest entry. The full partition map is intentionally excluded from this record.

## Validated readback

Direct Parquet filtering and the logged readback returned the same first three rows for station `02GA010`, 2020-01-01 through 2020-01-03:

- `discharge_daily_mean`: `31.0`, `19.299999237060547`, `15.300000190734863`
- `stage_daily_mean`: `3.865000009536743`, `3.6489999294281006`, `3.565000057220459`

All six timestamps are naive midnight wall-clock timestamps. Every `time_zone` value is `unknown`.

## Gates, logs, cleanup, and independent review

- The operational run started and finished on clean exact head `cc06fcfd1276cf7be297c4208fd4ad308da771f1` and tree `0906212ab65428fc204108349d4247e764db33e6`; the worktree, index, and untracked-file census were clean, and the branch equalled its upstream.
- Before the run, that exact head passed 1,987 tests with two optional `folium` skips, a focused 13-test public-help and bulk-recovery suite, Ruff format and lint, and source Ty. Full Ty had the same 270 pre-existing test-tree diagnostics as `origin/main`, with zero delta.
- The runner self-test passed with 62 rows, two partitions, and both product readbacks on the same runtime closure.
- Body log: mode `0444`, 26,023 bytes, SHA-256 `b9148c094ef4595c03c5cddb7bf23f3f91a339e9bbc5f585bf973a70595ab546`.
- Timing log: mode `0444`, 777 bytes, SHA-256 `0888d58e72b6d47dc973487874d3efba6fad5855a5402ec20ed815c6eb671fd2`.
- Final log: mode `0444`, 26,828 bytes, SHA-256 `53d7ecb82e0e084bb28a9208708d6431f2a77cf2370826a976f47fd7cc22949f`.
- Final log bytes equal the body log, then the timing log, then `CERTIFICATION_COMPLETE True` and a newline. The final marker occurs once and is the final line.
- Independent audit `effort-17-hydat-v8-independent-evidence-audit.md` has SHA-256 `3b7b200d4307b0cc3f8ba97c935797c6f78e241e2b6fa351cd89f42c4e64eb0` and approved v8 with no run discrepancy.
- Only the attempt-specific copied input was deleted. The checksum-pinned official source intentionally remains as external evidence.
- The temporary extracted SQLite is absent. No v8 destination staging, backup, quarantine, input-copy, or self-test residue exists. An unrelated diagnostic v2 staging directory remains, so this record makes no global no-staging claim.
- Current v5-v7 evidence hashes and read-only modes match their durable references. This current-state check is not an unrestricted claim about every historical filesystem state.

No national HYDAT ZIP or SQLite is tracked. No source archive, store object, binary payload, secret, absolute local path, local executable path, full installed-package manifest, full dependency-closure map, or full partition map is included here.

`CERTIFICATION_COMPLETE True`
