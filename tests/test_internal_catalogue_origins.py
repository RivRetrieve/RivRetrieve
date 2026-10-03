import hashlib
from dataclasses import FrozenInstanceError
from html.parser import HTMLParser
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.catalogue_origins import (
    ORIGIN_GATE_ENROLLED_PROVIDERS,
    Authored,
    AuthoredValue,
    Documented,
    DocumentedValue,
    Evidence,
    Field,
    FieldConversion,
    FloatConversion,
    IdentityConversion,
    NativeColumn,
    NotPublished,
    enforce_catalogue_origins,
    validate_catalogue_origins,
)
from rivretrieve._internal.catalogues.native import read_native_table
from rivretrieve._internal.catalogues.schemas import STATION_CATALOG_SCHEMA
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ca_eccc.generate_catalogue import build_stations as build_canada_stations
from rivretrieve._internal.providers.ca_eccc.origins import (
    STATION_CATALOGUE_ORIGINS as CANADA_ORIGINS,
)
from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import (
    build_hydro_stations,
    build_temp_stations,
)
from rivretrieve._internal.providers.fr_hubeau.origins import (
    HYDROMETRY_STATION_CATALOGUE_ORIGINS as FRANCE_HYDROMETRY_ORIGINS,
)
from rivretrieve._internal.providers.fr_hubeau.origins import (
    TEMPERATURE_STATION_CATALOGUE_ORIGINS,
    HydrometryCoordinateConversion,
)
from rivretrieve._internal.providers.jp_mlit.origins import WorldGeodeticDmsConversion
from rivretrieve._internal.providers.lt_lhmt.generate_catalogue import build_stations
from rivretrieve._internal.providers.lt_lhmt.origins import STATION_CATALOGUE_ORIGINS as LT_STATION_ORIGINS
from rivretrieve._internal.providers.th_thaiwater.generate_catalogue import build_stations as build_thai_stations
from rivretrieve._internal.providers.th_thaiwater.origins import (
    CRS_EVIDENCE_URL as THAI_CRS_EVIDENCE_URL,
)
from rivretrieve._internal.providers.th_thaiwater.origins import (
    STATION_CATALOGUE_ORIGINS as THAI_STATION_ORIGINS,
)
from rivretrieve._internal.providers.usgs_nwis.origins import DatumToCrsConversion
from rivretrieve._internal.providers.za_dws.origins import UnsignedDmsConversion

NATIVE_PATH = Path("src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet")
CANADA_NATIVE_PATH = Path("src/rivretrieve/_internal/providers/ca_eccc/catalogue/native.parquet")
THAI_NATIVE_PATH = Path("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
JAPAN_NATIVE_PATH = Path("src/rivretrieve/_internal/providers/jp_mlit/catalogue/native.parquet")
THAI_COORDINATE_EVIDENCE_PATH = Path("tests/test_data/th_thaiwater_coordinate_standard.html")
REPOSITORY_ROOT = Path(__file__).parents[1]
CATALOGUE_ORIGINS_MODULE_PATH = REPOSITORY_ROOT / "src/rivretrieve/_internal/catalogue_origins.py"


class _CanonicalLinkParser(HTMLParser):
    canonical_urls: list[str]

    def __init__(self) -> None:
        super().__init__()
        self.canonical_urls = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "link" and attributes.get("rel") == "canonical":
            href = attributes.get("href")
            if href is not None:
                self.canonical_urls.append(href)


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
        Field("station_code")  # ty: ignore[invalid-argument-type]


def test_field_defers_native_table_membership_to_the_build_gate() -> None:
    origin = Field(NativeColumn("column_not_yet_fetched"))

    assert origin.native_column == "column_not_yet_fetched"


def test_field_conversion_is_named_immutable_and_structurally_hashable() -> None:
    origin = Field(NativeColumn("coordinate"), FloatConversion())
    equivalent = Field(NativeColumn("coordinate"), FloatConversion())

    assert origin.conversion.name == "float"
    assert origin == equivalent
    assert hash(origin) == hash(equivalent)
    with pytest.raises(FrozenInstanceError):
        origin.conversion = IdentityConversion()  # ty: ignore[invalid-assignment]
    with pytest.raises(TypeError, match="Field.conversion must be a FieldConversion"):
        Field(NativeColumn("coordinate"), "float")  # ty: ignore[invalid-argument-type]


@pytest.mark.parametrize(
    ("conversion", "equivalent"),
    [
        (WorldGeodeticDmsConversion(), WorldGeodeticDmsConversion()),
        (HydrometryCoordinateConversion(), HydrometryCoordinateConversion()),
        (DatumToCrsConversion(), DatumToCrsConversion()),
        (UnsignedDmsConversion(), UnsignedDmsConversion()),
    ],
)
def test_provider_owned_conversions_have_structural_equality_and_hash(
    conversion: FieldConversion, equivalent: FieldConversion
) -> None:
    assert conversion == equivalent
    assert hash(conversion) == hash(equivalent)


@pytest.mark.parametrize(
    ("conversion", "canonical_column", "wrong_native_column"),
    [
        (WorldGeodeticDmsConversion(), "latitude", NativeColumn("日本測地系")),
        (HydrometryCoordinateConversion(), "latitude", NativeColumn("longitude_station")),
        (DatumToCrsConversion(), "crs", NativeColumn("coord_datum_cd")),
        (UnsignedDmsConversion(), "latitude", NativeColumn("Longitude (dd:mm:ss)")),
    ],
)
def test_provider_owned_conversions_reject_wrong_native_columns(
    conversion: FieldConversion,
    canonical_column: str,
    wrong_native_column: NativeColumn,
) -> None:
    with pytest.raises(ValueError, match="requires native field"):
        conversion.apply(canonical_column, wrong_native_column, {})


def test_authored_carries_an_exact_immutable_canonical_value() -> None:
    origin = Authored(AuthoredValue("provider_id"))

    assert origin.value == "provider_id"
    with pytest.raises(FrozenInstanceError):
        origin.value = AuthoredValue("other")  # ty: ignore[invalid-assignment]
    with pytest.raises(TypeError, match="Authored.value must be an AuthoredValue"):
        Authored("provider_id")  # ty: ignore[invalid-argument-type]


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
        NotPublished("https://provider.example/documentation")  # ty: ignore[invalid-argument-type]

    with pytest.raises(TypeError):
        NotPublished()  # ty: ignore[missing-argument]


def test_documented_carries_a_named_value_and_evidence_and_is_immutable() -> None:
    origin = Documented(
        DocumentedValue("EPSG:4326"),
        Evidence("https://provider.example/documentation"),
    )

    assert origin.value == "EPSG:4326"
    assert isinstance(origin.value, DocumentedValue)
    assert isinstance(origin.evidence, Evidence)
    with pytest.raises(FrozenInstanceError):
        origin.value = DocumentedValue("EPSG:9999")  # ty: ignore[invalid-assignment]


@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_documented_value_rejects_empty_values(value: str) -> None:
    with pytest.raises(ValueError, match="documented value must not be empty"):
        DocumentedValue(value)


def test_documented_requires_named_carriers() -> None:
    evidence = Evidence("https://provider.example/documentation")
    with pytest.raises(TypeError, match="Documented.value must be a DocumentedValue"):
        Documented("EPSG:4326", evidence)  # ty: ignore[invalid-argument-type]
    with pytest.raises(TypeError, match="Documented.evidence must be Evidence"):
        Documented(DocumentedValue("EPSG:4326"), str(evidence))  # ty: ignore[invalid-argument-type]


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


def test_origin_gate_enrols_exactly_the_registered_providers() -> None:
    expected = frozenset(
        {
            ProviderId("ba_fhmzbih"),
            ProviderId("br_ana"),
            ProviderId("ca_eccc"),
            ProviderId("ch_foen"),
            ProviderId("cz_chmi"),
            ProviderId("fr_hubeau"),
            ProviderId("fr_hydroportail"),
            ProviderId("jp_mlit"),
            ProviderId("lt_lhmt"),
            ProviderId("no_nve"),
            ProviderId("pl_imgw"),
            ProviderId("th_thaiwater"),
            ProviderId("usgs_nwis"),
            ProviderId("za_dws"),
        }
    )
    registered = frozenset(map(ProviderId, rr.providers().get_column("provider_id").to_list()))

    assert expected == ORIGIN_GATE_ENROLLED_PROVIDERS
    assert registered >= ORIGIN_GATE_ENROLLED_PROVIDERS
    assert registered == ORIGIN_GATE_ENROLLED_PROVIDERS


@pytest.mark.derived("src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet")
def test_committed_poland_origins_pass_validation_and_enforcement(retained_evidence_root: Path) -> None:
    from rivretrieve._internal.providers.pl_imgw.generate_catalogue import build_stations
    from rivretrieve._internal.providers.pl_imgw.origins import STATION_CATALOGUE_ORIGINS

    native = read_native_table(
        retained_evidence_root / "src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet"
    )
    assert native.data.schema == pl.Schema(
        {
            "gauge_id": pl.String,
            "gauge_name": pl.String,
            "river": pl.String,
            "area": pl.Float64,
            "gauge_altitude": pl.String,
            "latitude": pl.Float64,
            "longitude": pl.Float64,
            "retrieved_at": pl.Datetime("us", "UTC"),
        }
    )
    stations = build_stations(native)
    assert native.data.schema["gauge_id"] == stations.schema["station_id"]
    assert validate_catalogue_origins(ProviderId("pl_imgw"), STATION_CATALOGUE_ORIGINS, native, stations) == []
    enforce_catalogue_origins(ProviderId("pl_imgw"), STATION_CATALOGUE_ORIGINS, native, stations)


@pytest.mark.derived("src/rivretrieve/_internal/providers/jp_mlit/catalogue/native.parquet")
def test_committed_japan_origins_and_build_pass_gate(retained_evidence_root: Path) -> None:
    from rivretrieve._internal.providers.jp_mlit.generate_catalogue import build_catalogue
    from rivretrieve._internal.providers.jp_mlit.origins import STATION_CATALOGUE_ORIGINS

    native_table = read_native_table(retained_evidence_root / JAPAN_NATIVE_PATH)
    catalogue = build_catalogue(native_table, STATION_CATALOGUE_ORIGINS)
    assert (
        validate_catalogue_origins(ProviderId("jp_mlit"), STATION_CATALOGUE_ORIGINS, native_table, catalogue.stations)
        == []
    )
    enforce_catalogue_origins(ProviderId("jp_mlit"), STATION_CATALOGUE_ORIGINS, native_table, catalogue.stations)


@pytest.mark.derived("src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet")
def test_france_endpoint_declarations_validate_complete_native_partitions(retained_evidence_root: Path) -> None:
    native = read_native_table(
        retained_evidence_root / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet"
    )
    hydro = type(native)(native.data.filter(pl.col("source_endpoint") == "hydrometrie/referentiel/stations"))
    temperature = type(native)(native.data.filter(pl.col("source_endpoint") == "temperature/station"))
    hydro_stations = build_hydro_stations(hydro)
    temperature_stations = build_temp_stations(temperature)

    assert validate_catalogue_origins(ProviderId("fr_hubeau"), FRANCE_HYDROMETRY_ORIGINS, hydro, hydro_stations) == []
    assert (
        validate_catalogue_origins(
            ProviderId("fr_hubeau"), TEMPERATURE_STATION_CATALOGUE_ORIGINS, temperature, temperature_stations
        )
        == []
    )
    enforce_catalogue_origins(ProviderId("fr_hubeau"), FRANCE_HYDROMETRY_ORIGINS, hydro, hydro_stations)
    enforce_catalogue_origins(
        ProviderId("fr_hubeau"), TEMPERATURE_STATION_CATALOGUE_ORIGINS, temperature, temperature_stations
    )


@pytest.mark.derived("src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet")
def test_committed_bosnia_origins_pass_validation_and_enforcement(retained_evidence_root: Path) -> None:
    from rivretrieve._internal.providers.ba_fhmzbih.generate_catalogue import build_stations
    from rivretrieve._internal.providers.ba_fhmzbih.origins import STATION_CATALOGUE_ORIGINS

    native_table = read_native_table(
        retained_evidence_root / "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet"
    )
    stations = build_stations(native_table)
    assert validate_catalogue_origins(ProviderId("ba_fhmzbih"), STATION_CATALOGUE_ORIGINS, native_table, stations) == []
    enforce_catalogue_origins(ProviderId("ba_fhmzbih"), STATION_CATALOGUE_ORIGINS, native_table, stations)


@pytest.mark.parametrize("provider_id", [ProviderId("other_provider")])
def test_enforcing_gate_rejects_unenrolled_provider_before_evaluation(provider_id: ProviderId) -> None:
    with pytest.raises(FatalContractError) as exc_info:
        enforce_catalogue_origins(provider_id, {}, None, None)  # ty: ignore[invalid-argument-type]

    assert str(exc_info.value) == f"{provider_id}: provider is not enrolled in catalogue origin gate"


@pytest.mark.recorded("tests/test_data/th_thaiwater_coordinate_standard.html")
def test_thailand_coordinate_evidence_preserves_canonical_source_reference(retained_evidence_root: Path) -> None:
    parser = _CanonicalLinkParser()
    capture_bytes = (retained_evidence_root / THAI_COORDINATE_EVIDENCE_PATH).read_bytes()
    capture = capture_bytes.decode("utf-8")
    parser.feed(capture)

    assert len(capture_bytes) == 607_845
    assert hashlib.sha256(capture_bytes).hexdigest() == (
        "64e4c82a09ad547aeae5dac0493561f89ffd6618c15ac905a92109dd49aa2d04"
    )
    assert capture.count(THAI_CRS_EVIDENCE_URL) == 2
    assert parser.canonical_urls == [THAI_CRS_EVIDENCE_URL]


@pytest.mark.derived("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
def test_committed_thailand_origins_pass_validation(retained_evidence_root: Path) -> None:
    native_table = read_native_table(retained_evidence_root / THAI_NATIVE_PATH)
    stations = build_thai_stations(native_table)

    assert validate_catalogue_origins(ProviderId("th_thaiwater"), THAI_STATION_ORIGINS, native_table, stations) == []


@pytest.mark.derived("src/rivretrieve/_internal/providers/cz_chmi/catalogue/native.parquet")
def test_committed_czech_origins_pass_validation(retained_evidence_root: Path) -> None:
    from rivretrieve._internal.providers.cz_chmi.generate_catalogue import build_stations as build_czech_stations
    from rivretrieve._internal.providers.cz_chmi.origins import (
        STATION_CATALOGUE_ORIGINS as CZECH_ORIGINS,
    )

    native_table = read_native_table(
        retained_evidence_root / "src/rivretrieve/_internal/providers/cz_chmi/catalogue/native.parquet"
    )
    stations = build_czech_stations(native_table)

    assert validate_catalogue_origins(ProviderId("cz_chmi"), CZECH_ORIGINS, native_table, stations) == []


@pytest.mark.derived("src/rivretrieve/_internal/providers/ca_eccc/catalogue/native.parquet")
def test_committed_canada_origins_pass_validation(retained_evidence_root: Path) -> None:
    native_table = read_native_table(retained_evidence_root / CANADA_NATIVE_PATH)
    station_input = native_table.data.select(
        "id",
        "STATION_NUMBER",
        pl.col("geometry.coordinates[1]").alias("LATITUDE"),
        pl.col("geometry.coordinates[0]").alias("LONGITUDE"),
    ).to_dicts()
    stations = build_canada_stations(station_input)

    assert validate_catalogue_origins(ProviderId("ca_eccc"), CANADA_ORIGINS, native_table, stations) == []
    enforce_catalogue_origins(ProviderId("ca_eccc"), CANADA_ORIGINS, native_table, stations)


@pytest.mark.derived("src/rivretrieve/_internal/providers/za_dws/catalogue/native.parquet")
def test_committed_dws_origins_and_build_pass_gate(retained_evidence_root: Path) -> None:
    from rivretrieve._internal.providers.za_dws.generate_catalogue import build_catalogue
    from rivretrieve._internal.providers.za_dws.origins import STATION_CATALOGUE_ORIGINS

    native_table = read_native_table(
        retained_evidence_root / "src/rivretrieve/_internal/providers/za_dws/catalogue/native.parquet"
    )
    catalogue = build_catalogue(native_table, STATION_CATALOGUE_ORIGINS)

    assert (
        validate_catalogue_origins(ProviderId("za_dws"), STATION_CATALOGUE_ORIGINS, native_table, catalogue.stations)
        == []
    )
    enforce_catalogue_origins(ProviderId("za_dws"), STATION_CATALOGUE_ORIGINS, native_table, catalogue.stations)


def _native_and_stations(retained_evidence_root: Path):
    native_table = read_native_table(retained_evidence_root / NATIVE_PATH)
    return native_table, build_stations(native_table)


def _assert_single_issue(exc_info: pytest.ExceptionInfo[FatalContractError], code: str, column: str) -> None:
    assert len(exc_info.value.issues) == 1
    issue = exc_info.value.issues[0]
    assert issue.code == code
    assert issue.provider_id == ProviderId("lt_lhmt")
    assert issue.details == {"canonical_column": column}


def _synthetic_origin_inputs():
    from datetime import UTC, datetime

    from rivretrieve._internal.catalogues.native import RetrievedAt, stamp_native_table

    native = stamp_native_table(
        pl.DataFrame({"code": ["one"], "latitude": [55.0], "longitude": [24.0]}),
        RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    stations = pl.DataFrame(
        {
            "provider_id": ["lt_lhmt"],
            "station_id": ["one"],
            "latitude": [55.0],
            "longitude": [24.0],
            "crs": ["unknown"],
        },
        schema=STATION_CATALOG_SCHEMA.polars_schema,
    )
    declarations = {
        "provider_id": Authored(AuthoredValue("lt_lhmt")),
        "station_id": Field(NativeColumn("code")),
        "latitude": Field(NativeColumn("latitude")),
        "longitude": Field(NativeColumn("longitude")),
        "crs": NotPublished(Evidence("https://example.test/coordinate-fields")),
    }
    enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native, stations)
    return native, stations, declarations


@pytest.mark.parametrize("column", ["provider_id", "station_id", "latitude", "longitude", "crs"])
def test_origin_gate_rejects_undeclared_canonical_column(column: str) -> None:
    native, stations, declarations = _synthetic_origin_inputs()
    del declarations[column]

    with pytest.raises(FatalContractError) as caught:
        enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native, stations)

    expected = {"catalogue_origin.undeclared_column"}
    if column == "station_id":
        expected.add("catalogue_origin.unresolvable_alignment_key")
    assert {issue.code for issue in caught.value.issues} == expected
    assert all(issue.details == {"canonical_column": column} for issue in caught.value.issues)


def test_origin_gate_rejects_absent_native_column() -> None:
    native_table, stations, declarations = _synthetic_origin_inputs()
    declarations["latitude"] = Field(NativeColumn("absent_column"))

    with pytest.raises(
        FatalContractError,
        match=r"lt_lhmt\.latitude: native column 'absent_column' does not exist",
    ) as exc_info:
        enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native_table, stations)

    _assert_single_issue(exc_info, "catalogue_origin.absent_native_column", "latitude")


def test_origin_gate_rejects_unpropagated_native_value_on_aligned_row() -> None:
    native_table, stations, declarations = _synthetic_origin_inputs()
    first_station_id = stations["station_id"].item(0)
    broken_stations = stations.with_columns(
        pl.when(pl.col("station_id") == first_station_id).then(None).otherwise(pl.col("latitude")).alias("latitude")
    )

    with pytest.raises(
        FatalContractError,
        match=r"lt_lhmt\.latitude: canonical value is null where native column 'latitude' has a value",
    ) as exc_info:
        enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native_table, broken_stations)

    _assert_single_issue(exc_info, "catalogue_origin.unpropagated_value", "latitude")


def test_origin_gate_reports_when_station_id_alignment_key_is_unresolvable() -> None:
    native_table, stations, declarations = _synthetic_origin_inputs()
    declarations["station_id"] = NotPublished(Evidence("https://api.meteo.lt/"))
    broken_stations = stations.with_columns(pl.lit(None).cast(pl.Float64).alias("latitude"))

    with pytest.raises(
        FatalContractError,
        match=(
            r"lt_lhmt\.station_id: rule \(c\) could not be evaluated because the station_id "
            r"alignment key is unresolvable"
        ),
    ) as exc_info:
        enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native_table, broken_stations)

    assert exc_info.value.issues[0].code == "catalogue_origin.unresolvable_alignment_key"
    assert exc_info.value.issues[0].details == {"canonical_column": "station_id"}
    assert exc_info.value.issues[1].code == "catalogue_origin.not_published_marker_mismatch"


def test_origin_gate_rejects_malformed_not_published_declaration() -> None:
    native_table, stations, declarations = _synthetic_origin_inputs()
    declarations["crs"] = {"not_published": True}

    with pytest.raises(
        FatalContractError,
        match=r"lt_lhmt\.crs: NotPublished origin must carry Evidence",
    ) as exc_info:
        enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native_table, stations)

    _assert_single_issue(exc_info, "catalogue_origin.missing_evidence", "crs")


def test_origin_gate_rejects_documented_declaration_with_absent_evidence() -> None:
    native_table, stations, declarations = _synthetic_origin_inputs()
    malformed = object.__new__(Documented)
    object.__setattr__(malformed, "value", DocumentedValue("EPSG:4326"))
    declarations["crs"] = malformed

    with pytest.raises(
        FatalContractError,
        match=r"lt_lhmt\.crs: Documented origin must carry Evidence",
    ) as exc_info:
        enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native_table, stations)

    _assert_single_issue(exc_info, "catalogue_origin.missing_evidence", "crs")


def test_origin_gate_rejects_documented_value_drift_from_builder_output() -> None:
    native_table, stations, declarations = _synthetic_origin_inputs()
    declarations["crs"] = Documented(
        DocumentedValue("EPSG:9999"),
        Evidence("https://api.meteo.lt/"),
    )

    with pytest.raises(
        FatalContractError,
        match=r"lt_lhmt\.crs: emitted value does not match documented value 'EPSG:9999'",
    ) as exc_info:
        enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native_table, stations)

    _assert_single_issue(exc_info, "catalogue_origin.documented_value_mismatch", "crs")


@pytest.mark.derived("src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet")
def test_committed_lithuania_origins_pass_validation(retained_evidence_root: Path) -> None:
    native_table, stations = _native_and_stations(retained_evidence_root)

    assert validate_catalogue_origins(ProviderId("lt_lhmt"), LT_STATION_ORIGINS, native_table, stations) == []


@pytest.mark.derived("src/rivretrieve/_internal/providers/ch_foen/catalogue/native.parquet")
def test_committed_swiss_origins_pass_validation(retained_evidence_root: Path) -> None:
    from rivretrieve._internal.providers.ch_foen.generate_catalogue import build_stations
    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS

    native_table = read_native_table(
        retained_evidence_root / "src/rivretrieve/_internal/providers/ch_foen/catalogue/native.parquet"
    )

    assert (
        validate_catalogue_origins(
            ProviderId("ch_foen"), STATION_CATALOGUE_ORIGINS, native_table, build_stations(native_table)
        )
        == []
    )


@pytest.mark.derived("src/rivretrieve/_internal/providers/fr_hydroportail/catalogue/native.parquet")
def test_hydroportail_native_station_origins_pass_gate(retained_evidence_root: Path):
    from rivretrieve._internal.providers.fr_hydroportail.generate_catalogue import build_stations
    from rivretrieve._internal.providers.fr_hydroportail.origins import STATION_CATALOGUE_ORIGINS

    assert {
        "provider_id": Authored(AuthoredValue("fr_hydroportail")),
        "station_id": Field(NativeColumn("bookmarkCode")),
        "latitude": Field(NativeColumn("y")),
        "longitude": Field(NativeColumn("x")),
        "crs": Documented(DocumentedValue("EPSG:4326"), Evidence("https://hydro.eaufrance.fr/build/8529.fdb00780.js")),
    } == STATION_CATALOGUE_ORIGINS
    native = read_native_table(
        retained_evidence_root / "src/rivretrieve/_internal/providers/fr_hydroportail/catalogue/native.parquet"
    )
    stations = build_stations(native)
    assert tuple(STATION_CATALOGUE_ORIGINS) == tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert validate_catalogue_origins(ProviderId("fr_hydroportail"), STATION_CATALOGUE_ORIGINS, native, stations) == []
    enforce_catalogue_origins(ProviderId("fr_hydroportail"), STATION_CATALOGUE_ORIGINS, native, stations)
