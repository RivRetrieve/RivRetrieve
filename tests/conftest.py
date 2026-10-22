from __future__ import annotations

import os
import sys
from collections.abc import Callable, Generator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.catalogues.artifact import (
    ACQUISITION_PROVENANCE_ENROLLED_PROVIDERS,
    PackagedCatalogArtifact,
    load_packaged_catalogue_artifact,
    packaged_catalogue_artifact_from_components,
)
from rivretrieve._internal.catalogues.evidence import CatalogueEvidence
from rivretrieve._internal.catalogues.schemas import AvailabilityDtype
from rivretrieve._internal.registry import ProviderRegistry, _ProviderHandle, _registry


@pytest.fixture
def existenz_engine_replay(monkeypatch):
    """Keep retired-route engine regressions independent of the Swiss catalogue."""
    from importlib import import_module

    from rivretrieve._internal import discovery
    from tests._existenz import catalogue_for_replay, declaration_for_replay

    module = import_module("rivretrieve._internal.providers.ch_foen.declaration")
    declaration = declaration_for_replay(module.declaration)
    monkeypatch.setattr(module, "declaration", declaration)
    registry = ProviderRegistry()
    registry.register(
        "ch_foen",
        catalogue_for_replay(),
        engine_provider_module=declaration.observations.stages,
        public_archive_access=declaration.public_archive_access,
    )
    monkeypatch.setattr(discovery, "_registry", registry)
    monkeypatch.setattr(discovery, "_provider_lookup", registry.get)
    monkeypatch.setattr(discovery, "_ensure_default_providers_registered", lambda: None)


@pytest.fixture
def registered_dws_catalogue():
    """Opt in to the deferred DWS catalogue without offering it by default."""
    from rivretrieve._internal.providers.registration import register_manifest

    register_manifest(_registry, ("za_dws",))


@pytest.fixture(autouse=True)
def isolated_runtime_inputs(monkeypatch, tmp_path):
    """Keep ambient configuration out without replacing test-selected stores or dotenv."""
    from rivretrieve._internal import discovery
    from rivretrieve._internal.providers import registration

    for name in ("RIVRETRIEVE_CACHE_DIR", "NVE_API_KEY", "USGS_API_KEY", "ANA_IDENTIFICADOR", "ANA_SENHA"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NETRC", str(tmp_path / "absent.netrc"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost,::1")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost,::1")
    monkeypatch.setattr(discovery, "user_cache_dir", lambda *args, **kwargs: str(tmp_path / "cache"))
    monkeypatch.setattr(registration, "user_cache_dir", lambda *args, **kwargs: str(tmp_path / "cache"))
    original_dotenv = discovery.dotenv_values
    ambient_dotenv = Path.cwd() / ".env"

    def test_dotenv(path, *args, **kwargs):
        if Path(path) == ambient_dotenv:
            return {}
        return original_dotenv(path, *args, **kwargs)

    monkeypatch.setattr(discovery, "dotenv_values", test_dotenv)


@pytest.fixture(autouse=True)
def loopback_only_network(request, monkeypatch):
    """Source-independent tests may use real loopback HTTP, never publisher traffic."""
    if not request.config.getoption("--logic-only"):
        return
    import ipaddress
    import socket

    def check_host(host):
        if isinstance(host, bytes):
            host = host.decode("ascii")
        if host == "localhost":
            return
        try:
            allowed = ipaddress.ip_address(host).is_loopback
        except ValueError:
            allowed = False
        if not allowed:
            pytest.fail("Source-independent tests permit only loopback network access", pytrace=False)

    getaddrinfo = socket.getaddrinfo
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex

    def local_addresses(host, *args, **kwargs):
        check_host(host)
        return getaddrinfo(host, *args, **kwargs)

    def local_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            check_host(address[0])
        return connect(sock, address)

    def local_connect_ex(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            check_host(address[0])
        return connect_ex(sock, address)

    monkeypatch.setattr(socket, "getaddrinfo", local_addresses)
    monkeypatch.setattr(socket.socket, "connect", local_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", local_connect_ex)


@pytest.fixture(scope="session")
def retained_evidence_root() -> Path:
    """Locate explicitly supplied archive inputs in their repository-relative layout."""
    from tests._evidence import resolve_retained_evidence_root

    return resolve_retained_evidence_root(os.environ.get("RIVRETRIEVE_TEST_EVIDENCE_ROOT"))


@pytest.fixture(scope="session")
def thaiwater_review_evidence_root() -> Path:
    """Receive the verified governing root from the restricted archive coordinator."""
    from tests._evidence import resolve_retained_evidence_root

    configured = os.environ.get("THAIWATER_REVIEW_EVIDENCE_ROOT")
    if not configured:
        pytest.fail("The reviewed archive test command must supply ThaiWater governing inputs.", pytrace=False)
    return resolve_retained_evidence_root(configured)


def _packaged_provenance(provider_id: str) -> CatalogueEvidence | None:
    if provider_id not in ACQUISITION_PROVENANCE_ENROLLED_PROVIDERS:
        return None
    path = (
        Path(__file__).parents[1]
        / "src"
        / "rivretrieve"
        / "_internal"
        / "providers"
        / provider_id
        / "catalogue"
        / "provenance.json"
    )
    return load_packaged_catalogue_artifact(path.parent, on_issue="raise").acquisition_provenance


@dataclass(frozen=True)
class RegisteredStub:
    registry: ProviderRegistry
    handle: _ProviderHandle


def _provider_info(
    provider_id: str,
    catalogue_version: str | None,
    *,
    live_stations: bool = False,
    live_products: bool = False,
    live_station_products: bool = False,
) -> dict[str, object]:
    return {
        "provider_id": provider_id,
        "name": f"{provider_id} Provider",
        "live_stations": live_stations,
        "live_products": live_products,
        "live_station_products": live_station_products,
        "bulk_observations": "none",
        "catalogue_version": catalogue_version,
        "license": None,
        "citation": None,
    }


def _products(provider_id: str, *, rich: bool = False) -> pl.DataFrame:
    rows = [
        {
            "provider_id": provider_id,
            "product_id": "level",
            "observed_property": "water_level",
            "frequency": "daily",
            "statistic": "mean",
            "period_type": "calendar_day",
            "period_anchor": "UTC",
            "unit": "m",
            "native_id": "WATER_LEVEL",
        }
    ]
    if rich:
        rows.extend(
            [
                {
                    "provider_id": provider_id,
                    "product_id": "flow",
                    "observed_property": "discharge",
                    "frequency": "daily",
                    "statistic": "mean",
                    "period_type": "calendar_day",
                    "period_anchor": "UTC",
                    "unit": "m3/s",
                    "native_id": "FLOW",
                },
                {
                    "provider_id": provider_id,
                    "product_id": "level_hourly",
                    "observed_property": "water_level",
                    "frequency": "hourly",
                    "statistic": "instantaneous",
                    "period_type": "instant",
                    "period_anchor": "UTC",
                    "unit": "m",
                    "native_id": "WATER_LEVEL_HOURLY",
                },
                {
                    "provider_id": provider_id,
                    "product_id": "level_max",
                    "observed_property": "water_level",
                    "frequency": "daily",
                    "statistic": "max",
                    "period_type": "calendar_day",
                    "period_anchor": "UTC",
                    "unit": "m",
                    "native_id": "WATER_LEVEL_MAX",
                },
            ]
        )

    return pl.DataFrame(
        rows,
        schema={
            "provider_id": pl.Utf8,
            "product_id": pl.Utf8,
            "observed_property": pl.Utf8,
            "frequency": pl.Utf8,
            "statistic": pl.Utf8,
            "period_type": pl.Utf8,
            "period_anchor": pl.Utf8,
            "unit": pl.Utf8,
            "native_id": pl.Utf8,
        },
    )


def _stations(provider_id: str, *, rich: bool = False) -> pl.DataFrame:
    rows = [
        {
            "provider_id": provider_id,
            "station_id": "station-1",
            "latitude": 46.2,
            "longitude": 7.1,
            "crs": "unknown",
        }
    ]
    if rich:
        rows.append(
            {
                "provider_id": provider_id,
                "station_id": "station-2",
                "latitude": 47.1,
                "longitude": 8.3,
                "crs": "unknown",
            }
        )

    return pl.DataFrame(
        rows,
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "latitude": pl.Float64,
            "longitude": pl.Float64,
            "crs": pl.Utf8,
        },
    )


def _station_products(provider_id: str, *, rich: bool = False) -> pl.DataFrame:
    rows = [
        {
            "provider_id": provider_id,
            "station_id": "station-1",
            "product_id": "level",
            "availability": "available",
            "availability_reason": None,
            "published_record_start_date": date(2020, 1, 1),
            "published_record_end_date": None,
            "last_catalogue_check": date(2026, 1, 1),
        }
    ]
    if rich:
        rows.extend(
            [
                {
                    "provider_id": provider_id,
                    "station_id": "station-1",
                    "product_id": "flow",
                    "availability": "unknown",
                    "availability_reason": "not_catalogued",
                    "published_record_start_date": None,
                    "published_record_end_date": None,
                    "last_catalogue_check": date(2026, 1, 1),
                },
                {
                    "provider_id": provider_id,
                    "station_id": "station-2",
                    "product_id": "level_hourly",
                    "availability": "available",
                    "availability_reason": None,
                    "published_record_start_date": date(2021, 1, 1),
                    "published_record_end_date": None,
                    "last_catalogue_check": date(2026, 1, 1),
                },
                {
                    "provider_id": provider_id,
                    "station_id": "station-2",
                    "product_id": "level_max",
                    "availability": "unavailable",
                    "availability_reason": "derived_not_supported",
                    "published_record_start_date": None,
                    "published_record_end_date": None,
                    "last_catalogue_check": date(2026, 1, 1),
                },
            ]
        )

    return pl.DataFrame(
        rows,
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "availability": AvailabilityDtype,
            "availability_reason": pl.Utf8,
            "published_record_start_date": pl.Date,
            "published_record_end_date": pl.Date,
            "last_catalogue_check": pl.Date,
        },
    )


@pytest.fixture
def stub_packaged_catalogue_artifact() -> Callable[..., PackagedCatalogArtifact]:
    def build(
        provider_id: str = "stub_provider",
        *,
        catalogue_version: str | None = "2026.01",
        live_stations: bool = False,
        live_products: bool = False,
        live_station_products: bool = False,
    ) -> PackagedCatalogArtifact:
        return packaged_catalogue_artifact_from_components(
            _provider_info(
                provider_id,
                catalogue_version,
                live_stations=live_stations,
                live_products=live_products,
                live_station_products=live_station_products,
            ),
            _products(provider_id),
            _stations(provider_id),
            _station_products(provider_id),
            acquisition_provenance=_packaged_provenance(provider_id),
            withheld_rows_already_applied=True,
            on_issue="raise",
        )

    return build


@pytest.fixture
def stub_packaged_catalogue_artifact_rich() -> Callable[..., PackagedCatalogArtifact]:
    def build(
        provider_id: str = "stub_provider",
        *,
        catalogue_version: str | None = "2026.01",
        live_stations: bool = False,
        live_products: bool = False,
        live_station_products: bool = False,
    ) -> PackagedCatalogArtifact:
        return packaged_catalogue_artifact_from_components(
            _provider_info(
                provider_id,
                catalogue_version,
                live_stations=live_stations,
                live_products=live_products,
                live_station_products=live_station_products,
            ),
            _products(provider_id, rich=True),
            _stations(provider_id, rich=True),
            _station_products(provider_id, rich=True),
            acquisition_provenance=_packaged_provenance(provider_id),
            withheld_rows_already_applied=True,
            on_issue="raise",
        )

    return build


@pytest.fixture
def stub_packaged_catalogue_artifact_live_capable(
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> Callable[..., PackagedCatalogArtifact]:
    def build(
        provider_id: str = "stub_provider", *, catalogue_version: str | None = "2026.01"
    ) -> PackagedCatalogArtifact:
        return stub_packaged_catalogue_artifact(
            provider_id,
            catalogue_version=catalogue_version,
            live_stations=True,
            live_products=True,
            live_station_products=True,
        )

    return build


@pytest.fixture(scope="session")
def packaged_catalogue_inputs():
    from rivretrieve._internal.catalogues import artifact as artifact_module
    from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
    from tests._catalogue_inputs import PackagedCatalogueInputs

    providers = Path(artifact_module.__file__).parents[1] / "providers"
    return PackagedCatalogueInputs(
        (providers / provider / "catalogue" for provider in BUILTIN_PROVIDER_IDS),
        lambda path: artifact_module.load_packaged_catalogue_artifact(path, on_issue="raise"),
    )


@pytest.fixture
def reuse_packaged_catalogues(monkeypatch, packaged_catalogue_inputs) -> None:
    """Reuse detached package inputs, while registering a fresh real manifest.

    Opt in with ``pytest.mark.usefixtures("reuse_packaged_catalogues")`` only for
    behavior tests whose subject is not artifact loading or registration. Changed
    and unlisted paths still reach the real loader. Registry isolation, dynamic
    declarations, credentials and cache-root composition remain unchanged.
    """
    from functools import wraps

    from rivretrieve._internal.providers import registration

    register = registration.register_manifest

    @wraps(register)
    def register_with_inputs(*args, **kwargs):
        kwargs.setdefault("artifact_loader", packaged_catalogue_inputs.load)
        return register(*args, **kwargs)

    def provenance(provider_id: str) -> CatalogueEvidence | None:
        if provider_id not in ACQUISITION_PROVENANCE_ENROLLED_PROVIDERS:
            return None
        from tests._catalogue import catalogue_path

        return packaged_catalogue_inputs.load(catalogue_path(provider_id)).acquisition_provenance

    monkeypatch.setattr(registration, "register_manifest", register_with_inputs)
    monkeypatch.setattr(sys.modules[__name__], "_packaged_provenance", provenance)


@pytest.fixture(autouse=True)
def clear_provider_registry() -> Generator[None]:
    _registry.clear()
    yield
    _registry.clear()


@pytest.fixture
def fresh_registry() -> ProviderRegistry:
    return ProviderRegistry()


@pytest.fixture
def registered_stub(
    fresh_registry: ProviderRegistry,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> RegisteredStub:
    from tests._stubs import stub_provider

    artifact = stub_provider.build_artifact(stub_packaged_catalogue_artifact)
    handle = fresh_registry.register("stub_provider", artifact, provider_module=stub_provider)
    return RegisteredStub(registry=fresh_registry, handle=handle)


@pytest.fixture
def source_terms_catalogue_artifact() -> Callable[[str], PackagedCatalogArtifact]:
    """Wire real verified source terms to synthetic engine rows, not certify a catalogue.

    Only registry source-terms unit tests use this direct contract carrier. Ordinary
    stub catalogues continue through the shared component validator. The real
    metadata keeps all its national locator requirements unchanged.
    """

    def build(provider_id: str) -> PackagedCatalogArtifact:
        return PackagedCatalogArtifact(
            provider_info=_provider_info(provider_id, "2026.01"),
            products=_products(provider_id),
            stations=_stations(provider_id),
            station_products=_station_products(provider_id),
            acquisition_provenance=_packaged_provenance(provider_id),
        )

    return build


@pytest.fixture(scope="session")
def catalogue_input_receipt(retained_evidence_root: Path):
    """Read the coordinator's explicit member identities without opening source bodies."""
    from rivretrieve._internal.acquisition_provenance import RetainedInputReceipt
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    configured = os.environ.get("RIVRETRIEVE_CATALOGUE_INPUT_PROVENANCE")
    if not configured:
        pytest.fail("The reviewed archive command must supply catalogue input provenance.", pytrace=False)
    receipt = RetainedInputReceipt.model_validate_json(Path(configured).read_bytes())
    if receipt.code_revision != receipt.declaration_revision:
        pytest.fail("Catalogue declarations must use the explicitly selected executed revision.", pytrace=False)
    verify_retained_input_files(receipt.model_copy(update={"inputs": (), "support_inputs": ()}), retained_evidence_root)
    return receipt


@pytest.fixture(scope="session")
def catalogue_build_inputs(retained_evidence_root: Path, catalogue_input_receipt):
    """Adopt only explicit catalogue support from the restricted coordinator handoff."""
    import importlib

    from rivretrieve._internal.catalogues.inputs import (
        select_catalogue_build_inputs,
        verify_recording_envelopes,
        verify_retained_input_files,
    )

    receipt = catalogue_input_receipt

    def select(provenance):
        origins = importlib.import_module(f"rivretrieve._internal.providers.{provenance.provider_id}.origins")
        supporting_inputs = {}
        supporting_declarations = (
            origins.station_metadata_supporting_inputs(provenance)
            if provenance.provider_id in {"ch_foen", "fr_hubeau"}
            else origins.CATALOGUE_SUPPORTING_INPUTS
        )
        for fact, paths in supporting_declarations.items():
            if fact in provenance.fact_universe:
                for path in paths:
                    supporting_inputs.setdefault(path, []).append(fact)
        native_acquisitions = (
            tuple(
                binding.acquisition_id
                for binding in provenance.fact_bindings
                if "source.station.native_identity" in binding.facts and binding.transformation is None
            )
            if provenance.provider_id == "ch_foen"
            else origins.NATIVE_TABLE_ACQUISITION_IDS
        )
        if provenance.provider_id == "ch_foen":
            import json

            from rivretrieve._internal.providers.ch_foen.generate_catalogue import selected_supporting_inputs

            selection_path = "maintenance/catalogue/ch_foen/official/selection.json"
            if selection_path not in {item.consumer_path for item in receipt.declaration_inputs}:
                raise ValueError("Swiss build support requires the selected authored declaration")
            selection = json.loads((retained_evidence_root / selection_path).read_bytes())
            supporting_inputs.update(selected_supporting_inputs(provenance, selection))
        result = select_catalogue_build_inputs(
            provenance,
            receipt,
            native_acquisitions,
            origins.CATALOGUE_BUILD_DECLARATIONS,
            recording_artifact_sha256=verify_recording_envelopes(provenance, receipt, retained_evidence_root),
            supporting_inputs=supporting_inputs,
        )
        consumed_paths = {provenance.native_table.repository_path, *supporting_inputs}
        consumed_paths.update(
            item.recording.repository_path for source in provenance.source_records for item in source.evidence
        )
        adopted = receipt.model_copy(
            update={"inputs": tuple(item for item in receipt.inputs if item.consumer_path in consumed_paths)}
        )
        verify_retained_input_files(adopted, retained_evidence_root)
        family, locations, verifier = _governing_support_locations(provenance, retained_evidence_root)
        if locations:
            from rivretrieve._internal.catalogues.inputs import select_catalogue_support

            support = select_catalogue_support(
                provenance,
                receipt,
                family=family,
                locations=locations,
                verifier_location=verifier,
            )
            result = type(result).model_validate({**result.model_dump(mode="python"), "support": support})
        return result

    return select


def _governing_support_locations(provenance, root: Path):
    """Resolve explicitly supplied reviewed ledger rows without opening source bodies."""
    import csv
    import json

    provider = provenance.provider_id
    paths = {}
    if provider == "ba_fhmzbih":
        ledger = json.loads(
            (root / "maintenance/catalogue/ba_fhmzbih/inventory/baseline_workbook_access.json").read_text()
        )
        for pair in ledger["pairs"]:
            paths[f"workbook:{pair['station_no']}:{pair['product_id']}"] = (pair["response_file"],)
        return provider, paths, ("verification/ba_fhmzbih/verify_evidence.py", "main")
    if provider == "th_thaiwater":
        with (
            root / "maintenance/catalogue/th_thaiwater/inventory/governing_station_product_evidence.csv"
        ).open() as stream:
            for row in csv.DictReader(stream):
                locations = (row["evidence_body"], row["evidence_receipt"])
                previous = paths.setdefault(row["request_id"], locations)
                if previous != locations:
                    pytest.fail("Public ThaiWater ledger has conflicting acquisition support locators.", pytrace=False)
        return provider, paths, ("verification/th_thaiwater/verify_governing_evidence.py", "main")
    if provider in {"fr_hubeau", "fr_hydroportail"}:
        # The existing provider decoder has already selected the applicable
        # ledger acquisitions and retained their exact material locators.
        prefix = "availability_" if provider == "fr_hubeau" else "history_"
        for source in provenance.source_records:
            for acquisition in source.acquisitions:
                if not acquisition.acquisition_id.startswith(prefix):
                    continue
                if acquisition.material is None:
                    pytest.fail("French ledger acquisition has no exact source material locator.", pytrace=False)
                paths[acquisition.acquisition_id] = (acquisition.material.filename,)
        return "fr_hubeau", paths, ("verification/fr_hubeau/verify_governing_evidence.py", "main")
    return "", {}, ("", "")


@pytest.fixture
def catalogue_build_inputs_path(catalogue_build_inputs, tmp_path_factory):
    """Write an adopted selection for the test's explicitly supplied provenance."""
    directory = tmp_path_factory.mktemp("catalogue-build-inputs")
    count = 0

    def write(provenance):
        nonlocal count
        path = directory / f"{count}.json"
        count += 1
        path.write_text(catalogue_build_inputs(provenance).model_dump_json(), encoding="utf-8")
        return path

    return write
