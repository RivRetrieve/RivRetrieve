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
from rivretrieve._internal.transport import AuthenticatedTransport, TransportRequest, TransportResponse

_STATION = "1.200.0"
_PRODUCT = "stage_daily_mean"
_SECRET = "credential-secret-sentinel"
_DATA = Path(__file__).parent / "test_data"


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
    assert isinstance(no_nve_declaration.observations, LiveStages)
    _registry.register(
        "no_nve",
        artifact,
        engine_provider_module=no_nve_declaration.observations.stages,
        required_credentials=no_nve_declaration.required_credentials,
        credential_headers=no_nve_declaration.credential_headers,
    )
    return rr.find(provider="no_nve", station=_STATION, product=_PRODUCT)


def _recording():
    return read_recording(_DATA / "no_nve_1.200.0_1000_1440_2025-07-08_2025-07-14-eod.recording.json")


class _CapturingReplay:
    def __init__(self) -> None:
        self.replay = ReplayTransport((_recording(),))
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
        rr.fetch(selection, start="2025-07-10", end="2025-07-12")

    assert raised.value.missing_by_provider == {"no_nve": ("NVE_API_KEY",)}
    assert all(
        text in str(raised.value) for text in ("no_nve", "NVE_API_KEY", "process environment", "./.env", ".env.example")
    )
    assert constructions == 0
    assert _ForbiddenTransport.calls == 0


def test_dotenv_credential_reaches_nve_header_and_never_reaches_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NVE_API_KEY", raising=False)
    (tmp_path / ".env").write_text(f"NVE_API_KEY={_SECRET}\n", encoding="utf-8")
    selection = _register_no_nve(monkeypatch, stub_packaged_catalogue_artifact)
    transport = _CapturingReplay()
    recordings: list[RecordingTransport] = []

    def recorded_authentication(base, credentials):
        recording = RecordingTransport(AuthenticatedTransport(base, credentials))
        recordings.append(recording)
        return recording

    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    monkeypatch.setattr(discovery, "AuthenticatedTransport", recorded_authentication)

    result = rr.fetch(
        selection,
        start="2025-07-10",
        end="2025-07-12",
        receipts=True,
        on_issue="ignore",
    )

    assert transport.headers[0]["X-API-Key"] == _SECRET
    assert "NVE_API_KEY" not in os.environ
    assert result.data.height == 3
    assert _SECRET not in repr(result)
    assert len(recordings) == 1
    assert _SECRET not in repr(recordings[0].recordings)
    assert recordings[0].recordings[0].request.credential_header_names == ("X-API-Key",)
    assert _SECRET.encode() not in b"".join(entry.content for entry in result.receipts.entries)


def test_process_environment_wins_over_dotenv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stub_packaged_catalogue_artifact: Callable[..., PackagedCatalogArtifact],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NVE_API_KEY", "environment-value")
    (tmp_path / ".env").write_text("NVE_API_KEY=file-value\n", encoding="utf-8")
    selection = _register_no_nve(monkeypatch, stub_packaged_catalogue_artifact)
    transport = _CapturingReplay()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    rr.fetch(selection, start="2025-07-10", end="2025-07-12", on_issue="ignore")

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
        rr.fetch(selection, start="2025-07-10", end="2025-07-12")


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
        rr.fetch(selection, start="2025-07-10", end="2025-07-12")


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
        result = rr.fetch(selection, start="2025-07-10", end="2025-07-12", receipts=True)

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
                "selection = rr.find(provider='usgs_nwis', product='discharge_daily_mean'); "
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
        stub_packaged_catalogue_artifact("first_provider"),
        required_credentials=("FIRST_TOKEN",),
    )
    _registry.register(
        "second_provider",
        stub_packaged_catalogue_artifact("second_provider"),
        required_credentials=("SECOND_USER", "SECOND_PASSWORD"),
    )
    monkeypatch.setattr(
        discovery,
        "HttpClient",
        lambda: (_ for _ in ()).throw(AssertionError("transport must not be constructed")),
    )

    with pytest.raises(MissingCredentialError) as raised:
        rr.fetch_by_provider(rr.find(product="level"), start="2025-01-01", end="2025-01-02")

    assert raised.value.missing_by_provider == {
        "first_provider": ("FIRST_TOKEN",),
        "second_provider": ("SECOND_USER", "SECOND_PASSWORD"),
    }
