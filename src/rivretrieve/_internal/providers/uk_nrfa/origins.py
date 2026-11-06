"""NRFA catalogue origins and reviewed station metadata fields."""

from rivretrieve._internal.catalogue_origins import (
    Authored,
    AuthoredValue,
    Documented,
    DocumentedValue,
    Evidence,
    Field,
    NativeColumn,
)
from rivretrieve._internal.catalogues.station_metadata import MetadataField

API_HELP = "https://nrfaapps.ceh.ac.uk/nrfa/nrfa-api.html"

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("uk_nrfa")),
    "station_id": Field(NativeColumn("station_id")),
    "latitude": Field(NativeColumn("latitude")),
    "longitude": Field(NativeColumn("longitude")),
    "crs": Documented(DocumentedValue("EPSG:4326"), Evidence(API_HELP)),
}

STATION_METADATA_FIELDS = (
    MetadataField("station_name", "name"),
    MetadataField("water_body_name", "river"),
    MetadataField("drainage_area", "catchment-area", "km²", support_facts=("source.station.metadata_definitions",)),
    MetadataField(
        "elevation",
        "station-level",
        "m",
        datum_field="station_altitude_datum",
        support_facts=("source.station.metadata_definitions",),
        datum_support=("source.station.metadata_definitions", "source.station.uk_numbering"),
    ),
)

STATION_METADATA_NOTICE = (
    "Station metadata from the UK National River Flow Archive (UK Centre for Ecology & Hydrology). "
    "Station altitude generally describes the banks of the gauge, not stage zero. "
    "RivRetrieve preserves source values and names; the altitude datum association uses reviewed "
    "station numbering within the UK inventory."
)
