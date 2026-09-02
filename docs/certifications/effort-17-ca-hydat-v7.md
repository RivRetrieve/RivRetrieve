# Effort 17 Canada HYDAT national certification

This is a sanitized operational record. The source archive, generated store, runner, and full logs are external evidence and are not committed. This record does not claim that the 278,852,677-byte official response is replayable from a fresh clone. The committed compact fixture separately proves the compiler boundary on a checksum-pinned derived input.

## Certified runtime

- Code commit: `78cde3408df5cd9143b0f66b342f5b1bbbc405b1`
- Git tree: `fa374c074db260a9f13b129194a0a4d7f762aa04`
- Runner SHA-256: `dcf69ab211bec7f385a95bc9cdc3ff6d1c4cfa148844fe20da8822bc5444d693`
- Explicit dependency closure: 33 files, canonical closure SHA-256 `e40761a69ba1c5a6747e9e7e1e3e2aaa255256190de827367d0412549b154592`
- `pyproject.toml` SHA-256: `e12b6b09ceed5669978ea70fd99cc88f45c42041805f14b84b3332efe6b0dd72`
- `uv.lock` SHA-256: `3a2523f8d2471b4e2d771009b47688ce67a33fa8f7e8150896c34b23660a33e7`
- `.python-version` SHA-256: `02e735b3dfe1c32833eb550b7ff8ffa17f5f2bc3fa1e7bae61a8f5a3883ce398`
- Environment: Python 3.13.8 on macOS 15.7.3 arm64; the operational log binds the complete installed-package manifest without retaining a local executable path here.

The later commit that adds this record changes the PR head only. It does not change the certified runtime closure. No runtime result is attributed to the record-only commit.

## Official input

- Requested and final URL: `https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/Hydat_sqlite3_20260717.zip`
- HTTP response date: `Wed, 02 Sep 2026 15:12:53 GMT`
- Original UTC retrieval instant: `2026-09-02T15:17:12.591855Z`
- Last-Modified: `Mon, 20 Jul 2026 17:51:26 GMT`
- ETag: `"109ef445-6570e8e22909f"`
- MIME type: `application/zip`
- Size: 278,852,677 bytes
- SHA-256: `b05eb121a547ca4a179a27aa47c354089fd902e93e5dc1e4a5416fc4641eb298`
- Source vintage: `2026-07-17`

The precise retrieval instant above comes from the original repository attestation. The superseded v6 runner printed `2026-09-02T15:17:12Z`, which was whole-second normalization, not a second exact capture time. v7 uses the precise attested value.

## Independent source census and compilation

| Source table | Input records | Expected calendar contributions | Output product |
|---|---:|---:|---|
| `DLY_FLOWS` | 1,779,871 | 54,219,307 | `discharge_daily_mean` |
| `DLY_LEVELS` | 840,225 | 25,592,677 | `stage_daily_mean` |

The independently computed calendar-contribution census matched the source-closure gate exactly.

- Provider: `ca_eccc`
- Compiler version: `0.1.49`
- Build/start: `2026-09-02T22:27:14.684199+00:00`
- Finish: `2026-09-02T22:55:32.213946+00:00`
- Total rows: 79,811,984
- Product totals: 54,219,307 discharge; 25,592,677 stage
- Partitions: 344
- Output files: 345, comprising 344 partitions and one manifest
- Output bytes: 373,468,647
- Manifest SHA-256: `f6f101d4d9f4f112f11a62ada7f221b186dd1894a5eeb96a672784fc6962a020`
- Store tree SHA-256: `34e88cb1a91c92b2b78cc64a0d898d88ca2173ce12e86ba4bc0bb1c07b8b4d5b`
- Tree algorithm: SHA-256 over each file in sorted relative-path order as `relative path UTF-8`, NUL, then exact file bytes
- Elapsed time: 1,951.92 seconds
- Maximum resident set size: 1,588,510,720 bytes

## Validated readback

The shared validated-store reader returned these exact first three rows for station `02GA010`, 2020-01-01 through 2020-01-03. Every time zone remained `unknown`.

- `discharge_daily_mean`: `31.0`, `19.299999237060547`, `15.300000190734863`
- `stage_daily_mean`: `3.865000009536743`, `3.6489999294281006`, `3.565000057220459`

Both readbacks used naive midnight wall-clock timestamps on `2020-01-01`, `2020-01-02`, and `2020-01-03`.

## Gates, history, and review

- Before v7 started, exact head `78cde34` was clean; 1,967 tests passed with two optional `folium` skips; Ruff format/check and source Ty passed. Full Ty had the same 270 pre-existing test-tree diagnostics as `origin/main`, with zero delta.
- A fresh transaction reviewer approved the API-wide rollback repair before v7 started. It independently verified both certification APIs, prior-store retry, backup-absent safety, artifact timing, independent restoration/cleanup aggregation, and pre/post-commit boundaries.
- v5 failed before compilation because its census SQL rendered a literal `{table}`. Its failure evidence remains separate and is not a certification result.
- v6 completed 79,811,984 rows on runtime head `1811cab`, but was superseded after an API-wide pre-commit rollback defect was found. Its immutable result remains historical provisional evidence and is not used to certify `78cde34`.
- v7 is the authoritative operational run for `78cde34`. Final log `ca_final_78cde34_v7_certification.log` has SHA-256 `6d396508663bad8f9b8f6bb33bd2974ea71253a89b549488eabc2259e15c68b0` and ends with `CERTIFICATION_COMPLETE True`.
- Independent evidence audit `effort-17-hydat-v7-independent-audit.md` has SHA-256 `dac50fb51705fd5043e34e15761158672326f8af9c022dd612044dbdc9f50a5f` and approved v7 with no blocker.

`CERTIFICATION_COMPLETE True`
