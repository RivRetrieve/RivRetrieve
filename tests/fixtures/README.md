# Public historical catalogue controls

`usgs_registered_baseline.json` retains the complete reconstructed provenance
from the public USGS catalogue at the pinned `source_revision` and
`source_directory`. `source_sha256` records the original graph files and
station-metadata table used to create it. The graph was decoded with
`parse_catalogue_evidence` and `reconstruct_provenance`, not rebuilt by a provider
generator. Its build revision is `7dd47d9ec899eec2b2b91a111e7372222073c031`.

The metadata contains the five unchanged rows for station `01646500`, selected
from the original `station_metadata.parquet`. These cover all adopted fields
and the elevation-datum association. The fixture tests historical projection
and declaration validation independently of today's catalogue. It does not
replace full retained-input verification or the ordered historical source
oracle. No publisher response bodies are included.
