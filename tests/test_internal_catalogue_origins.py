import hashlib
import typing
from dataclasses import FrozenInstanceError
from html.parser import HTMLParser
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
from rivretrieve._internal.providers.ca_eccc.generate_catalogue import build_stations as build_canada_stations
from rivretrieve._internal.providers.ca_eccc.origins import (
    CRS_EVIDENCE_URL,
)
from rivretrieve._internal.providers.ca_eccc.origins import (
    STATION_CATALOGUE_ORIGINS as CANADA_ORIGINS,
)
from rivretrieve._internal.providers.lt_lhmt.generate_catalogue import build_stations
from rivretrieve._internal.providers.lt_lhmt.origins import STATION_CATALOGUE_ORIGINS as LT_STATION_ORIGINS
from rivretrieve._internal.providers.th_thaiwater.generate_catalogue import build_stations as build_thai_stations
from rivretrieve._internal.providers.th_thaiwater.origins import (
    CRS_EVIDENCE_URL as THAI_CRS_EVIDENCE_URL,
)
from rivretrieve._internal.providers.th_thaiwater.origins import (
    STATION_CATALOGUE_ORIGINS as THAI_STATION_ORIGINS,
)
from rivretrieve._internal.providers.usgs_nwis.origins import (
    STATION_CATALOGUE_ORIGINS as USGS_STATION_CATALOGUE_ORIGINS,
)

NATIVE_PATH = Path("src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet")
CANADA_NATIVE_PATH = Path("src/rivretrieve/_internal/providers/ca_eccc/catalogue/native.parquet")
THAI_NATIVE_PATH = Path("src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet")
JAPAN_NATIVE_PATH = Path("src/rivretrieve/_internal/providers/jp_mlit/catalogue/native.parquet")
THAI_COORDINATE_EVIDENCE_PATH = Path("tests/test_data/th_thaiwater_coordinate_standard.html")


class _CanonicalLinkParser(HTMLParser):
    canonical_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "link" and attributes.get("rel") == "canonical":
            self.canonical_url = attributes.get("href")


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


def test_origin_gate_enrols_exactly_bosnia_canada_czechia_japan_lithuania_south_africa_switzerland_thailand_and_usgs() -> (
    None
):
    assert (
        frozenset(
            {
                ProviderId("ba_fhmzbih"),
                ProviderId("ca_eccc"),
                ProviderId("ch_foen"),
                ProviderId("cz_chmi"),
                ProviderId("jp_mlit"),
                ProviderId("lt_lhmt"),
                ProviderId("th_thaiwater"),
                ProviderId("usgs_nwis"),
                ProviderId("za_dws"),
            }
        )
        == ORIGIN_GATE_ENROLLED_PROVIDERS
    )


def test_japan_declarations_match_canonical_schema_order_and_values() -> None:
    from rivretrieve._internal.providers.jp_mlit.origins import STATION_CATALOGUE_ORIGINS

    assert tuple(STATION_CATALOGUE_ORIGINS) == tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert {
        "provider_id": Field(NativeColumn("観測所記号")),
        "station_id": Field(NativeColumn("観測所記号")),
        "latitude": Field(NativeColumn("世界測地系")),
        "longitude": Field(NativeColumn("世界測地系")),
        "crs": NotPublished(Evidence("http://www1.river.go.jp/cgi-bin/SiteInfoDetail.exe?ID=301011281104010")),
    } == STATION_CATALOGUE_ORIGINS


def test_committed_japan_origins_and_build_pass_gate() -> None:
    from rivretrieve._internal.providers.jp_mlit.generate_catalogue import build_catalogue
    from rivretrieve._internal.providers.jp_mlit.origins import STATION_CATALOGUE_ORIGINS

    native_table = read_native_table(JAPAN_NATIVE_PATH)
    catalogue = build_catalogue(native_table, STATION_CATALOGUE_ORIGINS)
    assert (
        validate_catalogue_origins(ProviderId("jp_mlit"), STATION_CATALOGUE_ORIGINS, native_table, catalogue.stations)
        == []
    )
    enforce_catalogue_origins(ProviderId("jp_mlit"), STATION_CATALOGUE_ORIGINS, native_table, catalogue.stations)


def test_bosnia_declarations_match_canonical_schema_order_and_values() -> None:
    from rivretrieve._internal.providers.ba_fhmzbih.origins import STATION_CATALOGUE_ORIGINS

    assert tuple(STATION_CATALOGUE_ORIGINS) == tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert {
        "provider_id": Field(NativeColumn("metadata_station_no")),
        "station_id": Field(NativeColumn("metadata_station_no")),
        "latitude": Field(NativeColumn("metadata_station_latitude")),
        "longitude": Field(NativeColumn("metadata_station_longitude")),
        "crs": NotPublished(Evidence("https://vodostaji.voda.ba/data/internet/stations/stations.json")),
    } == STATION_CATALOGUE_ORIGINS
    carriers = {str(origin.native_column) for origin in STATION_CATALOGUE_ORIGINS.values() if isinstance(origin, Field)}
    assert carriers.isdisjoint(
        {
            "metadata_station_id",
            "metadata_station_carteasting",
            "metadata_station_cartnorthing",
            "metadata_station_local_x",
            "metadata_station_local_y",
            "station_gauge_datum",
            "GAUGE_DATUM",
            "GWREF_DATUM",
        }
    )
    assert "EPSG:4326" not in repr(STATION_CATALOGUE_ORIGINS)


def test_committed_bosnia_origins_pass_validation_and_enforcement() -> None:
    from rivretrieve._internal.providers.ba_fhmzbih.generate_catalogue import build_stations
    from rivretrieve._internal.providers.ba_fhmzbih.origins import STATION_CATALOGUE_ORIGINS

    native_table = read_native_table(Path("src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet"))
    stations = build_stations(native_table)
    assert validate_catalogue_origins(ProviderId("ba_fhmzbih"), STATION_CATALOGUE_ORIGINS, native_table, stations) == []
    enforce_catalogue_origins(ProviderId("ba_fhmzbih"), STATION_CATALOGUE_ORIGINS, native_table, stations)


def test_enforcing_gate_rejects_unenrolled_provider_before_evaluation() -> None:
    with pytest.raises(
        FatalContractError,
        match=r"other_provider: provider is not enrolled in catalogue origin gate",
    ):
        enforce_catalogue_origins(ProviderId("other_provider"), {}, None, None)  # type: ignore[arg-type]


def test_lithuania_declarations_match_canonical_schema_order_and_values() -> None:
    assert tuple(LT_STATION_ORIGINS) == tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert {
        "provider_id": Field(NativeColumn("code")),
        "station_id": Field(NativeColumn("code")),
        "latitude": Field(NativeColumn("coordinates")),
        "longitude": Field(NativeColumn("coordinates")),
        "crs": Documented(DocumentedValue("EPSG:4326"), Evidence("https://api.meteo.lt/")),
    } == LT_STATION_ORIGINS


def test_usgs_declarations_match_canonical_schema_order_and_values() -> None:
    assert tuple(USGS_STATION_CATALOGUE_ORIGINS) == tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert {
        "provider_id": Field(NativeColumn("site_no")),
        "station_id": Field(NativeColumn("site_no")),
        "latitude": Field(NativeColumn("dec_lat_va")),
        "longitude": Field(NativeColumn("dec_long_va")),
        "crs": Field(NativeColumn("dec_coord_datum_cd")),
    } == USGS_STATION_CATALOGUE_ORIGINS


def test_thailand_declarations_match_schema_and_committed_coordinate_evidence() -> None:
    parser = _CanonicalLinkParser()
    capture_bytes = THAI_COORDINATE_EVIDENCE_PATH.read_bytes()
    capture = capture_bytes.decode("utf-8")
    parser.feed(capture)

    assert len(capture_bytes) == 607_845
    assert hashlib.sha256(capture_bytes).hexdigest() == (
        "64e4c82a09ad547aeae5dac0493561f89ffd6618c15ac905a92109dd49aa2d04"
    )
    assert tuple(THAI_STATION_ORIGINS) == tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert {
        "provider_id": Field(NativeColumn("station.id")),
        "station_id": Field(NativeColumn("station.id")),
        "latitude": Field(NativeColumn("station.tele_station_lat")),
        "longitude": Field(NativeColumn("station.tele_station_long")),
        "crs": NotPublished(Evidence(THAI_CRS_EVIDENCE_URL)),
    } == THAI_STATION_ORIGINS
    assert parser.canonical_url == THAI_CRS_EVIDENCE_URL
    assert THAI_CRS_EVIDENCE_URL in capture


def test_committed_thailand_origins_pass_validation() -> None:
    native_table = read_native_table(THAI_NATIVE_PATH)
    stations = build_thai_stations(native_table)

    assert validate_catalogue_origins(ProviderId("th_thaiwater"), THAI_STATION_ORIGINS, native_table, stations) == []


def test_czech_declarations_match_canonical_schema_order_and_values() -> None:
    from rivretrieve._internal.providers.cz_chmi.origins import (
        STATION_CATALOGUE_ORIGINS as CZECH_ORIGINS,
    )

    assert tuple(CZECH_ORIGINS) == tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert {
        "provider_id": Field(NativeColumn("objID")),
        "station_id": Field(NativeColumn("objID")),
        "latitude": Field(NativeColumn("GEOGR1")),
        "longitude": Field(NativeColumn("GEOGR2")),
        "crs": NotPublished(Evidence("https://opendata.chmi.cz/hydrology/read_me/Popis_kodu_historical.pdf")),
    } == CZECH_ORIGINS


def test_committed_czech_origins_pass_validation() -> None:
    from rivretrieve._internal.providers.cz_chmi.generate_catalogue import build_stations as build_czech_stations
    from rivretrieve._internal.providers.cz_chmi.origins import (
        STATION_CATALOGUE_ORIGINS as CZECH_ORIGINS,
    )

    native_table = read_native_table(Path("src/rivretrieve/_internal/providers/cz_chmi/catalogue/native.parquet"))
    stations = build_czech_stations(native_table)

    assert validate_catalogue_origins(ProviderId("cz_chmi"), CZECH_ORIGINS, native_table, stations) == []


def test_canada_declarations_match_canonical_schema_order_and_values() -> None:
    assert tuple(CANADA_ORIGINS) == tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert {
        "provider_id": Field(NativeColumn("STATION_NUMBER")),
        "station_id": Field(NativeColumn("STATION_NUMBER")),
        "latitude": Field(NativeColumn("geometry.coordinates[1]")),
        "longitude": Field(NativeColumn("geometry.coordinates[0]")),
        "crs": Documented(DocumentedValue("EPSG:4326"), Evidence(CRS_EVIDENCE_URL)),
    } == CANADA_ORIGINS


def test_committed_canada_origins_pass_validation() -> None:
    native_table = read_native_table(CANADA_NATIVE_PATH)
    station_input = native_table.data.select(
        "id",
        "STATION_NUMBER",
        pl.col("geometry.coordinates[1]").alias("LATITUDE"),
        pl.col("geometry.coordinates[0]").alias("LONGITUDE"),
    ).to_dicts()
    stations = build_canada_stations(station_input)

    assert validate_catalogue_origins(ProviderId("ca_eccc"), CANADA_ORIGINS, native_table, stations) == []
    enforce_catalogue_origins(ProviderId("ca_eccc"), CANADA_ORIGINS, native_table, stations)


def test_dws_declarations_match_canonical_schema_order_and_values() -> None:
    from rivretrieve._internal.providers.za_dws.generate_catalogue import CATALOGUE_URL
    from rivretrieve._internal.providers.za_dws.origins import (
        CRS_EVIDENCE_EXPLANATION,
        DMS_SIGN_CONVENTION,
        STATION_CATALOGUE_ORIGINS,
    )

    evidence_url = "https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA1_Limpopo-Olifants_River.pdf"
    assert tuple(STATION_CATALOGUE_ORIGINS) == tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert {
        "provider_id": Field(NativeColumn("Station")),
        "station_id": Field(NativeColumn("Station")),
        "latitude": Field(NativeColumn("Latitude (dd:mm:ss)")),
        "longitude": Field(NativeColumn("Longitude (dd:mm:ss)")),
        "crs": NotPublished(Evidence(evidence_url)),
    } == STATION_CATALOGUE_ORIGINS
    assert CATALOGUE_URL not in str(STATION_CATALOGUE_ORIGINS["crs"])
    assert CRS_EVIDENCE_EXPLANATION == (
        "The cited River PDF's own two-line coordinate header reads Latitude / dd:mm:ss and "
        "Longitude / dd:mm:ss; this names a representation format but never a datum. A "
        "case-insensitive review of all eight River PDFs found zero datum, WGS, ellipsoid, "
        "geodetic, projection, or EPSG occurrences. HyCatalogue.aspx is only a link index with "
        "no prose or coordinate header and is not CRS evidence."
    )
    assert DMS_SIGN_CONVENTION == (
        "DWS publishes unsigned DMS magnitudes with no leading sign, hemisphere marker, or "
        "hemisphere note; the build applies a southern negative latitude sign and an eastern "
        "positive longitude sign that the source does not carry."
    )


def test_committed_dws_origins_and_build_pass_gate() -> None:
    from rivretrieve._internal.providers.za_dws.generate_catalogue import build_catalogue
    from rivretrieve._internal.providers.za_dws.origins import STATION_CATALOGUE_ORIGINS

    native_table = read_native_table(Path("src/rivretrieve/_internal/providers/za_dws/catalogue/native.parquet"))
    catalogue = build_catalogue(native_table, STATION_CATALOGUE_ORIGINS)

    assert (
        validate_catalogue_origins(ProviderId("za_dws"), STATION_CATALOGUE_ORIGINS, native_table, catalogue.stations)
        == []
    )
    enforce_catalogue_origins(ProviderId("za_dws"), STATION_CATALOGUE_ORIGINS, native_table, catalogue.stations)


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
    declarations: dict[str, object] = dict(LT_STATION_ORIGINS)
    del declarations["longitude"]
    native_table, stations = _native_and_stations()

    with pytest.raises(
        FatalContractError,
        match=r"lt_lhmt\.longitude: canonical column has no origin declaration",
    ) as exc_info:
        enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native_table, stations)

    _assert_single_issue(exc_info, "catalogue_origin.undeclared_column", "longitude")


def test_origin_gate_rejects_absent_native_column() -> None:
    declarations: dict[str, object] = dict(LT_STATION_ORIGINS)
    declarations["latitude"] = Field(NativeColumn("absent_column"))
    native_table, stations = _native_and_stations()

    with pytest.raises(
        FatalContractError,
        match=r"lt_lhmt\.latitude: native column 'absent_column' does not exist",
    ) as exc_info:
        enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native_table, stations)

    _assert_single_issue(exc_info, "catalogue_origin.absent_native_column", "latitude")


def test_origin_gate_rejects_unpropagated_native_value_on_aligned_row() -> None:
    declarations: dict[str, object] = dict(LT_STATION_ORIGINS)
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
    declarations: dict[str, object] = dict(LT_STATION_ORIGINS)
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
    declarations: dict[str, object] = dict(LT_STATION_ORIGINS)
    declarations["crs"] = {"not_published": True}
    native_table, stations = _native_and_stations()

    with pytest.raises(
        FatalContractError,
        match=r"lt_lhmt\.crs: NotPublished origin must carry Evidence",
    ) as exc_info:
        enforce_catalogue_origins(ProviderId("lt_lhmt"), declarations, native_table, stations)

    _assert_single_issue(exc_info, "catalogue_origin.missing_evidence", "crs")


def test_origin_gate_rejects_documented_declaration_with_absent_evidence() -> None:
    declarations: dict[str, object] = dict(LT_STATION_ORIGINS)
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
    declarations: dict[str, object] = dict(LT_STATION_ORIGINS)
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

    assert validate_catalogue_origins(ProviderId("lt_lhmt"), LT_STATION_ORIGINS, native_table, stations) == []


def test_committed_swiss_origins_pass_validation() -> None:
    from rivretrieve._internal.providers.ch_foen.generate_catalogue import build_stations
    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS

    native_table = read_native_table(Path("src/rivretrieve/_internal/providers/ch_foen/catalogue/native.parquet"))

    assert (
        validate_catalogue_origins(
            ProviderId("ch_foen"), STATION_CATALOGUE_ORIGINS, native_table, build_stations(native_table)
        )
        == []
    )
