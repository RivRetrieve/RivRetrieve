# Bosnia recorded public-path expectations

These expectations were authored by the independent `source-boundaries` worker and accepted by the root reviewer on 2026-09-14. The author read only the four authorized complete XLSX bodies, their exact new recordings and acquisition manifest. No Bosnia implementation, production parser output, earlier derived summary or implementation diff was read. The implementing worker transcribed the accepted literals below.

The independent author inspected ZIP/XML worksheet rows and shared strings. `date1904=false`, timestamp cell styles and Excel serial values establish naive wall clocks; no observation zone is stated. Numerical and blank measurement cells were counted separately. `#Rows` was checked against actual cells, not used as a numerical witness. The original source-only script SHA-256 is `b171900c41807d55d90e880b093fd7f127dc89f4fdc7b8ab2f5438f1200efc1f`; its output SHA-256 is `5b5326ec4d18ddbf86d9fa83f0a9e35e3d0ef923d1fd79acb8f63614ed7ca79d`. Manifest SHA-256: `48b93896bae8a47ebddff9e2f0f2c1c444ace30eff9836db4886b93b82d0d8cc`.

The adjacent four `ba_fhmzbih_{station}_{code}_1Y.recording.json` files retain the complete source bodies, actual September 14 retrieval dates and v2 executed request headers. They are a reviewed test subset, not the private baseline corpus. The existing metadata recording is reused unchanged. The catalogue ledger still uses its original September 2/7/9/13 acquisitions, not these test captures.

| Station/code | Closed public interval | Rows | Numeric | Blank | First wall clock | Last wall clock |
| --- | --- | ---: | ---: | ---: | --- | --- |
| 2101-B/Q | 2026-09-01 through 2026-09-03T23:59:59 | 72 | 72 | 0 | 2026-09-01T00:00:00 | 2026-09-03T23:00:00 |
| 2101-B/H | same | 72 | 72 | 0 | 2026-09-01T00:00:00 | 2026-09-03T23:00:00 |
| 2010/Q | 2026-05-22 through 2026-05-24T23:59:59 | 70 | 68 | 2 | 2026-05-22T00:00:00 | 2026-05-24T23:00:00 |

All zones are `unknown`. 2101-B/WT is a valid station/parameter/unit-matched workbook with zero actual rows; it has no invented positive first/last boundary assertion. Its public case uses the September 1–3 interval.

The 2101-B Q first/last values are 0.432 m³/s; H first/last values are 5.2 cm (worksheet rows 8398/8469). The two 2010 blanks in the public interval are May 23 at 01:00 and 04:00. The first is an empty `<c r="B5929" s="3"/>` measurement cell with a real timestamp. Seventy rows are not a filled 72-hour grid.

The complete 2010 workbook has 8,232 timestamped rows: 8,212 numerical and 20 blank. Its annual range contains two different values at the duplicated wall clock 2025-10-26T02:00:00 (worksheet rows 970/971: 11.786 and 11.713000000000001). All three nonempty workbooks contain duplicate wall clocks outside the selected narrow windows. The tests preserve the complete receipts, do not infer DST or a zone, do not change engine duplicate handling, and do not claim the annual source-row count equals final public output.

## Complete-body identities

- `ba_fhmzbih_2101-B_Q_1Y.recording.json`: body `5630fb3bb31da956a5d3d37e0571423fed9e8ed3c6fc4b9d374dfecf612c4167`, 119545 bytes.
- `ba_fhmzbih_2101-B_H_1Y.recording.json`: body `931766224a7267cebf2df0faddfa6867a09935bedd87cf545d326c5eb5bf2ac3`, 118454 bytes.
- `ba_fhmzbih_2101-B_WT_1Y.recording.json`: body `54a1004f6b84366dadea4fe049c99850b9263304d23f20021bb9a04a7b40a370`, 3633 bytes.
- `ba_fhmzbih_2010_Q_1Y.recording.json`: body `ae9bf71f9291a92749188231f78f3af3f4b2a3abb41b6983912917a876405acb`, 121388 bytes.
