# Trail: Japan — RESOLVED. No action needed.

**Do not spend time on this.** It is written down so nobody re-opens it.

The concern was that Japan's station coordinates came from `japan_sites.csv`, a file
inherited from older code with no recorded source. That was true of the *legacy* code and
is **no longer true of what RivRetrieve ships.**

## What actually ships

`jp_mlit`'s native table was rebuilt by fetching **MLIT's own per-station register**,
`http://www1.river.go.jp/cgi-bin/SiteInfoDetail.exe?ID=<station id>`, one request per
station, on 2026-08-02. Its columns are MLIT's own Japanese field names, and the
coordinates come from MLIT's `世界測地系` (world geodetic system) field, published as
degrees-minutes-seconds — for example `北緯 44度04分29秒 東経 142度44分25秒`.

Every one of those requests is recorded: the generator keeps a manifest carrying, per
station, the URL, the file, its byte count, its SHA-256, the HTTP status and the retrieval
instant, and it refuses any response that does not carry the expected source marker.

So Japan already has exactly the acquisition record this project now requires — it was
built before there was a name for it.

## What the inherited file turned out to be

Chased to the end anyway, because a dead trail that nobody wrote down gets re-walked:

- `data-raw/GaugeData.R` in the original R package (`github.com/Ryan-Riggs/RivRetrieve`),
  added 2023-03-21, **deleted** 2023-07-13 in commit `6597b41`. Deletion is why every
  search of the working tree came up empty.
- Its Japan block, verbatim:

  ```r
  japan_sites = data.table::fread("E:\\research\\GSIM\\GSIM_metadata\\GSIM_catalog\\GSIM_metadata.csv")
  japan_sites = japan_sites[japan_sites$reference.db=="mlit",]
  ```

- So the legacy coordinates were **never MLIT's**. They were read from a local copy of the
  **GSIM** (Global Streamflow Indices and Metadata) archive on a personal drive, filtered
  to the rows GSIM attributes to MLIT. That CSV is in no commit and its release is
  unrecoverable from the repository.
- `japan_sites.rda` has been byte-identical since 2023-03-21 (md5
  `754ca856f77eec5664ed8f94d2df26c2`) and was never regenerated.
- The associated paper (doi:10.1088/1748-9326/acd407, open access) credits the Japanese
  Water Information System for the *records* and never states where the *coordinates* came
  from. Its Table 1 reports 1023 Japanese gauges; the file holds 1029.

None of that matters for what we ship, because we no longer use the file. It matters only
so that nobody mistakes GSIM-derived coordinates for MLIT's again.

## Your only job for `jp_mlit`

The terms and citation, in `finding.md`. Note that MLIT's site actively refuses automated
access, which is itself relevant to the terms question.
