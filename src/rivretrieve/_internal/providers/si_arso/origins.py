"""Slovenia ARSO source declarations for offline river station discovery.

Coordinate conversion: ARSO publishes national grid coordinates ``GKY`` (easting)
and ``GKX`` (northing) in Slovene National Grid ``D48 / Gauss-Kruger`` (``EPSG:3912``;
explicitly labelled ``GKY (D48)`` / ``GKX (D48)`` in ARSO's statutory ZDMHS
``Register-infrastrukture-ARSO.pdf`` and ``Spisek vodomernih postaj_okt2019.xlsx``).
Pre-computed ``LON``/``LAT`` columns in ``Spisek`` and ``Program_2021`` carry a
systematic ~370–440 m eastward datum-shift error and are never used; instead,
``D48GkToWgs84Conversion`` transforms ``(gky, gkx)`` via ``EPSG:3912 -> EPSG:4326``
(verified against ARSO's real-time ``hidro_podatki_zadnji.xml`` ``wgs84_*`` tags
to < 0.7 m). Seven legacy archive gauges without published coordinates in any
ARSO inventory keep ``latitude=None``, ``longitude=None``, and ``crs="unknown"``.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache

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
    Field,
    FieldConversion,
    NativeColumn,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE
from rivretrieve._internal.catalogues.station_metadata import MetadataField


@lru_cache(maxsize=1)
def _d48_transformer():
    from pyproj import Transformer

    return Transformer.from_crs("EPSG:3912", "EPSG:4326", always_xy=True)


def _coerce_gk_coord(value: object, *, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"si_arso {name} must be a numeric D48/GK coordinate or null")
    return float(value)


class D48GkToWgs84Conversion(FieldConversion):
    """Re-project native Slovene D48/GK (``EPSG:3912``) ``(gky, gkx)`` to ``EPSG:4326``."""

    __slots__ = ()

    @property
    def name(self) -> ConversionName:
        return ConversionName("d48gk_epsg3912_to_wgs84")

    def apply(self, canonical_column: str, native_column: NativeColumn, native_row: Mapping[str, object]) -> object:
        del native_column
        if canonical_column not in {"latitude", "longitude"}:
            raise ValueError("D48GkToWgs84Conversion applies only to latitude or longitude")
        gky = _coerce_gk_coord(native_row["gky"], name="gky")
        gkx = _coerce_gk_coord(native_row["gkx"], name="gkx")
        if (gky is None) != (gkx is None):
            raise ValueError("si_arso native row must supply both gky and gkx or neither")
        if gky is None or gkx is None:
            return None
        lon, lat = _d48_transformer().transform(gky, gkx)
        return float(lon) if canonical_column == "longitude" else float(lat)


class D48GkCrsConversion(FieldConversion):
    """Emit ``EPSG:4326`` where ``D48/GK`` coordinates are present and ``unknown`` where absent."""

    __slots__ = ()

    @property
    def name(self) -> ConversionName:
        return ConversionName("d48gk_to_wgs84_crs")

    def apply(self, canonical_column: str, native_column: NativeColumn, native_row: Mapping[str, object]) -> object:
        del native_column
        if canonical_column != "crs":
            raise ValueError("D48GkCrsConversion applies only to crs")
        gky = _coerce_gk_coord(native_row["gky"], name="gky")
        gkx = _coerce_gk_coord(native_row["gkx"], name="gkx")
        if (gky is None) != (gkx is None):
            raise ValueError("si_arso native row must supply both gky and gkx or neither")
        return "unknown" if gky is None else "EPSG:4326"


STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("si_arso")),
    "station_id": Field(NativeColumn("sifra")),
    "latitude": Field(NativeColumn("gkx"), D48GkToWgs84Conversion()),
    "longitude": Field(NativeColumn("gky"), D48GkToWgs84Conversion()),
    "crs": Field(NativeColumn("gky"), D48GkCrsConversion()),
}

STATION_METADATA_NOTICE = (
    "Station metadata from Agencija Republike Slovenije za okolje (ARSO), published through the ARSO "
    "hydrological archive (https://vode.arso.gov.si/hidarhiv/) and listed on Open Data Slovenia "
    "(https://podatki.gov.si/) under Creative Commons Attribution 4.0 International (CC BY 4.0) with "
    "required attribution to Agencija Republike Slovenije za okolje (ARSO). RivRetrieve selected the "
    "declared station-name, water-body-name, and drainage-area scalars (preserving documented ARSO "
    "indeterminable-catchment codes 88888.88 and 99999.99 verbatim as native values); source strings "
    "and absence states remain unchanged."
)

SPISEK_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField(
        "station_name",
        "VODOMERNA POSTAJA",
        source_scope="spisek_vodomernih_postaj",
        source_facts=("source.station.spisek_registry",),
    ),
    MetadataField(
        "water_body_name",
        "VODOTOK",
        source_scope="spisek_vodomernih_postaj",
        source_facts=("source.station.spisek_registry",),
    ),
    MetadataField(
        "drainage_area",
        "ZALEDJE - F (km2)",
        "km2",
        source_scope="spisek_vodomernih_postaj",
        source_facts=("source.station.spisek_registry",),
        support_facts=(
            "source.station.spisek_legenda_sentinels",
            "source.station.program_2021_sentinels",
        ),
    ),
)

Q_STATS_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField(
        "station_name",
        "Postaja",
        source_scope="q_obdobne_stat",
        source_facts=("source.station.q_stats_rescue",),
    ),
    MetadataField(
        "water_body_name",
        "Vodotok",
        source_scope="q_obdobne_stat",
        source_facts=("source.station.q_stats_rescue",),
    ),
    MetadataField(
        "drainage_area",
        "F (km2)",
        "km2",
        source_scope="q_obdobne_stat",
        source_facts=("source.station.q_stats_rescue",),
        support_facts=(
            "source.station.spisek_legenda_sentinels",
            "source.station.program_2021_sentinels",
        ),
    ),
)

DROPDOWN_METADATA_FIELDS: tuple[MetadataField, ...] = (
    MetadataField(
        "station_name",
        "dropdown_postaja",
        source_scope="pov_arhiv_dropdown",
        source_facts=("source.station.hidarhiv_dropdown",),
    ),
    MetadataField(
        "water_body_name",
        "dropdown_vodotok",
        source_scope="pov_arhiv_dropdown",
        source_facts=("source.station.hidarhiv_dropdown",),
    ),
)

STATION_METADATA_FIELDS: tuple[MetadataField, ...] = (
    *SPISEK_METADATA_FIELDS,
    *Q_STATS_METADATA_FIELDS,
    *DROPDOWN_METADATA_FIELDS,
)

NATIVE_TABLE_ACQUISITION_IDS: tuple[str, ...] = (
    "si-arso-hidarhiv-dropdown",
    "si-arso-spisek-okt2019",
    "si-arso-q-stats-workbooks",
    "si-arso-register-infrastrukture",
)

_CATALOGUE_SOURCE_FACTS = {
    "station": (
        "source.station.hidarhiv_dropdown",
        "source.station.spisek_registry",
        "source.station.q_stats_rescue",
        "source.station.register_infrastrukture",
        "source.station.spisek_legenda_sentinels",
        "source.station.program_2021_sentinels",
        "source.station.d48gk_crs",
    ),
    "product": (
        "source.station_product.archive_daily_witnesses",
        "source.station_product.archive_monthly_extremes_witnesses",
        "source.station_product.amp_telemetry_witnesses",
        "source.product.archive_methodology",
        "source.product.monthly_extremes_units_and_definitions",
        "source.product.amp_operational_semantics",
        "source.station.gauge_zero_definition",
    ),
    "station_product": (
        "source.station.hidarhiv_dropdown",
        "source.station_product.archive_daily_witnesses",
        "source.station_product.archive_monthly_extremes_witnesses",
        "source.station_product.amp_telemetry_witnesses",
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
    """Bind selected official ARSO source evidence and derived native table to catalogue facts."""
    if any(binding.source_id != "si_arso" or binding.transformation is not None for binding in source_bindings):
        raise ValueError("ARSO source bindings must directly identify selected acquisitions")
    facts = tuple(fact for binding in source_bindings for fact in binding.facts)
    required = {fact for group in _CATALOGUE_SOURCE_FACTS.values() for fact in group}
    required.update(("source.provider.license", "source.provider.citation"))
    if missing := required - set(facts):
        raise ValueError(f"Missing ARSO source facts: {sorted(missing)!r}")
    if not any(statement.kind == "license" and statement.fact is not None for statement in statements):
        raise ValueError("si_arso catalogue requires selected license evidence")
    if not any(statement.kind == "citation" and statement.fact is not None for statement in statements):
        raise ValueError("si_arso catalogue requires selected citation evidence")
    provenance = AcquisitionProvenance(
        schema_version=2,
        provider_id="si_arso",
        native_table=native_identity,
        source_records=(
            SourceRecord(
                source_id="si_arso",
                issuer="Agencija Republike Slovenije za okolje (ARSO)",
                operator="Urad za meteorologijo, hidrologijo in oceanografijo (ZDMHS)",
                acquisitions=acquisitions,
                evidence=tuple(
                    EvidenceReference(
                        evidence_id=item.recording_id,
                        description="Selected official Slovenia ARSO catalogue source",
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
                name=f"ARSO source facts to canonical {carrier}; unestablished temporal/datum meanings remain unknown",
                external_inputs=tuple(ExternalFactReference(source_id="si_arso", fact=fact) for fact in source_facts),
            ),
            fact_group=f"canonical_si_arso_{carrier}",
        )
    term_facts = tuple(statement.fact for statement in statements if statement.fact is not None)
    provenance = complete_transformed_fact_universe(
        provenance,
        ("provider.license", "provider.citation"),
        transformation=Transformation(
            name="Selected OPSI CC BY 4.0 license and ARSO attribution terms",
            external_inputs=tuple(ExternalFactReference(source_id="si_arso", fact=fact) for fact in term_facts),
        ),
        fact_group="canonical_si_arso_terms",
    )
    return complete_transformed_fact_universe(
        provenance,
        tuple(fact for fact in CATALOGUE_FACT_UNIVERSE if fact.startswith("provider.")),
        transformation=Transformation(
            name="RivRetrieve si_arso identity and live observation capabilities",
            kind="authored_constant",
            external_inputs=(),
        ),
        fact_group="canonical_si_arso_provider",
    )


CATALOGUE_SUPPORTING_INPUTS: dict[str, tuple[str, ...]] = {}
CATALOGUE_BUILD_DECLARATIONS = (
    ("maintenance/catalogue/si_arso/official/selection.json", None),
    ("src/rivretrieve/_internal/providers/si_arso/origins.py", "build_acquisition_provenance"),
    ("src/rivretrieve/_internal/providers/si_arso/origins.py", "STATION_METADATA_FIELDS"),
    ("src/rivretrieve/_internal/providers/si_arso/origins.py", "STATION_METADATA_NOTICE"),
    ("src/rivretrieve/_internal/providers/si_arso/generate_catalogue.py", "build_catalogue"),
    ("src/rivretrieve/_internal/providers/si_arso/generate_catalogue.py", "read_catalogue_sources"),
    ("src/rivretrieve/_internal/providers/si_arso/series.py", "source_series"),
    ("src/rivretrieve/_internal/providers/si_arso/station_metadata.py", "project_station_metadata"),
)
