"""Poland station origins : CanonicalStationColumn → CatalogueOrigin."""

from rivretrieve._internal.catalogue_origins import Evidence, Field, NativeColumn, NotPublished

CRS_EVIDENCE_URL = "https://danepubliczne.imgw.pl/pl/apiinfo"

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Field(NativeColumn("gauge_id")),
    "station_id": Field(NativeColumn("gauge_id")),
    "latitude": Field(NativeColumn("latitude")),
    "longitude": Field(NativeColumn("longitude")),
    "crs": NotPublished(Evidence(CRS_EVIDENCE_URL)),
}
