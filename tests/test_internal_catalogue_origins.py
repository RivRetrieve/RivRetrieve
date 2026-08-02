import typing
from dataclasses import FrozenInstanceError
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.catalogue_origins import (
    ORIGIN_GATE_ENROLLED_PROVIDERS,
    CatalogueOrigin,
    Documented,
    DocumentedValue,
    Evidence,
    Field,
    NativeColumn,
    NotPublished,
    enforce_catalogue_origins,
    validate_catalogue_origins,
)
from rivretrieve._internal.catalogues.native import read_native_table
from rivretrieve._internal.catalogues.schemas import STATION_CATALOG_SCHEMA
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.lt_lhmt.generate_catalogue import build_stations
from rivretrieve._internal.providers.lt_lhmt.origins import STATION_CATALOGUE_ORIGINS
from rivretrieve._internal.providers.usgs_nwis.origins import (
    STATION_CATALOGUE_ORIGINS as USGS_STATION_CATALOGUE_ORIGINS,
)

NATIVE_PATH = Path("src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet")


def test_field_carries_an_exact_native_column_and_is_immutable() -> None:
    native_column = NativeColumn(" station code ")
    origin = Field(native_column)

    assert origin.native_column == " station code "
    assert isinstance(origin.native_column, NativeColumn)
    attribute = "native_column"
    with pytest.raises(FrozenInstanceError):
        setattr(origin, attribute, NativeColumn("other"))


@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_native_column_rejects_empty_names(value: str) -> None:
    with pytest.raises(ValueError, match="native column name must not be empty"):
        NativeColumn(value)


def test_field_rejects_a_bare_string_carrier() -> None:
    with pytest.raises(TypeError, match="Field.native_column must be a NativeColumn"):
        Field("station_code")  # type: ignore[arg-type]


def test_field_defers_native_table_membership_to_the_build_gate() -> None:
    origin = Field(NativeColumn("column_not_yet_fetched"))

    assert origin.native_column == "column_not_yet_fetched"


@pytest.mark.parametrize(
    "url",
    [
        "http://provider.example/documentation",
        "https://provider.example/catalogue?view=stations#fields",
    ],
)
def test_not_published_carries_http_documentation_evidence_and_is_immutable(url: str) -> None:
    evidence = Evidence(url)
    origin = NotPublished(evidence)

    assert origin.evidence == url
    assert isinstance(origin.evidence, Evidence)
    attribute = "evidence"
    with pytest.raises(FrozenInstanceError):
        setattr(origin, attribute, Evidence("https://provider.example/other"))


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "/provider-documentation",
        "ftp://provider.example/documentation",
        "https://",
        "https://provider.example/has whitespace",
    ],
)
def test_evidence_rejects_empty_or_non_http_documentation_links(value: str) -> None:
    with pytest.raises(ValueError, match=r"evidence must be an absolute HTTP\(S\) documentation link"):
        Evidence(value)


def test_not_published_requires_the_named_evidence_carrier() -> None:
    with pytest.raises(TypeError, match="NotPublished.evidence must be Evidence"):
        NotPublished("https://provider.example/documentation")  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        NotPublished()  # type: ignore[call-arg]


def test_documented_carries_a_named_value_and_evidence_and_is_immutable() -> None:
    origin = Documented(
        DocumentedValue("EPSG:4326"),
        Evidence("https://provider.example/documentation"),
    )

    assert origin.value == "EPSG:4326"
    assert isinstance(origin.value, DocumentedValue)
    assert isinstance(origin.evidence, Evidence)
    with pytest.raises(FrozenInstanceError):
        origin.value = DocumentedValue("EPSG:9999")


@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_documented_value_rejects_empty_values(value: str) -> None:
    with pytest.raises(ValueError, match="documented value must not be empty"):
        DocumentedValue(value)


def test_documented_requires_named_carriers() -> None:
    evidence = Evidence("https://provider.example/documentation")
    with pytest.raises(TypeError, match="Documented.value must be a DocumentedValue"):
        Documented("EPSG:4326", evidence)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Documented.evidence must be Evidence"):
        Documented(DocumentedValue("EPSG:4326"), str(evidence))  # type: ignore[arg-type]


def test_catalogue_origin_union_contains_exactly_the_implemented_forms() -> None:
    assert typing.get_args(CatalogueOrigin.__value__) == (Field, NotPublished, Documented)


def test_field_has_value_equality_and_hashing() -> None:
    first = Field(NativeColumn("station_code"))
    equal = Field(NativeColumn("station_code"))
    different = Field(NativeColumn("station_name"))

    assert first == equal
    assert first != different
    assert hash(first) == hash(equal)
    assert {first, equal, different} == {first, different}


def test_not_published_has_value_equality_and_hashing() -> None:
    first = NotPublished(Evidence("https://provider.example/documentation"))
    equal = NotPublished(Evidence("https://provider.example/documentation"))
    different = NotPublished(Evidence("https://provider.example/catalogue"))

    assert first == equal
    assert first != different
    assert hash(first) == hash(equal)
    assert {first, equal, different} == {first, different}


def test_documented_has_value_equality_and_hashing() -> None:
    evidence = Evidence("https://provider.example/documentation")
    first = Documented(DocumentedValue("EPSG:4326"), evidence)
    equal = Documented(DocumentedValue("EPSG:4326"), evidence)
    different = Documented(DocumentedValue("EPSG:9999"), evidence)

    assert first == equal
    assert first != different
    assert hash(first) == hash(equal)
    assert {first, equal, different} == {first, different}


def test_catalogue_origin_forms_never_compare_equal_to_each_other() -> None:
    value = "https://provider.example/documentation"

    assert Field(NativeColumn(value)) != NotPublished(Evidence(value))
    assert Documented(DocumentedValue(value), Evidence(value)) != NotPublished(Evidence(value))


def test_origin_gate_enrols_exactly_lithuania_and_usgs() -> None:
    assert frozenset({ProviderId("lt_lhmt"), ProviderId("usgs_nwis")}) == ORIGIN_GATE_ENROLLED_PROVIDERS


def test_enforcing_gate_rejects_unenrolled_provider_before_evaluation() -> None:
    with pytest.raises(
        FatalContractError,
        match=r"other_provider: provider is not enrolled in catalogue origin gate",
    ):
        enforce_catalogue_origins(ProviderId("other_provider"), {}, None, None)  # type: ignore[arg-type]


def test_lithuania_declarations_match_canonical_schema_order_and_values() -> None:
    assert tuple(STATION_CATALOGUE_ORIGINS) == tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert {
        "provider_id": Field(NativeColumn("code")),
        "station_id": Field(NativeColumn("code")),
        "latitude": Field(NativeColumn("coordinates")),
        "longitude": Field(NativeColumn("coordinates")),
        "crs": Documented(DocumentedValue("EPSG:4326"), Evidence("https://api.meteo.lt/")),
    } == STATION_CATALOGUE_ORIGINS


def test_usgs_declarations_match_canonical_schema_order_and_values() -> None:
    assert tuple(USGS_STATION_CATALOGUE_ORIGINS) == tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert {
        "provider_id": Field(NativeColumn("site_no")),
        "station_id": Field(NativeColumn("site_no")),
        "latitude": Field(NativeColumn("dec_lat_va")),
        "longitude": Field(NativeColumn("dec_long_va")),
        "crs": Field(NativeColumn("dec_coord_datum_cd")),
    } == USGS_STATION_CATALOGUE_ORIGINS


def _native_and_stations():
    native_table = read_native_table(NATIVE_PATH)
    return native_table, build_stations(native_table)


def _assert_single_issue(exc_info: pytest.ExceptionInfo[FatalContractError], code: str, column: str) -> None:
    assert len(exc_info.value.issues) == 1
    issue = exc_info.value.issues[0]
    assert issue.code == code
    assert issue.provider_id == ProviderId("lt_lhmt")
    assert issue.details == {"canonical_column": column}


def test_origin_gate_rejects_undeclared_canonical_column() -> None:
    declarations: dict[str, object] = dict(STATION_CATALOGUE_ORIGINS)
    del declarations["longitude"]
    native_table, stations = _native_and_stations()

    with pytest.raises(
        FatalContractError,
        match=r"lt_lhmt\.longitude: canonical column has no origin declaration",
    ) as exc_info:
        enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native_table, stations)

    _assert_single_issue(exc_info, "catalogue_origin.undeclared_column", "longitude")


def test_origin_gate_rejects_absent_native_column() -> None:
    declarations: dict[str, object] = dict(STATION_CATALOGUE_ORIGINS)
    declarations["latitude"] = Field(NativeColumn("absent_column"))
    native_table, stations = _native_and_stations()

    with pytest.raises(
        FatalContractError,
        match=r"lt_lhmt\.latitude: native column 'absent_column' does not exist",
    ) as exc_info:
        enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native_table, stations)

    _assert_single_issue(exc_info, "catalogue_origin.absent_native_column", "latitude")


def test_origin_gate_rejects_unpropagated_native_value_on_aligned_row() -> None:
    declarations: dict[str, object] = dict(STATION_CATALOGUE_ORIGINS)
    declarations["latitude"] = Field(NativeColumn("name"))
    native_table, stations = _native_and_stations()
    first_station_id = stations["station_id"].item(0)
    broken_stations = stations.with_columns(
        pl.when(pl.col("station_id") == first_station_id).then(None).otherwise(pl.col("latitude")).alias("latitude")
    )

    with pytest.raises(
        FatalContractError,
        match=r"lt_lhmt\.latitude: canonical value is null where native column 'name' has a value",
    ) as exc_info:
        enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native_table, broken_stations)

    _assert_single_issue(exc_info, "catalogue_origin.unpropagated_value", "latitude")


def test_origin_gate_reports_when_station_id_alignment_key_is_unresolvable() -> None:
    declarations: dict[str, object] = dict(STATION_CATALOGUE_ORIGINS)
    declarations["station_id"] = NotPublished(Evidence("https://api.meteo.lt/"))
    native_table, stations = _native_and_stations()
    broken_stations = stations.with_columns(pl.lit(None).cast(pl.Float64).alias("latitude"))

    with pytest.raises(
        FatalContractError,
        match=(
            r"lt_lhmt\.station_id: rule \(c\) could not be evaluated because the station_id "
            r"alignment key is unresolvable"
        ),
    ) as exc_info:
        enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native_table, broken_stations)

    _assert_single_issue(exc_info, "catalogue_origin.unresolvable_alignment_key", "station_id")


def test_origin_gate_rejects_malformed_not_published_declaration() -> None:
    declarations: dict[str, object] = dict(STATION_CATALOGUE_ORIGINS)
    declarations["crs"] = {"not_published": True}
    native_table, stations = _native_and_stations()

    with pytest.raises(
        FatalContractError,
        match=r"lt_lhmt\.crs: NotPublished origin must carry Evidence",
    ) as exc_info:
        enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native_table, stations)

    _assert_single_issue(exc_info, "catalogue_origin.missing_evidence", "crs")


def test_origin_gate_rejects_documented_declaration_with_absent_evidence() -> None:
    declarations: dict[str, object] = dict(STATION_CATALOGUE_ORIGINS)
    malformed = object.__new__(Documented)
    object.__setattr__(malformed, "value", DocumentedValue("EPSG:4326"))
    declarations["crs"] = malformed
    native_table, stations = _native_and_stations()

    with pytest.raises(
        FatalContractError,
        match=r"lt_lhmt\.crs: Documented origin must carry Evidence",
    ) as exc_info:
        enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native_table, stations)

    _assert_single_issue(exc_info, "catalogue_origin.missing_evidence", "crs")


def test_origin_gate_rejects_documented_value_drift_from_builder_output() -> None:
    declarations: dict[str, object] = dict(STATION_CATALOGUE_ORIGINS)
    declarations["crs"] = Documented(
        DocumentedValue("EPSG:9999"),
        Evidence("https://api.meteo.lt/"),
    )
    native_table, stations = _native_and_stations()

    with pytest.raises(
        FatalContractError,
        match=r"lt_lhmt\.crs: emitted value does not match documented value 'EPSG:9999'",
    ) as exc_info:
        enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native_table, stations)

    _assert_single_issue(exc_info, "catalogue_origin.documented_value_mismatch", "crs")


def test_committed_lithuania_origins_pass_validation() -> None:
    native_table, stations = _native_and_stations()

    assert validate_catalogue_origins(ProviderId("lt_lhmt"), STATION_CATALOGUE_ORIGINS, native_table, stations) == []
