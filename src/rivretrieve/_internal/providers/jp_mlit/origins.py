"""Japan canonical station columns : OriginDeclarations."""

from rivretrieve._internal.catalogue_origins import Evidence, Field, NativeColumn, NotPublished

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Field(NativeColumn("観測所記号")),
    "station_id": Field(NativeColumn("観測所記号")),
    "latitude": Field(NativeColumn("世界測地系")),
    "longitude": Field(NativeColumn("世界測地系")),
    "crs": NotPublished(Evidence("http://www1.river.go.jp/cgi-bin/SiteInfoDetail.exe?ID=301011281104010")),
}
