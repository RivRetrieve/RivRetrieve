"""SENAMHI source declarations for offline station discovery."""

from rivretrieve._internal.catalogue_origins import (
    Authored,
    AuthoredValue,
    Field,
    FloatConversion,
    NativeColumn,
    Withheld,
)

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("pe_senamhi")),
    "station_id": Field(NativeColumn("stationId")),
    "latitude": Field(NativeColumn("latitude"), FloatConversion()),
    "longitude": Field(NativeColumn("longitude"), FloatConversion()),
    "crs": Withheld(),
}
STATION_METADATA_NOTICE = (
    "Station metadata is from Servicio Nacional de Meteorología e Hidrología del Perú (SENAMHI). "
    "Source names and descriptive values remain unchanged. This metadata projection is produced by RivRetrieve."
)
