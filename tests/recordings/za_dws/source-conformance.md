# DWS source conformance

## Scope and physical mappings

DWS remains `CatalogueOnly`. Discovery reads 2,905 stations and 8,715
unknown-availability edges. No observation service is registered.
The field definitions below establish admission independently of observation
availability. No numerical values are retrieved by the library.

| Native column | Established quantity and source unit | Temporal facts |
| --- | --- | --- |
| `D AVG F/R` | discharge, `cubic metres/sec` | daily average, interval |
| `COR.FLOW` | discharge, `cubic metres/sec` | unestablished |
| `COR.LEVEL` | stage, `m` | unestablished |

Normalization of `cubic metres/sec` to `m3/s` preserves scale. No conversion
is applied to observation values because retrieval is unavailable. Source
zone, daily support boundaries, timestamp anchor and vertical reference are
not established. The Point format calls these corrected measurements, but
does not define averaging support or frequency. Internal product IDs retain
their existing spelling; they are not evidence for an instantaneous statistic.
Sanitized former column aliases are replaced by exact published headers.

## Historical field definitions recovered from the repository

Commit `df1b17778fb1f5d8db8eb3a803822571dc1dde85` added two source-response
fixtures and documented live HTTP 200 checks for X3H001. Its tests read the
fixtures directly. Git history shows their initial addition and later removal
in `e5465b0`, without intervening content changes. The original port notes
attest Daily first value 1.257 and Point first values 0.146 and 1.230, which
match these files. The original test also distinguishes synthetic sentinel
cases from the retained response fixture.

The files here preserve those Git blobs byte-for-byte:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `X3H001_daily_2020-01.html` | 2188 | `d7edcd596883840c36800535c9ad7eaa52fc3d920c837ad134b902c96fa31d20` |
| `X3H001_point_2020-01.html` | 5134 | `7b266fa724354709d1c3cb5602e0bf1b5bfa80e09bc5b272d4145d6153d88ae4` |

These are repository-recovered historical publisher-response fixtures, not
new certified HTTP recordings. Original capture time and response headers
are unavailable. Point completeness is unestablished. The commit instant
2026-06-11T09:28:43Z is a repository provenance lower bound, not an HTTP
retrieval instant. Recovery acquisitions and checksums are in catalogue
lineage. No response replay, transport completeness or present availability
is asserted from them.

Exact Daily definition: `POS. 10-18  = Daily avg flow rate in cubic metres/sec 99999.999`.
Exact Point definitions: `POS. 27-35  = Corrected level in m` and
`POS. 52-60  = Corrected flow in cubic metres/sec`.
Both publish `Variable 100.00 Surface Water Level` and X3H001.
The embedded form records `Station=X3H001100.00`, `DataType=Daily` or
`Point`, `StartDT=2020-01-01`, and `EndDT=2020-01-31` or `2020-01-03`,
respectively, with `SiteType=RIV` on `HyData.aspx`.

Catalogue claims retain that exact variable ID and description only at
X3H001 and those route/column coordinates. The general field mapping does
not assign that variable to every station, create a variant, or promise an
exhaustive source inventory. The historical response identity and the
provider's field definitions are different claims.

## Independently retained Monthly response

`tests/test_data/za_dws_terms_licence-5.html` remains unchanged, SHA-256
`5d10dfdb5c487c4884983cf71149a0533f35b9af0f7ad45f81a8f2e9540baf36`.
Its acquisition is recorded in DWS origins and packaged evidence:

- Archive URL: <http://web.archive.org/web/20230525074558id_/https://www.dws.gov.za/hydrology/Verified/HyData.aspx?Station=A2H023100.00&DataType=Monthly&StartDT=1965-10-23&EndDT=2022-02-09&SiteType=RIV&Format=Old>.
- Retrieved: 2026-08-21T11:33:37Z.
- Header: `MONTHLY VOLUMES A2H023`.
- Identity: `Variable 100.00 Surface Water Level`.
- Field definition: `12 Monthly volumes in million cubic metres from Oct to Sep.`
- Value 13 is the yearly total.

The Monthly volume definition does not establish stage or discharge units.
This claim remains scoped to that evidence record; no mapping to enrolled
Daily/Point columns or national variable inventory follows from its label.
Volume retrieval and computing flow from volume remain outside scope.

## Access and remaining limits

A read-only GET to <https://www.dws.gov.za/hydrology/Verified/> on
2026-09-20 returned HTTP 403. Exact response bytes and non-secret headers
are saved in local effort evidence. Search-service configuration was
unavailable. Neither failure establishes source silence or no alternatives.
No credentials or private external corpus were used.
Station PDFs establish station identity and unsigned DMS, not observed
series availability. Existing CRS and unsigned-DMS provenance is unchanged.
All inventories remain incomplete. Historical field legends do not prove
present retrieval, per-station availability or timeless identity completeness.

## Executable checks

`tests/test_za_dws_source_conformance.py` checks exact retained bytes,
physical mappings, station-scoped variable claims, truthful generated metadata
and lineage. It exercises offline public `find`, `series`, `pick` and `fetch`
refusal under every issue policy and cache mode. Existing DWS tests retain
station counts, unsigned-DMS transformations, unknown CRS and deterministic
catalogue regeneration. RED logs precede repairs of metadata, source mapping
and claim omissions in the local effort evidence directory.
