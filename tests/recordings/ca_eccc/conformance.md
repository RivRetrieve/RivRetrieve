# Canada HYDAT conformance

## Source facts

Publisher: https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/HYDAT_Definition_EN.pdf

The exact retained definition is `HYDAT_Definition_EN.pdf` in the private source archive
(SHA-256 `b3ab1954bf5aeedb026cebe939764fcfbda0266fb267cb6a7315544c9be8e1ee`).
Pages 4–5 define DLY_FLOWS daily flow values in m^3/s and DLY_LEVELS daily water levels
in m. Their symbol definitions refer to daily mean values. These establish quantity,
unit, daily frequency and mean statistic. Day definition, time zone, level reference
and datum remain unknown. Table identities are RivRetrieve mapping namespaces, not
publisher variant identifiers. Symbols, precision, completeness and archive release
vintage are not separate series.

## Executable evidence

- `tests/store/test_ca_eccc_streaming.py`: actual certified compiler, bounded batches,
  sparse-month calendar expansion, invalid tail cells and reconciliation refusal.
- `tests/store/test_ca_eccc_publisher_schema.py`: publisher-shaped DOUBLE schema through
  certified compilation. This is a mechanical fixture, not a publisher artifact.
- `tests/test_ca_eccc_no_days_evidence.py`: exact publisher CSV responses and retained
  sparse SQLite row witnesses pass through certified compilation; NO_DAYS does not
  truncate March 2013 or May 2014 at station 07HF001. The containing SQLite fixture is
  reconstructed, not a complete publisher database.
- `tests/test_ca_eccc_boundary_probe.py`: the explicitly derived compact ZIP compiles,
  preserves cells and serves the public API with honest store-excerpt receipts.
  Exact OGC responses corroborate values; they are never HYDAT compiler input.
- `tests/test_ca_eccc_conformance.py`: explicit preparation metadata and shared
  station-independent source facts with scientific unknowns retained.

## Inventory and proof limits

GeoMet supplies the station snapshot, not product availability in HYDAT. Catalogue
availability and inventory completeness remain unknown. Explicit download and
certified compilation prepare the local native store; retrieval does not fetch HYDAT
or execute observation queries against SQLite.

A complete publisher-artifact compilation was not repeated for this change. The
retained audit attests the 2026-07-17 ZIP at 278,852,677 bytes with SHA-256
`b05eb121a547ca4a179a27aa47c354089fd902e93e5dc1e4a5416fc4641eb298` and 2,620,096
monthly source records. No complete ZIP was found in the local evidence directory;
reacquisition and certification of approximately 80 million daily rows was not
attempted. This limit does not turn derived fixtures into exact publisher bytes.

Catalogue descriptions and compiled cells share the same full-content physical-fact
identifier. A documented daily mean has interval support; this establishes neither
the day boundary nor timestamp anchor or time zone. Public interval filtering and
retrieval are tested against the certified derived-input store.
