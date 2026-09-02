# jp_mlit provider port notes

## Source and runtime chain

MLIT observations come from `http://www1.river.go.jp/cgi-bin/DspWaterData.exe`. Each engine-planned source window makes one HTML request and follows exactly one publisher-minted, same-host `/dat/dload/download/*.dat` link. HTML is decoded as strict EUC-JP. DAT is decoded as strict Shift-JIS. Both untouched responses remain in ordered receipts and provenance.

The runtime adapter is exactly `config.py`, `fetch.py`, and `parse.py`. Window decomposition belongs to the shared engine. KIND 2 and 6 use inclusive complete year-month windows. KIND 3 and 7 use inclusive complete year windows. Fetch only removes hyphens when rendering `BGNDATE` and `ENDDATE`.

## Products

The accepted source responses establish frequency and physical quantity, but do not establish a mean statistic, interval anchor, time zone, datum, or hydrological-day definition. Japan therefore uses four provider-specific products:

| KIND | product_id | property | frequency | statistic | period anchor | unit |
| ---: | --- | --- | --- | --- | --- | --- |
| 2 | `stage_hourly` | stage | hourly | unknown | unknown | m |
| 3 | `stage_daily` | stage | daily | unknown | unknown | m |
| 6 | `discharge_hourly` | discharge | hourly | unknown | unknown | m3/s |
| 7 | `discharge_daily` | discharge | daily | unknown | unknown | m3/s |

## Source labels and flags

Hourly columns are labelled `1時` through `24時`. The parser preserves those labels as hour 1 on the same source date at 01:00 and hour 24 on the following source date at 00:00. Daily values use their calendar date at 00:00. All rows retain `time_zone="unknown"`. No JST or UTC conversion is made.

Values and native flags are parsed as exact pairs. Blank flags and `*` are usable only with numeric values; `*` also emits `source_tentative`. `$`, `#`, and `-` are non-observations and emit distinct `source_missing`, `source_closed_station`, and `source_unregistered` issues. No numeric sentinel rule is used. Unknown flags, malformed pairs, and nonnumeric usable values are fatal contract failures. Exact DAT bytes, including flags and legends, remain in receipts.

## Catalogue

The committed native table contains 1,023 accepted station-detail responses. It remains unchanged. The four corrected products replace the former unsupported `*_mean` products one-for-one across all 4,092 station-product edges. Availability, reason, bounds, and check dates are preserved. Canonical artefacts rebuild without network access from the committed native table and declared origins.

## Native capture availability

The representative station response was captured successfully during the 2026-08-02 campaign. A later request at `2026-08-03T12:31:42Z` returned HTTP 403 with a 77-byte restriction body. The accepted native evidence is therefore non-refetchable; rebuilds use the committed native table and origins without network access.
