"""Canada station origins : CanonicalStationColumn → CatalogueOrigin."""

from rivretrieve._internal import catalogue_origins

CRS_EVIDENCE_URL = "https://api.weather.gc.ca/collections/hydrometric-stations?f=json"

STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Field(catalogue_origins.NativeColumn("STATION_NUMBER")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("STATION_NUMBER")),
    "latitude": catalogue_origins.Field(catalogue_origins.NativeColumn("geometry.coordinates[1]")),
    "longitude": catalogue_origins.Field(catalogue_origins.NativeColumn("geometry.coordinates[0]")),
    "crs": catalogue_origins.Documented(
        catalogue_origins.DocumentedValue("EPSG:4326"),
        catalogue_origins.Evidence(CRS_EVIDENCE_URL),
    ),
}
