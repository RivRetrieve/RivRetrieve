"""Station HydroPortail contracts : recorded source interactions → station-own rows or explicit defects."""

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.boundary_probes import BoundaryProbe, WallClockExpectation
from rivretrieve._internal.engine import (
    Payload,
    RenderedWindow,
    SourceCallOrigin,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.fr_hydroportail.config import config
from rivretrieve._internal.providers.fr_hydroportail.fetch import fetch
from rivretrieve._internal.providers.fr_hydroportail.parse import parse
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.source_series import SeriesScope

DATA = Path("tests/test_data")
PRODUCT = ProductId("discharge_instantaneous")


def _window(start, stop):
    return _make_fetch_window(
        WindowEndpoint.from_datetime(datetime.fromisoformat(start)),
        WindowEndpoint.from_datetime(datetime.fromisoformat(stop)),
    )


def _empty_payload(retained_evidence_root):
    # Genuine empty source body and original receipt, not an authored capture.
    receipt = json.loads((retained_evidence_root / DATA / "fr_hydroportail_J783301020_empty.receipt.json").read_text())
    return Payload(
        config().products[PRODUCT].coordinates,
        (("J783301020", PRODUCT),),
        _window("2023-06-01", "2023-06-08T23:59:59"),
        (retained_evidence_root / DATA / "fr_hydroportail_J783301020_empty.body").read_bytes(),
        SourceCallOrigin(
            receipt["request"]["url"],
            {},
            receipt["response"]["status"],
            datetime.fromisoformat(receipt["response"]["retrieved_at"]),
            receipt["response"]["media_type"],
            UnknownOriginFact(),
            UnknownOriginFact(),
        ),
        (),
    )


@pytest.mark.recorded("tests/test_data/fr_hydroportail_station_Q_padded.recording.json")
def test_station_own_discharge_fetch_replays_exact_non_sample_station(retained_evidence_root):
    recording = read_recording(retained_evidence_root / DATA / "fr_hydroportail_station_Q_padded.recording.json")
    fetched = fetch(
        ("1232000101",),
        (PRODUCT,),
        {PRODUCT: (RenderedWindow("30/05/2026", "04/06/2026"),)},
        _window("2026-05-30", "2026-06-04T23:59:59"),
        config(),
        ReplayTransport((recording,)),
        scope=SeriesScope(restriction="explicit", variants=("raw",)),
    )
    (payload,) = fetched.value
    assert payload.content == recording.content
    frame = parse(payload, config()).rows
    assert not frame.is_empty()
    assert frame["station_id"].unique().to_list() == ["1232000101"]


@pytest.mark.recorded("tests/test_data/fr_hydroportail_station_Q_padded.recording.json")
def test_station_own_discharge_parser_does_not_require_the_old_sample_site(retained_evidence_root):
    recording = read_recording(retained_evidence_root / DATA / "fr_hydroportail_station_Q_padded.recording.json")
    assert recording.content_type is not None
    payload = Payload(
        config().products[PRODUCT].coordinates,
        (("1232000101", PRODUCT),),
        _window("2026-05-30", "2026-06-04T23:59:59"),
        recording.content,
        SourceCallOrigin(
            recording.request.url,
            dict(recording.request.parameters or {}),
            recording.status_code,
            recording.retrieved_at,
            recording.content_type,
            UnknownOriginFact(),
            UnknownOriginFact(),
        ),
        recording.prerequisite_calls,
    )
    assert not parse(payload, config()).rows.is_empty()


@pytest.mark.recorded(
    "tests/test_data/fr_hydroportail_J783301020_empty.body",
    "tests/test_data/fr_hydroportail_J783301020_empty.receipt.json",
)
def test_valid_empty_envelope_is_not_a_source_identity_failure(retained_evidence_root):
    assert parse(_empty_payload(retained_evidence_root), config()).rows.is_empty()


@pytest.mark.parametrize(
    "field,value",
    [
        ("code", "Y2510020"),
        ("metric", "H"),
        ("unit", "m3"),
        ("statuses", "validated"),
    ],
)
@pytest.mark.recorded(
    "tests/test_data/fr_hydroportail_J783301020_empty.body",
    "tests/test_data/fr_hydroportail_J783301020_empty.receipt.json",
)
def test_empty_envelope_checks_series_contract_before_iteration(retained_evidence_root, field, value):
    payload = _empty_payload(retained_evidence_root)
    document = json.loads(payload.content)
    document["series"][field] = value
    unsupported = parse(replace(payload, content=json.dumps(document).encode()), config())
    assert unsupported.rows.is_empty()
    assert unsupported.outcomes[0].status == "unsupported"
    assert unsupported.outcomes[0].reason


@pytest.mark.recorded(
    "tests/test_data/fr_hydroportail_J783301020_empty.body",
    "tests/test_data/fr_hydroportail_J783301020_empty.receipt.json",
)
def test_empty_envelope_requires_source_utc_before_iteration(retained_evidence_root):
    payload = _empty_payload(retained_evidence_root)
    document = json.loads(payload.content)
    document["timezone"] = "Europe/Paris"
    unsupported = parse(replace(payload, content=json.dumps(document).encode()), config())
    assert unsupported.rows.is_empty()
    assert unsupported.outcomes[0].status == "unsupported"
    assert unsupported.outcomes[0].reason


@pytest.mark.recorded(
    "tests/test_data/fr_hydroportail_J783301020_empty.body",
    "tests/test_data/fr_hydroportail_J783301020_empty.receipt.json",
)
def test_empty_envelope_requires_identity_metadata_before_iteration(retained_evidence_root):
    payload = _empty_payload(retained_evidence_root)
    document = json.loads(payload.content)
    del document["series"]["code"]
    unsupported = parse(replace(payload, content=json.dumps(document).encode()), config())
    assert unsupported.rows.is_empty()
    assert unsupported.outcomes[0].status == "unsupported"
    assert unsupported.outcomes[0].reason


def _run_station_discharge_boundary(replay):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(discovery, "HttpClient", lambda: replay)
        selection = rr.find(
            provider="fr_hydroportail", station="1232000101", quantity="discharge", statistic="instantaneous"
        )
        return rr.fetch(rr.pick(selection, variant="raw"), start="2026-06-01", end="2026-06-02", on_issue="raise").data


# Three literals supplied by the independent source-only author, not this parser.
# Exact source material and authorship are recorded in the adjacent provenance document.
def station_discharge_probe(retained_evidence_root):
    return BoundaryProbe(
        ProviderId("fr_hydroportail"),
        PRODUCT,
        (read_recording(retained_evidence_root / DATA / "fr_hydroportail_station_Q_padded.recording.json"),),
        {
            "reading_count": 282,
            "first_wall_clock_time": WallClockExpectation("2026-06-01T00:00:00", "+00:00"),
            "last_wall_clock_time": WallClockExpectation("2026-06-02T18:00:00", "+00:00"),
        },
        _run_station_discharge_boundary,
    )
