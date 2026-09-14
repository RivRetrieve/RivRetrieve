"""Bosnia catalogue authority : WorkbookAccessLedger → AcquisitionProvenance (pure)."""

from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, NaiveDatetime, StrictInt, StrictStr, model_validator
from pydantic import Field as ModelField

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    AcquisitionRecord,
    EvidenceReference,
    ExternalFactReference,
    FactBinding,
    MaterialIdentity,
    NativeTableIdentity,
    RecordingReference,
    SemanticDigest,
    SourceRecord,
    SourceStatement,
    Transformation,
    complete_transformed_fact_universe,
)
from rivretrieve._internal.catalogue_origins import (
    Authored,
    AuthoredValue,
    Evidence,
    Field,
    FloatConversion,
    NativeColumn,
    NotPublished,
)
from rivretrieve._internal.catalogues.artifact import CATALOGUE_FACT_UNIVERSE

STATION_CATALOGUE_ORIGINS = {
    "provider_id": Authored(AuthoredValue("ba_fhmzbih")),
    "station_id": Field(NativeColumn("metadata_station_no")),
    "latitude": Field(NativeColumn("metadata_station_latitude"), FloatConversion()),
    "longitude": Field(NativeColumn("metadata_station_longitude"), FloatConversion()),
    "crs": NotPublished(Evidence("https://vodostaji.voda.ba/data/internet/stations/stations.json")),
}
NATIVE_TABLE_SHA256 = "abcbc2d2234ea1751d638307f89fba4cba4feca96c9cd1d77c728b87a0fea77a"
NATIVE_TABLE_BYTE_SIZE = 13430
NATIVE_TABLE_REVISION = "f805d2556a72617644f9bf90de2e3438e743b888"
NATIVE_TABLE_REPOSITORY_PATH = "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet"
DATA_STANDING_TEXT = "Svi podaci koji se prikazuju i koji se dobiju kao rezultat pretrage su informativnog karaktera i ne mogu služiti kao zvanični podaci."


class WorkbookAccess(BaseModel):
    """One reviewed station/product workbook acquisition and availability conclusion."""

    model_config = ConfigDict(frozen=True)
    station_no: StrictStr
    site_no: StrictStr
    product_id: Literal["discharge_reported", "stage_reported", "water_temperature_reported"]
    source_code: StrictStr
    workbook: StrictStr
    method: Literal["GET"]
    url: StrictStr
    parameters: None
    retrieved_at: AwareDatetime
    http_status: Literal[200]
    media_type: Literal["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]
    response_sha256: Annotated[str, ModelField(pattern=r"^[0-9a-f]{64}$")]
    byte_size: Annotated[StrictInt, ModelField(gt=0)]
    parameter: StrictStr
    source_unit: StrictStr
    status: Literal["measurements_present", "no_data_rows"]
    availability: Literal["available", "unknown"]
    data_rows: Annotated[StrictInt, ModelField(ge=0)]
    numerical_rows: Annotated[StrictInt, ModelField(ge=0)]
    blank_rows: Annotated[StrictInt, ModelField(ge=0)]
    observed_window_start: NaiveDatetime | None
    observed_window_end: NaiveDatetime | None

    @model_validator(mode="after")
    def consistent_workbook(self) -> Self:
        if self.retrieved_at.utcoffset() != timedelta(0):
            raise ValueError("workbook retrieval instant must be UTC")
        physics = {
            "discharge_reported": ("Q", "Q_1Y.xlsx", "Proticaj", "m³/s"),
            "stage_reported": ("H", "H_1Y.xlsx", "Vodostaj", "cm"),
            "water_temperature_reported": ("WT", "Tvode_1Y.xlsx", "Temperatura vode", "°C"),
        }
        if (self.source_code, self.workbook, self.parameter, self.source_unit) != physics[self.product_id]:
            raise ValueError("workbook product identity or physics mismatch")
        expected_url = (
            "https://vodostaji.voda.ba/data/internet/stations/"
            f"{self.site_no}/{self.station_no}/{self.source_code}/{self.workbook}"
        )
        if not self.station_no or not self.site_no or self.url != expected_url:
            raise ValueError("workbook station/site request mismatch")
        if self.data_rows != self.numerical_rows + self.blank_rows:
            raise ValueError("workbook row counts disagree")
        if self.status == "measurements_present":
            if self.availability != "available" or self.numerical_rows == 0:
                raise ValueError("positive workbook status requires numerical rows and available conclusion")
            if self.observed_window_start is None or self.observed_window_end is None:
                raise ValueError("positive workbook requires observed window")
            if self.observed_window_start > self.observed_window_end:
                raise ValueError("observed window is reversed")
        elif (
            self.availability != "unknown"
            or self.data_rows != 0
            or self.observed_window_start is not None
            or self.observed_window_end is not None
        ):
            raise ValueError("empty workbook requires zero rows, unknown availability and no observed window")
        return self

    @property
    def acquisition_id(self) -> str:
        return f"workbook:{self.station_no}:{self.product_id}"

    @property
    def source_fact(self) -> str:
        return f"source.workbook:{self.station_no}:{self.product_id}.availability"

    @property
    def availability_reason(self) -> str:
        if self.status == "no_data_rows":
            return f"Valid station/parameter/unit-matched workbook contained zero data rows at {self.retrieved_at.isoformat()}; availability remains unknown"
        return f"Workbook contained {self.numerical_rows} numerical measurement rows at {self.retrieved_at.isoformat()}"


class WorkbookAccessLedger(BaseModel):
    """Reviewed workbook conclusions tied to the approved native inventory."""

    model_config = ConfigDict(frozen=True)
    schema_version: Literal[1]
    publisher: Literal["Agencija za vodno područje rijeke Save"]
    baseline_native_sha256: Literal["abcbc2d2234ea1751d638307f89fba4cba4feca96c9cd1d77c728b87a0fea77a"]
    pairs: tuple[WorkbookAccess, ...]

    @model_validator(mode="after")
    def unique_pairs(self) -> Self:
        keys = {(pair.station_no, pair.product_id) for pair in self.pairs}
        if not keys or len(keys) != len(self.pairs):
            raise ValueError("workbook ledger has empty or duplicate pairs")
        return self


def _build_provider_acquisition_provenance(workbook_access: WorkbookAccessLedger) -> AcquisitionProvenance:
    absence = RecordingReference(
        recording_id="ba_fhmzbih_terms_absence",
        repository_path="tests/test_data/ba_fhmzbih_terms_absence.html",
        source_url="https://vodostaji.voda.ba/data/html/impressum.html",
        retrieved_at=datetime.fromisoformat("2026-08-20T09:31:25Z"),
        media_type="text/html; charset=UTF-8",
        sha256="dd5daa83187fd11e1cd1321e4ffc78251f7f31f9e2cf528b742976f409d61709",
    )
    provider_facts = ("source.provider.service_operator", "source.provider.station_service_identity")
    product_facts = ("source.product.native_identifiers", "source.product.native_physics")
    station_ids = sorted({pair.station_no for pair in workbook_access.pairs})
    bound_stations = tuple(f"source.station:{station}.identity_location" for station in station_ids)
    bound_observations = tuple(f"source.observation:{station}.values_quality" for station in station_ids)
    workbook_facts = tuple(pair.source_fact for pair in workbook_access.pairs)
    availability_facts = tuple(
        f"station_product:{pair.station_no}:{pair.product_id}.availability" for pair in workbook_access.pairs
    )
    universe = (
        provider_facts + product_facts + bound_stations + bound_observations + workbook_facts + availability_facts
    )
    return AcquisitionProvenance(
        schema_version=2,
        provider_id="ba_fhmzbih",
        native_table=NativeTableIdentity(
            repository_path=NATIVE_TABLE_REPOSITORY_PATH,
            revision=NATIVE_TABLE_REVISION,
            sha256=NATIVE_TABLE_SHA256,
            byte_size=NATIVE_TABLE_BYTE_SIZE,
            semantic_digest=SemanticDigest(
                name="ba_fhmzbih.stable_metadata_sha256",
                sha256="14ab47126fe40f16f23ddc66620fc8ae30910cd812c69806f867a851e659b23d",
            ),
        ),
        source_records=(
            SourceRecord(
                source_id="ba_avp_sava",
                issuer="Agencija za vodno područje rijeke Save",
                operator="vodostaji.voda.ba",
                acquisitions=(
                    AcquisitionRecord(
                        acquisition_id="catalogue_capture_2026_08_02",
                        method="http_request",
                        instant_type="retrieval",
                        description="60-row stable station metadata response with volatile L1 snapshot fields excluded",
                        requested_from=("https://vodostaji.voda.ba/data/internet/layers/20/index.json",),
                        retrieved_at_start=datetime.fromisoformat("2026-08-02T12:42:03Z"),
                    ),
                    AcquisitionRecord(
                        acquisition_id="terms_surface_capture_2026_08_20",
                        method="http_request",
                        instant_type="retrieval",
                        description="Exact-host Impressum response examined for published terms and citation words",
                        requested_from=(absence.source_url,),
                        retrieved_at_start=absence.retrieved_at,
                        recording_ids=(absence.recording_id,),
                    ),
                    AcquisitionRecord(
                        acquisition_id="observation_request",
                        method="runtime_http_request",
                        instant_type="runtime",
                        description="Exact station workbook request and response",
                        requested_from=(
                            "https://vodostaji.voda.ba/data/internet/stations/{group}/{station_id}/{code}/{file}",
                        ),
                    ),
                )
                + tuple(
                    AcquisitionRecord(
                        acquisition_id=pair.acquisition_id,
                        method="http_request",
                        instant_type="retrieval",
                        description=(
                            f"GET station/parameter/unit-matched rolling workbook; {pair.availability_reason}. "
                            f"Observed capture span: {pair.observed_window_start} to {pair.observed_window_end}. "
                            "Private response body retained for review; original measurement producer not established."
                        ),
                        requested_from=(pair.url,),
                        retrieved_at_start=pair.retrieved_at,
                        material=MaterialIdentity(
                            filename=pair.workbook, byte_count=pair.byte_size, sha256=pair.response_sha256
                        ),
                    )
                    for pair in workbook_access.pairs
                ),
                evidence=(
                    EvidenceReference(
                        evidence_id="terms_absence_surface",
                        description="Exact-host Impressum examined for terms and citation",
                        recording=absence,
                    ),
                ),
                statements=(
                    SourceStatement(
                        kind="terms",
                        exact_text=DATA_STANDING_TEXT,
                        recording_id=absence.recording_id,
                        fact="source.provider.terms_absence_statement",
                    ),
                ),
            ),
        ),
        fact_bindings=(
            FactBinding(
                fact_group="terms_surface_statement",
                facts=("source.provider.terms_absence_statement",),
                source_id="ba_avp_sava",
                acquisition_id="terms_surface_capture_2026_08_20",
            ),
            FactBinding(
                fact_group="canonical_provider",
                facts=provider_facts,
                source_id="ba_avp_sava",
                acquisition_id="catalogue_capture_2026_08_02",
            ),
            FactBinding(
                fact_group="canonical_products",
                facts=product_facts,
                source_id="ba_avp_sava",
                acquisition_id="catalogue_capture_2026_08_02",
            ),
            FactBinding(
                fact_group="station_identities",
                facts=bound_stations,
                source_id="ba_avp_sava",
                acquisition_id="catalogue_capture_2026_08_02",
            ),
            FactBinding(
                fact_group="runtime_observations",
                facts=bound_observations,
                source_id="ba_avp_sava",
                acquisition_id="observation_request",
            ),
        )
        + tuple(
            FactBinding(
                fact_group=pair.acquisition_id,
                facts=(pair.source_fact,),
                source_id="ba_avp_sava",
                acquisition_id=pair.acquisition_id,
            )
            for pair in workbook_access.pairs
        )
        + tuple(
            FactBinding(
                fact_group=f"availability:{pair.station_no}:{pair.product_id}",
                facts=(f"station_product:{pair.station_no}:{pair.product_id}.availability",),
                source_id=None,
                acquisition_id=None,
                transformation=Transformation(
                    name="reviewed workbook numerical/empty conclusion to selectable availability",
                    external_inputs=(ExternalFactReference(source_id="ba_avp_sava", fact=pair.source_fact),),
                ),
            )
            for pair in workbook_access.pairs
        ),
        withheld_facts=(),
        fact_universe=universe + ("source.provider.terms_absence_statement",),
    )


def _complete_catalogue_carrier(
    provenance: AcquisitionProvenance, workbook_access: WorkbookAccessLedger
) -> AcquisitionProvenance:
    return complete_transformed_fact_universe(
        provenance,
        CATALOGUE_FACT_UNIVERSE,
        transformation=Transformation(
            name="ba_fhmzbih external facts to RivRetrieve canonical catalogue carriers",
            external_inputs=tuple(
                ExternalFactReference(source_id="ba_avp_sava", fact=fact)
                for fact in (
                    "source.provider.service_operator",
                    "source.provider.station_service_identity",
                    "source.product.native_identifiers",
                    "source.product.native_physics",
                )
                + tuple(
                    f"source.station:{station}.identity_location"
                    for station in sorted({pair.station_no for pair in workbook_access.pairs})
                )
            ),
        ),
    )


def build_acquisition_provenance(workbook_access: WorkbookAccessLedger) -> AcquisitionProvenance:
    """Build closed ba_fhmzbih acquisition provenance."""
    return _complete_catalogue_carrier(_build_provider_acquisition_provenance(workbook_access), workbook_access)
