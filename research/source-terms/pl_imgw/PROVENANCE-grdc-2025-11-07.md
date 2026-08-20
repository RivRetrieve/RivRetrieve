# Provenance record: Poland's station coordinates

Evidence behind the `## Answer` in `TRAIL.md`. Redacted deliberately: this repository is
public, and the correspondents' addresses are not needed to establish provenance. The
original message is held by Thiago Nascimento and can be produced if this is ever disputed.

## The message

| | |
|---|---|
| Sent | **2025-11-07 12:40:38 +0000** |
| From | a sender at **`bafg.de`** — the Bundesanstalt für Gewässerkunde, which hosts the GRDC |
| To | three RivRetrieve maintainers, **including the maintainer who committed PR #83**; addresses withheld |
| Subject | `AW: Some Updates` |
| Format | `.eml`, 188,701 bytes, sha256 `5a12e0fd96d5f2b35e15cc75a76e6e9a62416a87d7d483e28be3d18c03a936e0` |

## The attachment

| | |
|---|---|
| Filename | `Metadata_GRDC_30.10.2025.xlsx` |
| Type | OOXML spreadsheet, single sheet `List1` |
| Size | 116,301 bytes |
| sha256 | `dfab6ea7de80fb1570f4a8dded8743ed7c7dcb4eb67fe75e2c0e02e9b964b7bf` |
| Content | 1,301 data rows; columns *Station code, Station name, River/Lake, Latitude, Longitude, Catchment area (square kilometre), Height of gauge zero (m above sea level), Vertical reference system* |

Coordinates are given as **degrees-minutes-seconds with three decimal places on the
seconds**, comma as the decimal separator — for example `49° 59' 37,035" N`.

## The verification

Every row of `tests/test_data/pl_imgw_stations.csv` was matched by `Station code` against the
attachment, and each field compared. Performed 2026-08-20.

| Field | Result |
|---|---|
| station ids | 1,301 / 1,301 matched; none missing on either side |
| latitude | 1,301 / 1,301 identical |
| longitude | 1,301 / 1,301 identical |
| catchment area | 1,301 / 1,301 identical |
| gauge altitude | 1,241 / 1,241 identical (60 are `ND` in both) |
| station name | 1,301 / 1,301 identical |
| river | 1,301 / 1,301 identical |

Largest coordinate deviation across all 2,602 values: **7.1 × 10⁻¹⁵ degrees**, which is
float64 round-trip noise from the DMS-to-decimal conversion, not a difference in the data.

**This is an exact match on every field of every row.** The shipped Polish catalogue is this
attachment, converted from DMS to decimal degrees. The provenance question is closed.

## Why the DMS fingerprint pointed here

`TRAIL.md` recorded that all 2,602 coordinate values are exact multiples of 0.001
arc-seconds, and inferred a DMS register rather than the public API. Re-verified on
2026-08-20: 2,602 / 2,602, zero violations. The attachment is precisely that register, and
the inference was correct.
