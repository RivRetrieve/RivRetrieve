"""HydAPI source fidelity over legacy captures and explicit-version public recordings.

Legacy captures keep their original omitted-version request provenance. They prove
parser behavior, not that the old upstream default satisfies an all-series request.
"""

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.no_nve.config import NoNveSourceCoordinates, config
from rivretrieve._internal.providers.no_nve.parse import parse
from rivretrieve._internal.recordings import read_recording
from rivretrieve._internal.source_series import admission

_DATA = Path("tests/test_data")
_PRODUCTS = tuple(config().products)
_STATION = "1.200.0"


def _recording_path(retained_evidence_root, station, product, window):
    coordinates = config().products[product].coordinates.value
    assert isinstance(coordinates, NoNveSourceCoordinates)
    return (
        retained_evidence_root
        / _DATA
        / f"no_nve_{station}_{coordinates.parameter}_{coordinates.resolution_time}_{window}.recording.json"
    )


def _payload(retained_evidence_root, product, station=_STATION, window="2025-07-08_2025-07-14"):
    recording = read_recording(_recording_path(retained_evidence_root, station, product, window))
    unknown = UnknownOriginFact()
    return Payload(
        config().products[product].coordinates,
        ((station, product),),
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(1800, 1, 1)), WindowEndpoint.from_datetime(datetime(2030, 1, 1))
        ),
        recording.content,
        SourceCallOrigin(
            recording.request.url,
            recording.request.parameters,
            recording.status_code,
            recording.retrieved_at,
            recording.content_type,
            unknown,
            unknown,
        ),
        recording.prerequisite_calls,
    )


@pytest.mark.parametrize("product", _PRODUCTS)
def test_each_real_native_product_preserves_every_source_cell_and_identity(retained_evidence_root, product):
    payload = _payload(retained_evidence_root, product)
    source = json.loads(payload.content)["data"][0]
    parsed = parse(payload, config())
    assert parsed.rows.height == source["observationCount"]
    assert parsed.rows["value"].to_list() == [row["value"] for row in source["observations"]]
    assert parsed.rows["time"].to_list() == [
        datetime.strptime(row["time"], "%Y-%m-%dT%H:%M:%SZ") for row in source["observations"]
    ]
    assert parsed.rows["time_zone"].unique().to_list() == ["+00:00"]
    assert parsed.series[0].identity.published_id == str(source["serieVersionNo"])
    assert parsed.series[0].facts[0].source_unit.value == source["unit"]
    assert admission(parsed.series[0].facts[0]).status == "supported"
    assert parsed.outcomes[0].status.value == "success"


@pytest.mark.parametrize("product", _PRODUCTS)
def test_legacy_capture_keeps_exact_omitted_version_request_and_safe_credentials(retained_evidence_root, product):
    path = _recording_path(retained_evidence_root, _STATION, product, "2025-07-08_2025-07-14")
    recording = read_recording(path)
    assert "VersionNumber" not in recording.request.parameters
    document = json.loads(path.read_text())
    assert document["request"]["credential_header_names"] == ["X-API-Key"]
    assert "X-API-Key" not in document["request"]["ordinary_headers"]
    assert _payload(retained_evidence_root, product).content == recording.content


def test_source_quality_and_correction_codes_remain_uninterpreted_diagnostics(retained_evidence_root):
    parsed = parse(_payload(retained_evidence_root, ProductId("water_temperature_daily_mean")), config())
    assert {issue.code for issue in parsed.issues} == {"source_quality_code", "source_correction_code"}
    assert {issue.severity for issue in parsed.issues} == {"info"}
    assert "quality" not in parsed.rows.columns
    quality = next(issue for issue in parsed.issues if issue.code == "source_quality_code")
    assert quality.details["source_quality_code"] == 1
    assert quality.details["count"] == 6


def test_a_published_empty_identified_series_establishes_empty_outcome(retained_evidence_root):
    parsed = parse(
        _payload(retained_evidence_root, ProductId("stage_daily_mean"), window="1900-01-01_1900-01-07"), config()
    )
    assert parsed.rows.is_empty()
    assert parsed.outcomes[0].status.value == "empty"
    assert parsed.outcomes[0].series_id == parsed.series[0].series_id


def test_recorded_inclusive_instant_stop_and_null_values_are_preserved(retained_evidence_root):
    product = ProductId("stage_daily_mean")
    midnight = parse(_payload(retained_evidence_root, product, window="2023-03-23_2023-03-27"), config())
    day_end = parse(_payload(retained_evidence_root, product, window="2023-03-23_2023-03-27-eod"), config())
    assert midnight.rows.height == 4
    assert midnight.rows["time"].to_list()[-1] == datetime(2023, 3, 26, 11)
    assert midnight.rows["value"].null_count() == 4
    assert day_end.rows.height == 5
    assert day_end.rows["time"].to_list()[-1] == datetime(2023, 3, 27, 11)
    quality = next(issue for issue in midnight.issues if issue.code == "source_quality_code")
    assert quality.details["source_quality_code"] == 2


def test_response_aggregation_is_not_overridden_by_hourly_product_label(retained_evidence_root):
    parsed = parse(
        _payload(retained_evidence_root, ProductId("water_temperature_hourly_mean"), station="103.3.0"), config()
    )
    assert parsed.rows.height > 0
    facts = parsed.series[0].facts[0]
    assert facts.statistic.value == "instantaneous"
    assert facts.frequency.value == "hourly"
    assert facts.temporal_support.value is None


def test_unestablished_source_unit_cannot_reuse_configured_conversion(retained_evidence_root):
    original = _payload(retained_evidence_root, ProductId("stage_daily_mean"))
    assert b'"unit":"m"' in original.content
    # Clearly marked structural mutation, not a publisher recording.
    result = parse(
        replace(original, content=original.content.replace(b'"unit":"m"', b'"unit":"unrecognised-metre-label"', 1)),
        config(),
    )
    assert result.rows.is_empty()
    assert result.outcomes[0].status.value == "unsupported"
    assert result.series[0].facts[0].source_unit.value == "unrecognised-metre-label"
    assert result.issues
