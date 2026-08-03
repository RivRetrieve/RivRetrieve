"""ThaiWater station origins : CanonicalStationColumn → CatalogueOrigin."""

from rivretrieve._internal import catalogue_origins

CRS_EVIDENCE_URL = "https://standard.thaiwater.net/docs/การจัดทำมาตรฐานน้ำ-ระยะ/ข้อมูลอ้างอิง-ข้อมูลอ้า/การระบุพิกัดตำแหน่ง/"

STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Field(catalogue_origins.NativeColumn("station.id")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("station.id")),
    "latitude": catalogue_origins.Field(catalogue_origins.NativeColumn("station.tele_station_lat")),
    "longitude": catalogue_origins.Field(catalogue_origins.NativeColumn("station.tele_station_long")),
    "crs": catalogue_origins.NotPublished(catalogue_origins.Evidence(CRS_EVIDENCE_URL)),
}
