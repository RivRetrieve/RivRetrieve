"""public credential boundary : Selection × CredentialSources × ProviderDeclaration → ObservationResult."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.issues import MissingCredentialError
from rivretrieve._internal.providers.no_nve.declaration import declaration as no_nve_declaration
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.recordings import RecordingTransport, ReplayTransport, read_recording
from rivretrieve._internal.registry import _registry
from rivretrieve._internal.transport import AuthenticatedTransport, HttpMethod, TransportRequest, TransportResponse

_STATION = "109.42.0"
_PRODUCT = "discharge_daily_mean"
_SECRET = "credential-secret-sentinel"


def _register_no_nve(
    monkeypatch: pytest.MonkeyPatch,
    artifact_factory: Callable[..., PackagedCatalogArtifact],
):
    monkeypatch.setattr(discovery, "_DEFAULT_PROVIDER_REGISTRATION_ENABLED", False)
    artifact = artifact_factory("credential_test")
    artifact = replace(
        artifact,
        provider_info={**artifact.provider_info, "provider_id": "no_nve"},
        products=artifact.products.with_columns(
            pl.lit("no_nve").alias("provider_id"),
            pl.lit(_PRODUCT).alias("product_id"),
            pl.lit("STAGE").alias("native_id"),
        ),
        stations=artifact.stations.with_columns(
            pl.lit("no_nve").alias("provider_id"),
            pl.lit(_STATION).alias("station_id"),
        ),
        station_products=artifact.station_products.with_columns(
            pl.lit("no_nve").alias("provider_id"),
            pl.lit(_STATION).alias("station_id"),
            pl.lit(_PRODUCT).alias("product_id"),
        ),
    )
    from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
    from rivretrieve._internal.providers.no_nve.series import describe_series

    native = describe_series(_STATION, 1001, 2, 1440, "Mean", "m³/s", origin="catalogue")
    artifact = replace(
        artifact,
        source_descriptions=SourceDescriptions(
            provider_id="no_nve",
            descriptions=(
                SourceDescription(
                    product_id=_PRODUCT,
                    identity_key=("HydAPI.version", "1001", "2", "1440"),
                    identity=native.identity,
                    variant="2",
                    facts=native.facts,
                ),
            ),
        ),
    )
    assert isinstance(no_nve_declaration.observations, LiveStages)
    _registry.register(
        "no_nve",
        artifact,
        engine_provider_module=no_nve_declaration.observations.stages,
        required_credentials=no_nve_declaration.required_credentials,
        credential_headers=no_nve_declaration.credential_headers,
    )
    return rr.pick(
        rr.find(provider="no_nve", station=_STATION, quantity="discharge", frequency="daily", statistic="mean"),
        variant="2",
    )


def _recording(retained_evidence_root: Path):
    return read_recording(
        retained_evidence_root
        / "tests/test_data"
        / "no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json"
    )


class _CapturingReplay:
    def __init__(self, retained_evidence_root: Path) -> None:
        self.replay = ReplayTransport((_recording(retained_evidence_root),))
        self.headers: list[dict[str, str]] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.headers.append(dict(request.headers))
        return self.replay.send(request)


class _ForbiddenTransport:
    calls = 0

    def send(self, request: TransportRequest) -> TransportResponse:
        del request
        self.calls += 1
        raise AssertionError("credential preflight must prevent every source request")


def test_missing_credential_fails_before_transport_construction_or_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NVE_API_KEY", raising=False)
    selection = _register_no_nve(monkeypatch, stub_packaged_catalogue_artifact)
    constructions = 0

    def forbidden_client():
        nonlocal constructions
        constructions += 1
        return _ForbiddenTransport()

    monkeypatch.setattr(discovery, "HttpClient", forbidden_client)

    with pytest.raises(MissingCredentialError) as raised:
        rr.fetch(selection, start="2024-01-02", end="2024-01-02")

    assert raised.value.missing_by_provider == {"no_nve": ("NVE_API_KEY",)}
    assert all(
        text in str(raised.value) for text in ("no_nve", "NVE_API_KEY", "process environment", "./.env", ".env.example")
    )
    assert constructions == 0
    assert _ForbiddenTransport.calls == 0


@pytest.mark.recorded("tests/test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json")
def test_dotenv_credential_reaches_nve_header_and_never_reaches_result(
    retained_evidence_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NVE_API_KEY", raising=False)
    (tmp_path / ".env").write_text(f"NVE_API_KEY={_SECRET}\n", encoding="utf-8")
    selection = _register_no_nve(monkeypatch, stub_packaged_catalogue_artifact)
    transport = _CapturingReplay(retained_evidence_root)
    recordings: list[RecordingTransport] = []

    def recorded_authentication(base, credentials):
        recording = RecordingTransport(AuthenticatedTransport(base, credentials))
        recordings.append(recording)
        return recording

    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    monkeypatch.setattr(discovery, "AuthenticatedTransport", recorded_authentication)

    result = rr.fetch(
        selection,
        start="2024-01-02",
        end="2024-01-02",
        receipts=True,
        on_issue="ignore",
    )

    assert transport.headers[0]["X-API-Key"] == _SECRET
    assert "NVE_API_KEY" not in os.environ
    assert result.data.height == 1
    assert _SECRET not in repr(result)
    assert len(recordings) == 1
    assert _SECRET not in repr(recordings[0].recordings)
    assert recordings[0].recordings[0].request.credential_header_names == ("X-API-Key",)
    assert _SECRET.encode() not in b"".join(entry.content for entry in result.receipts.entries)


@pytest.mark.recorded("tests/test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json")
def test_process_environment_wins_over_dotenv(
    retained_evidence_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NVE_API_KEY", "environment-value")
    (tmp_path / ".env").write_text("NVE_API_KEY=file-value\n", encoding="utf-8")
    selection = _register_no_nve(monkeypatch, stub_packaged_catalogue_artifact)
    transport = _CapturingReplay(retained_evidence_root)
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    rr.fetch(selection, start="2024-01-02", end="2024-01-02", on_issue="ignore")

    assert transport.headers[0]["X-API-Key"] == "environment-value"
    assert "file-value" not in repr(transport.headers)


def test_blank_process_environment_shadows_dotenv_and_remains_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NVE_API_KEY", "")
    (tmp_path / ".env").write_text("NVE_API_KEY=file-value\n", encoding="utf-8")
    selection = _register_no_nve(monkeypatch, stub_packaged_catalogue_artifact)
    monkeypatch.setattr(
        discovery,
        "HttpClient",
        lambda: (_ for _ in ()).throw(AssertionError("transport must not be constructed")),
    )

    providers = rr.providers()
    assert providers.filter(pl.col("provider_id") == "no_nve").item(0, "access") == "missing NVE_API_KEY"
    with pytest.raises(MissingCredentialError):
        rr.fetch(selection, start="2024-01-02", end="2024-01-02")


def test_committed_environment_template_stays_unresolved_when_copied_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("NVE_API_KEY", "ANA_IDENTIFICADOR", "ANA_SENHA"):
        monkeypatch.delenv(name, raising=False)
    template = Path(__file__).parents[1] / ".env.example"
    (tmp_path / ".env").write_bytes(template.read_bytes())

    access = dict(rr.providers().select("provider_id", "access").iter_rows())
    assert access["no_nve"] == "missing NVE_API_KEY"
    assert access["br_ana"] == "missing ANA_IDENTIFICADOR, ANA_SENHA"

    _registry.clear()
    selection = _register_no_nve(monkeypatch, stub_packaged_catalogue_artifact)
    monkeypatch.setattr(
        discovery,
        "HttpClient",
        lambda: (_ for _ in ()).throw(AssertionError("transport must not be constructed")),
    )
    with pytest.raises(MissingCredentialError):
        rr.fetch(selection, start="2024-01-02", end="2024-01-02")


@pytest.mark.parametrize(
    ("status_code", "severity", "expected_code", "names_credential"),
    [
        (403, "error", "source.request_failed", True),
        (404, "warning", "source.http_not_found", False),
    ],
)
def test_credential_echo_preserves_safe_status_and_exposes_no_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
    status_code: int,
    severity: str,
    expected_code: str,
    names_credential: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NVE_API_KEY", _SECRET)
    selection = _register_no_nve(monkeypatch, stub_packaged_catalogue_artifact)

    class CredentialEchoResponse:
        def send(self, request: TransportRequest) -> TransportResponse:
            return TransportResponse(
                content=f"source echoed {_SECRET}".encode(),
                status_code=status_code,
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
                content_type="text/plain",
                url=request.url,
                request_parameters={} if request.params is None else request.params,
            )

    monkeypatch.setattr(discovery, "HttpClient", CredentialEchoResponse)

    with pytest.warns(RuntimeWarning) as captured:
        result = rr.fetch(selection, start="2024-01-02", end="2024-01-02", receipts=True)

    assert result.data.is_empty()
    source_issues = tuple(issue for issue in result.issues if issue.code.startswith("source."))
    assert len(source_issues) == 1
    assert len(captured) == 1
    assert source_issues[0].severity == severity
    assert source_issues[0].code == expected_code
    assert f"HTTP {status_code}" in source_issues[0].message
    assert ("NVE_API_KEY" in source_issues[0].message) is names_credential
    public_text = repr((result, tuple(str(item.message) for item in captured)))
    assert _SECRET not in public_text
    assert result.receipts.entries == ()


def test_providers_reloads_the_working_dotenv_each_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("NVE_API_KEY", "ANA_IDENTIFICADOR", "ANA_SENHA"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("NVE_API_KEY=first\n", encoding="utf-8")

    first = rr.providers()
    env_file.write_text("ANA_IDENTIFICADOR=id\nANA_SENHA=password\n", encoding="utf-8")
    second = rr.providers()

    first_access = dict(first.select("provider_id", "access").iter_rows())
    second_access = dict(second.select("provider_id", "access").iter_rows())
    assert first_access["no_nve"] == "ready"
    assert first_access["br_ana"] == "missing ANA_IDENTIFICADOR, ANA_SENHA"
    assert second_access["no_nve"] == "missing NVE_API_KEY"
    assert second_access["br_ana"] == "ready"


def test_import_and_open_provider_discovery_need_no_credentials(tmp_path: Path) -> None:
    environment = os.environ.copy()
    for name in ("NVE_API_KEY", "ANA_IDENTIFICADOR", "ANA_SENHA"):
        environment.pop(name, None)
    root = Path(__file__).parents[1]
    environment["PYTHONPATH"] = str(root / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import rivretrieve as rr; "
                "selection = rr.find(provider='usgs_nwis', quantity='discharge', frequency='daily', statistic='mean'); "
                "assert selection.series"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def _admitted_protocol_artifact(artifact):
    from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
    from rivretrieve._internal.source_series import PhysicalFacts, SourceIdentity, known, stable_id

    provider = artifact.provider_info["provider_id"]
    descriptions = []
    for product in artifact.products["product_id"]:
        descriptions.append(
            SourceDescription(
                product_id=product,
                identity=SourceIdentity(
                    namespace="protocol.fixture", origin="mapping", evidence=("protocol-only typed fixture",)
                ),
                facts=(
                    PhysicalFacts(
                        facts_id=stable_id(provider, product, "fixture"),
                        quantity=known("discharge", "protocol-only typed fixture"),
                        source_unit=known("m3/s", "protocol-only typed fixture"),
                        normalized_unit="m3/s",
                    ),
                ),
            )
        )
    return replace(
        artifact, source_descriptions=SourceDescriptions(provider_id=provider, descriptions=tuple(descriptions))
    )


def test_fetch_by_provider_preflights_every_selected_provider_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery, "_DEFAULT_PROVIDER_REGISTRATION_ENABLED", False)
    for name in ("FIRST_TOKEN", "SECOND_USER", "SECOND_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    _registry.register(
        "first_provider",
        _admitted_protocol_artifact(stub_packaged_catalogue_artifact("first_provider")),
        required_credentials=("FIRST_TOKEN",),
    )
    _registry.register(
        "second_provider",
        _admitted_protocol_artifact(stub_packaged_catalogue_artifact("second_provider")),
        required_credentials=("SECOND_USER", "SECOND_PASSWORD"),
    )
    monkeypatch.setattr(
        discovery,
        "HttpClient",
        lambda: (_ for _ in ()).throw(AssertionError("transport must not be constructed")),
    )

    with pytest.raises(MissingCredentialError) as raised:
        rr.fetch_by_provider(rr.find(quantity="discharge"), start="2025-01-01", end="2025-01-02")

    assert raised.value.missing_by_provider == {
        "first_provider": ("FIRST_TOKEN",),
        "second_provider": ("SECOND_USER", "SECOND_PASSWORD"),
    }


@pytest.mark.parametrize("status", [401, 403, 404, 302])
def test_rejected_exchange_is_isolated_by_public_fetch(
    monkeypatch,
    tmp_path,
    stub_packaged_catalogue_artifact,
    status,
):
    from rivretrieve._internal.transport import HttpClient

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EXCHANGE_ID", _SECRET)
    monkeypatch.setenv("EXCHANGE_PASSWORD", "password-sentinel")
    selection = _register_exchange(monkeypatch, stub_packaged_catalogue_artifact)
    calls = []

    def sender(request, timeout_seconds):
        calls.append(request.url)
        return b"rejected", status, "text/plain"

    monkeypatch.setattr(discovery, "HttpClient", lambda: HttpClient(sender=sender))
    result = rr.fetch(selection, start="2024-01-02", end="2024-01-02", receipts=True, on_issue="ignore")
    assert calls == ["https://hydapi.nve.no/token"]
    assert result.data.columns == [
        "time",
        "time_zone",
        "station_id",
        "product_id",
        "series_id",
        "facts_id",
        "quantity",
        "source_unit",
        "unit",
        "value",
    ]
    assert result.data.is_empty()
    assert result.receipts.entries == ()
    issues = [issue for issue in result.issues if issue.code == "source.request_failed"]
    assert len(issues) == 1
    assert issues[0].severity == "error"
    if status in (401, 403):
        assert "EXCHANGE_ID" in issues[0].message
    assert _SECRET not in repr(result)


def _register_exchange(monkeypatch, artifact_factory, series=None, origin="https://hydapi.nve.no"):
    """Protocol-only exchange over admitted NVE bytes, not a claim about NVE authentication."""
    from rivretrieve._internal.authentication import ExchangeSpec
    from rivretrieve._internal.providers.registration import CredentialExchangeBinding, CredentialHeaderBinding

    _register_no_nve(monkeypatch, artifact_factory)
    record = _registry.get("no_nve")
    artifact = record._artifact
    _registry.clear()
    if series is not None:
        artifact = replace(
            artifact,
            stations=pl.concat(
                [
                    artifact.stations.with_columns(pl.lit(station).alias("station_id"))
                    for station in dict.fromkeys(station for station, product in series)
                ]
            ),
            products=pl.concat(
                [
                    artifact.products.with_columns(pl.lit(product).alias("product_id"))
                    for product in dict.fromkeys(product for station, product in series)
                ]
            ),
            station_products=pl.concat(
                [
                    artifact.station_products.with_columns(
                        pl.lit(station).alias("station_id"), pl.lit(product).alias("product_id")
                    )
                    for station, product in series
                ]
            ),
        )
    assert isinstance(no_nve_declaration.observations, LiveStages)
    spec = ExchangeSpec(f"{origin}/token", ("token",), "Bearer", 3600, 3300, origin)
    _registry.register(
        "no_nve",
        artifact,
        engine_provider_module=no_nve_declaration.observations.stages,
        required_credentials=("EXCHANGE_ID", "EXCHANGE_PASSWORD"),
        credential_exchange=CredentialExchangeBinding(
            spec,
            (
                CredentialHeaderBinding("EXCHANGE_ID", "Identifier", (origin,)),
                CredentialHeaderBinding("EXCHANGE_PASSWORD", "Password", (origin,)),
            ),
        ),
    )
    return rr.pick(rr.find(provider="no_nve"), variant="2")


@pytest.mark.recorded("tests/test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json")
def test_public_declared_exchange_composes_and_sanitizes(
    retained_evidence_root: Path, monkeypatch, tmp_path, stub_packaged_catalogue_artifact
):
    from rivretrieve._internal.transport import HttpClient

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EXCHANGE_ID", "protocol-identifier-sentinel")
    monkeypatch.setenv("EXCHANGE_PASSWORD", "protocol-password-sentinel")
    selection = _register_exchange(monkeypatch, stub_packaged_catalogue_artifact)
    calls = []

    def sender(request, timeout_seconds):
        calls.append((request.url, dict(request.headers)))
        if request.url.endswith("/token"):
            return b'{"token":"protocol-bearer-sentinel"}', 200, "application/json"
        return _recording(retained_evidence_root).content, 200, "application/json"

    monkeypatch.setattr(discovery, "HttpClient", lambda: HttpClient(sender=sender, sleeper=lambda seconds: None))
    result = rr.fetch(selection, start="2024-01-02", end="2024-01-02", receipts=True, on_issue="ignore")
    assert len(calls) == 2
    assert calls[0][1]["Identifier"] == "protocol-identifier-sentinel"
    assert calls[0][1]["Password"] == "protocol-password-sentinel"
    assert calls[1][1]["Authorization"] == "Bearer protocol-bearer-sentinel"
    assert result.data.height == 1
    for secret in ("protocol-identifier-sentinel", "protocol-password-sentinel", "protocol-bearer-sentinel"):
        assert secret not in repr(result)
        assert secret.encode() not in b"".join(entry.content for entry in result.receipts.entries)


class _ExchangeClock:
    value = 100.0

    def monotonic(self):
        return self.value

    def utcnow(self):
        return datetime(2026, 1, 1, tzinfo=UTC)


def _exchange_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EXCHANGE_ID", "protocol-identifier-sentinel")
    monkeypatch.setenv("EXCHANGE_PASSWORD", "protocol-password-sentinel")


@pytest.mark.parametrize("elapsed, exchanges", [(3299, 1), (3300, 2), (3601, 2)])
@pytest.mark.recorded(
    "tests/test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_12.210.0_1003_1440_2025-07-08_2025-07-14.recording.json",
)
def test_public_exchange_reuses_and_refreshes_across_stations(
    retained_evidence_root: Path,
    monkeypatch,
    tmp_path,
    stub_packaged_catalogue_artifact,
    elapsed,
    exchanges,
):
    from rivretrieve._internal.authentication import CredentialExchangeTransport
    from rivretrieve._internal.transport import HttpClient

    _exchange_environment(monkeypatch, tmp_path)
    selection = _register_exchange(
        monkeypatch,
        stub_packaged_catalogue_artifact,
        (("109.42.0", _PRODUCT), ("12.210.0", _PRODUCT)),
    )
    clock = _ExchangeClock()
    calls = []
    captures = []

    def sender(request, timeout_seconds):
        calls.append(request)
        if request.url.endswith("/token"):
            return b'{"token":"protocol-bearer-sentinel"}', 200, "application/json"
        station = request.params["StationId"]
        recording = (
            _recording(retained_evidence_root)
            if station == _STATION
            else read_recording(
                retained_evidence_root
                / "tests/test_data"
                / "no_nve_12.210.0_1003_1440_2025-07-08_2025-07-14.recording.json"
            )
        )
        clock.value = 100.0 + elapsed
        return recording.content, recording.status_code, recording.content_type

    def recorded_exchange(*args):
        capture = RecordingTransport(CredentialExchangeTransport(*args))
        captures.append(capture)
        return capture

    monkeypatch.setattr(discovery, "HttpClient", lambda: HttpClient(sender=sender, clock=clock, sleeper=lambda _: None))
    monkeypatch.setattr(discovery, "_SystemClock", lambda: clock)
    monkeypatch.setattr(discovery, "CredentialExchangeTransport", recorded_exchange)
    result = rr.fetch(selection, start="2024-01-02", end="2024-01-02", receipts=True, on_issue="ignore")
    assert sum(request.url.endswith("/token") for request in calls) == exchanges
    assert len(calls) == 2 + exchanges
    assert result.data["station_id"].unique().to_list() == ["109.42.0"]
    assert any(issue.code == "source.http_not_found" for issue in result.issues)
    assert len(captures) == 1
    recordings = captures[0].recordings
    assert len(recordings) == 2
    assert sum(len(recording.prerequisite_calls) for recording in recordings) == exchanges
    assert all(recording.request.credential_header_names == ("Authorization",) for recording in recordings)
    for secret in ("protocol-identifier-sentinel", "protocol-password-sentinel", "protocol-bearer-sentinel"):
        assert secret not in repr((result, recordings, captures))


@pytest.mark.recorded("tests/test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json")
def test_public_exchange_failure_does_not_cancel_independent_station(
    retained_evidence_root: Path,
    monkeypatch,
    tmp_path,
    stub_packaged_catalogue_artifact,
):
    from rivretrieve._internal.transport import HttpClient

    _exchange_environment(monkeypatch, tmp_path)
    selection = _register_exchange(
        monkeypatch,
        stub_packaged_catalogue_artifact,
        (("0.protocol", _PRODUCT), ("109.42.0", _PRODUCT)),
    )
    calls = []

    def sender(request, timeout_seconds):
        calls.append(request.url)
        if len(calls) == 1:
            return b"denied", 401, "text/plain"
        if request.url.endswith("/token"):
            return b'{"token":"protocol-bearer-sentinel"}', 200, "application/json"
        return (
            _recording(retained_evidence_root).content,
            200,
            "application/json",
        )

    monkeypatch.setattr(discovery, "HttpClient", lambda: HttpClient(sender=sender, sleeper=lambda _: None))
    result = rr.fetch(selection, start="2024-01-02", end="2024-01-02", on_issue="ignore")
    assert len(calls) == 3
    assert result.data["station_id"].unique().to_list() == ["109.42.0"]
    assert len([issue for issue in result.issues if issue.code == "source.request_failed"]) == 1


@pytest.mark.parametrize("identifier", [None, "", "environment-identifier"])
def test_public_exchange_environment_precedence_and_preflight(
    monkeypatch,
    tmp_path,
    stub_packaged_catalogue_artifact,
    identifier,
):
    from rivretrieve._internal.transport import HttpClient

    _exchange_environment(monkeypatch, tmp_path)
    (tmp_path / ".env").write_text("EXCHANGE_ID=file-identifier\nEXCHANGE_PASSWORD=file-password\n")
    if identifier is None:
        monkeypatch.delenv("EXCHANGE_ID")
    else:
        monkeypatch.setenv("EXCHANGE_ID", identifier)
    selection = _register_exchange(monkeypatch, stub_packaged_catalogue_artifact)
    calls = []

    def sender(request, timeout_seconds):
        calls.append(request)
        return b"denied", 401, "text/plain"

    def client():
        assert identifier != "", "missing credential must precede construction"
        return HttpClient(sender=sender)

    monkeypatch.setattr(discovery, "HttpClient", client)
    if identifier == "":
        with pytest.raises(MissingCredentialError) as raised:
            rr.fetch(selection, start="2024-01-02", end="2024-01-02")
        assert raised.value.missing_by_provider == {"no_nve": ("EXCHANGE_ID",)}
        assert not calls
    else:
        rr.fetch(selection, start="2024-01-02", end="2024-01-02", on_issue="ignore")
        assert calls[0].headers["Identifier"] == (identifier or "file-identifier")
        assert calls[0].headers["Password"] == "protocol-password-sentinel"


@pytest.mark.parametrize("unsafe_call", ["exchange", "data"])
def test_public_exchange_secret_echo_is_not_retained(
    monkeypatch,
    tmp_path,
    stub_packaged_catalogue_artifact,
    unsafe_call,
    caplog,
):
    from rivretrieve._internal.authentication import CredentialExchangeTransport
    from rivretrieve._internal.transport import HttpClient

    _exchange_environment(monkeypatch, tmp_path)
    selection = _register_exchange(monkeypatch, stub_packaged_catalogue_artifact)
    captures = []

    def sender(request, timeout_seconds):
        if request.url.endswith("/token"):
            if unsafe_call == "exchange":
                raise RuntimeError("protocol-identifier-sentinel protocol-password-sentinel")
            return b'{"token":"protocol-bearer-sentinel"}', 200, "application/json"
        return b"protocol-bearer-sentinel protocol-password-sentinel", 200, "text/plain"

    def recorded_exchange(*args):
        capture = RecordingTransport(CredentialExchangeTransport(*args))
        captures.append(capture)
        return capture

    monkeypatch.setattr(discovery, "HttpClient", lambda: HttpClient(sender=sender, sleeper=lambda _: None))
    monkeypatch.setattr(discovery, "CredentialExchangeTransport", recorded_exchange)
    result = rr.fetch(selection, start="2024-01-02", end="2024-01-02", receipts=True, on_issue="ignore")
    assert result.data.is_empty()
    assert result.receipts.entries == ()
    assert captures[0].recordings == ()
    for secret in ("protocol-identifier-sentinel", "protocol-password-sentinel", "protocol-bearer-sentinel"):
        assert secret not in repr((result, captures)) + caplog.text


@pytest.mark.parametrize("origin", ["http://hydapi.nve.no", "https://hydapi.nve.no:444", "https://sub.hydapi.nve.no"])
@pytest.mark.recorded("tests/test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json")
def test_public_exchange_exact_origin_never_forwards_credentials(
    retained_evidence_root: Path,
    monkeypatch,
    tmp_path,
    stub_packaged_catalogue_artifact,
    origin,
):
    from rivretrieve._internal.transport import HttpClient

    _exchange_environment(monkeypatch, tmp_path)
    selection = _register_exchange(monkeypatch, stub_packaged_catalogue_artifact, origin=origin)
    calls = []

    def sender(request, timeout_seconds):
        calls.append(request)
        return _recording(retained_evidence_root).content, 200, "application/json"

    monkeypatch.setattr(discovery, "HttpClient", lambda: HttpClient(sender=sender))
    result = rr.fetch(selection, start="2024-01-02", end="2024-01-02", on_issue="ignore")
    assert result.data.height == 1
    assert len(calls) == 1
    assert set(calls[0].headers) == {"Accept", "User-Agent"}


@pytest.mark.parametrize("redirected_call", ["exchange", "data"])
def test_public_exchange_real_redirect_refusal(
    monkeypatch,
    tmp_path,
    stub_packaged_catalogue_artifact,
    redirected_call,
):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from importlib import import_module
    from threading import Thread

    _exchange_environment(monkeypatch, tmp_path)
    targets = []

    class Target(BaseHTTPRequestHandler):
        def do_GET(self):
            targets.append(dict(self.headers))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format, *args):
            pass

    target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
    target_thread = Thread(target=target.serve_forever, daemon=True)
    target_thread.start()

    class Source(BaseHTTPRequestHandler):
        def do_GET(self):
            if (redirected_call == "exchange" and self.path == "/token") or (
                redirected_call == "data" and self.path.startswith("/data")
            ):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{target.server_port}/target")
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"token":"protocol-bearer-sentinel"}')

        def log_message(self, format, *args):
            pass

    source = ThreadingHTTPServer(("127.0.0.1", 0), Source)
    source_thread = Thread(target=source.serve_forever, daemon=True)
    source_thread.start()
    origin = f"http://127.0.0.1:{source.server_port}"
    try:
        selection = _register_exchange(monkeypatch, stub_packaged_catalogue_artifact, origin=origin)
        fetch_module = import_module("rivretrieve._internal.providers.no_nve.fetch")
        monkeypatch.setattr(fetch_module, "_URL", f"{origin}/data")
        result = rr.fetch(selection, start="2024-01-02", end="2024-01-02", receipts=True, on_issue="ignore")
        assert result.data.is_empty()
        assert result.receipts.entries == ()
        assert targets == []
        assert any(
            issue.details is not None and issue.details["failure_reason"] == f"{redirected_call}_redirect_refused"
            for issue in result.issues
            if issue.code == "source.request_failed"
        )
    finally:
        source.shutdown()
        target.shutdown()
        source.server_close()
        target.server_close()
        source_thread.join()
        target_thread.join()


def test_public_exchange_issue_exception_is_sanitized(
    monkeypatch,
    tmp_path,
    stub_packaged_catalogue_artifact,
    caplog,
):
    import traceback

    from rivretrieve._internal.issues import IssuePolicyError
    from rivretrieve._internal.transport import HttpClient

    _exchange_environment(monkeypatch, tmp_path)
    selection = _register_exchange(monkeypatch, stub_packaged_catalogue_artifact)

    def sender(request, timeout_seconds):
        raise RuntimeError("protocol-password-sentinel")

    monkeypatch.setattr(discovery, "HttpClient", lambda: HttpClient(sender=sender))
    with pytest.raises(IssuePolicyError) as raised:
        rr.fetch(selection, start="2024-01-02", end="2024-01-02", on_issue="raise")
    rendered = "".join(traceback.format_exception(raised.value))
    assert "protocol-password-sentinel" not in rendered + repr(raised.value) + caplog.text
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


@pytest.mark.recorded("tests/test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json")
def test_public_exchange_cache_contains_only_observations(
    retained_evidence_root: Path,
    monkeypatch,
    tmp_path,
    stub_packaged_catalogue_artifact,
):
    from rivretrieve._internal.transport import HttpClient

    _exchange_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(discovery, "user_cache_dir", lambda _: str(tmp_path / "cache"))
    selection = _register_exchange(monkeypatch, stub_packaged_catalogue_artifact)
    calls = []

    def sender(request, timeout_seconds):
        calls.append(request.url)
        if request.url.endswith("/token"):
            return b'{"token":"protocol-bearer-sentinel"}', 200, "application/json"
        return _recording(retained_evidence_root).content, 200, "application/json"

    monkeypatch.setattr(discovery, "HttpClient", lambda: HttpClient(sender=sender, sleeper=lambda _: None))
    refreshed = rr.fetch(selection, start="2024-01-02", end="2024-01-02", cache="refresh", on_issue="ignore")
    reused = rr.fetch(selection, start="2024-01-02", end="2024-01-02", cache="reuse", receipts=True, on_issue="ignore")
    from polars.testing import assert_frame_equal

    assert_frame_equal(refreshed.data, reused.data)
    assert len(calls) == 2
    cache_files = tuple(path for path in (tmp_path / "cache").rglob("*") if path.is_file())
    assert cache_files
    retained = b"".join(path.read_bytes() for path in cache_files) + repr((refreshed, reused)).encode()
    for secret in (b"protocol-identifier-sentinel", b"protocol-password-sentinel", b"protocol-bearer-sentinel"):
        assert secret not in retained


def test_public_exchange_missing_both_credentials_prevents_network(
    monkeypatch,
    tmp_path,
    stub_packaged_catalogue_artifact,
):
    monkeypatch.chdir(tmp_path)
    for name in ("EXCHANGE_ID", "EXCHANGE_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    selection = _register_exchange(monkeypatch, stub_packaged_catalogue_artifact)
    monkeypatch.setattr(discovery, "HttpClient", lambda: pytest.fail("transport constructed before preflight"))
    with pytest.raises(MissingCredentialError) as raised:
        rr.fetch(selection, start="2024-01-02", end="2024-01-02")
    assert raised.value.missing_by_provider == {"no_nve": ("EXCHANGE_ID", "EXCHANGE_PASSWORD")}


@pytest.mark.parametrize(
    "environment,file_value,expected",
    [
        (None, None, None),
        (None, "file-key", "file-key"),
        ("environment-key", "file-key", "environment-key"),
        ("", "file-key", None),
    ],
)
def test_usgs_optional_key_resolution_and_origin_isolation(
    monkeypatch,
    tmp_path,
    stub_packaged_catalogue_artifact,
    environment,
    file_value,
    expected,
):
    from rivretrieve._internal.providers.registration import register_manifest
    from rivretrieve._internal.providers.usgs_nwis.declaration import declaration
    from rivretrieve._internal.transport import HttpClient

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery, "_DEFAULT_PROVIDER_REGISTRATION_ENABLED", False)
    monkeypatch.delenv("USGS_API_KEY", raising=False)
    if environment is not None:
        monkeypatch.setenv("USGS_API_KEY", environment)
    if file_value is not None:
        (tmp_path / ".env").write_text(f"USGS_API_KEY={file_value}\n")
    artifact = stub_packaged_catalogue_artifact("credential_test")
    artifact = replace(artifact, provider_info={**artifact.provider_info, "provider_id": "usgs_nwis"})
    register_manifest(
        _registry,
        ("usgs_nwis",),
        declaration_loader=lambda _: declaration,
        artifact_loader=lambda _: artifact,
    )
    handle = _registry.get("usgs_nwis")
    assert handle.required_credentials == ()
    assert handle.optional_credentials == ("USGS_API_KEY",)
    assert rr.providers().row(0, named=True) == {
        "provider_id": "usgs_nwis",
        "credentials": [],
        "access": "open",
    }
    values = discovery._resolve_credentials(("usgs_nwis",), require_all=True)["usgs_nwis"]
    assert values == ({} if expected is None else {"USGS_API_KEY": expected})
    calls = []

    def sender(request, timeout_seconds):
        calls.append(request)
        return b"{}", 200, "application/json"

    monkeypatch.setattr(discovery, "HttpClient", lambda: HttpClient(sender=sender))
    transport = discovery._credentialed_transport("usgs_nwis", values)
    for origin in (
        "https://api.waterdata.usgs.gov",
        "http://api.waterdata.usgs.gov",
        "https://api.waterdata.usgs.gov:444",
        "https://other.test",
        "https://waterservices.usgs.gov",
        "https://sub.api.waterdata.usgs.gov",
    ):
        transport.send(TransportRequest(method=HttpMethod.GET, url=f"{origin}/ogcapi/v1/collections/daily/items"))
    assert calls[0].headers.get("X-Api-Key") == expected
    assert all("X-Api-Key" not in call.headers for call in calls[1:])


@pytest.mark.parametrize("credentials", [["TOKEN"], ("",), ("lowercase",), ("TOKEN", "TOKEN"), (1,)])
def test_malformed_optional_credentials_are_refused(tmp_path, credentials):
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.registration import CatalogueOnly, ProviderDeclaration, load_manifest

    declaration = ProviderDeclaration(tmp_path, CatalogueOnly(), optional_credentials=credentials)
    with pytest.raises(FatalContractError, match="malformed optional credentials"):
        load_manifest(("xx_test",), declaration_loader=lambda _: declaration)


def test_required_and_optional_credentials_cannot_overlap(tmp_path):
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.registration import CatalogueOnly, ProviderDeclaration, load_manifest

    declaration = ProviderDeclaration(
        tmp_path,
        CatalogueOnly(),
        required_credentials=("TOKEN",),
        optional_credentials=("TOKEN",),
    )
    with pytest.raises(FatalContractError, match="required and optional credentials overlap"):
        load_manifest(("xx_test",), declaration_loader=lambda _: declaration)


def test_optional_key_does_not_satisfy_or_block_required_credentials(
    monkeypatch,
    tmp_path,
    stub_packaged_catalogue_artifact,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REQUIRED_KEY", raising=False)
    monkeypatch.setenv("OPTIONAL_KEY", "optional-value")
    _registry.register(
        "credential_test",
        stub_packaged_catalogue_artifact("credential_test"),
        required_credentials=("REQUIRED_KEY",),
        optional_credentials=("OPTIONAL_KEY",),
    )
    with pytest.raises(MissingCredentialError) as raised:
        discovery._resolve_credentials(("credential_test",), require_all=True)
    assert raised.value.missing_by_provider == {"credential_test": ("REQUIRED_KEY",)}
    monkeypatch.setenv("REQUIRED_KEY", "required-value")
    monkeypatch.delenv("OPTIONAL_KEY")
    assert discovery._resolve_credentials(("credential_test",), require_all=True) == {
        "credential_test": {"REQUIRED_KEY": "required-value"},
    }
