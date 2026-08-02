"""Czech station origins : CanonicalStationColumn → CatalogueOrigin."""

from rivretrieve._internal import catalogue_origins

STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Field(catalogue_origins.NativeColumn("objID")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("objID")),
    "latitude": catalogue_origins.Field(catalogue_origins.NativeColumn("GEOGR1")),
    "longitude": catalogue_origins.Field(catalogue_origins.NativeColumn("GEOGR2")),
    "crs": catalogue_origins.NotPublished(
        catalogue_origins.Evidence("https://opendata.chmi.cz/hydrology/read_me/Popis_kodu_historical.pdf")
    ),
}
