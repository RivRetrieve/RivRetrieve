# fr_hubeau Provider Port Notes

## Source Endpoints

| Endpoint | Role | Auth | Notes |
|---|---|---|---|
| `https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations` | Native hydrometry catalogue refresh | None | Seven attested JSON pages; 6,454 rows. |
| `https://hubeau.eaufrance.fr/api/v1/temperature/station` | Native temperature catalogue refresh | None | One attested JSON response; 869 rows disjoint from hydrometry. |
| `https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab` and `observations_tr` | Observation retrieval | None | Existing paginated observation behavior is unchanged. |
| `https://hubeau.eaufrance.fr/api/v1/temperature/chronique` | Temperature observation retrieval | None | Existing observation behavior is unchanged. |

## Catalogue and Observation Source Split

Catalogue refresh preserves the two station endpoints in a committed 7,323-row `native.parquet`.
Canonical generation is a pure, network-free build from that table and endpoint-specific origin
declarations. Observation retrieval remains on the existing hydrometry and temperature clients; this
migration changes no pagination, windowing, issue vocabulary, parsing, or unit conversion.

## Native Catalogue and Origins

The native table contains 6,454 `hydrometrie/referentiel/stations` rows retrieved at
`2026-08-02T17:32:58Z` and 869 `temperature/station` rows retrieved at `2026-08-02T17:33:34Z`.
Both complete captures have zero null coordinate rows. Endpoint vocabularies and all 54
`code_projection == 31` source rows remain verbatim; no native value is renamed, coalesced, corrected,
or filtered.

| Source field | Canonical target | Notes |
|---|---|---|
| Hydrometry `code_station` | `provider_id`, `station_id` | Exact string identity. |
| Hydrometry `latitude_station`, `longitude_station` | `latitude`, `longitude` | Documented as EPSG:4326; CRS84 establishes longitude/latitude source order while canonical columns name each axis separately. No transformation or reprojection. |
| Temperature `code_station` | `provider_id`, `station_id` | Exact string identity. |
| Temperature `latitude`, `longitude` | `latitude`, `longitude` | Documented as EPSG:4326; CRS84 establishes longitude/latitude source order while canonical columns name each axis separately. No transformation or reprojection. |

Hydrometry evidence is
`https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?code_station=1011000101&format=geojson`,
captured in `tests/test_data/fr_hubeau_geojson_crs_evidence.json`. Its collection and feature geometry
declare `urn:ogc:def:crs:OGC:1.3:CRS84`; geometry and properties contain the same unrounded values.
The complete JSON capture in `tests/test_data/fr_hubeau_referentiel_stations_full.json` uses the same
properties rounded to nine decimal places: 6,400 rows differ before rounding, all agree afterward,
and the 54 exact agreements are precisely the projection-31 subset. The OpenAPI capture corroborates
that the decimal properties are WGS 84 and documents `code_projection` as belonging to the separate
projected coordinate pair.

Temperature evidence is the endpoint-local
`https://hubeau.eaufrance.fr/api/v1/temperature/station?size=2000&format=json`, captured in
`tests/test_data/fr_hubeau_temperature_stations_full.json`. Every geometry carries CRS84; all 869
geometry scalars differ from the consumed nine-decimal properties before rounding and agree after it.

## Narrow Coordinate Correction

Exactly 54 hydrometry rows have integer `code_projection == 31` and the evidenced signature
`coordonnee_x_station == latitude_station` plus `coordonnee_y_station == longitude_station`. The
canonical build transposes only those two scalar axes. It rejects a signature mismatch and applies an
inclusive metropolitan tripwire of latitude `42.4174..49.989435` and longitude
`-0.616424..5.593353` after transposition. These bounds describe only the known code-31 subset, not
France or French territory generally. Every non-code-31 scalar passes through unchanged. No geometry
value is substituted and no reprojection occurs.

## Products and Availability

The six existing product identities and assignments are unchanged: five hydrometry products and one
water-temperature product. All 33,139 station-product rows retain `availability = "unknown"` because
the station endpoints do not publish per-variable availability. Product and station-product metadata
is non-null compact JSON.

## Dates and Determinism

Each station-product row uses its own native row's retrieval date for `last_catalogue_check`.
`catalogue_version` is the maximum native retrieval date. The canonical CLI accepts only
`--native <path> --out <directory>` and cannot fetch live or consume fixtures. Fixture-native refresh
remains available solely to maintain the source-faithful native table.

## Station Count

7,323 canonical stations: 6,454 hydrometry plus 869 disjoint temperature stations. No station is
filtered. The former 6,420 hydrometry / 7,289 total was the superseded pre-m10-s3 shipping state; the
truthful live-refresh safety floor remains 500.

## Observation Notes

Hydrometry pagination follows response `next` links and accepts HTTP 206. Daily elaborated timestamps
remain date-only values interpreted as UTC midnight. Existing conversions remain l/s ÷ 1000 for
discharge and mm ÷ 1000 for stage. Temperature observations remain in degrees Celsius.
