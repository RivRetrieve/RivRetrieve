"""Lithuania station origins : CanonicalStationColumn → CatalogueOrigin."""

from rivretrieve._internal import catalogue_origins

STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Field(catalogue_origins.NativeColumn("code")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("code")),
    "latitude": catalogue_origins.Field(catalogue_origins.NativeColumn("coordinates")),
    "longitude": catalogue_origins.Field(catalogue_origins.NativeColumn("coordinates")),
    "crs": catalogue_origins.Field(catalogue_origins.NativeColumn("coordinates")),
}
