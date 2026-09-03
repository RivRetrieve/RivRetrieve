"""record_observations : fake sender → secret-free, correctly named evidence or failed envelopes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.record_observations import credential_value, record_observations
from rivretrieve._internal.recordings import RecordingTransport, read_recording
from rivretrieve._internal.transport import (
    AuthenticatedTransport,
    CredentialHeader,
    HttpClient,
    HttpMethod,
    TransportRequest,
)

_SECRET = "SENTINEL-NOT-A-REAL-KEY"
_ORIGIN = "https://hydapi.nve.no"
_EMPTY_SERIES = (
    b'{"currentLink":"https://hydapi.nve.no/api/v1/Observations","apiVersion":"1.0",'
    b'"license":"https://data.norge.no/nlod/en","createdAt":"2026-09-03T00:00:00Z","queryTime":"00:00:00.001",'
    b'"itemCount":1,"data":[{"stationId":"1.200.0","stationName":"Lierelv","parameter":1000,'
    b'"parameterName":"Vannstand","parameterNameEng":"Stage","serieVersionNo":1,"method":"Mean","unit":"m",'
    b'"observationCount":0,"observations":[]}]}'
)


def test_credential_value_prefers_environment_then_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('OTHER=1\nNVE_API_KEY="from-file"\n', encoding="utf-8")

    assert credential_value("NVE_API_KEY", {"NVE_API_KEY": "from-env"}, env_file) == "from-env"
    assert credential_value("NVE_API_KEY", {}, env_file) == "from-file"
    with pytest.raises(FatalContractError, match="NVE_API_KEY"):
        credential_value("NVE_API_KEY", {}, tmp_path / "absent")


def test_recording_transport_reports_the_wrapped_credential_scope() -> None:
    credentialed = AuthenticatedTransport(HttpClient(), (CredentialHeader("X-API-Key", _SECRET, (_ORIGIN,)),))

    assert RecordingTransport(credentialed).can_authenticate(f"{_ORIGIN}/api/v1/Observations") is True
    assert RecordingTransport(credentialed).can_authenticate("https://other.invalid/") is False
    assert RecordingTransport(HttpClient()).can_authenticate(f"{_ORIGIN}/api/v1/Observations") is False


def test_credentialed_recording_keeps_the_header_name_and_never_the_value(tmp_path: Path) -> None:
    seen_headers: list[dict[str, str]] = []

    def sender(request, timeout_seconds):
        seen_headers.append(dict(request.headers))
        return _EMPTY_SERIES, 200, "application/json; charset=utf-8"

    (written,) = record_observations(
        "no_nve",
        ("1.200.0",),
        ("stage_daily_mean",),
        "1900-01-03T00:00:00",
        "1900-01-05T00:00:00",
        tmp_path,
        "no_nve_probe",
        credentials=(CredentialHeader("X-API-Key", _SECRET, (_ORIGIN,)),),
        transport=HttpClient(sender=sender),
    )

    assert seen_headers[0]["X-API-Key"] == _SECRET
    text = written.read_text(encoding="utf-8")
    assert _SECRET not in text
    document = json.loads(text)
    assert document["request"]["credential_header_names"] == ["X-API-Key"]
    assert "X-API-Key" not in document["request"]["ordinary_headers"]
    recording = read_recording(written)
    assert recording.content == _EMPTY_SERIES
    assert recording.request.parameters is not None
    assert recording.request.parameters["ReferenceTime"] == "1900-01-01T00:00:00Z/1900-01-07T00:00:00Z"


_DAILY_PAGE = (
    b"<p><pre>Data are continuously updated and reviewed.\n"
    b"POS.  1-8   = Date of daily flow  CCYYMMDD\n"
    b"X3H001\nVariable 100.00 Surface Water Level\n\nDATE     D AVG F/R  QUAL\n"
    b"20200101     1.257     1\nZZZZZZZZZZZZ\n</pre></p>"
)
_POINT_PAGE = (
    b"<p><pre>Data are continuously updated and reviewed.\n"
    b"POS.  1-8   = Date of measurement CCYYMMDD\n"
    b"X3H001\nVariable 100.00 Surface Water Level\n"
    b"DATE     TIME             COR.LEVEL QUA           COR.FLOW  QUA\n"
    b"20200105 000000               0.146   1               1.230   1\n</pre></p>"
)


class _Clock:
    def monotonic(self) -> float:
        return 0.0

    def utcnow(self) -> datetime:
        return datetime(2026, 9, 4, tzinfo=UTC)


def _client(status: int, body: bytes | None = None) -> HttpClient:
    def sender(request, timeout_seconds):
        if body is not None:
            return body, status, "text/html; charset=utf-8"
        page = _POINT_PAGE if (request.params or {}).get("DataType") == "Point" else _DAILY_PAGE
        return page, status, "text/html; charset=utf-8"

    return HttpClient(sender=sender, clock=_Clock(), sleeper=lambda seconds: None)


def test_recording_transport_keeps_every_exchange_in_send_order() -> None:
    transport = RecordingTransport(_client(200))
    request = TransportRequest(HttpMethod.GET, "https://source.test/a", params={"x": "1"})
    response = transport.send(request)
    transport.send(TransportRequest(HttpMethod.GET, "https://source.test/b"))

    assert response.content == _DAILY_PAGE
    assert [item.request.url for item in transport.recordings] == ["https://source.test/a", "https://source.test/b"]
    assert transport.recordings[0].request.parameters == {"x": "1"}
    assert transport.recordings[0].request.ordinary_headers == {"User-Agent": "RivRetrieve"}


def test_single_exchange_is_written_under_the_evidence_name_and_round_trips(tmp_path: Path) -> None:
    written = record_observations(
        "za_dws",
        ["X3H001"],
        ["discharge_daily_mean"],
        "2019-12-30",
        "2020-01-02",
        tmp_path,
        "daily",
        transport=_client(200),
    )

    assert written == (tmp_path / "daily.recording.json",)
    recording = read_recording(written[0])
    assert recording.status_code == 200
    assert recording.content == _DAILY_PAGE
    assert dict(recording.request.parameters or {}) == {
        "Station": "X3H001100.00",
        "DataType": "Daily",
        "StartDT": "2019-12-28",
        "EndDT": "2020-01-05",
        "SiteType": "RIV",
    }


def test_several_exchanges_are_numbered_in_send_order(tmp_path: Path) -> None:
    # Daily and Point products issue one call each.
    written = record_observations(
        "za_dws",
        ["X3H001"],
        ["discharge_daily_mean", "stage_instantaneous"],
        "2020-01-05",
        "2020-01-06",
        tmp_path,
        "both",
        transport=_client(200),
    )

    assert written == (tmp_path / "both_p1.recording.json", tmp_path / "both_p2.recording.json")
    assert [dict(read_recording(path).request.parameters or {})["DataType"] for path in written] == ["Daily", "Point"]


def test_non_2xx_exchange_is_preserved_under_the_failed_name(tmp_path: Path) -> None:
    with pytest.raises(FatalContractError, match="unexpected HTTP status 403"):
        record_observations(
            "za_dws",
            ["X3H001"],
            ["discharge_daily_mean"],
            "2019-12-30",
            "2020-01-02",
            tmp_path,
            "d",
            transport=_client(403, b"<html>Forbidden</html>"),
        )

    assert sorted(path.name for path in tmp_path.iterdir()) == ["d.failed.recording.json"]
    assert read_recording(tmp_path / "d.failed.recording.json").status_code == 403


def test_refuses_providers_without_live_stages(tmp_path: Path) -> None:
    with pytest.raises(FatalContractError, match="not a LiveStages provider"):
        record_observations("br_ana", ["1"], ["discharge_daily_mean"], "2020-01-01", "2020-01-02", tmp_path, "x")
    assert list(tmp_path.iterdir()) == []


def test_expected_non_2xx_status_is_evidence_but_any_other_still_fails(tmp_path: Path) -> None:
    # za_dws turns a 404 into an issue rather than raising, so the drive completes.
    written = record_observations(
        "za_dws",
        ["X3H001"],
        ["discharge_daily_mean"],
        "2019-12-30",
        "2020-01-02",
        tmp_path / "expected",
        "missing",
        transport=_client(404, b"<html>Not Found</html>"),
        expected_status=404,
    )
    assert written == (tmp_path / "expected" / "missing.recording.json",)
    assert read_recording(written[0]).status_code == 404

    with pytest.raises(FatalContractError, match="unexpected HTTP status 403"):
        record_observations(
            "za_dws",
            ["X3H001"],
            ["discharge_daily_mean"],
            "2019-12-30",
            "2020-01-02",
            tmp_path / "other",
            "forbidden",
            transport=_client(403, b"<html>Forbidden</html>"),
            expected_status=404,
        )
    assert sorted(path.name for path in (tmp_path / "other").iterdir()) == ["forbidden.failed.recording.json"]

    with pytest.raises(FatalContractError, match="expected_status"):
        record_observations(
            "za_dws",
            ["X3H001"],
            ["discharge_daily_mean"],
            "2020-01-01",
            "2020-01-02",
            tmp_path,
            "x",
            expected_status=42,
        )
