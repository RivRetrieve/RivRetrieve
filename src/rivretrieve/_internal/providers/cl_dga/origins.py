"""Chile DGA source declarations for offline river station discovery."""

from __future__ import annotations

import re
from collections.abc import Mapping

from rivretrieve._internal.acquisition_provenance import (
    AbsenceMarkerValue,
    AcquisitionProvenance,
    AcquisitionRecord,
    EvidenceReference,
    ExternalFactReference,
    FactBinding,
    NativeTableIdentity,
    RecordingReference,
    SourceRecord,
    SourceStatement,
    Transformation,
    WithheldFact,
    complete_transformed_fact_universe,
)
from rivretrieve._internal.catalogue_origins import (
    Authored,
    AuthoredValue,
    ConversionName,
    Field,
    FieldConversion,
    NativeColumn,
    Withheld,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.catalogues.station_metadata import MetadataField

_UNSIGNED_DMS_7 = re.compile(r"\d{7}")

MOP_TERMS_TEXT = (
    "Siempre que no sea para fines comerciales, el MOP autoriza la reproducción de los contenidos de este sitio, "
    "citando en forma clara su procedencia. Si se desea hacer dicha referencia en materiales promocionales u otros "
    "medios, se podrá hacer sólo con el permiso por escrito de parte del Ministerio de Obras Públicas, lo cual debe "
    "solicitarse en Contáctenos o a través de la Oficina de Información, Reclamos y Sugerencias (OIRS)."
)

DGA_CITATION = (
    "Dirección General de Aguas (DGA), Ministerio de Obras Públicas (MOP), Chile — "
    "Estadística Hidrométrica (https://mapas2.mop.gob.cl/); "
    "condiciones de uso: https://www.mop.gob.cl/condiciones-de-uso/"
)


def unsigned_dms_coordinate(value: object, canonical_column: str) -> float:
    """Convert DGA's 7-digit unsigned DDDMMSS string to signed decimal degrees.

    DGA publishes magnitudes without hemisphere sign across Chilean stations
    (southern latitude and western longitude). Seven verified stations carry
    ``seconds == 60`` across both historical ZIPs and ``Informe Nacional``,
    which evaluates to the exact 1-minute carry matching ``mapas2`` JSON.
    """
    if canonical_column not in {"latitude", "longitude"}:
        raise ValueError("Chile DMS conversion is only defined for latitude and longitude")
    if not isinstance(value, str) or _UNSIGNED_DMS_7.fullmatch(value) is None:
        raise ValueError("Chile DMS coordinate must be a 7-digit DDDMMSS string")
    degrees = int(value[:3])
    minutes = int(value[3:5])
    seconds = int(value[5:7])
    if minutes >= 60 or seconds > 60:
        raise ValueError(f"Chile DMS coordinate has out-of-range minutes or seconds: {value!r}")
    magnitude = degrees + minutes / 60.0 + seconds / 3600.0
    if canonical_column == "latitude":
        if not 15.0 <= magnitude <= 57.0:
            raise ValueError(f"Chile latitude outside Chilean bounds: {value!r}")
        return -magnitude
    if not 65.0 <= magnitude <= 110.0:
        raise ValueError(f"Chile longitude outside Chilean bounds: {value!r}")
    return -magnitude


class ChileUnsignedDmsConversion(FieldConversion):
    """Apply Chile's southern and western signs to DGA's unsigned 7-digit DDDMMSS fields."""

    __slots__ = ()

    @property
    def name(self) -> ConversionName:
        return ConversionName("cl_dga.unsigned_dms")

    def apply(
        self,
        canonical_column: str,
        native_column: NativeColumn,
        native_row: Mapping[str, object],
    ) -> object:
        expected_native_column = {"latitude": "LAT", "longitude": "LONG"}.get(canonical_column)
        if expected_native_column is None:
            raise ValueError("Chile DMS conversion is only defined for coordinates")
        if native_column != expected_native_column:
            raise ValueError(f"Chile {canonical_column} conversion requires native field {expected_native_column!r}")
        return unsigned_dms_coordinate(native_row[str(native_column)], canonical_column)


STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("cl_dga")),
    "station_id": Field(NativeColumn("CODIGO ESTACION")),
    "latitude": Field(NativeColumn("LAT"), ChileUnsignedDmsConversion()),
    "longitude": Field(NativeColumn("LONG"), ChileUnsignedDmsConversion()),
    "crs": Withheld(),
}

STATION_METADATA_NOTICE = (
    "Station metadata from Chile's Dirección General de Aguas (DGA), Ministerio de Obras Públicas (MOP), "
    "published via Estadística Hidrométrica (https://mapas2.mop.gob.cl/). Packaged catalogues and station "
    "metadata are excluded from RivRetrieve's MIT software licence; source material remains governed by MOP "
    "terms (https://www.mop.gob.cl/condiciones-de-uso/), which authorize non-commercial reproduction with clear "
    "citation and may require written permission for commercial reuse, while a dataset-specific open licence "
    "remains unestablished. Source station names and elevations are preserved without hydrological interpretation; "
    "ALTITUD=0 placeholders are withheld as source_null and vertical datum remains unknown. "
    "Processing and projection: RivRetrieve."
)

STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField(
        "station_name",
        "NOMBRE ESTACION",
        source_scope="mapas2_historico",
        source_facts=("source.station.zip_metadata",),
    ),
    MetadataField(
        "elevation",
        "ALTITUD",
        "m",
        source_scope="mapas2_historico",
        source_facts=("source.station.zip_metadata",),
        support_facts=("source.station.altitud_unit",),
    ),
)

NATIVE_TABLE_ACQUISITION_IDS: tuple[str, ...] = (
    "cl-dga-mapas2-caudal-diario-nacional",
    "cl-dga-mapas2-caudal-medio-mensual-nacional",
    "cl-dga-mapas2-home",
    "cl-dga-informe-nacional-2026-09",
)

_CATALOGUE_SOURCE_FACTS = {
    "station": (
        "source.station.zip_metadata",
        "source.station.supporting_reconciliation",
    ),
    "product": (
        "source.product.daily_discharge_zip",
        "source.product.monthly_discharge_zip",
    ),
    "station_product": (
        "source.product.daily_discharge_zip",
        "source.product.monthly_discharge_zip",
        "source.station.zip_metadata",
    ),
}


def build_acquisition_provenance(
    native_identity: NativeTableIdentity,
    recordings: tuple[RecordingReference, ...],
    *,
    acquisitions: tuple[AcquisitionRecord, ...],
    source_bindings: tuple[FactBinding, ...],
    statements: tuple[SourceStatement, ...] = (),
) -> AcquisitionProvenance:
    """Bind selected DGA/MOP source evidence and derived native table to catalogue facts.

    Acquisitions and exact statements come from the verified selection. Unestablished
    horizontal CRS, vertical datum, daily statistic, temporal support, time zone,
    and canonical record bounds remain unknown; ``ProviderInfoCatalog.license``
    remains ``None`` under MOP portal terms.
    """
    if any(binding.source_id != "cl_dga" or binding.transformation is not None for binding in source_bindings):
        raise ValueError("DGA source bindings must directly identify selected acquisitions")
    facts = tuple(fact for binding in source_bindings for fact in binding.facts)
    required = {fact for group in _CATALOGUE_SOURCE_FACTS.values() for fact in group}
    required.update(("source.station.altitud_unit", "source.provider.terms", "source.provider.attribution"))
    if missing := required - set(facts):
        raise ValueError(f"Missing DGA source facts: {sorted(missing)!r}")
    if any(statement.kind == "license" for statement in statements):
        raise ValueError("cl_dga has no established open-data license statement")
    if not any(statement.kind == "terms" and statement.fact is not None for statement in statements):
        raise ValueError("cl_dga catalogue requires verified MOP terms statement evidence")
    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="cl_dga",
        native_table=native_identity,
        source_records=(
            SourceRecord(
                source_id="cl_dga",
                issuer="Dirección General de Aguas (DGA), Ministerio de Obras Públicas (MOP)",
                operator="Visor de Mapas y Estadística Hidrométrica (mapas2.mop.gob.cl)",
                acquisitions=acquisitions,
                evidence=tuple(
                    EvidenceReference(
                        evidence_id=item.recording_id,
                        description="Selected official DGA/MOP catalogue source",
                        recording=item,
                    )
                    for item in recordings
                ),
                statements=statements,
            ),
        ),
        fact_bindings=source_bindings,
        fact_universe=(*facts, "source.station.crs"),
        withheld_facts=(
            WithheldFact(
                fact_group="unestablished_station_crs",
                source_id="cl_dga",
                facts=("source.station.crs",),
                reason="no_acquisition_record_established",
            ),
        ),
    )
    provenance = complete_transformed_fact_universe(
        provenance,
        ("station.crs",),
        transformation=Transformation(
            name="Unestablished source CRS remains unknown",
            kind="absence_marker",
            marker_value=AbsenceMarkerValue.UNKNOWN,
            external_inputs=(ExternalFactReference(source_id="cl_dga", fact="source.station.crs"),),
        ),
        fact_group="canonical_cl_dga_crs",
    )
    for carrier, source_facts in _CATALOGUE_SOURCE_FACTS.items():
        provenance = complete_transformed_fact_universe(
            provenance,
            tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith(carrier + ".")),
            transformation=Transformation(
                name=f"DGA source facts to canonical {carrier}; unestablished temporal meanings remain unknown",
                external_inputs=tuple(ExternalFactReference(source_id="cl_dga", fact=fact) for fact in source_facts),
            ),
            fact_group=f"canonical_cl_dga_{carrier}",
        )
    provenance = complete_transformed_fact_universe(
        provenance,
        ("provider.license", "provider.citation"),
        transformation=Transformation(
            name="Selected MOP portal terms and DGA attribution; dataset license remains null",
            external_inputs=(
                ExternalFactReference(source_id="cl_dga", fact="source.provider.terms"),
                ExternalFactReference(source_id="cl_dga", fact="source.provider.attribution"),
            ),
        ),
        fact_group="canonical_cl_dga_terms",
    )
    return complete_transformed_fact_universe(
        provenance,
        tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")),
        transformation=Transformation(
            name="RivRetrieve Chile DGA identity and bulk observation capabilities",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_cl_dga_provider",
    )


CATALOGUE_SUPPORTING_INPUTS: dict[str, tuple[str, ...]] = {}
CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/cl_dga/official/selection.json", None),
    ("maintenance/catalogue/station_metadata/review.json", None),
    ("src/rivretrieve/_internal/providers/cl_dga/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/cl_dga/origins.py", "NATIVE_TABLE_ACQUISITION_IDS"),
    ("src/rivretrieve/_internal/providers/cl_dga/origins.py", "CATALOGUE_SUPPORTING_INPUTS"),
    ("src/rivretrieve/_internal/providers/cl_dga/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/cl_dga/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/cl_dga/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/providers/cl_dga/generate_catalogue.py", "read_catalogue_sources"),
    ("src/rivretrieve/_internal/providers/cl_dga/station_metadata.py", "project_station_metadata"),
    ("src/rivretrieve/_internal/providers/cl_dga/catalogue_series.py", "describe_catalogue"),
)
