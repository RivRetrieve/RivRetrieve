"""Synthetic checks for source labels in FOEN live sensor headers."""

import pytest

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ch_foen.station_metadata import parse_live_sensor_units


def page(headers: str, *, identity: str = "1234") -> bytes:
    return (
        f"<h1>Example river <small>{identity}</small></h1>"
        '<table class="table-carousel sensors-table columns-3"><thead><tr>'
        f"{headers}</tr></thead><tbody><tr><td>1.2</td></tr></tbody></table>"
    ).encode()


def header(parameter: str, unit: str) -> str:
    return f'<th><div>{parameter}</div><div class="opacity-75">{unit}</div></th>'


def test_live_headers_preserve_labels_and_blanks_without_station_information():
    body = page(
        header("Discharge", "l/s")
        + header("Water level", "m ü. M.")
        + header("Water temperature", "")
        + header("Other source label", " m&sup3;/s ")
    )
    body += (
        '<table class="table-carousel"><thead><tr>'
        + header("Discharge", "wrong reference unit")
        + "</tr></thead></table>"
    ).encode()
    assert parse_live_sensor_units(body, "1234") == {
        "Discharge": "l/s",
        "Water level": "m ü. M.",
        "Water temperature": "",
        "Other source label": " m³/s ",
    }


@pytest.mark.parametrize("identity", ["9999", "", "1234</small><small>1234"])
def test_units_require_one_matching_station_identity(identity):
    with pytest.raises(FatalContractError):
        parse_live_sensor_units(page(header("Discharge", "l/s"), identity=identity), "1234")


def test_repeated_identical_headers_are_allowed_but_conflicts_fail():
    same = header("Discharge", "m³/s") * 2
    assert parse_live_sensor_units(page(same), "1234") == {"Discharge": "m³/s"}
    with pytest.raises(FatalContractError):
        parse_live_sensor_units(page(same + header("Discharge", "l/s")), "1234")


@pytest.mark.parametrize(
    "headers",
    [
        "<th><div>Discharge</div></th>",
        "<th><div>Discharge</div><div>l/s</div></th>",
        '<th><div><span>Discharge</span></div><div class="opacity-75">l/s</div></th>',
        '<th><div>Discharge</div><div class="opacity-75"><div>l/s</div></div></th>',
        '<th>Discharge<div>Discharge</div><div class="opacity-75">l/s</div></th>',
        '<th><div>Discharge</div><div class="opacity-75">l/s</div><div>extra</div></th>',
        '<th><div>Discharge</div><div class="opacity-75">l/s</th>',
        "<table><thead><tr>" + header("Discharge", "l/s") + "</tr></thead></table>",
    ],
)
def test_ambiguous_header_markup_fails(headers):
    with pytest.raises(FatalContractError):
        parse_live_sensor_units(page(headers), "1234")


def test_absent_headers_remain_absent_and_blank_labels_remain_blank():
    assert parse_live_sensor_units(page(""), "1234") == {}
    assert parse_live_sensor_units(page(header("", "")), "1234") == {"": ""}


@pytest.mark.parametrize(
    "body",
    [
        page(header("Discharge", "l/s"))[:-8],
        page(header("Discharge", "l/s")) + b"\xff",
        b'<h1>Example <small>1234</small></h1><table class="sensors-table"><thead><tr>',
    ],
)
def test_incomplete_markup_and_invalid_encoding_fail(body):
    with pytest.raises(FatalContractError):
        parse_live_sensor_units(body, "1234")


def test_empty_leading_corner_is_not_a_parameter_with_a_blank_unit():
    body = page("<th></th>" + header("Discharge", ""))
    assert parse_live_sensor_units(body, "1234") == {"Discharge": ""}
