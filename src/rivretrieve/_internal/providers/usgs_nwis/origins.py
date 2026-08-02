"""USGS station origins : CanonicalStationColumn → CatalogueOrigin."""

from rivretrieve._internal import catalogue_origins

STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Field(catalogue_origins.NativeColumn("site_no")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("site_no")),
    "latitude": catalogue_origins.Field(catalogue_origins.NativeColumn("dec_lat_va")),
    "longitude": catalogue_origins.Field(catalogue_origins.NativeColumn("dec_long_va")),
    "crs": catalogue_origins.Field(catalogue_origins.NativeColumn("dec_coord_datum_cd")),
}
