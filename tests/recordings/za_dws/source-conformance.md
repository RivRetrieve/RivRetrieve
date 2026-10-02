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

## Retained inputs and interpretation limits

The private [source archive](https://github.com/RivRetrieve/verification-evidence)
retains the historical publisher responses, acquisition records and exact byte
identities. The Daily and Point inputs were recovered from repository history.
They are historical publisher-response fixtures, not new certified HTTP recordings.
Original capture times and response headers are unavailable. Point completeness
is unestablished. A repository commit time does not establish HTTP retrieval time.

The historical response identity and the provider's field definitions are
different claims. Catalogue variable claims remain scoped to the recorded
station and route/column coordinates. General field mappings do not assign a
variable to every station, create a variant or establish an exhaustive source
inventory. Historical field definitions do not prove present retrieval,
per-station availability or timeless identity completeness.

The separately retained Monthly response defines volume. It does not establish
stage or discharge units for the enrolled Daily and Point columns. Its variable
label does not establish a national variable inventory. Volume retrieval and
computing flow from volume remain outside scope.

Station PDFs establish station identity and unsigned DMS coordinates, not
observed series availability. Existing CRS and unsigned-DMS provenance is
unchanged. Failed access attempts do not establish source silence or the absence
of alternative sources. All inventories remain incomplete.

## Executable checks

Follow the [verification guide](../../../docs/maintenance/evidence.md) to retrieve
the exact inputs outside source checkouts in their repository-relative layout.
Set `RIVRETRIEVE_TEST_EVIDENCE_ROOT` to that external root, then run:

```sh
uv run pytest tests/test_za_dws*.py -q --tb=no -p no:cacheprovider
```

`tests/test_za_dws_source_conformance.py` checks exact retained bytes, physical
mappings, station-scoped variable claims, generated metadata and lineage. It
exercises offline public `find`, `series`, `pick` and `fetch` refusal under every
issue policy and cache mode. The other DWS tests check station counts, unsigned-DMS
transformations, unknown CRS and deterministic catalogue regeneration. Missing
retained inputs block the corresponding checks. Keep detailed test output private.
