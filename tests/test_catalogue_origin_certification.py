"""catalogue origin certification : EnrolledProvider × CommittedNative × Origins × Receipts → CertifiedBuilds."""

from __future__ import annotations

import hashlib
import importlib
import json
import lzma
import re
import socket
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path
from types import ModuleType
from urllib.parse import urlparse

import polars as pl
import pytest
import requests
from pydantic import TypeAdapter

from rivretrieve._internal import discovery, transport
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
from rivretrieve._internal.catalogues.native import NativeTable, read_native_table
from rivretrieve._internal.catalogues.schemas import STATION_CATALOG_SCHEMA, StationCatalog
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import decode_availability
from rivretrieve._internal.providers.fr_hubeau.origins import HydrometryCoordinateConversion
from rivretrieve._internal.providers.jp_mlit.origins import WorldGeodeticDmsConversion
from rivretrieve._internal.providers.th_thaiwater.generate_catalogue import GraphAvailabilityEvidence
from rivretrieve._internal.providers.usgs_nwis.origins import DatumToCrsConversion
from rivretrieve._internal.providers.za_dws.origins import UnsignedDmsConversion

ROOT = Path(__file__).parents[1]
THAI_AVAILABILITY_EVIDENCE_PATH = Path(
    "maintenance/catalogue/th_thaiwater/inventory/governing_station_product_evidence.csv"
)
RECEIPTS_PATH = Path("tests/test_data/catalogue_origin_evidence_receipts.json")
PROVIDER_NOTES = ROOT / "docs/provider_ports"
SCHEMA_COLUMNS = tuple(column.name for column in STATION_CATALOG_SCHEMA.columns)
DEFERRED_PROVIDERS: frozenset[ProviderId] = frozenset()


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


def _adapter(retained_evidence_root: Path, provider: str, cases: tuple[DeclarationCase, ...]) -> ProviderAdapter:
    generator = _module(provider, "generate_catalogue")
    native_path = retained_evidence_root / "src/rivretrieve/_internal/providers" / provider / "catalogue/native.parquet"
    build = generator.build_catalogue
    if provider == "br_ana":
        from rivretrieve._internal.providers.br_ana.capture import parse_adopted_telemetry_evidence, read_capture_record
        from rivretrieve._internal.providers.br_ana.origins import (
            build_acquisition_provenance,
            with_observation_products,
        )
        from rivretrieve._internal.recordings import read_recording

        capture = read_capture_record(retained_evidence_root / "tests/test_data/br_ana_inventory/capture.json")
        data = retained_evidence_root / "tests/recordings/br_ana"
        recorded_path = data / "telemetry_15400000_2024-01-04_DIAS_30.recording.json"
        telemetry = parse_adopted_telemetry_evidence(
            (data / "manual-page11-acquisition.json").read_bytes(),
            (data / "manual-page11-derived.txt").read_bytes(),
            read_recording(recorded_path),
            str(recorded_path.relative_to(retained_evidence_root)),
        )
        provenance = with_observation_products(
            build_acquisition_provenance(capture),
            capture,
            generator.project_stations(read_native_table(native_path)).data,
            telemetry,
        )
        build = partial(build, provenance=provenance, telemetry=telemetry)
    if provider == "fr_hubeau":
        ledger = ROOT / "maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz"
        availability = decode_availability(lzma.decompress(ledger.read_bytes()))
        from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import NativeInventoryCapture

        capture = NativeInventoryCapture.model_validate_json(
            (ROOT / "maintenance/catalogue/fr_hubeau/inventory/native_capture.json").read_bytes()
        )
        build = partial(build, availability=availability, native_capture=capture)
    if provider == "fr_hydroportail":
        from rivretrieve._internal.acquisition_provenance import (
            EvidenceReference,
            NativeTableIdentity,
            RecordingReference,
        )

        evidence = retained_evidence_root / "maintenance/catalogue/fr_hydroportail/evidence"
        receipt = json.loads((evidence / "national-tests.receipt.json").read_bytes())
        documents = []
        for name, description in (
            ("about", "HydroPortail publication and PHyC platform"),
            ("legal", "HydroPortail public access and operator; reuse licence not established"),
            ("chunk-8529.fdb00780.js", "Module 71324 emits station x/y directly as GeoJSON longitude/latitude"),
        ):
            record = json.loads((evidence / f"{name}.receipt.json").read_bytes())
            documents.append(
                EvidenceReference(
                    evidence_id=name,
                    description=description,
                    recording=RecordingReference(
                        recording_id=name,
                        repository_path=(evidence / f"{name}.body").relative_to(retained_evidence_root).as_posix(),
                        source_url=record["url"],
                        retrieved_at=datetime.fromisoformat(record["retrieved_at"]),
                        media_type=record["content_type"],
                        sha256=record["sha256"],
                    ),
                )
            )
        material = native_path.read_bytes()
        identity = NativeTableIdentity(
            repository_path=native_path.relative_to(retained_evidence_root).as_posix(),
            revision="eb2b4fcb3a38875329225b7dbe5f949216c01599",
            sha256=hashlib.sha256(material).hexdigest(),
            byte_size=len(material),
        )
        historical = decode_availability(
            lzma.decompress(
                (ROOT / "maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz").read_bytes()
            )
        )
        build = partial(
            build, historical=historical, receipt=receipt, documents=tuple(documents), native_identity=identity
        )
    if provider == "th_thaiwater":
        build = partial(
            build,
            availability_evidence=GraphAvailabilityEvidence((ROOT / THAI_AVAILABILITY_EVIDENCE_PATH).read_bytes()),
        )
    if provider == "ba_fhmzbih":
        workbook_access = TypeAdapter(generator.WorkbookAccessLedger).validate_json(
            (ROOT / "maintenance/catalogue/ba_fhmzbih/inventory/baseline_workbook_access.json").read_bytes()
        )
        build = partial(build, workbook_access=workbook_access)
    return ProviderAdapter(
        provider_id=ProviderId(provider),
        native_path=native_path,
        generator=generator,
        main=generator.main,
        build=build,
        cases=cases,
    )


def _stations_case(provider: str) -> tuple[DeclarationCase, ...]:
    origins = _module(provider, "origins").STATION_CATALOGUE_ORIGINS
    return (DeclarationCase("stations", origins),)


_france_origins = _module("fr_hubeau", "origins")
DECLARATIONS = {
    ProviderId(provider): _stations_case(provider)
    for provider in (
        "ba_fhmzbih",
        "br_ana",
        "ca_eccc",
        "ch_foen",
        "cz_chmi",
        "fr_hydroportail",
        "jp_mlit",
        "lt_lhmt",
        "no_nve",
        "pl_imgw",
        "th_thaiwater",
        "usgs_nwis",
        "za_dws",
    )
}
DECLARATIONS[ProviderId("fr_hubeau")] = (
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
)


CASES = [(provider, case) for provider, cases in DECLARATIONS.items() for case in cases]


@pytest.fixture(scope="module")
def adapter(request: pytest.FixtureRequest, retained_evidence_root: Path) -> ProviderAdapter:
    return _adapter(retained_evidence_root, request.param, DECLARATIONS[request.param])


def _build(adapter: ProviderAdapter, native: NativeTable | None = None, origins: Mapping[str, object] | None = None):
    table = read_native_table(adapter.native_path) if native is None else native
    return adapter.build(table, adapter.origins_argument() if origins is None else origins)


def _case_frames(
    adapter: ProviderAdapter, case: DeclarationCase, native: NativeTable, stations: StationCatalog
) -> tuple[NativeTable, StationCatalog]:
    case_native = native
    if adapter.provider_id == ProviderId("br_ana"):
        case_native = adapter.generator.project_stations(native)
    if case.native_partition is not None:
        case_native = NativeTable(native.data.filter(pl.col("source_endpoint") == case.native_partition))
    station_origin = case.declarations["station_id"]
    assert isinstance(station_origin, Field)
    station_ids = case_native.data[str(station_origin.native_column)].cast(pl.String).unique()
    return case_native, stations.filter(pl.col("station_id").is_in(station_ids.implode()))


def _expected_declarations() -> dict[tuple[ProviderId, str], Mapping[str, CatalogueOrigin]]:
    def field(name: str, conversion: FieldConversion | None = None) -> Field:
        return Field(NativeColumn(name), IdentityConversion() if conversion is None else conversion)

    def authored(value: str) -> Authored:
        return Authored(AuthoredValue(value))

    def unpublished(url: str) -> NotPublished:
        return NotPublished(Evidence(url))

    def documented(url: str) -> Documented:
        return Documented(DocumentedValue("EPSG:4326"), Evidence(url))

    def withheld() -> Withheld:
        return Withheld()

    return {
        (ProviderId("br_ana"), "stations"): {
            "provider_id": authored("br_ana"),
            "station_id": field("codigoestacao"),
            "latitude": field("Latitude", FloatConversion()),
            "longitude": field("Longitude", FloatConversion()),
            "crs": withheld(),
        },
        (ProviderId("ba_fhmzbih"), "stations"): {
            "provider_id": authored("ba_fhmzbih"),
            "station_id": field("metadata_station_no"),
            "latitude": field("metadata_station_latitude", FloatConversion()),
            "longitude": field("metadata_station_longitude", FloatConversion()),
            "crs": unpublished("https://vodostaji.voda.ba/data/internet/stations/stations.json"),
        },
        (ProviderId("ca_eccc"), "stations"): {
            "provider_id": authored("ca_eccc"),
            "station_id": field("STATION_NUMBER"),
            "latitude": field("geometry.coordinates[1]", FloatConversion()),
            "longitude": field("geometry.coordinates[0]", FloatConversion()),
            "crs": documented("https://api.weather.gc.ca/collections/hydrometric-stations?f=json"),
        },
        (ProviderId("ch_foen"), "stations"): {
            "provider_id": authored("ch_foen"),
            "station_id": field("name"),
            "latitude": field("details.lat", FloatConversion()),
            "longitude": field("details.lon", FloatConversion()),
            "crs": unpublished("https://api.existenz.ch/#hydro"),
        },
        (ProviderId("cz_chmi"), "stations"): {
            "provider_id": authored("cz_chmi"),
            "station_id": field("objID"),
            "latitude": field("GEOGR1", FloatConversion()),
            "longitude": field("GEOGR2", FloatConversion()),
            "crs": unpublished("https://opendata.chmi.cz/hydrology/read_me/Popis_kodu_historical.pdf"),
        },
        (ProviderId("fr_hubeau"), "hydrometrie/referentiel/stations"): {
            "provider_id": authored("fr_hubeau"),
            "station_id": field("code_station"),
            "latitude": field("latitude_station", HydrometryCoordinateConversion()),
            "longitude": field("longitude_station", HydrometryCoordinateConversion()),
            "crs": documented(
                "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?code_station=1011000101&format=geojson"
            ),
        },
        (ProviderId("fr_hydroportail"), "stations"): {
            "provider_id": authored("fr_hydroportail"),
            "station_id": field("bookmarkCode"),
            "latitude": field("y"),
            "longitude": field("x"),
            "crs": documented("https://hydro.eaufrance.fr/build/8529.fdb00780.js"),
        },
        (ProviderId("fr_hubeau"), "temperature/station"): {
            "provider_id": authored("fr_hubeau"),
            "station_id": field("code_station"),
            "latitude": field("latitude", FloatConversion()),
            "longitude": field("longitude", FloatConversion()),
            "crs": documented("https://hubeau.eaufrance.fr/api/v1/temperature/station?size=2000&format=json"),
        },
        (ProviderId("jp_mlit"), "stations"): {
            "provider_id": authored("jp_mlit"),
            "station_id": field("観測所記号"),
            "latitude": field("世界測地系", WorldGeodeticDmsConversion()),
            "longitude": field("世界測地系", WorldGeodeticDmsConversion()),
            "crs": unpublished("http://www1.river.go.jp/cgi-bin/SiteInfoDetail.exe?ID=301011281104010"),
        },
        (ProviderId("lt_lhmt"), "stations"): {
            "provider_id": authored("lt_lhmt"),
            "station_id": field("code"),
            "latitude": field("coordinates", StructMemberConversion()),
            "longitude": field("coordinates", StructMemberConversion()),
            "crs": documented("https://api.meteo.lt/"),
        },
        (ProviderId("no_nve"), "stations"): {
            "provider_id": authored("no_nve"),
            "station_id": field("stationId"),
            "latitude": field("latitude", FloatConversion()),
            "longitude": field("longitude", FloatConversion()),
            "crs": unpublished("https://hydapi.nve.no/swagger/v1/swagger.json"),
        },
        (ProviderId("pl_imgw"), "stations"): {
            "provider_id": authored("pl_imgw"),
            "station_id": field("gauge_id"),
            "latitude": field("latitude", FloatConversion()),
            "longitude": field("longitude", FloatConversion()),
            "crs": withheld(),
        },
        (ProviderId("th_thaiwater"), "stations"): {
            "provider_id": authored("th_thaiwater"),
            "station_id": field("station.id"),
            "latitude": field("station.tele_station_lat", FloatConversion()),
            "longitude": field("station.tele_station_long", FloatConversion()),
            "crs": unpublished(
                "https://standard.thaiwater.net/docs/การจัดทำมาตรฐานน้ำ-ระยะ/ข้อมูลอ้างอิง-ข้อมูลอ้า/การระบุพิกัดตำแหน่ง/"
            ),
        },
        (ProviderId("usgs_nwis"), "stations"): {
            "provider_id": authored("usgs_nwis"),
            "station_id": field("site_no"),
            "latitude": field("dec_lat_va", FloatConversion()),
            "longitude": field("dec_long_va", FloatConversion()),
            "crs": field("dec_coord_datum_cd", DatumToCrsConversion()),
        },
        (ProviderId("za_dws"), "stations"): {
            "provider_id": authored("za_dws"),
            "station_id": field("Station"),
            "latitude": field("Latitude (dd:mm:ss)", UnsignedDmsConversion()),
            "longitude": field("Longitude (dd:mm:ss)", UnsignedDmsConversion()),
            "crs": unpublished(
                "https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA1_Limpopo-Olifants_River.pdf"
            ),
        },
    }


@pytest.mark.derived(
    "maintenance/catalogue/fr_hydroportail/evidence",
    "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/br_ana/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/ca_eccc/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/ch_foen/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/cz_chmi/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/fr_hydroportail/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/jp_mlit/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/no_nve/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/usgs_nwis/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/za_dws/catalogue/native.parquet",
    "tests/recordings/br_ana/manual-page11-acquisition.json",
    "tests/recordings/br_ana/manual-page11-derived.txt",
    "tests/recordings/br_ana/telemetry_15400000_2024-01-04_DIAS_30.recording.json",
    "tests/test_data/br_ana_inventory/capture.json",
)
def test_adapter_discovery_is_exact_and_deferred_providers_remain_building(retained_evidence_root: Path) -> None:
    adapters = {provider: _adapter(retained_evidence_root, provider, cases) for provider, cases in DECLARATIONS.items()}
    discovery._ensure_default_providers_registered()
    registered = frozenset(ProviderId(value) for value in discovery._registry.list_provider_ids())

    assert frozenset(adapters) == ORIGIN_GATE_ENROLLED_PROVIDERS
    assert registered - frozenset(adapters) == DEFERRED_PROVIDERS, (
        "Every registered provider must declare its certification status explicitly"
    )
    assert not (DEFERRED_PROVIDERS & ORIGIN_GATE_ENROLLED_PROVIDERS)
    assert all(adapter.native_path.is_file() for adapter in adapters.values())
    assert all(callable(adapter.main) and callable(adapter.build) for adapter in adapters.values())
    assert {(provider, case.identity): case.declarations for provider, case in CASES} == _expected_declarations()
    assert len(CASES) == 15
    assert all(tuple(case.declarations) == SCHEMA_COLUMNS for _, case in CASES)


@pytest.mark.parametrize(
    ("adapter", "case"),
    CASES,
    ids=[f"{provider}-{case.identity}" for provider, case in CASES],
    indirect=["adapter"],
)
@pytest.mark.derived(
    "maintenance/catalogue/fr_hydroportail/evidence",
    "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/br_ana/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/ca_eccc/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/ch_foen/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/cz_chmi/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/fr_hydroportail/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/jp_mlit/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/no_nve/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/usgs_nwis/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/za_dws/catalogue/native.parquet",
    "tests/recordings/br_ana/manual-page11-acquisition.json",
    "tests/recordings/br_ana/manual-page11-derived.txt",
    "tests/recordings/br_ana/telemetry_15400000_2024-01-04_DIAS_30.recording.json",
    "tests/test_data/br_ana_inventory/capture.json",
    "tests/test_data/catalogue_origin_evidence_receipts.json",
)
def test_committed_declaration_case_passes_real_build_and_origin_gate(
    retained_evidence_root: Path, adapter: ProviderAdapter, case: DeclarationCase
) -> None:
    native = read_native_table(adapter.native_path)
    catalogue = _build(adapter, native)
    case_native, stations = _case_frames(adapter, case, native, catalogue.stations)

    assert not case_native.data.is_empty()
    assert not stations.is_empty()
    assert validate_catalogue_origins(adapter.provider_id, case.declarations, case_native, stations) == []
    enforce_catalogue_origins(adapter.provider_id, case.declarations, case_native, stations)
    _assert_reviewed_crs(retained_evidence_root, adapter, case, case_native, stations)


REMOVAL_CASES = [(adapter, case, column) for adapter, case in CASES for column in SCHEMA_COLUMNS]


@pytest.mark.parametrize(
    ("adapter", "case", "column"),
    REMOVAL_CASES,
    ids=[f"{provider}-{case.identity}-{column}" for provider, case, column in REMOVAL_CASES],
    indirect=["adapter"],
)
@pytest.mark.derived(
    "maintenance/catalogue/fr_hydroportail/evidence",
    "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/br_ana/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/ca_eccc/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/ch_foen/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/cz_chmi/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/fr_hydroportail/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/jp_mlit/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/no_nve/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/usgs_nwis/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/za_dws/catalogue/native.parquet",
    "tests/recordings/br_ana/manual-page11-acquisition.json",
    "tests/recordings/br_ana/manual-page11-derived.txt",
    "tests/recordings/br_ana/telemetry_15400000_2024-01-04_DIAS_30.recording.json",
    "tests/test_data/br_ana_inventory/capture.json",
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


def _receipts(retained_evidence_root: Path) -> list[dict[str, object]]:
    value = json.loads((retained_evidence_root / RECEIPTS_PATH).read_text(encoding="utf-8"))
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
        (str(provider), case.identity, column, str(origin.evidence))
        for provider, case in CASES
        for column, origin in case.declarations.items()
        if isinstance(origin, NotPublished)
    }


@pytest.mark.derived("tests/test_data/catalogue_origin_evidence_receipts.json")
def test_receipt_discovery_schema_order_urls_and_statuses_fail_closed(retained_evidence_root: Path) -> None:
    receipts = _receipts(retained_evidence_root)
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


@pytest.mark.parametrize(
    "provider", ("ba_fhmzbih", "ch_foen", "cz_chmi", "jp_mlit", "no_nve", "pl_imgw", "th_thaiwater", "za_dws")
)
@pytest.mark.governing(
    "tests/test_data/catalogue_origin_evidence_receipts.json",
    "tests/test_data/ba_fhmzbih_crs_evidence_stations.json",
    "tests/test_data/ch_foen_api_docs.html",
    "tests/test_data/cz_chmi_popis_kodu_historical.pdf",
    "tests/test_data/jp_mlit_site_info_detail_301011281104010.html",
    "tests/test_data/no_nve_swagger.json",
    "tests/test_data/pl_imgw_apiinfo.html",
    "tests/test_data/th_thaiwater_coordinate_standard.html",
)
def test_receipt_capture_digest(retained_evidence_root: Path, provider: str) -> None:
    receipts = [row for row in _receipts(retained_evidence_root) if row["provider_id"] == provider]
    assert receipts
    for receipt in receipts:
        capture_path = receipt["capture_path"]
        if capture_path is None:
            assert receipt["provider_id"] == "za_dws"
            continue
        path = retained_evidence_root / str(capture_path)
        assert path.is_relative_to(retained_evidence_root / "tests/test_data")
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


@pytest.mark.derived("tests/test_data/catalogue_origin_evidence_receipts.json")
def test_receipt_provider_specific_url_bindings_and_attested_exceptions(retained_evidence_root: Path) -> None:
    rows = {row["provider_id"]: row for row in _receipts(retained_evidence_root)}
    assert rows["ch_foen"]["requested_url"] == rows["ch_foen"]["final_url"] == "https://api.existenz.ch/"
    assert rows["ch_foen"]["evidence_url"] == "https://api.existenz.ch/#hydro"
    assert rows["cz_chmi"]["evidence_url"] == rows["cz_chmi"]["requested_url"] == rows["cz_chmi"]["final_url"]
    assert rows["jp_mlit"]["evidence_url"] == rows["jp_mlit"]["requested_url"] == rows["jp_mlit"]["final_url"]
    assert rows["th_thaiwater"]["evidence_url"] == rows["th_thaiwater"]["final_url"]
    dws = rows["za_dws"]
    assert dws["evidence_url"] != dws["requested_url"] == dws["final_url"]
    assert "web.archive.org/web/20251122081546id_/" in str(dws["requested_url"])


EXPECTED_CRS_COUNTS = {
    (ProviderId("ba_fhmzbih"), "stations"): (60, "unknown"),
    (ProviderId("ca_eccc"), "stations"): (8_057, "EPSG:4326"),
    (ProviderId("ch_foen"), "stations"): (246, "unknown"),
    (ProviderId("cz_chmi"), "stations"): (831, "unknown"),
    # Native publication inventories acquired 2026-09-21.
    (ProviderId("fr_hubeau"), "hydrometrie/referentiel/stations"): (6_475, "EPSG:4326"),
    (ProviderId("fr_hubeau"), "temperature/station"): (872, "EPSG:4326"),
    (ProviderId("fr_hydroportail"), "stations"): (6_409, "EPSG:4326"),
    (ProviderId("jp_mlit"), "stations"): (1_023, "unknown"),
    (ProviderId("lt_lhmt"), "stations"): (97, "EPSG:4326"),
    (ProviderId("no_nve"), "stations"): (4_902, "unknown"),
    (ProviderId("pl_imgw"), "stations"): (1_301, "unknown"),
    (ProviderId("th_thaiwater"), "stations"): (825, "unknown"),
    (ProviderId("za_dws"), "stations"): (2_905, "unknown"),
}


@pytest.mark.derived("src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet")
def test_france_provider_owned_converter_refuses_a_swapped_existing_native_column(retained_evidence_root: Path) -> None:
    adapter = _adapter(retained_evidence_root, "fr_hubeau", DECLARATIONS[ProviderId("fr_hubeau")])
    native = read_native_table(adapter.native_path)
    contradicted = dict(_france_origins.HYDROMETRY_STATION_CATALOGUE_ORIGINS)
    contradicted["latitude"] = Field(NativeColumn("longitude_station"), HydrometryCoordinateConversion())
    origins = adapter.origins_argument({"hydrometrie/referentiel/stations": contradicted})

    with pytest.raises(FatalContractError, match="cannot undergo fr_hubeau.projection_31_axis_correction"):
        _build(adapter, native, origins)


def _assert_reviewed_crs(
    retained_evidence_root: Path,
    adapter: ProviderAdapter,
    case: DeclarationCase,
    case_native: NativeTable,
    stations: StationCatalog,
) -> None:
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
            for row in _receipts(retained_evidence_root)
        )
    elif isinstance(origin, Documented):
        expected_count, expected_value = EXPECTED_CRS_COUNTS[(adapter.provider_id, case.identity)]
        assert stations.height == expected_count
        assert expected_value == origin.value
        assert stations["crs"].unique().to_list() == [origin.value]
        assert "unknown" not in stations["crs"].unique().to_list()
    elif isinstance(origin, Withheld):
        assert adapter.provider_id in {ProviderId("pl_imgw"), ProviderId("br_ana")}
        assert origin.reason == "acquisition_not_established"
        assert stations["crs"].unique().to_list() == ["unknown"]
    else:
        assert adapter.provider_id == ProviderId("usgs_nwis")
        assert isinstance(origin, Field)
        assert str(origin.native_column) == "dec_coord_datum_cd"


def test_not_published_and_documented_count_totals_are_pinned() -> None:
    assert sum(count for (_, _), (count, value) in EXPECTED_CRS_COUNTS.items() if value == "unknown") == 12_093
    assert 6_454 + 869 == 7_323


@pytest.mark.governing(
    "src/rivretrieve/_internal/providers/jp_mlit/catalogue/native.parquet",
    "tests/test_data/jp_mlit_site_info_detail_301011281104010.html",
)
def test_japan_accepted_receipt_build_and_dws_historical_review_are_honest(retained_evidence_root: Path) -> None:
    capture = (retained_evidence_root / "tests/test_data/jp_mlit_site_info_detail_301011281104010.html").read_bytes()
    assert len(capture) == 3_208
    assert hashlib.sha256(capture).hexdigest() == "81e7269886397975867bf556c8d5b6659bd5f8d7318c4cf062cd0f47419418f9"
    assert "世界測地系".encode("euc_jp") in capture
    japan = _adapter(retained_evidence_root, "jp_mlit", DECLARATIONS[ProviderId("jp_mlit")])
    assert _build(japan).stations["crs"].unique().to_list() == ["unknown"]

    dws_origins = _module("za_dws", "origins")
    assert dws_origins.CRS_EVIDENCE_EXPLANATION == (
        "The cited River PDF's own two-line coordinate header reads Latitude / dd:mm:ss and "
        "Longitude / dd:mm:ss; this names a representation format but never a datum. A "
        "case-insensitive review of all eight River PDFs found zero datum, WGS, ellipsoid, "
        "geodetic, projection, or EPSG occurrences. HyCatalogue.aspx is only a link index with "
        "no prose or coordinate header and is not CRS evidence."
    )


@pytest.mark.derived("src/rivretrieve/_internal/providers/usgs_nwis/catalogue/native.parquet")
def test_usgs_committed_datum_carrier_maps_exactly_to_reviewed_crs(retained_evidence_root: Path) -> None:
    adapter = _adapter(retained_evidence_root, "usgs_nwis", DECLARATIONS[ProviderId("usgs_nwis")])
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
@pytest.mark.derived("src/rivretrieve/_internal/providers/usgs_nwis/catalogue/native.parquet")
def test_usgs_full_native_string_datum_variants_use_explicit_unknown(
    retained_evidence_root: Path, datum: str, expected: str
) -> None:
    adapter = _adapter(retained_evidence_root, "usgs_nwis", DECLARATIONS[ProviderId("usgs_nwis")])
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


@pytest.mark.derived("src/rivretrieve/_internal/providers/usgs_nwis/catalogue/native.parquet")
def test_usgs_full_native_null_datum_variant_fails_closed_with_station_message(retained_evidence_root: Path) -> None:
    adapter = _adapter(retained_evidence_root, "usgs_nwis", DECLARATIONS[ProviderId("usgs_nwis")])
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


@pytest.mark.parametrize("adapter", tuple(DECLARATIONS), indirect=True)
@pytest.mark.governing(
    "maintenance/catalogue/fr_hubeau/inventory/hydrometry-stations-2026-09-21.json.xz",
    "maintenance/catalogue/fr_hubeau/inventory/temperature-stations-2026-09-21.json.xz",
    "maintenance/catalogue/fr_hydroportail/evidence",
    "maintenance/catalogue/fr_hydroportail/evidence/about.body",
    "maintenance/catalogue/fr_hydroportail/evidence/chunk-8529.fdb00780.js.body",
    "maintenance/catalogue/fr_hydroportail/evidence/legal.body",
    "research/usgs-modern-coverage",
    "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/br_ana/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/ca_eccc/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/ch_foen/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/cz_chmi/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/fr_hydroportail/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/jp_mlit/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/lt_lhmt/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/no_nve/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/pl_imgw/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/usgs_nwis/catalogue/native.parquet",
    "src/rivretrieve/_internal/providers/za_dws/catalogue/native.parquet",
    "tests/recordings/br_ana",
    "tests/recordings/br_ana/manual-page11-acquisition.json",
    "tests/recordings/br_ana/manual-page11-derived.txt",
    "tests/recordings/br_ana/telemetry_15400000_2024-01-04_DIAS_30.recording.json",
    "tests/test_data/ba_fhmzbih_4024_H_1Y.recording.json",
    "tests/test_data/ba_fhmzbih_4024_Q_1Y.recording.json",
    "tests/test_data/ba_fhmzbih_4110_Tvode_1Y.recording.json",
    "tests/test_data/ba_fhmzbih_metadata_index.recording.json",
    "tests/test_data/ba_fhmzbih_terms_absence.html",
    "tests/test_data/br_ana_inventory",
    "tests/test_data/br_ana_inventory/capture.json",
    "tests/test_data/br_ana_terms_licence.html",
    "tests/test_data/ca_eccc_terms_citation.html",
    "tests/test_data/ca_eccc_terms_licence.html",
    "tests/test_data/ch_foen_2135_flux_2020-01-01.recording.json",
    "tests/test_data/ch_foen_2135_rest_2026-09-01.recording.json",
    "tests/test_data/ch_foen_bafu_current_hydrological_data.html",
    "tests/test_data/ch_foen_bafu_hydrology_data_service.html",
    "tests/test_data/ch_foen_parameters_2026-09-02.recording.json",
    "tests/test_data/ch_foen_terms_bafu.html",
    "tests/test_data/ch_foen_terms_existenz.html",
    "tests/test_data/cz_chmi_terms_licence.html",
    "tests/test_data/cz_meta2.json",
    "tests/test_data/fr_hubeau_hydrometrie.html",
    "tests/test_data/fr_hubeau_temperature_openapi.json",
    "tests/test_data/fr_hubeau_terms_licence.html",
    "tests/test_data/jp_mlit_discharge_daily_2023_dat.recording.json",
    "tests/test_data/jp_mlit_discharge_daily_2023_html.recording.json",
    "tests/test_data/jp_mlit_discharge_hourly_2023_dat.recording.json",
    "tests/test_data/jp_mlit_discharge_hourly_2023_html.recording.json",
    "tests/test_data/jp_mlit_stage_daily_2023_dat.recording.json",
    "tests/test_data/jp_mlit_stage_daily_2023_html.recording.json",
    "tests/test_data/jp_mlit_stage_hourly_2023_dat.recording.json",
    "tests/test_data/jp_mlit_stage_hourly_2023_html.recording.json",
    "tests/test_data/jp_mlit_terms_citation.pdf",
    "tests/test_data/jp_mlit_terms_licence_euc_jp.html",
    "tests/test_data/lt_lhmt_terms_licence.html",
    "tests/test_data/no_nve_stations_active_0.json",
    "tests/test_data/no_nve_stations_active_1.json",
    "tests/test_data/no_nve_swagger.json",
    "tests/test_data/no_nve_terms_licence.html",
    "tests/test_data/pl_imgw_annual/CODZ_publiczne_format.txt",
    "tests/test_data/pl_imgw_annual/yearbook-2025.pdf",
    "tests/test_data/pl_imgw_terms_regulations.html",
    "tests/test_data/th_thaiwater_official_app.chunk-2026-09-02.js",
    "tests/test_data/th_thaiwater_official_water_wl-2026-09-02.html",
    "tests/test_data/th_thaiwater_terms_licence-1.html",
    "tests/test_data/usgs_nwis_instantaneous_values_definition.html",
    "tests/test_data/usgs_nwis_terms_citation-1.html",
    "tests/test_data/usgs_nwis_terms_licence-1.html",
    "tests/test_data/za_dws_terms_licence-1.html",
    "tests/test_data/za_dws_terms_licence-4.html",
    "tests/test_data/za_dws_terms_licence-5.html",
)
def test_native_composition_root_rebuilds_committed_artifacts_without_network(
    retained_evidence_root: Path, adapter: ProviderAdapter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
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
    source_inputs_before: dict[Path, bytes] = {}
    output = tmp_path / str(adapter.provider_id)
    arguments = ["--native", str(adapter.native_path), "--out", str(output)]
    if adapter.provider_id in {
        "ba_fhmzbih",
        "ca_eccc",
        "ch_foen",
        "cz_chmi",
        "lt_lhmt",
        "no_nve",
        "th_thaiwater",
        "za_dws",
    }:
        arguments.extend(("--evidence-root", str(retained_evidence_root)))
    if adapter.provider_id == "br_ana":
        arguments.extend(
            (
                "--evidence-root",
                str(retained_evidence_root),
                "--capture-record",
                str(retained_evidence_root / "tests/test_data/br_ana_inventory/capture.json"),
            )
        )
    elif adapter.provider_id == "ba_fhmzbih":
        ledger = ROOT / "maintenance/catalogue/ba_fhmzbih/inventory/baseline_workbook_access.json"
        series_recording = retained_evidence_root / "tests/test_data/ba_fhmzbih_metadata_index.recording.json"
        source_inputs_before = {path: path.read_bytes() for path in (ledger, series_recording)}
        arguments.extend(("--workbook-access-ledger", str(ledger), "--series-recording", str(series_recording)))
    elif adapter.provider_id == "usgs_nwis":
        metadata = retained_evidence_root / "research/usgs-modern-coverage"
        source_inputs_before = {path: path.read_bytes() for path in metadata.glob("metadata-*") if path.is_file()}
        arguments.extend(("--modern-metadata", str(metadata), "--evidence-root", str(retained_evidence_root)))
    elif adapter.provider_id == "jp_mlit":
        arguments.extend(
            (
                "--license-recording",
                str(retained_evidence_root / "tests/test_data/jp_mlit_terms_licence_euc_jp.html"),
                "--citation-recording",
                str(retained_evidence_root / "tests/test_data/jp_mlit_terms_citation.pdf"),
            )
        )
    elif adapter.provider_id == "fr_hubeau":
        arguments.extend(
            (
                "--evidence-root",
                str(retained_evidence_root),
                "--availability-ledger",
                str(ROOT / "maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz"),
                "--native-capture",
                str(ROOT / "maintenance/catalogue/fr_hubeau/inventory/native_capture.json"),
            )
        )
    elif adapter.provider_id == "fr_hydroportail":
        arguments.extend(
            (
                "--native-revision",
                "eb2b4fcb3a38875329225b7dbe5f949216c01599",
                "--repository-root",
                str(retained_evidence_root),
                "--evidence",
                str(retained_evidence_root / "maintenance/catalogue/fr_hydroportail/evidence"),
                "--availability-ledger",
                str(ROOT / "maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz"),
            )
        )
    elif adapter.provider_id == "th_thaiwater":
        arguments.extend(("--availability-evidence", str(ROOT / THAI_AVAILABILITY_EVIDENCE_PATH)))
    elif adapter.provider_id == "pl_imgw":
        committed_provenance = json.loads(
            (
                ROOT / "src/rivretrieve/_internal/providers" / str(adapter.provider_id) / "catalogue/provenance.json"
            ).read_text()
        )
        grdc = next(source for source in committed_provenance["source_records"] if source["source_id"] == "sr.pl.grdc")
        redacted_record = tmp_path / "pl_imgw-redacted-private-verification.json"
        redacted_record.write_text(json.dumps(grdc["statements"][0]["private_verification"]))
        arguments.extend(
            (
                "--terms-recording",
                str(retained_evidence_root / "tests/test_data/pl_imgw_terms_regulations.html"),
                "--private-verification-record",
                str(redacted_record),
            )
        )
    assert adapter.main(arguments) == 0
    assert calls == []
    assert adapter.native_path.read_bytes() == native_before
    assert {path: path.read_bytes() for path in source_inputs_before} == source_inputs_before

    catalogue_dir = ROOT / "src/rivretrieve/_internal/providers" / str(adapter.provider_id) / "catalogue"
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
        "provenance_facts.parquet",
        "provenance_acquisitions.parquet",
        "provenance_bindings.parquet",
        "provenance_binding_facts.parquet",
        "provenance_external_inputs.parquet",
        "format.json",
        "source_series.json",
        "series_claims.parquet",
        "croissant.json",
    }
    if adapter.provider_id == "usgs_nwis":
        expected_names.add("monitoring_locations.json")
    assert committed_names == rebuilt_names == expected_names
    for name in committed_names:
        committed = (catalogue_dir / name).read_bytes()
        rebuilt = (output / name).read_bytes()
        if name.endswith(".json") and name != "croissant.json":
            assert _normalized_built_at(rebuilt) == _normalized_built_at(committed)
        else:
            assert rebuilt == committed
