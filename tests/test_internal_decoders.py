import csv
import json

import pytest

from rivretrieve._internal.decoders import decode_csv, decode_json


def test_decode_json_accepts_text_and_bytes() -> None:
    assert decode_json('{"station": "A", "values": [1, 2]}') == {
        "station": "A",
        "values": [1, 2],
    }
    assert decode_json(b'{"station": "A", "values": [1, 2]}') == {
        "station": "A",
        "values": [1, 2],
    }


def test_decode_json_preserves_unicode() -> None:
    assert decode_json('{"river": "Ångermanälven", "status": "観測"}') == {
        "river": "Ångermanälven",
        "status": "観測",
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            '{"nested": {"values": [1, 2.5, true, false, null, "x"]}}',
            {"nested": {"values": [1, 2.5, True, False, None, "x"]}},
        ),
        ('[1, "two", null]', [1, "two", None]),
        ('"river"', "river"),
        ("42", 42),
        ("2.5", 2.5),
        ("true", True),
        ("null", None),
    ],
)
def test_decode_json_returns_representative_json_values(text: str, expected: object) -> None:
    result = decode_json(text)

    if expected is True or expected is None:
        assert result is expected
    else:
        assert result == expected


def test_decode_json_uses_explicit_non_utf8_encoding() -> None:
    payload = '{"station": "東京"}'.encode("shift_jis")

    assert decode_json(payload, encoding="shift_jis") == {"station": "東京"}


@pytest.mark.parametrize("content", ["", b""])
def test_decode_json_empty_input_raises_json_decode_error(
    content: bytes | str,
) -> None:
    with pytest.raises(json.JSONDecodeError):
        decode_json(content)


def test_decode_json_malformed_input_raises_json_decode_error() -> None:
    with pytest.raises(json.JSONDecodeError):
        decode_json('{"station":')


def test_decode_json_invalid_byte_encoding_raises_unicode_decode_error() -> None:
    with pytest.raises(UnicodeDecodeError):
        decode_json(bytes([0xFF]), encoding="utf-8")


@pytest.mark.parametrize("content", ["station,value\nA,1\nB,2\n", b"station,value\nA,1\nB,2\n"])
def test_decode_csv_accepts_text_and_bytes_and_preserves_header(
    content: bytes | str,
) -> None:
    assert decode_csv(content) == [
        ["station", "value"],
        ["A", "1"],
        ["B", "2"],
    ]


def test_decode_csv_preserves_unicode() -> None:
    assert decode_csv("station,river\nÅngermanälven,観測所\n") == [
        ["station", "river"],
        ["Ångermanälven", "観測所"],
    ]


def test_decode_csv_honors_quoting() -> None:
    assert decode_csv('station,note\nA,"high, rising"\nB,"said ""ok"""\n') == [
        ["station", "note"],
        ["A", "high, rising"],
        ["B", 'said "ok"'],
    ]


def test_decode_csv_honors_delimiter_override() -> None:
    assert decode_csv("station;value\nA;1\n", delimiter=";") == [
        ["station", "value"],
        ["A", "1"],
    ]


def test_decode_csv_honors_custom_dialect() -> None:
    class PipeDialect(csv.Dialect):
        delimiter = "|"
        quotechar = "'"
        escapechar = None
        doublequote = True
        skipinitialspace = False
        lineterminator = "\n"
        quoting = csv.QUOTE_MINIMAL
        strict = True

    assert decode_csv("name|note\nalpha|'left|right'\n", dialect=PipeDialect()) == [
        ["name", "note"],
        ["alpha", "left|right"],
    ]


def test_decode_csv_handles_crlf_and_quoted_embedded_newline() -> None:
    assert decode_csv('station,note\r\nA,"line one\r\nline two"\r\n') == [
        ["station", "note"],
        ["A", "line one\r\nline two"],
    ]


def test_decode_csv_uses_explicit_non_utf8_encoding() -> None:
    payload = "station,name\n1,東京\n".encode("shift_jis")

    assert decode_csv(payload, encoding="shift_jis") == [
        ["station", "name"],
        ["1", "東京"],
    ]


@pytest.mark.parametrize("content", ["", b""])
def test_decode_csv_empty_input_returns_no_rows(content: bytes | str) -> None:
    assert decode_csv(content) == []


def test_decode_csv_malformed_input_raises_csv_error() -> None:
    with pytest.raises(csv.Error):
        decode_csv('station,note\nA,"unterminated\n')


def test_decode_csv_invalid_byte_encoding_raises_unicode_decode_error() -> None:
    with pytest.raises(UnicodeDecodeError):
        decode_csv(b"station" + bytes([0x0A, 0xFF, 0x0A]), encoding="utf-8")
