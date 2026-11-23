"""Estonia (`ee_est`) source declarations for offline station discovery.

Coordinate conversion: every retained station's `kesk_x`, `kesk_y` in
keskkonnaandmed.envir.ee `f_seirejaamad` (`seiretyyp == "HJ"`) is in Estonia's
official L-EST97 projection (`EPSG:3301`). Re-projecting all 60 inland river
stations to `EPSG:4326` and checking Estonia's bounding box confirmed this
numerically (`research/ee-est-source-access.md`, 2026-11-23).
"""

from __future__ import annotations

from collections.abc import Mapping

from rivretrieve._internal.acquisition_provenance import (
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
    complete_transformed_fact_universe,
)
from rivretrieve._internal.catalogue_origins import (
    Authored,
    AuthoredValue,
    ConversionName,
    Documented,
    DocumentedValue,
    Evidence,
    Field,
    FieldConversion,
    NativeColumn,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.catalogues.station_metadata import MetadataField


class EstonianLest97ToWgs84Conversion(FieldConversion):
    """Re-project native L-EST97 (EPSG:3301) station coordinates to EPSG:4326.

    Reads both `kesk_x` (Easting) and `kesk_y` (Northing) from the native row
    regardless of which one `native_column` names.
    """

    __slots__ = ()

    @property
    def name(self) -> ConversionName:
        return ConversionName("lest97_epsg3301_to_wgs84")

    def apply(self, canonical_column: str, native_column: NativeColumn, native_row: Mapping[str, object]) -> object:
        del native_column
        if canonical_column not in {"latitude", "longitude"}:
            raise ValueError("EstonianLest97ToWgs84Conversion applies only to latitude or longitude")
        x, y = native_row["kesk_x"], native_row["kesk_y"]
        if x is None or y is None:
            return None
        from pyproj import Transformer

        transformer = Transformer.from_crs("EPSG:3301", "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(x, y)
        return lon if canonical_column == "longitude" else lat


_CRS_EVIDENCE = Evidence("https://keskkonnaandmed.envir.ee/f_seirejaamad")

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("ee_est")),
    "station_id": Field(NativeColumn("kkr_kood")),
    "latitude": Field(NativeColumn("kesk_y"), EstonianLest97ToWgs84Conversion()),
    "longitude": Field(NativeColumn("kesk_x"), EstonianLest97ToWgs84Conversion()),
    "crs": Documented(DocumentedValue("EPSG:4326"), _CRS_EVIDENCE),
}

STATION_METADATA_NOTICE = (
    "Station metadata from the Estonian Environment Agency (Keskkonnaagentuur) across its "
    "keskkonnaandmed.envir.ee PostgREST registry (f_seirejaamad, seiretyyp=HJ: station name `nimi` "
    "and water body name `veekogu_nimi`) and estmodel.envir.ee station list (catchment `area` in km2). "
    "Elevation is withheld (`merepinnast` is null for all 60 stations in f_seirejaamad and absent in "
    "EstModel). Published under CC BY 4.0 with mandatory attribution under Keskkonnaseire seadus § 13(4)."
)

STATION_METADATA_FIELDS = (
    MetadataField(
        "station_name",
        "nimi",
        source_scope="f_seirejaamad_hj",
        source_facts=("source.station.registry",),
    ),
    MetadataField(
        "water_body_name",
        "veekogu_nimi",
        source_scope="f_seirejaamad_hj",
        source_facts=("source.station.registry",),
    ),
    MetadataField(
        "drainage_area",
        "area",
        "km2",
        source_scope="estmodel_stations",
        source_facts=("source.station.drainage_area",),
        support_facts=("source.station.drainage_area_unit",),
    ),
)

_CATALOGUE_SOURCE_FACTS = {
    "station": ("source.station.registry",),
    "product": ("source.station_product.associations",),
    "station_product": ("source.station_product.associations",),
}


def build_acquisition_provenance(
    native_identity: NativeTableIdentity,
    recordings: tuple[RecordingReference, ...],
    *,
    acquisitions: tuple[AcquisitionRecord, ...],
    source_bindings: tuple[FactBinding, ...],
    statements: tuple[SourceStatement, ...] = (),
) -> AcquisitionProvenance:
    """Bind Keskkonnaagentuur originals and derived native table to catalogue facts."""
    if any(binding.source_id != "ee_est" or binding.transformation is not None for binding in source_bindings):
        raise ValueError("Estonia source bindings must directly identify selected acquisitions")
    facts = tuple(fact for binding in source_bindings for fact in binding.facts)
    required = {fact for group in _CATALOGUE_SOURCE_FACTS.values() for fact in group}
    required.update(
        (
            "source.station.drainage_area",
            "source.station.drainage_area_unit",
            "source.provider.terms",
            "source.provider.attribution",
            "source.series.fields",
        )
    )
    if missing := required - set(facts):
        raise ValueError(f"Missing Estonia source facts: {sorted(missing)!r}")
    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="ee_est",
        native_table=native_identity,
        source_records=(
            SourceRecord(
                source_id="ee_est",
                issuer="Estonian Environment Agency (Keskkonnaagentuur)",
                acquisitions=acquisitions,
                evidence=tuple(
                    EvidenceReference(
                        evidence_id=item.recording_id,
                        description="Selected Keskkonnaagentuur catalogue source",
                        recording=item,
                    )
                    for item in recordings
                ),
                statements=statements,
            ),
        ),
        fact_bindings=source_bindings,
        fact_universe=facts,
    )
    for carrier, source_facts in _CATALOGUE_SOURCE_FACTS.items():
        provenance = complete_transformed_fact_universe(
            provenance,
            tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith(carrier + ".")),
            transformation=Transformation(
                name=f"Keskkonnaagentuur source facts to canonical {carrier}",
                external_inputs=tuple(ExternalFactReference(source_id="ee_est", fact=fact) for fact in source_facts),
            ),
            fact_group=f"canonical_ee_est_{carrier}",
        )
    provenance = complete_transformed_fact_universe(
        provenance,
        ("provider.license", "provider.citation"),
        transformation=Transformation(
            name="Selected Keskkonnaagentuur CC BY 4.0 terms and attribution",
            external_inputs=(
                ExternalFactReference(source_id="ee_est", fact="source.provider.terms"),
                ExternalFactReference(source_id="ee_est", fact="source.provider.attribution"),
            ),
        ),
        fact_group="canonical_ee_est_terms",
    )
    return complete_transformed_fact_universe(
        provenance,
        tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")),
        transformation=Transformation(
            name="RivRetrieve ee_est identity and catalogue-only capabilities",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_ee_est_provider",
    )


NATIVE_TABLE_ACQUISITION_IDS = ("estmodel-stations-500", "ka-f-seirejaamad-hj")

CATALOGUE_SUPPORTING_INPUTS: dict[str, tuple[str, ...]] = {}

CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/ee_est/official/selection.json", None),
    ("src/rivretrieve/_internal/providers/ee_est/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/ee_est/origins.py", "NATIVE_TABLE_ACQUISITION_IDS"),
    ("src/rivretrieve/_internal/providers/ee_est/origins.py", "CATALOGUE_SUPPORTING_INPUTS"),
    ("src/rivretrieve/_internal/providers/ee_est/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/ee_est/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/ee_est/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/providers/ee_est/series.py", "PRODUCT_SPECS"),
    ("src/rivretrieve/_internal/providers/ee_est/series.py", "catalogue_product_rows"),
    ("src/rivretrieve/_internal/providers/ee_est/series.py", "describe_associations"),
    ("src/rivretrieve/_internal/providers/ee_est/generate_catalogue.py", "read_catalogue_sources"),
    ("src/rivretrieve/_internal/providers/ee_est/station_metadata.py", "project_station_metadata"),
)
