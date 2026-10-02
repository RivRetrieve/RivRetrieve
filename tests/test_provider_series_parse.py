"""Recorded singleton parser identity and sibling isolation."""

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from rivretrieve._internal.engine import WindowEndpoint, _make_fetch_window
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.lt_lhmt.declaration import declaration
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.source_series import ParsedSeries
from rivretrieve._internal.window_planning import plan_windows


def payload(retained_evidence_root: Path):
    recording = read_recording(retained_evidence_root / "tests/test_data/lt_lhmt_anyksciu-vms_2023-06.recording.json")
    stages = declaration.observations.stages
    products = (ProductId("discharge_daily_mean"), ProductId("stage_daily_mean"))
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2023, 6, 1)), WindowEndpoint.from_datetime(datetime(2023, 6, 30))
    )
    fetched = stages.fetch(
        ("anyksciu-vms",),
        products,
        {p: plan_windows(window, stages.window_declarations.products[p]) for p in products},
        window,
        stages.config,
        ReplayTransport((recording,)),
    )
    return stages, replace(fetched.value[0], station_products=tuple(("anyksciu-vms", p) for p in products))


def test_recorded_singletons_preserve_unspecified_identity(retained_evidence_root: Path):
    stages, source = payload(retained_evidence_root)
    parsed = stages.parse(source, stages.config)
    assert isinstance(parsed, ParsedSeries)
    assert len(parsed.series) == 2
    assert parsed.rows.height == 60
    assert all(s.identity.published_id is None for s in parsed.series)
    assert all(i.completeness == "incomplete" for i in parsed.inventories)


def test_unsupported_field_preserves_recorded_sibling(retained_evidence_root: Path):
    stages, source = payload(retained_evidence_root)
    document = json.loads(source.content)
    document["observations"][0]["waterLevel"] = "unsupported"
    parsed = stages.parse(replace(source, content=json.dumps(document).encode()), stages.config)
    assert parsed.rows.height == 30
    assert {o.status for o in parsed.outcomes} == {"success", "unsupported"}


def test_empty_source_answer_has_concrete_outcomes(retained_evidence_root: Path):
    stages, source = payload(retained_evidence_root)
    document = json.loads(source.content)
    document["observations"] = []
    parsed = stages.parse(replace(source, content=json.dumps(document).encode()), stages.config)
    assert parsed.rows.is_empty()
    assert len(parsed.outcomes) == 2
    assert all(o.status == "empty" and o.series_id for o in parsed.outcomes)


def test_invalid_internal_tags_remain_fatal(retained_evidence_root: Path):
    import pytest

    from rivretrieve._internal.issues import FatalContractError

    stages, source = payload(retained_evidence_root)
    with pytest.raises(FatalContractError):
        stages.parse(replace(source, station_products=()), stages.config)


def test_other_recorded_provider_parsers_retain_series_context(retained_evidence_root: Path):
    from importlib import import_module

    from rivretrieve._internal.engine import SourceCoordinates
    from rivretrieve._internal.providers.cz_chmi.fetch import CzChmiRequestCoordinates
    from rivretrieve._internal.providers.jp_mlit.fetch import JpMlitPayloadCoordinates

    cases = (
        ("jp_mlit", "301011281104010", "discharge_daily", "jp_mlit_discharge_daily_2023_dat.recording.json"),
        ("ba_fhmzbih", "2010", "discharge_reported", "ba_fhmzbih_2010_Q_1Y.recording.json"),
        ("cz_chmi", "0-203-1-000400", "discharge_daily_mean", "cz_chmi_0-203-1-000400_DQ_2023.recording.json"),
        ("fr_hubeau", "1011000101", "discharge_daily_mean", "fr_hubeau_1011000101_QmnJ_padded.recording.json"),
        ("th_thaiwater", "1373273", "discharge_reported", "th_thaiwater_1373273_2026-08-01_2026-08-02.recording.json"),
    )
    _, template = payload(retained_evidence_root)
    for provider, station, product, filename in cases:
        config = import_module(f"rivretrieve._internal.providers.{provider}.config").config()
        parse = import_module(f"rivretrieve._internal.providers.{provider}.parse").parse
        recording = read_recording(retained_evidence_root / "tests/test_data" / filename)
        coordinates = config.products[ProductId(product)].coordinates
        if provider == "cz_chmi":
            coordinates = SourceCoordinates(CzChmiRequestCoordinates("DQ", ("QD",)))
        if provider == "jp_mlit":
            coordinates = SourceCoordinates(JpMlitPayloadCoordinates(7, "dat"))
        source = replace(
            template,
            station_products=((station, ProductId(product)),),
            source_coordinates=coordinates,
            content=recording.content,
        )
        parsed = parse(source, config)
        assert parsed.rows.height > 0, (provider, parsed.issues)
        assert len(parsed.series) == 1
        assert parsed.outcomes[0].status == "success"
        assert parsed.rows["series_id"].unique().to_list() == [parsed.series[0].series_id]


def test_czech_internal_request_coordinates_are_not_rewritten_to_match_tags(retained_evidence_root: Path):
    import pytest

    from rivretrieve._internal.engine import SourceCoordinates
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.cz_chmi.config import config
    from rivretrieve._internal.providers.cz_chmi.fetch import CzChmiRequestCoordinates
    from rivretrieve._internal.providers.cz_chmi.parse import parse

    _, template = payload(retained_evidence_root)
    recording = read_recording(retained_evidence_root / "tests/test_data/cz_chmi_0-203-1-000400_DQ_2023.recording.json")
    source = replace(
        template,
        station_products=(("0-203-1-000400", ProductId("discharge_daily_mean")),),
        source_coordinates=SourceCoordinates(CzChmiRequestCoordinates("DQ", ("HD",))),
        content=recording.content,
    )
    with pytest.raises(FatalContractError, match="request coordinates"):
        parse(source, config())


def test_response_receipt_identity_changes_with_bytes_and_retrieval_instant(retained_evidence_root: Path):
    from datetime import timedelta

    stages, source = payload(retained_evidence_root)
    first = stages.parse(source, stages.config)
    changed_bytes = stages.parse(replace(source, content=source.content + b"\n"), stages.config)
    changed_time = stages.parse(
        replace(source, origin=replace(source.origin, retrieved_at=source.origin.retrieved_at + timedelta(seconds=1))),
        stages.config,
    )
    for changed in (changed_bytes, changed_time):
        assert first.series == changed.series
        assert first.outcomes[0].outcome_id != changed.outcomes[0].outcome_id
        assert first.inventories[0].snapshot_id != changed.inventories[0].snapshot_id
