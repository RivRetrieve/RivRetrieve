"""South Africa station origins : CanonicalStationColumn → CatalogueOrigin."""

from rivretrieve._internal import catalogue_origins

CRS_EVIDENCE_URL = "https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA1_Limpopo-Olifants_River.pdf"
CRS_EVIDENCE_EXPLANATION = (
    "The cited River PDF's own two-line coordinate header reads Latitude / dd:mm:ss and "
    "Longitude / dd:mm:ss; this names a representation format but never a datum. A "
    "case-insensitive review of all eight River PDFs found zero datum, WGS, ellipsoid, "
    "geodetic, projection, or EPSG occurrences. HyCatalogue.aspx is only a link index with "
    "no prose or coordinate header and is not CRS evidence."
)
DMS_SIGN_CONVENTION = (
    "DWS publishes unsigned DMS magnitudes with no leading sign, hemisphere marker, or "
    "hemisphere note; the build applies a southern negative latitude sign and an eastern "
    "positive longitude sign that the source does not carry."
)

STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Field(catalogue_origins.NativeColumn("Station")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("Station")),
    "latitude": catalogue_origins.Field(catalogue_origins.NativeColumn("Latitude (dd:mm:ss)")),
    "longitude": catalogue_origins.Field(catalogue_origins.NativeColumn("Longitude (dd:mm:ss)")),
    "crs": catalogue_origins.NotPublished(catalogue_origins.Evidence(CRS_EVIDENCE_URL)),
}
