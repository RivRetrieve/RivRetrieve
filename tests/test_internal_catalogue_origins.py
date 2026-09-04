import ast
import hashlib
import typing
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
    CatalogueOrigin,
    Documented,
    DocumentedValue,
    Evidence,
    Field,
    FieldConversion,
    FloatConversion,
    IdentityConversion,
    NativeColumn,
    NotPublished,
    StructMemberConversion,
    Withheld,
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
from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import (
    build_hydro_stations,
    build_temp_stations,
)
from rivretrieve._internal.providers.fr_hubeau.origins import (
    CRS_EVIDENCE_URL as FRANCE_CRS_EVIDENCE_URL,
)
from rivretrieve._internal.providers.fr_hubeau.origins import (
    HYDROMETRY_STATION_CATALOGUE_ORIGINS as FRANCE_HYDROMETRY_ORIGINS,
)
from rivretrieve._internal.providers.fr_hubeau.origins import (
    TEMPERATURE_CRS_EVIDENCE_URL,
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
from rivretrieve._internal.providers.usgs_nwis.origins import (
    STATION_CATALOGUE_ORIGINS as USGS_STATION_CATALOGUE_ORIGINS,
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
CATALOGUE_ORIGINS_ADR_PATH = REPOSITORY_ROOT / "docs/adr/0012-a-catalogue-column-declares-its-origin.md"
CATALOGUE_PROVENANCE_PATH = REPOSITORY_ROOT / "docs/catalogue-provenance.md"
CONTEXT_PATH = REPOSITORY_ROOT / "CONTEXT.md"


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


def test_shared_origin_gate_has_no_provider_specific_conversion_vocabulary() -> None:
    source = CATALOGUE_ORIGINS_MODULE_PATH.read_text(encoding="utf-8")
    forbidden = {
        "JAPAN_COMBINED_DMS",
        "DWS_UNSIGNED_DMS",
        "USGS_DATUM_TO_CRS",
        "FRANCE_PROJECTION_31",
        "_JAPAN_DMS",
        "_USGS_DATUM_TO_CRS",
        "code_projection",
        "dec_coord_datum_cd",
    }

    assert all(token not in source for token in forbidden)


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


def test_catalogue_origin_union_contains_exactly_the_implemented_forms() -> None:
    assert typing.get_args(CatalogueOrigin.__value__) == (Field, Authored, NotPublished, Documented, Withheld)


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


def test_origin_gate_enrols_exactly_the_twelve_in_scope_providers() -> None:
    expected = frozenset(
        {
            ProviderId("ba_fhmzbih"),
            ProviderId("ca_eccc"),
            ProviderId("ch_foen"),
            ProviderId("cz_chmi"),
            ProviderId("fr_hubeau"),
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
    assert registered - ORIGIN_GATE_ENROLLED_PROVIDERS == frozenset({ProviderId("br_ana")})


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def test_origin_scope_documentation_contract_pins_the_constant_docstring() -> None:
    module = ast.parse(CATALOGUE_ORIGINS_MODULE_PATH.read_text())
    assignment_index = next(
        (
            index
            for index, statement in enumerate(module.body)
            if isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "ORIGIN_GATE_ENROLLED_PROVIDERS"
                for target in statement.targets
            )
        ),
        None,
    )
    assert assignment_index is not None, "ORIGIN_GATE_ENROLLED_PROVIDERS assignment is missing"
    assert assignment_index + 1 < len(module.body), "origin gate scope docstring is missing after the assignment"
    docstring_statement = module.body[assignment_index + 1]
    assert isinstance(docstring_statement, ast.Expr) and isinstance(docstring_statement.value, ast.Constant), (
        "origin gate scope docstring is not immediately after the assignment"
    )
    assert docstring_statement.value.value == (
        "The twelve providers with complete audited catalogue origin declarations. br_ana remains explicitly deferred."
    ), "origin gate scope docstring has drifted"


def test_origin_scope_documentation_contract_pins_adr_ruling() -> None:
    adr = _collapse_whitespace(CATALOGUE_ORIGINS_ADR_PATH.read_text())
    scoped_state = _collapse_whitespace(
        "There is no half-landed state within `ORIGIN_GATE_ENROLLED_PROVIDERS`: every provider in the enrolled "
        "set is completely declared, while the explicitly deferred `br_ana` remains outside that set."
    )

    assert "## Consequence: the build stays red until every enrolled provider is declared" in adr, (
        "ADR consequence heading does not scope the build-red rule to enrolled providers"
    )
    assert "2026-08-03" in adr, "ADR is missing the dated human scope ruling"
    assert "`br_ana`" in adr, "ADR is missing the deferred br_ana provider id"
    assert "`no_nve`" in adr, "ADR is missing the historical no_nve provider id"
    assert "deferred `br_ana` and `no_nve` to separate work" in adr, (
        "ADR does not preserve the historical deferral boundary"
    )
    assert "`no_nve` subsequently gained" in adr, "ADR does not record Norway's later enrolment"
    assert scoped_state in adr, "ADR is missing the exact scoped half-landed-state contract"
    assert "ORIGIN_GATE_ENROLLED_PROVIDERS" in adr, "ADR is missing the explicit enrolment boundary name"
    assert "26,231" in adr, "ADR lost the USGS defect-history station count"
    assert "52,145" in adr, "ADR lost the Brazil defect-history row count"
    assert "4,889" in adr, "ADR lost the Norway defect-history station count"

    maintenance = _collapse_whitespace(CATALOGUE_PROVENANCE_PATH.read_text())
    assert "`ORIGIN_GATE_ENROLLED_PROVIDERS`" in maintenance
    assert "ADR 0012" in maintenance
    assert "`br_ana` remains outside it" in maintenance
    assert "`no_nve` is enrolled" in maintenance


def test_origin_scope_documentation_contract_pins_glossary_boundary() -> None:
    glossary = _collapse_whitespace(CONTEXT_PATH.read_text())
    origin_scope = _collapse_whitespace(
        "Every canonical column carries one for every provider in `ORIGIN_GATE_ENROLLED_PROVIDERS`; an unenrolled "
        "provider is explicitly outside origin certification rather than treated as compliant."
    )
    best_effort_scope = _collapse_whitespace(
        "In the catalogue this is enforced rather than intended: a best-effort column still carries an [[origin]] "
        "for every [[provider]] in `ORIGIN_GATE_ENROLLED_PROVIDERS`, so being empty is a declared claim and not "
        "permission to leave it unfilled."
    )

    assert origin_scope in glossary, "Origin glossary entry is missing the explicit enrolment boundary"
    assert best_effort_scope in glossary, "Best-effort glossary entry is missing the explicit enrolment boundary"


def test_poland_declarations_match_canonical_schema_order_and_values() -> None:
    from rivretrieve._internal.providers.pl_imgw.origins import STATION_CATALOGUE_ORIGINS

    assert tuple(STATION_CATALOGUE_ORIGINS) == tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert {
        "provider_id": Authored(AuthoredValue("pl_imgw")),
        "station_id": Field(NativeColumn("gauge_id")),
        "latitude": Field(NativeColumn("latitude"), FloatConversion()),
        "longitude": Field(NativeColumn("longitude"), FloatConversion()),
        "crs": Withheld(),
    } == STATION_CATALOGUE_ORIGINS


def test_committed_poland_origins_pass_validation_and_enforcement() -> None:
    from rivretrieve._internal.providers.pl_imgw.generate_catalogue import build_stations
    from rivretrieve._internal.providers.pl_imgw.origins import STATION_CATALOGUE_ORIGINS

    native = read_native_table(Path("src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet"))
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


def test_japan_declarations_match_canonical_schema_order_and_values() -> None:
    from rivretrieve._internal.providers.jp_mlit.origins import STATION_CATALOGUE_ORIGINS

    assert tuple(STATION_CATALOGUE_ORIGINS) == tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert {
        "provider_id": Authored(AuthoredValue("jp_mlit")),
        "station_id": Field(NativeColumn("観測所記号")),
        "latitude": Field(NativeColumn("世界測地系"), WorldGeodeticDmsConversion()),
        "longitude": Field(NativeColumn("世界測地系"), WorldGeodeticDmsConversion()),
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


def test_france_declarations_match_schema_order_and_endpoint_values() -> None:
    expected_hydrometry = {
        "provider_id": Authored(AuthoredValue("fr_hubeau")),
        "station_id": Field(NativeColumn("code_station")),
        "latitude": Field(NativeColumn("latitude_station"), HydrometryCoordinateConversion()),
        "longitude": Field(NativeColumn("longitude_station"), HydrometryCoordinateConversion()),
        "crs": Documented(DocumentedValue("EPSG:4326"), Evidence(FRANCE_CRS_EVIDENCE_URL)),
    }
    expected_temperature = {
        "provider_id": Authored(AuthoredValue("fr_hubeau")),
        "station_id": Field(NativeColumn("code_station")),
        "latitude": Field(NativeColumn("latitude"), FloatConversion()),
        "longitude": Field(NativeColumn("longitude"), FloatConversion()),
        "crs": Documented(DocumentedValue("EPSG:4326"), Evidence(TEMPERATURE_CRS_EVIDENCE_URL)),
    }
    schema_order = tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert tuple(FRANCE_HYDROMETRY_ORIGINS) == schema_order
    assert tuple(TEMPERATURE_STATION_CATALOGUE_ORIGINS) == schema_order
    assert expected_hydrometry == FRANCE_HYDROMETRY_ORIGINS
    assert expected_temperature == TEMPERATURE_STATION_CATALOGUE_ORIGINS
    assert TEMPERATURE_CRS_EVIDENCE_URL != FRANCE_CRS_EVIDENCE_URL


def test_france_endpoint_declarations_validate_complete_native_partitions() -> None:
    native = read_native_table(
        Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet"
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


def test_bosnia_declarations_match_canonical_schema_order_and_values() -> None:
    from rivretrieve._internal.providers.ba_fhmzbih.origins import STATION_CATALOGUE_ORIGINS

    assert tuple(STATION_CATALOGUE_ORIGINS) == tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert {
        "provider_id": Authored(AuthoredValue("ba_fhmzbih")),
        "station_id": Field(NativeColumn("metadata_station_no")),
        "latitude": Field(NativeColumn("metadata_station_latitude"), FloatConversion()),
        "longitude": Field(NativeColumn("metadata_station_longitude"), FloatConversion()),
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


@pytest.mark.parametrize("provider_id", [ProviderId("br_ana"), ProviderId("other_provider")])
def test_enforcing_gate_rejects_unenrolled_provider_before_evaluation(provider_id: ProviderId) -> None:
    with pytest.raises(FatalContractError) as exc_info:
        enforce_catalogue_origins(provider_id, {}, None, None)  # ty: ignore[invalid-argument-type]

    assert str(exc_info.value) == f"{provider_id}: provider is not enrolled in catalogue origin gate"


def test_lithuania_declarations_match_canonical_schema_order_and_values() -> None:
    assert tuple(LT_STATION_ORIGINS) == tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert {
        "provider_id": Authored(AuthoredValue("lt_lhmt")),
        "station_id": Field(NativeColumn("code")),
        "latitude": Field(NativeColumn("coordinates"), StructMemberConversion()),
        "longitude": Field(NativeColumn("coordinates"), StructMemberConversion()),
        "crs": Documented(DocumentedValue("EPSG:4326"), Evidence("https://api.meteo.lt/")),
    } == LT_STATION_ORIGINS


def test_usgs_declarations_match_canonical_schema_order_and_values() -> None:
    assert tuple(USGS_STATION_CATALOGUE_ORIGINS) == tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
    assert {
        "provider_id": Authored(AuthoredValue("usgs_nwis")),
        "station_id": Field(NativeColumn("site_no")),
        "latitude": Field(NativeColumn("dec_lat_va"), FloatConversion()),
        "longitude": Field(NativeColumn("dec_long_va"), FloatConversion()),
        "crs": Field(NativeColumn("dec_coord_datum_cd"), DatumToCrsConversion()),
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
        "provider_id": Authored(AuthoredValue("th_thaiwater")),
        "station_id": Field(NativeColumn("station.id")),
        "latitude": Field(NativeColumn("station.tele_station_lat"), FloatConversion()),
        "longitude": Field(NativeColumn("station.tele_station_long"), FloatConversion()),
        "crs": NotPublished(Evidence(THAI_CRS_EVIDENCE_URL)),
    } == THAI_STATION_ORIGINS
    assert len(THAI_CRS_EVIDENCE_URL) == 104
    assert capture.count(THAI_CRS_EVIDENCE_URL) == 2
    assert parser.canonical_urls == [THAI_CRS_EVIDENCE_URL]


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
        "provider_id": Authored(AuthoredValue("cz_chmi")),
        "station_id": Field(NativeColumn("objID")),
        "latitude": Field(NativeColumn("GEOGR1"), FloatConversion()),
        "longitude": Field(NativeColumn("GEOGR2"), FloatConversion()),
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
        "provider_id": Authored(AuthoredValue("ca_eccc")),
        "station_id": Field(NativeColumn("STATION_NUMBER")),
        "latitude": Field(NativeColumn("geometry.coordinates[1]"), FloatConversion()),
        "longitude": Field(NativeColumn("geometry.coordinates[0]"), FloatConversion()),
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
        "provider_id": Authored(AuthoredValue("za_dws")),
        "station_id": Field(NativeColumn("Station")),
        "latitude": Field(NativeColumn("Latitude (dd:mm:ss)"), UnsignedDmsConversion()),
        "longitude": Field(NativeColumn("Longitude (dd:mm:ss)"), UnsignedDmsConversion()),
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
    native_table, stations = _native_and_stations()
    first_station_id = stations["station_id"].item(0)
    broken_stations = stations.with_columns(
        pl.when(pl.col("station_id") == first_station_id).then(None).otherwise(pl.col("latitude")).alias("latitude")
    )

    with pytest.raises(
        FatalContractError,
        match=r"lt_lhmt\.latitude: canonical value is null where native column 'coordinates' has a value",
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

    assert exc_info.value.issues[0].code == "catalogue_origin.unresolvable_alignment_key"
    assert exc_info.value.issues[0].details == {"canonical_column": "station_id"}
    assert exc_info.value.issues[1].code == "catalogue_origin.not_published_marker_mismatch"


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
