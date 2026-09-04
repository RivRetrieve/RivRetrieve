"""catalogue origin certification : EnrolledProvider × CommittedNative × Origins × Receipts → CertifiedBuilds."""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import socket
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import ModuleType
from urllib.parse import urlparse

import polars as pl
import pytest
import requests

from rivretrieve._internal import discovery, transport
from rivretrieve._internal.catalogue_origins import (
    ORIGIN_GATE_ENROLLED_PROVIDERS,
    CatalogueOrigin,
    Documented,
    DocumentedValue,
    Evidence,
    Field,
    NativeColumn,
    NotPublished,
    Withheld,
    enforce_catalogue_origins,
    validate_catalogue_origins,
)
from rivretrieve._internal.catalogues.native import NativeTable, read_native_table
from rivretrieve._internal.catalogues.schemas import STATION_CATALOG_SCHEMA, StationCatalog
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId

ROOT = Path(__file__).parents[1]
RECEIPTS_PATH = ROOT / "tests/test_data/catalogue_origin_evidence_receipts.json"
PROVIDER_NOTES = ROOT / "docs/provider_ports"
SCHEMA_COLUMNS = tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
DEFERRED_PROVIDERS = frozenset({ProviderId("br_ana")})


@dataclass(frozen=True, slots=True)
class DeclarationCase:
    identity: str
    declarations: Mapping[str, CatalogueOrigin]
    native_partition: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderAdapter:
    provider_id: ProviderId
    native_path: Path
    generator: ModuleType
    main: Callable[[list[str] | None], int]
    build: Callable[[NativeTable, Mapping[str, object]], object]
    cases: tuple[DeclarationCase, ...]

    def origins_argument(
        self, replacement: Mapping[str, Mapping[str, CatalogueOrigin]] | None = None
    ) -> Mapping[str, object]:
        maps: dict[str, Mapping[str, CatalogueOrigin]] = {case.identity: dict(case.declarations) for case in self.cases}
        if replacement is not None:
            maps.update(replacement)
        if self.provider_id == ProviderId("fr_hubeau"):
            return maps
        return maps["stations"]


def _module(provider: str, leaf: str) -> ModuleType:
    return importlib.import_module(f"rivretrieve._internal.providers.{provider}.{leaf}")


def _adapter(provider: str, cases: tuple[DeclarationCase, ...]) -> ProviderAdapter:
    generator = _module(provider, "generate_catalogue")
    module_path = generator.__file__
    assert module_path is not None
    native_path = Path(module_path).parent / "catalogue/native.parquet"
    return ProviderAdapter(
        provider_id=ProviderId(provider),
        native_path=native_path,
        generator=generator,
        main=generator.main,
        build=generator.build_catalogue,
        cases=cases,
    )


def _stations_case(provider: str) -> tuple[DeclarationCase, ...]:
    origins = _module(provider, "origins").STATION_CATALOGUE_ORIGINS
    return (DeclarationCase("stations", origins),)


_france_origins = _module("fr_hubeau", "origins")
ADAPTERS = {
    ProviderId(provider): _adapter(provider, _stations_case(provider))
    for provider in (
        "ba_fhmzbih",
        "ca_eccc",
        "ch_foen",
        "cz_chmi",
        "jp_mlit",
        "lt_lhmt",
        "no_nve",
        "pl_imgw",
        "th_thaiwater",
        "usgs_nwis",
        "za_dws",
    )
}
ADAPTERS[ProviderId("fr_hubeau")] = _adapter(
    "fr_hubeau",
    (
        DeclarationCase(
            "hydrometrie/referentiel/stations",
            _france_origins.HYDROMETRY_STATION_CATALOGUE_ORIGINS,
            "hydrometrie/referentiel/stations",
        ),
        DeclarationCase(
            "temperature/station",
            _france_origins.TEMPERATURE_STATION_CATALOGUE_ORIGINS,
            "temperature/station",
        ),
    ),
)


def _all_cases() -> list[tuple[ProviderAdapter, DeclarationCase]]:
    return [(adapter, case) for adapter in ADAPTERS.values() for case in adapter.cases]


CASES = _all_cases()


def _build(adapter: ProviderAdapter, native: NativeTable | None = None, origins: Mapping[str, object] | None = None):
    table = read_native_table(adapter.native_path) if native is None else native
    return adapter.build(table, adapter.origins_argument() if origins is None else origins)


def _case_frames(
    adapter: ProviderAdapter, case: DeclarationCase, native: NativeTable, stations: StationCatalog
) -> tuple[NativeTable, StationCatalog]:
    case_native = native
    if case.native_partition is not None:
        case_native = NativeTable(native.data.filter(pl.col("source_endpoint") == case.native_partition))
    station_origin = case.declarations["station_id"]
    assert isinstance(station_origin, Field)
    station_ids = case_native.data[str(station_origin.native_column)].cast(pl.String).unique()
    return case_native, stations.filter(pl.col("station_id").is_in(station_ids.implode()))


def _expected_declarations() -> dict[tuple[ProviderId, str], Mapping[str, CatalogueOrigin]]:
    def field(name: str) -> Field:
        return Field(NativeColumn(name))

    def unpublished(url: str) -> NotPublished:
        return NotPublished(Evidence(url))

    def documented(url: str) -> Documented:
        return Documented(DocumentedValue("EPSG:4326"), Evidence(url))

    def withheld() -> Withheld:
        return Withheld()

    return {
        (ProviderId("ba_fhmzbih"), "stations"): {
            "provider_id": field("metadata_station_no"),
            "station_id": field("metadata_station_no"),
            "latitude": field("metadata_station_latitude"),
            "longitude": field("metadata_station_longitude"),
            "crs": unpublished("https://vodostaji.voda.ba/data/internet/stations/stations.json"),
        },
        (ProviderId("ca_eccc"), "stations"): {
            "provider_id": field("STATION_NUMBER"),
            "station_id": field("STATION_NUMBER"),
            "latitude": field("geometry.coordinates[1]"),
            "longitude": field("geometry.coordinates[0]"),
            "crs": documented("https://api.weather.gc.ca/collections/hydrometric-stations?f=json"),
        },
        (ProviderId("ch_foen"), "stations"): {
            "provider_id": field("name"),
            "station_id": field("name"),
            "latitude": field("details.lat"),
            "longitude": field("details.lon"),
            "crs": unpublished("https://api.existenz.ch/#hydro"),
        },
        (ProviderId("cz_chmi"), "stations"): {
            "provider_id": field("objID"),
            "station_id": field("objID"),
            "latitude": field("GEOGR1"),
            "longitude": field("GEOGR2"),
            "crs": unpublished("https://opendata.chmi.cz/hydrology/read_me/Popis_kodu_historical.pdf"),
        },
        (ProviderId("fr_hubeau"), "hydrometrie/referentiel/stations"): {
            "provider_id": field("code_station"),
            "station_id": field("code_station"),
            "latitude": field("latitude_station"),
            "longitude": field("longitude_station"),
            "crs": documented(
                "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?code_station=1011000101&format=geojson"
            ),
        },
        (ProviderId("fr_hubeau"), "temperature/station"): {
            "provider_id": field("code_station"),
            "station_id": field("code_station"),
            "latitude": field("latitude"),
            "longitude": field("longitude"),
            "crs": documented("https://hubeau.eaufrance.fr/api/v1/temperature/station?size=2000&format=json"),
        },
        (ProviderId("jp_mlit"), "stations"): {
            "provider_id": field("観測所記号"),
            "station_id": field("観測所記号"),
            "latitude": field("世界測地系"),
            "longitude": field("世界測地系"),
            "crs": unpublished("http://www1.river.go.jp/cgi-bin/SiteInfoDetail.exe?ID=301011281104010"),
        },
        (ProviderId("lt_lhmt"), "stations"): {
            "provider_id": field("code"),
            "station_id": field("code"),
            "latitude": field("coordinates"),
            "longitude": field("coordinates"),
            "crs": documented("https://api.meteo.lt/"),
        },
        (ProviderId("no_nve"), "stations"): {
            "provider_id": field("stationId"),
            "station_id": field("stationId"),
            "latitude": field("latitude"),
            "longitude": field("longitude"),
            "crs": unpublished("https://hydapi.nve.no/swagger/v1/swagger.json"),
        },
        (ProviderId("pl_imgw"), "stations"): {
            "provider_id": field("gauge_id"),
            "station_id": field("gauge_id"),
            "latitude": field("latitude"),
            "longitude": field("longitude"),
            "crs": withheld(),
        },
        (ProviderId("th_thaiwater"), "stations"): {
            "provider_id": field("station.id"),
            "station_id": field("station.id"),
            "latitude": field("station.tele_station_lat"),
            "longitude": field("station.tele_station_long"),
            "crs": unpublished(
                "https://standard.thaiwater.net/docs/การจัดทำมาตรฐานน้ำ-ระยะ/ข้อมูลอ้างอิง-ข้อมูลอ้า/การระบุพิกัดตำแหน่ง/"
            ),
        },
        (ProviderId("usgs_nwis"), "stations"): {
            "provider_id": field("site_no"),
            "station_id": field("site_no"),
            "latitude": field("dec_lat_va"),
            "longitude": field("dec_long_va"),
            "crs": field("dec_coord_datum_cd"),
        },
        (ProviderId("za_dws"), "stations"): {
            "provider_id": field("Station"),
            "station_id": field("Station"),
            "latitude": field("Latitude (dd:mm:ss)"),
            "longitude": field("Longitude (dd:mm:ss)"),
            "crs": unpublished(
                "https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA1_Limpopo-Olifants_River.pdf"
            ),
        },
    }


def test_adapter_discovery_is_exact_and_deferred_providers_remain_building() -> None:
    discovery._ensure_default_providers_registered()
    registered = frozenset(ProviderId(value) for value in discovery._registry.list_provider_ids())

    assert frozenset(ADAPTERS) == ORIGIN_GATE_ENROLLED_PROVIDERS
    assert registered - frozenset(ADAPTERS) == DEFERRED_PROVIDERS, (
        "br_ana must remain registered and BUILDING until it has a committed full native input"
    )
    assert not (DEFERRED_PROVIDERS & ORIGIN_GATE_ENROLLED_PROVIDERS)
    assert all(adapter.native_path.is_file() for adapter in ADAPTERS.values())
    assert all(callable(adapter.main) and callable(adapter.build) for adapter in ADAPTERS.values())
    assert {
        (adapter.provider_id, case.identity): case.declarations for adapter, case in CASES
    } == _expected_declarations()
    assert len(CASES) == 13
    assert all(tuple(case.declarations) == SCHEMA_COLUMNS for _, case in CASES)


@pytest.mark.parametrize(
    ("adapter", "case"),
    CASES,
    ids=[f"{adapter.provider_id}-{case.identity}" for adapter, case in CASES],
)
def test_committed_declaration_case_passes_real_build_and_origin_gate(
    adapter: ProviderAdapter, case: DeclarationCase
) -> None:
    native = read_native_table(adapter.native_path)
    catalogue = _build(adapter, native)
    case_native, stations = _case_frames(adapter, case, native, catalogue.stations)

    assert not case_native.data.is_empty()
    assert not stations.is_empty()
    assert validate_catalogue_origins(adapter.provider_id, case.declarations, case_native, stations) == []
    enforce_catalogue_origins(adapter.provider_id, case.declarations, case_native, stations)


REMOVAL_CASES = [(adapter, case, column) for adapter, case in CASES for column in SCHEMA_COLUMNS]


@pytest.mark.parametrize(
    ("adapter", "case", "column"),
    REMOVAL_CASES,
    ids=[f"{adapter.provider_id}-{case.identity}-{column}" for adapter, case, column in REMOVAL_CASES],
)
def test_real_build_rejects_each_removed_declaration(
    adapter: ProviderAdapter, case: DeclarationCase, column: str
) -> None:
    declarations = dict(case.declarations)
    del declarations[column]
    origins = adapter.origins_argument({case.identity: declarations})

    with pytest.raises(FatalContractError) as caught:
        _build(adapter, origins=origins)

    undeclared_message = f"{adapter.provider_id}.{column}: canonical column has no origin declaration"
    issues = caught.value.issues
    if column == "station_id":
        alignment_message = (
            f"{adapter.provider_id}.station_id: rule (c) could not be evaluated because the station_id "
            "alignment key is unresolvable"
        )
        assert str(caught.value) == alignment_message
        assert len(issues) == 2
        assert [issue.code for issue in issues] == [
            "catalogue_origin.unresolvable_alignment_key",
            "catalogue_origin.undeclared_column",
        ]
        assert [issue.message for issue in issues] == [alignment_message, undeclared_message]
    else:
        assert str(caught.value) == undeclared_message
        assert len(issues) == 1
        assert issues[0].code == "catalogue_origin.undeclared_column"
        assert issues[0].message == undeclared_message
    assert all(issue.provider_id == adapter.provider_id for issue in issues)
    assert all(issue.details == {"canonical_column": column} for issue in issues)


def _receipts() -> list[dict[str, object]]:
    value = json.loads(RECEIPTS_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, list)
    return value


RECEIPT_KEYS = {
    "provider_id",
    "declaration_map",
    "canonical_column",
    "evidence_url",
    "requested_url",
    "final_url",
    "http_status",
    "status_record",
    "retrieved_at",
    "sha256",
    "digest_method",
    "capture_path",
    "attestation_identity",
}


def _not_published_keys() -> set[tuple[str, str, str, str]]:
    return {
        (str(adapter.provider_id), case.identity, column, str(origin.evidence))
        for adapter, case in CASES
        for column, origin in case.declarations.items()
        if isinstance(origin, NotPublished)
    }


def test_receipt_discovery_schema_order_urls_and_statuses_fail_closed() -> None:
    receipts = _receipts()
    keys = {
        (row["provider_id"], row["declaration_map"], row["canonical_column"], row["evidence_url"]) for row in receipts
    }

    def sort_key(row: dict[str, object]) -> tuple[object, object, object, object]:
        return (row["provider_id"], row["declaration_map"], row["canonical_column"], row["evidence_url"])

    retired_poland_geometry_evidence = {("pl_imgw", "stations", "crs", "https://danepubliczne.imgw.pl/pl/apiinfo")}
    assert keys == _not_published_keys() | retired_poland_geometry_evidence
    assert receipts == sorted(receipts, key=sort_key)
    assert all(set(row) == RECEIPT_KEYS for row in receipts)
    assert all(isinstance(row["attestation_identity"], str) and row["attestation_identity"] for row in receipts)
    for row in receipts:
        for name in ("evidence_url", "requested_url"):
            parsed = urlparse(str(row[name]))
            assert parsed.scheme in {"http", "https"} and parsed.netloc
        if row["final_url"] is not None:
            parsed = urlparse(str(row["final_url"]))
            assert parsed.scheme in {"http", "https"} and parsed.netloc
        if row["status_record"] == "recorded":
            assert isinstance(row["http_status"], int) and 200 <= row["http_status"] < 300
        else:
            assert row["status_record"] == "not_recorded"
            assert row["http_status"] is None
    unrecorded = {row["provider_id"] for row in receipts if row["status_record"] == "not_recorded"}
    assert unrecorded == {"ba_fhmzbih", "pl_imgw", "th_thaiwater"}
    local = {row["provider_id"] for row in receipts if row["capture_path"] is not None}
    assert local == {"ba_fhmzbih", "ch_foen", "cz_chmi", "jp_mlit", "no_nve", "pl_imgw", "th_thaiwater"}
    assert [row["provider_id"] for row in receipts if row["capture_path"] is None] == ["za_dws"]


@pytest.mark.parametrize("receipt", _receipts(), ids=lambda row: str(row["provider_id"]))
def test_receipt_capture_digest(receipt: dict[str, object]) -> None:
    provider_id = str(receipt["provider_id"])
    notes_path = PROVIDER_NOTES / f"{provider_id}.md"
    assert notes_path.is_file()
    assert f"provider_ports/{provider_id}.md" in (ROOT / "docs/README.md").read_text(encoding="utf-8")

    capture_path = receipt["capture_path"]
    if capture_path is None:
        assert receipt["provider_id"] == "za_dws"
        return
    path = ROOT / str(capture_path)
    assert path.is_relative_to(ROOT / "tests/test_data")
    assert path.is_file()
    payload = path.read_bytes()
    if receipt["digest_method"] == "raw":
        digest_payload = payload
    else:
        assert receipt["digest_method"] == (
            'json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")'
        )
        digest_payload = json.dumps(
            json.loads(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    assert hashlib.sha256(digest_payload).hexdigest() == receipt["sha256"]


def test_receipt_provider_specific_url_bindings_and_attested_exceptions() -> None:
    rows = {row["provider_id"]: row for row in _receipts()}
    assert rows["ch_foen"]["requested_url"] == rows["ch_foen"]["final_url"] == "https://api.existenz.ch/"
    assert rows["ch_foen"]["evidence_url"] == "https://api.existenz.ch/#hydro"
    assert rows["cz_chmi"]["evidence_url"] == rows["cz_chmi"]["requested_url"] == rows["cz_chmi"]["final_url"]
    assert rows["jp_mlit"]["evidence_url"] == rows["jp_mlit"]["requested_url"] == rows["jp_mlit"]["final_url"]
    assert rows["th_thaiwater"]["evidence_url"] == rows["th_thaiwater"]["final_url"]
    dws = rows["za_dws"]
    assert dws["evidence_url"] != dws["requested_url"] == dws["final_url"]
    assert "web.archive.org/web/20251122081546id_/" in str(dws["requested_url"])

    japan = (PROVIDER_NOTES / "jp_mlit.md").read_text(encoding="utf-8")
    assert "2026-08-03T12:31:42Z" in japan
    assert "HTTP 403" in japan
    assert "77-byte" in japan
    assert "non-refetchable" in japan
    swiss = (PROVIDER_NOTES / "ch_foen.md").read_text(encoding="utf-8")
    assert "fragment" in swiss and "not sent" in swiss and "no redirect" in swiss


def test_committed_tests_and_receipts_never_depend_on_supply_tree() -> None:
    needle = b"plan" + b"ning/"
    candidates = [RECEIPTS_PATH, *PROVIDER_NOTES.glob("*.md"), *ROOT.joinpath("tests").rglob("*.py")]
    assert all(needle not in path.read_bytes() for path in candidates)


EXPECTED_CRS_COUNTS = {
    (ProviderId("ba_fhmzbih"), "stations"): (60, "unknown"),
    (ProviderId("ca_eccc"), "stations"): (8_057, "EPSG:4326"),
    (ProviderId("ch_foen"), "stations"): (246, "unknown"),
    (ProviderId("cz_chmi"), "stations"): (831, "unknown"),
    (ProviderId("fr_hubeau"), "hydrometrie/referentiel/stations"): (6_454, "EPSG:4326"),
    (ProviderId("fr_hubeau"), "temperature/station"): (869, "EPSG:4326"),
    (ProviderId("jp_mlit"), "stations"): (1_023, "unknown"),
    (ProviderId("lt_lhmt"), "stations"): (97, "EPSG:4326"),
    (ProviderId("no_nve"), "stations"): (4_902, "unknown"),
    (ProviderId("pl_imgw"), "stations"): (1_301, "unknown"),
    (ProviderId("th_thaiwater"), "stations"): (825, "unknown"),
    (ProviderId("za_dws"), "stations"): (2_905, "unknown"),
}


@pytest.mark.parametrize(
    ("adapter", "case"), CASES, ids=[f"{adapter.provider_id}-{case.identity}" for adapter, case in CASES]
)
def test_real_build_crs_semantics_are_complete_and_reviewed(adapter: ProviderAdapter, case: DeclarationCase) -> None:
    native = read_native_table(adapter.native_path)
    catalogue = _build(adapter, native)
    case_native, stations = _case_frames(adapter, case, native, catalogue.stations)
    origin = case.declarations["crs"]

    assert not case_native.data.is_empty() and not stations.is_empty()
    assert stations["crs"].null_count() == 0
    if isinstance(origin, NotPublished):
        expected_count, expected_value = EXPECTED_CRS_COUNTS[(adapter.provider_id, case.identity)]
        assert stations.height == expected_count
        assert stations["crs"].unique().to_list() == [expected_value]
        assert any(
            row["provider_id"] == adapter.provider_id
            and row["declaration_map"] == case.identity
            and row["evidence_url"] == origin.evidence
            for row in _receipts()
        )
    elif isinstance(origin, Documented):
        expected_count, expected_value = EXPECTED_CRS_COUNTS[(adapter.provider_id, case.identity)]
        assert stations.height == expected_count
        assert expected_value == origin.value
        assert stations["crs"].unique().to_list() == [origin.value]
        assert "unknown" not in stations["crs"].unique().to_list()
    elif isinstance(origin, Withheld):
        assert adapter.provider_id == ProviderId("pl_imgw")
        assert origin.reason == "acquisition_not_established"
        assert stations["crs"].unique().to_list() == ["unknown"]
    else:
        assert adapter.provider_id == ProviderId("usgs_nwis")
        assert isinstance(origin, Field)
        assert str(origin.native_column) == "dec_coord_datum_cd"


def test_not_published_and_documented_count_totals_are_pinned() -> None:
    assert sum(count for (_, _), (count, value) in EXPECTED_CRS_COUNTS.items() if value == "unknown") == 12_093
    assert 6_454 + 869 == 7_323


def test_japan_accepted_receipt_build_and_dws_historical_review_are_honest() -> None:
    capture = (ROOT / "tests/test_data/jp_mlit_site_info_detail_301011281104010.html").read_bytes()
    assert len(capture) == 3_208
    assert hashlib.sha256(capture).hexdigest() == "81e7269886397975867bf556c8d5b6659bd5f8d7318c4cf062cd0f47419418f9"
    assert "世界測地系".encode("euc_jp") in capture
    japan = ADAPTERS[ProviderId("jp_mlit")]
    assert _build(japan).stations["crs"].unique().to_list() == ["unknown"]

    dws_origins = _module("za_dws", "origins")
    assert dws_origins.CRS_EVIDENCE_EXPLANATION == (
        "The cited River PDF's own two-line coordinate header reads Latitude / dd:mm:ss and "
        "Longitude / dd:mm:ss; this names a representation format but never a datum. A "
        "case-insensitive review of all eight River PDFs found zero datum, WGS, ellipsoid, "
        "geodetic, projection, or EPSG occurrences. HyCatalogue.aspx is only a link index with "
        "no prose or coordinate header and is not CRS evidence."
    )


def test_usgs_committed_datum_carrier_maps_exactly_to_reviewed_crs() -> None:
    adapter = ADAPTERS[ProviderId("usgs_nwis")]
    native = read_native_table(adapter.native_path)
    stations = _build(adapter, native).stations
    datum = native.data.select("site_no", "dec_coord_datum_cd")
    joined = stations.join(datum, left_on="station_id", right_on="site_no", how="left", validate="1:1")

    assert native.data.height == stations.height == joined.height == 26_258
    assert native.data["dec_coord_datum_cd"].null_count() == 0
    assert native.data.filter(pl.col("dec_coord_datum_cd").str.strip_chars() == "").is_empty()
    assert native.data["dec_coord_datum_cd"].unique().to_list() == ["NAD83"]
    assert joined.select("dec_coord_datum_cd", "crs").unique().rows() == [("NAD83", "EPSG:4269")]
    assert "unknown" not in stations["crs"].unique().to_list()


@pytest.mark.parametrize(("datum", "expected"), [("", "unknown"), ("ZZZ99", "unknown")])
def test_usgs_full_native_string_datum_variants_use_explicit_unknown(datum: str, expected: str) -> None:
    adapter = ADAPTERS[ProviderId("usgs_nwis")]
    native = read_native_table(adapter.native_path)
    changed = NativeTable(
        native.data.with_columns(
            pl.when(pl.col("site_no") == "01010000")
            .then(pl.lit(datum, dtype=pl.String))
            .otherwise(pl.col("dec_coord_datum_cd"))
            .alias("dec_coord_datum_cd")
        )
    )
    catalogue = _build(adapter, changed)
    assert catalogue.stations.height == 26_258
    assert catalogue.stations.filter(pl.col("station_id") == "01010000").select("crs").item() == expected


def test_usgs_full_native_null_datum_variant_fails_closed_with_station_message() -> None:
    adapter = ADAPTERS[ProviderId("usgs_nwis")]
    native = read_native_table(adapter.native_path)
    changed = NativeTable(
        native.data.with_columns(
            pl.when(pl.col("site_no") == "01010000")
            .then(pl.lit(None, dtype=pl.String))
            .otherwise(pl.col("dec_coord_datum_cd"))
            .alias("dec_coord_datum_cd")
        )
    )
    with pytest.raises(FatalContractError) as caught:
        _build(adapter, changed)
    assert str(caught.value) == "USGS station '01010000' has invalid dec_coord_datum_cd"


def _normalized_built_at(payload: bytes) -> bytes:
    parsed = json.loads(payload)
    if not isinstance(parsed, dict) or "built_at" not in parsed:
        return payload
    value = parsed["built_at"]
    assert isinstance(value, str)
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    pattern = rb'("built_at"\s*:\s*")[^"]*(")'
    replaced, count = re.subn(pattern, rb"\g<1>2000-01-01T00:00:00Z\g<2>", payload, count=1)
    assert count == 1
    return replaced


@pytest.mark.parametrize("adapter", ADAPTERS.values(), ids=lambda adapter: str(adapter.provider_id))
def test_native_composition_root_rebuilds_committed_artifacts_without_network(
    adapter: ProviderAdapter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    def denied(name: str):
        def raiser(*args: object, **kwargs: object) -> None:
            calls.append(name)
            raise AssertionError(f"network or refresh attempt: {name}")

        return raiser

    monkeypatch.setattr(transport.HttpClient, "send", denied("HttpClient.send"))
    monkeypatch.setattr(transport, "_send_with_requests", denied("_send_with_requests"))
    monkeypatch.setattr(requests, "get", denied("requests.get"))
    monkeypatch.setattr(requests, "post", denied("requests.post"))
    monkeypatch.setattr(requests, "request", denied("requests.request"))
    monkeypatch.setattr(requests.sessions.Session, "request", denied("Session.request"))
    monkeypatch.setattr(urllib.request, "urlopen", denied("urlopen"))
    monkeypatch.setattr(socket, "create_connection", denied("socket.create_connection"))
    monkeypatch.setattr(socket.socket, "connect", denied("socket.socket.connect"))
    for name in dir(adapter.generator):
        if name.startswith("refresh") and callable(getattr(adapter.generator, name)):
            monkeypatch.setattr(adapter.generator, name, denied(f"{adapter.provider_id}.{name}"))

    native_before = adapter.native_path.read_bytes()
    output = tmp_path / str(adapter.provider_id)
    arguments = ["--native", str(adapter.native_path), "--out", str(output)]
    if adapter.provider_id == "jp_mlit":
        arguments.extend(
            (
                "--license-recording",
                "tests/test_data/jp_mlit_terms_licence_euc_jp.html",
                "--citation-recording",
                "tests/test_data/jp_mlit_terms_citation.pdf",
            )
        )
    elif adapter.provider_id == "pl_imgw":
        committed_provenance = json.loads((adapter.native_path.parent / "provenance.json").read_text())
        grdc = next(source for source in committed_provenance["source_records"] if source["source_id"] == "sr.pl.grdc")
        redacted_record = tmp_path / "pl_imgw-redacted-private-verification.json"
        redacted_record.write_text(json.dumps(grdc["statements"][0]["private_verification"]))
        arguments.extend(
            (
                "--terms-recording",
                "tests/test_data/pl_imgw_terms_regulations.html",
                "--private-verification-record",
                str(redacted_record),
            )
        )
    assert adapter.main(arguments) == 0
    assert calls == []
    assert adapter.native_path.read_bytes() == native_before

    catalogue_dir = adapter.native_path.parent
    committed_names = {
        path.name for path in catalogue_dir.iterdir() if path.is_file() and path.name != "native.parquet"
    }
    rebuilt_names = {path.name for path in output.iterdir() if path.is_file()}
    expected_names = {
        "provider.json",
        "products.parquet",
        "stations.parquet",
        "station_products.parquet",
        "provenance.json",
    }
    assert committed_names == rebuilt_names == expected_names
    for name in committed_names:
        committed = (catalogue_dir / name).read_bytes()
        rebuilt = (output / name).read_bytes()
        if name.endswith(".json"):
            assert _normalized_built_at(rebuilt) == _normalized_built_at(committed)
        else:
            assert rebuilt == committed
