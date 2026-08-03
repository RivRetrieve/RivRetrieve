"""France station origins : Endpoint → CanonicalStationColumn → CatalogueOrigin."""

from types import MappingProxyType

from rivretrieve._internal import catalogue_origins

CRS_EVIDENCE_URL = (
    "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?code_station=1011000101&format=geojson"
)
TEMPERATURE_CRS_EVIDENCE_URL = "https://hubeau.eaufrance.fr/api/v1/temperature/station?size=2000&format=json"

HYDROMETRY_STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Field(catalogue_origins.NativeColumn("code_station")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("code_station")),
    "latitude": catalogue_origins.Field(catalogue_origins.NativeColumn("latitude_station")),
    "longitude": catalogue_origins.Field(catalogue_origins.NativeColumn("longitude_station")),
    "crs": catalogue_origins.Documented(
        catalogue_origins.DocumentedValue("EPSG:4326"),
        catalogue_origins.Evidence(CRS_EVIDENCE_URL),
    ),
}

TEMPERATURE_STATION_CATALOGUE_ORIGINS: dict[str, catalogue_origins.CatalogueOrigin] = {
    "provider_id": catalogue_origins.Field(catalogue_origins.NativeColumn("code_station")),
    "station_id": catalogue_origins.Field(catalogue_origins.NativeColumn("code_station")),
    "latitude": catalogue_origins.Field(catalogue_origins.NativeColumn("latitude")),
    "longitude": catalogue_origins.Field(catalogue_origins.NativeColumn("longitude")),
    "crs": catalogue_origins.Documented(
        catalogue_origins.DocumentedValue("EPSG:4326"),
        catalogue_origins.Evidence(TEMPERATURE_CRS_EVIDENCE_URL),
    ),
}

FRANCE_ORIGIN_DECLARATIONS = MappingProxyType(
    {
        "hydrometrie/referentiel/stations": HYDROMETRY_STATION_CATALOGUE_ORIGINS,
        "temperature/station": TEMPERATURE_STATION_CATALOGUE_ORIGINS,
    }
)

CODE_PROJECTION_31_AXIS_TRANSPOSITION = MappingProxyType(
    {"latitude": "longitude_station", "longitude": "latitude_station"}
)
CODE_PROJECTION_31_METROPOLITAN_BOUNDS = MappingProxyType(
    {"latitude": (42.4174, 49.989435), "longitude": (-0.616424, 5.593353)}
)
