"""Bosnia station origins : CanonicalStationColumn → CatalogueOrigin."""

from rivretrieve._internal.catalogue_origins import Evidence, Field, NativeColumn, NotPublished

# The origin gate requires a native field for provider_id; the native code aligns the constant rows.
STATION_CATALOGUE_ORIGINS = {
    "provider_id": Field(NativeColumn("metadata_station_no")),
    "station_id": Field(NativeColumn("metadata_station_no")),
    "latitude": Field(NativeColumn("metadata_station_latitude")),
    "longitude": Field(NativeColumn("metadata_station_longitude")),
    "crs": NotPublished(Evidence("https://vodostaji.voda.ba/data/internet/stations/stations.json")),
}
