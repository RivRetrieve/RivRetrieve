"""Synthetic access-boundary cases; captured archive evidence lives in separate tests."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import polars.testing as pl_testing
import pytest
import requests

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.coverage import RequestedInterval
from rivretrieve._internal.driver import _padded_interval
from rivretrieve._internal.engine import WindowEndpoint, _make_fetch_window
from rivretrieve._internal.transport import HttpClient, HttpMethod, TransportFailure, TransportRequest

NOW = datetime(2026, 9, 20, tzinfo=UTC)
REST = "https://api.existenz.ch/apiv1/hydro/daterange"
ARCHIVE = "https://influx.konzept.space/api/v2/query"
CSV = b"_time,_value,_field,_measurement,loc\n2024-01-01T00:00:00Z,108.045,flow,hydro,2018\n"


@pytest.fixture(autouse=True)
def fixed_clock_and_safe_credential(monkeypatch):
    from rivretrieve._internal.providers.ch_foen import access
    from rivretrieve._internal.transport import CredentialHeader

    monkeypatch.setattr(discovery._SystemClock, "utcnow", lambda self: NOW)
    monkeypatch.setattr(
        access,
        "_SHARED_ARCHIVE_CREDENTIAL",
        CredentialHeader("Authorization", "Token SOURCE-READONLY-SENTINEL", ("https://influx.konzept.space",)),
    )


def _intercept(monkeypatch, *, status=200, echo=False, fail=False, payload=CSV):
    calls = []
    secrets = []

    def send(method, url, **kwargs):
        authorization = kwargs["headers"].get("Authorization")
        if authorization:
            secrets.append(authorization)
        # Retain only safe request evidence so test diagnostics cannot reveal credentials.
        calls.append(
            (method, url, kwargs["params"], kwargs.get("data"), authorization is not None, kwargs["allow_redirects"])
        )
        if fail:
            raise requests.RequestException(authorization or "synthetic sender failure")
        content = authorization.encode() if echo and authorization else payload
        if echo == "raw" and authorization:
            content = authorization.removeprefix("Token ").encode()
        return SimpleNamespace(content=content, status_code=status, headers={"Content-Type": "application/csv"})

    monkeypatch.setattr(requests, "get", lambda url, **kw: send("GET", url, **kw))
    monkeypatch.setattr(requests, "post", lambda url, **kw: send("POST", url, **kw))
    return calls, secrets


def _fetch(start="2024-01-01", end="2024-01-31", **kwargs):
    selection = rr.find(provider="ch_foen", station="2018", quantity="discharge")
    return rr.fetch(selection, start=start, end=end, receipts=True, on_issue="ignore", **kwargs)


def _assert_secret_free(secrets, *values):
    # Boolean assertions deliberately prevent pytest from printing a real shared token.
    safe = all(
        secret not in str(value) and secret.removeprefix("Token ") not in str(value)
        for secret in secrets
        for value in values
    )
    assert safe, "credential appeared in retained output"


def _bundle_contents(result):
    with ZipFile(BytesIO(rr.to_bundle(result))) as archive:
        return tuple(archive.read(name) for name in archive.namelist())


@pytest.mark.parametrize(
    ("start", "end", "method", "endpoint"),
    [
        ("2026-09-15T00:00:00", "2026-09-16T00:00:00", "GET", REST),
        # The engine pads by two days: August 21 reaches the exact August 19 horizon.
        ("2026-08-21T00:00:00", "2026-08-22T00:00:00", "GET", REST),
        ("2026-08-20T23:59:59", "2026-08-22T00:00:00", "POST", ARCHIVE),
        ("2026-08-18T00:00:00", "2026-08-22T00:00:00", "POST", ARCHIVE),
    ],
)
def test_public_route_uses_actual_padded_start(monkeypatch, start, end, method, endpoint):
    calls, _ = _intercept(monkeypatch, status=403)
    _fetch(start, end)
    assert [(call[0], call[1]) for call in calls] == [(method, endpoint)]
    assert calls[0][4] is (method == "POST")
    if method == "POST":
        assert calls[0][5] is False
        assert calls[0][2] == {"org": "api.existenz.ch"}
        window = _padded_interval(RequestedInterval(datetime.fromisoformat(start), datetime.fromisoformat(end)))
        padded_start = window.start.isoformat() + "Z"
        padded_stop = (datetime.fromisoformat(window.end.isoformat()) + timedelta(microseconds=1)).isoformat() + "Z"
        assert f"range(start: {padded_start}, stop: {padded_stop})" in calls[0][3]


@pytest.mark.parametrize("status", [401, 403])
def test_public_archive_auth_failure_is_retained_without_rest_fallback(monkeypatch, status):
    calls, secrets = _intercept(monkeypatch, status=status)
    result = _fetch()
    assert [(call[0], call[1]) for call in calls] == [("POST", ARCHIVE)]
    assert result.data.is_empty()
    assert result.issues
    assert str(status) in str(result.issues)
    assert any("http_status" in str(issue) for issue in result.issues)
    _assert_secret_free(secrets, result, result.provenance, result.receipts, *_bundle_contents(result))


@pytest.mark.parametrize(
    ("status", "echo", "fail", "reason"),
    [
        (302, False, False, "redirect_refused"),
        (200, True, False, "retained_metadata_unsafe"),
        (200, "raw", False, "retained_metadata_unsafe"),
        (200, False, True, "terminal_sender_failure"),
    ],
)
def test_public_archive_unsafe_response_is_retained_not_exported(monkeypatch, status, echo, fail, reason):
    calls, secrets = _intercept(monkeypatch, status=status, echo=echo, fail=fail)
    result = _fetch()
    assert len(calls) == 1
    assert calls[0][0:2] == ("POST", ARCHIVE)
    assert calls[0][5] is False
    assert result.data.is_empty()
    receipts_retained = bool(result.receipts.entries)
    assert receipts_retained is False
    assert any(reason in str(issue) for issue in result.issues)
    _assert_secret_free(secrets, result, result.provenance, result.receipts, *_bundle_contents(result))


def test_public_success_keeps_receipt_and_bundle_without_credentials(monkeypatch):
    calls, secrets = _intercept(monkeypatch)
    result = _fetch()
    assert calls[0][0:2] == ("POST", ARCHIVE)
    assert result.data.height == 1
    assert result.receipts.entries[0].content == CSV
    restored = rr.from_bundle(rr.to_bundle(result))
    pl_testing.assert_frame_equal(restored.data, result.data)
    assert restored.receipts.entries[0].content == CSV
    _assert_secret_free(secrets, calls, result, result.provenance, result.receipts, *_bundle_contents(result))


def _archive_transport():
    from rivretrieve._internal.providers.ch_foen.access import compose_transport

    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 1)), WindowEndpoint.from_datetime(datetime(2024, 2, 1))
    )
    return compose_transport(HttpClient(), window, NOW)


@pytest.mark.parametrize(
    "url",
    [
        REST,
        "http://influx.konzept.space/api/v2/query",
        "https://influx.konzept.space:444/api/v2/query",
        "https://influx.konzept.space.evil.invalid/api/v2/query",
    ],
)
def test_bundled_authentication_is_scoped_to_exact_archive_origin(monkeypatch, url):
    calls, _ = _intercept(monkeypatch)
    transport = _archive_transport()
    assert transport.can_authenticate(ARCHIVE)
    assert not transport.can_authenticate(url)
    transport.send(TransportRequest(HttpMethod.POST, url))
    assert calls[0][4] is False


def test_bundled_authentication_repr_and_exception_do_not_reveal_echo(monkeypatch):
    calls, secrets = _intercept(monkeypatch, fail=True)
    transport = _archive_transport()
    with pytest.raises(TransportFailure) as caught:
        transport.send(TransportRequest(HttpMethod.POST, ARCHIVE))
    assert calls[0][4] is True
    error = caught.value
    assert error.__cause__ is None
    _assert_secret_free(secrets, repr(transport), str(error), repr(error), repr(error.request))


def test_public_archive_closed_datetime_bound_keeps_final_label(monkeypatch):
    import polars as pl

    content = (
        b"_time,_value,_field,_measurement,loc\n"
        b"2023-12-31T23:59:59.999999Z,1,flow,hydro,2018\n"
        b"2024-01-01T00:00:00Z,2,flow,hydro,2018\n"
        b"2024-01-01T00:00:00.000001Z,3,flow,hydro,2018\n"
    )
    calls, _ = _intercept(monkeypatch, payload=content)
    result = _fetch(datetime(2024, 1, 1), datetime(2024, 1, 1))
    expected = pl.DataFrame({"time": [datetime(2024, 1, 1)], "value": [2.0]})
    pl_testing.assert_frame_equal(result.data.select("time", "value"), expected)
    assert "stop: 2024-01-03T00:00:00.000001Z" in calls[0][3]
    assert result.receipts.entries[0].content == content


def test_public_recent_rest_preserves_anonymous_success(monkeypatch):
    import json

    import polars as pl

    label = datetime(2026, 9, 15)
    payload = json.dumps(
        {"payload": {"timestamp": [int(label.replace(tzinfo=UTC).timestamp())], "2018|flow": [108.045]}}
    ).encode()
    calls, secrets = _intercept(monkeypatch, payload=payload)
    result = _fetch(label, label)
    assert [(call[0], call[1], call[4]) for call in calls] == [("GET", REST, False)]
    assert secrets == []
    expected = pl.DataFrame({"time": [label], "value": [108.045]})
    pl_testing.assert_frame_equal(result.data.select("time", "value"), expected)
    assert result.receipts.entries[0].content == payload


@pytest.mark.parametrize("scheme", ["Token", "Bearer"])
@pytest.mark.parametrize("location", ["url", "params", "body"])
def test_raw_sentinel_in_ordinary_request_is_refused_and_sanitized(monkeypatch, scheme, location):
    from rivretrieve._internal.transport import AuthenticatedTransport, CredentialHeader

    raw = "SOURCE-READONLY-SENTINEL"
    credential = f"{scheme} {raw}"
    calls, _ = _intercept(monkeypatch)
    transport = AuthenticatedTransport(
        HttpClient(), (CredentialHeader("Authorization", credential, ("https://influx.konzept.space",)),)
    )
    request = TransportRequest(
        HttpMethod.POST,
        ARCHIVE + (f"?leak={raw}" if location == "url" else ""),
        {"leak": raw} if location == "params" else None,
        body=raw if location == "body" else None,
    )
    with pytest.raises(TransportFailure) as caught:
        transport.send(request)
    assert calls == []
    _assert_secret_free([credential], str(caught.value), repr(caught.value.request))
    assert caught.value.__cause__ is None
