"""Swiss station origins : CanonicalStationColumn → CatalogueOrigin."""

from rivretrieve._internal.catalogue_origins import Evidence, Field, NativeColumn, NotPublished

# The origin gate requires a native field for provider_id; native name does not contain the RivRetrieve constant.
STATION_CATALOGUE_ORIGINS = {
    "provider_id": Field(NativeColumn("name")),
    "station_id": Field(NativeColumn("name")),
    "latitude": Field(NativeColumn("details.lat")),
    "longitude": Field(NativeColumn("details.lon")),
    "crs": NotPublished(Evidence("https://api.existenz.ch/#hydro")),
}
