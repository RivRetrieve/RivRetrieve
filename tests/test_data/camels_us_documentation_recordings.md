# CAMELS-US documentation recordings

These three recording-format-v2 envelopes preserve exact response bytes from
`https://waterservices.usgs.gov/nwis/dv/`. They were acquired live on
2026-09-20 through RivRetrieve's real public `find` / `pick` / `fetch` path,
with `RecordingTransport(HttpClient())` at the transport seam. No response
body, method identifier, value or qualifier was authored or edited.

The public request selected discharge, daily frequency and mean statistic for
stations `01013500`, `01022500`, `01030500`, from `2025-01-01` through
`2025-12-31`. Engine padding produced `startDT=2024-12-30` and
`endDT=2026-01-02`. Each request also sent `format=json`, `parameterCd=00060`,
`statCd=00003` and the individual station as `sites`. The envelopes preserve
executed ordinary headers, status, content type, retrieval instant, exact
base64-encoded response bytes and their SHA-256 digest. No credentials were used.

Live acquisition returned 1,095 harmonised rows (365 per station), no issues,
and three response-discovered method identities: `63596`, `63716`, `63740`.
This is acquisition evidence for that date, not a promise about future USGS
availability or revisions.

`tests/test_camels_documentation.py` executes every Python block from
`docs/examples/camels-us.md` in document order through the real public API.
Only transport is replaced, by exact request-matched replay. Tests check all
literal printed outputs, all 2025 dates and values against independent decoding
of publisher bytes, source method identities, outcomes, issues, and saved
Parquet and bundle round trips. Those regression runs are deterministic offline
replay, not live-service checks.

## Recorded byte identity

| Station | Retrieved at (UTC) | Response SHA-256 |
|---|---|---|
| `01013500` | `2026-09-20T13:12:43.783682Z` | `321fa0e85f0db8a0ef907d7b74c3ec6ad2a62080d9f3289c96dbe4b0e49cd36a` |
| `01022500` | `2026-09-20T13:12:44.808397Z` | `7454a2fee56a7877a028aa4f15072187e914b6506e211a9426984ac9e5456502` |
| `01030500` | `2026-09-20T13:12:45.762060Z` | `3fc4e54e01c3937a0681cacf3310629a604454408fe1bdc7097f500f6469054a` |
