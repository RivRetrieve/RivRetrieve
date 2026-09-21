"""HTML declarations select only the recorder's inspection decoder, never saved bytes."""

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rivretrieve._internal.recordings import (
    InvalidRecordingError,
    RecordingEnvelope,
    RecordingTransport,
    ReplayTransport,
    read_recording,
    write_recording,
)
from rivretrieve._internal.transport import (
    TRANSPORT_POLICY,
    ExecutedRequestEvidence,
    HttpMethod,
    TransportRequest,
    TransportResponse,
)

_MLIT_META = '<META http-equiv="Content-Type" content="text/html; charset=EUC-JP">'


class _ResponseTransport:
    def __init__(self, content: bytes, content_type: str = "text/html") -> None:
        self.content = content
        self.content_type = content_type

    def send(self, request: TransportRequest) -> TransportResponse:
        return TransportResponse(
            content=self.content,
            status_code=200,
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            content_type=self.content_type,
            url=request.url,
            request_parameters=request.params or {},
            executed_request=ExecutedRequestEvidence({"User-Agent": TRANSPORT_POLICY.user_agent}, ()),
        )


def _capture(content: bytes, content_type: str = "text/html") -> RecordingEnvelope:
    recorder = RecordingTransport(_ResponseTransport(content, content_type))
    recorder.send(TransportRequest(HttpMethod.GET, "https://example.test/data"))
    return recorder.recordings[0]


@pytest.mark.parametrize(
    "declaration",
    [
        _MLIT_META,
        '<meta charset="EUC-JP">',
        "<MeTa ChArSeT='x-euc-jp' />",
        '<meta content="text/html; charset=EUC-JP" HTTP-EQUIV=Content-Type>',
        "<meta charset=euc-jp><meta charset=cseucpkdfmtjapanese>",
        '<meta charset=euc-jp http-equiv=Content-Type content="text/html; charset=EUC-JP">',
    ],
)
def test_html_declaration_capture_write_read_replay_preserves_evidence(tmp_path: Path, declaration: str) -> None:
    content = f"<HTML>\n<HEAD>\n{declaration}<TITLE>日水位年表検索結果</TITLE></HEAD></HTML>".encode("euc-jp")
    request = TransportRequest(HttpMethod.GET, "https://example.test/data", {"station": "A"})
    source = _ResponseTransport(content, "text/html")
    recorder = RecordingTransport(source)
    response = recorder.send(request)
    assert response == source.send(request)
    recording = recorder.recordings[0]
    assert recording.content == content
    assert recording.content_type == "text/html"
    assert recording.status_code == 200
    path = tmp_path / "html.recording.json"
    write_recording(recording, path)
    assert read_recording(path) == recording
    assert ReplayTransport([path]).send(request) == response


@pytest.mark.parametrize("declaration", [_MLIT_META, '<meta charset="euc-jp">'])
@pytest.mark.parametrize("field", ["password", "api_key", "access_token"])
def test_declared_html_still_rejects_sensitive_fields(declaration: str, field: str) -> None:
    content = f'{declaration}<p>水位</p><input name="{field}" value="秘密">'.encode("euc-jp")
    recorder = RecordingTransport(_ResponseTransport(content))
    with pytest.raises(ValueError, match="secret-bearing"):
        recorder.send(TransportRequest(HttpMethod.GET, "https://example.test/data"))
    assert recorder.recordings == ()


@pytest.mark.parametrize(
    "declaration",
    [
        '<meta charset="">',
        "<meta charset>",
        '<meta charset="unknown-encoding">',
        '<meta charset="utf-7">',
        '<meta charset="utf-16">',
        '<meta charset="base64_codec">',
        '<meta charset="euc_jp">',
        '<meta charset="euc-jp" charset="utf-8">',
        '<meta charset="euc-jp" CHARSET="euc-jp">',
        '<meta http-equiv="Content-Type" http-equiv="refresh" content="value">',
        '<meta content="text/html; charset=euc-jp" content="value">',
        '<meta charset="euc-jp"><meta charset="utf-8">',
        '<meta charset="utf-8" http-equiv="Content-Type" content="text/html; charset=EUC-JP">',
        '<meta http-equiv="Content-Type" content="text/html; charset=EUC-JP; charset=utf-8">',
        '<meta http-equiv="Content-Type" content="text/html; charset=">',
        '<meta http-equiv="Content-Type">',
        '<meta content="text/html; charset=EUC-JP">',
        '<meta http-equiv="refresh" content="text/html; charset=EUC-JP">',
        '<meta charset="euc-jp>',
        "<meta charset=euc-jp",
        '<meta charset="euc-jp"junk>',
        '<meta charset="euc&#45;jp">',
        '<meta charset="euc-jp"/ junk>',
    ],
)
def test_invalid_html_declaration_is_fail_closed_even_for_ascii_content(declaration: str) -> None:
    recorder = RecordingTransport(_ResponseTransport((declaration + "<p>value</p>").encode()))
    with pytest.raises(ValueError, match="HTML"):
        recorder.send(TransportRequest(HttpMethod.GET, "https://example.test/data"))
    assert recorder.recordings == ()


@pytest.mark.parametrize("content", [b"\xff", b"\xa4", b"\x8f\xa1"])
def test_declared_html_rejects_undecodable_bytes(content: bytes) -> None:
    with pytest.raises(ValueError, match="cannot be decoded safely"):
        _capture(_MLIT_META.encode() + content)


@pytest.mark.parametrize(
    "decoy",
    [
        '<!-- <meta charset="euc-jp"> -->',
        "<script>const example = '<meta charset=euc-jp>';</script>",
        "<div title='<meta charset=euc-jp>'>value</div>",
    ],
)
def test_non_declarations_cannot_select_a_decoder(decoy: str) -> None:
    with pytest.raises(ValueError, match="cannot be decoded safely"):
        _capture((decoy + "水位").encode("euc-jp"))
    assert _capture((decoy + "水位").encode()).content == (decoy + "水位").encode()


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-32"])
def test_html_bom_keeps_precedence_over_meta(encoding: str) -> None:
    text = _MLIT_META + "<p>水位</p>"
    assert _capture(text.encode(encoding)).content == text.encode(encoding)
    with pytest.raises(ValueError, match="secret-bearing"):
        _capture((text + '<input name="password">').encode(encoding))


def test_html_http_charset_keeps_precedence_over_meta_and_bom() -> None:
    content = ("\ufeff" + _MLIT_META + "水位").encode()
    assert _capture(content, "text/html; charset=UTF-8").content == content
    with pytest.raises(ValueError, match="secret-bearing"):
        _capture(content + b'<input name="access_token">', "text/html; charset=UTF-8")


@pytest.mark.parametrize("content_type", ["text/plain", "application/xml", "application/json"])
def test_non_html_does_not_use_html_declarations(content_type: str) -> None:
    with pytest.raises(ValueError, match="cannot be decoded safely"):
        _capture((_MLIT_META + "水位").encode("euc-jp"), content_type)


@pytest.mark.parametrize("prefix", ["", '<meta name="description" content="river levels">', "<meta charset=utf8>"])
def test_utf8_html_without_legacy_encoding_is_unchanged(prefix: str) -> None:
    content = (prefix + "<p>水位</p>").encode()
    assert _capture(content).content == content


@pytest.mark.parametrize(
    "text",
    [
        _MLIT_META + '<input name="password" value="秘密">',
        '<meta charset="euc-jp"><meta charset="utf-8">',
        '<meta charset="utf-7">',
    ],
)
def test_read_and_replay_revalidate_html_safety_even_with_correct_digest(tmp_path: Path, text: str) -> None:
    path = tmp_path / "unsafe.recording.json"
    write_recording(_capture((_MLIT_META + "水位").encode("euc-jp")), path)
    document = json.loads(path.read_text())
    content = text.encode("euc-jp")
    document["response"]["content_base64"] = base64.b64encode(content).decode("ascii")
    document["response"]["sha256"] = hashlib.sha256(content).hexdigest()
    path.write_text(json.dumps(document))
    with pytest.raises(InvalidRecordingError, match="invalid response"):
        read_recording(path)
    with pytest.raises(InvalidRecordingError, match="invalid response"):
        ReplayTransport([path])


@pytest.mark.parametrize(
    "metadata",
    [
        '<meta name="description" content="The charset is UTF-8">',
        '<meta name="description" content="text/html; charset=unknown">',
        '<meta content="The charset is UTF-8">',
        '<meta name="description" content="river &amp; gauge">',
    ],
)
def test_non_declaration_metadata_does_not_select_or_reject_encoding(metadata: str) -> None:
    for declaration, encoding in [("", "utf-8"), (_MLIT_META, "euc-jp")]:
        content = (metadata + declaration + "水位").encode(encoding)
        assert _capture(content).content == content


@pytest.mark.parametrize(
    "declaration",
    [
        '<meta charset=euc-jp data-note="river &amp; gauge">',
        '<meta data-note="river &amp; gauge" charset=euc-jp>',
        '<meta data-note="charset=&amp;" charset=euc-jp>',
        '<meta http-equiv="Content-Type" content="text/html; charset=EUC-JP" data-note="river &amp; gauge">',
    ],
)
def test_unrelated_escaped_attributes_do_not_invalidate_declaration(declaration: str) -> None:
    content = (declaration + "水位").encode("euc-jp")
    assert _capture(content).content == content
    with pytest.raises(ValueError, match="secret-bearing"):
        _capture(content + b'<input name="password">')
