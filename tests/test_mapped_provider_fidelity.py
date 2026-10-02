"""Publisher-backed mapped facts stay identical across the public workflow."""

from pathlib import Path

import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import ReplayTransport, read_recording

CASES = (
    (
        "jp_mlit",
        "301011281104010",
        tuple(
            f"jp_mlit_{quantity}_{frequency}_2023_{role}.recording.json"
            for quantity in ("stage", "discharge")
            for frequency in ("hourly", "daily")
            for role in ("html", "dat")
        ),
        "2023-01-03",
        "2023-01-29T23:00:00",
    ),
    (
        "cz_chmi",
        "0-203-1-000400",
        ("cz_chmi_0-203-1-000400_DQ_2023.recording.json", "cz_chmi_0-203-1-000400_HQ_2023.recording.json"),
        "2023-01-03",
        "2023-01-29",
    ),
    ("lt_lhmt", "anyksciu-vms", ("lt_lhmt_anyksciu-vms_2023-06.recording.json",), "2023-06-03", "2023-06-28"),
    (
        "th_thaiwater",
        "1373273",
        ("th_thaiwater_1373273_2026-07-30_2026-08-04.recording.json",),
        "2026-08-01",
        "2026-08-02T23:50:00",
    ),
)


@pytest.mark.recorded(
    "tests/test_data/cz_chmi_0-203-1-000400_DQ_2023.recording.json",
    "tests/test_data/cz_chmi_0-203-1-000400_HQ_2023.recording.json",
    "tests/test_data/jp_mlit_discharge_daily_2023_dat.recording.json",
    "tests/test_data/jp_mlit_discharge_daily_2023_html.recording.json",
    "tests/test_data/jp_mlit_discharge_hourly_2023_dat.recording.json",
    "tests/test_data/jp_mlit_discharge_hourly_2023_html.recording.json",
    "tests/test_data/jp_mlit_stage_daily_2023_dat.recording.json",
    "tests/test_data/jp_mlit_stage_daily_2023_html.recording.json",
    "tests/test_data/jp_mlit_stage_hourly_2023_dat.recording.json",
    "tests/test_data/jp_mlit_stage_hourly_2023_html.recording.json",
    "tests/test_data/lt_lhmt_anyksciu-vms_2023-06.recording.json",
    "tests/test_data/th_thaiwater_1373273_2026-07-30_2026-08-04.recording.json",
)
@pytest.mark.parametrize(("provider", "station", "recordings", "start", "end"), CASES)
def test_public_discovery_retrieval_and_bundle_have_identical_facts(
    retained_evidence_root: Path, monkeypatch, provider, station, recordings, start, end
):
    envelopes = tuple(read_recording(retained_evidence_root / "tests/test_data" / name) for name in recordings)
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(envelopes))
    selection = rr.find(provider=provider, station=station)
    result = rr.fetch(selection, start=start, end=end, receipts=True, on_issue="ignore")
    expected = {item.series_id: item.facts for item in selection.series}
    assert {item.series_id: item.facts for item in result.source_series} == expected
    restored = rr.from_bundle(rr.to_bundle(result))
    assert restored.source_series == result.source_series
    pl_testing.assert_frame_equal(restored.data, result.data)
    assert all(entry.content in {envelope.content for envelope in envelopes} for entry in result.receipts.entries)


def test_japan_cadence_does_not_establish_interval_or_anchor():
    selection = rr.find(provider="jp_mlit", station="301011281104010")
    assert all(f.temporal_support.value is None for s in selection.series for f in s.facts)
    assert all(f.timestamp_anchor.value is None for s in selection.series for f in s.facts)
    assert all(f.statistic.value is None for s in selection.series for f in s.facts)


def test_thaiwater_published_sea_level_reference_is_not_a_named_datum():
    selection = rr.find(provider="th_thaiwater", station="1373273", quantity="stage")
    assert selection.series
    assert all(f.vertical_reference.value == "above_sea_level" for s in selection.series for f in s.facts)
    assert all(f.vertical_datum.value is None for s in selection.series for f in s.facts)
    assert all(f.time_zone.value is None for s in selection.series for f in s.facts)


def test_daily_means_retain_support_without_inventing_interval_anchor():
    for provider, station in (("cz_chmi", "0-203-1-000400"), ("lt_lhmt", "anyksciu-vms")):
        selection = rr.find(provider=provider, station=station, frequency="daily", statistic="mean")
        assert selection.series
        for series in selection.series:
            for facts in series.facts:
                assert facts.temporal_support.value == "interval"
                assert facts.timestamp_anchor.value is None
                assert facts.day_definition.value is None
                assert facts.label_time == "00:00"


@pytest.mark.recorded(
    "tests/test_data/cz_chmi_0-203-1-000400_DQ_2023.recording.json",
    "tests/test_data/cz_chmi_0-203-1-000400_HQ_2023.recording.json",
    "tests/test_data/jp_mlit_discharge_daily_2023_dat.recording.json",
    "tests/test_data/jp_mlit_discharge_daily_2023_html.recording.json",
    "tests/test_data/jp_mlit_discharge_hourly_2023_dat.recording.json",
    "tests/test_data/jp_mlit_discharge_hourly_2023_html.recording.json",
    "tests/test_data/jp_mlit_stage_daily_2023_dat.recording.json",
    "tests/test_data/jp_mlit_stage_daily_2023_html.recording.json",
    "tests/test_data/jp_mlit_stage_hourly_2023_dat.recording.json",
    "tests/test_data/jp_mlit_stage_hourly_2023_html.recording.json",
    "tests/test_data/lt_lhmt_anyksciu-vms_2023-06.recording.json",
    "tests/test_data/th_thaiwater_1373273_2026-07-30_2026-08-04.recording.json",
)
@pytest.mark.parametrize(("provider", "station", "recordings", "start", "end"), CASES)
def test_explicit_series_cache_refresh_preserves_siblings_facts_and_native_values(
    retained_evidence_root: Path, monkeypatch, tmp_path, provider, station, recordings, start, end
):
    envelopes = tuple(read_recording(retained_evidence_root / "tests/test_data" / name) for name in recordings)
    calls = []

    class CountingReplay(ReplayTransport):
        def send(self, request):
            calls.append(request)
            return super().send(request)

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(discovery, "HttpClient", lambda: CountingReplay(envelopes))
    broad = rr.find(provider=provider, station=station)
    explicit = rr.pick(broad, series_id=[series.series_id for series in broad.series])
    first = rr.fetch(explicit, start=start, end=end, cache="refresh", receipts=True, on_issue="ignore")
    count = len(calls)
    reused = rr.fetch(explicit, start=start, end=end, cache="reuse", receipts=True, on_issue="ignore")
    assert len(calls) == count
    pl_testing.assert_frame_equal(first.data, reused.data)
    assert first.source_series == reused.source_series
    assert all(entry.authorship.value == "store_excerpt" for entry in reused.receipts.entries)
    subset = rr.pick(explicit, series_id=explicit.series[0].series_id)
    rr.fetch(subset, start=start, end=end, cache="refresh", on_issue="ignore")
    assert len(calls) > count
    count = len(calls)
    retained = rr.fetch(explicit, start=start, end=end, cache="reuse", on_issue="ignore")
    assert len(calls) == count
    pl_testing.assert_frame_equal(first.data, retained.data)
    assert first.source_series == retained.source_series
    restored = rr.from_bundle(rr.to_bundle(retained))
    pl_testing.assert_frame_equal(retained.data, restored.data)
    # These singleton access mappings do not claim exhaustive publisher inventory.
    assert all(snapshot.completeness.value == "incomplete" for snapshot in first.inventories)
    rr.fetch(broad, start=start, end=end, cache="reuse", on_issue="ignore")
    assert len(calls) > count


@pytest.mark.recorded(
    "tests/test_data/ba_fhmzbih_4024_H_1Y.recording.json",
    "tests/test_data/ba_fhmzbih_4024_Q_1Y.recording.json",
    "tests/test_data/ba_fhmzbih_4110_Tvode_1Y.recording.json",
    "tests/test_data/cz_chmi_0-203-1-000400_DQ_2023.recording.json",
    "tests/test_data/cz_chmi_0-203-1-000400_HQ_2023.recording.json",
    "tests/test_data/cz_meta2.json",
    "tests/test_data/fr_hubeau_01001336_temp_padded_p1.recording.json",
    "tests/test_data/fr_hubeau_1011000101_HIXnJ_padded.recording.json",
    "tests/test_data/fr_hubeau_1011000101_QIXnJ_padded.recording.json",
    "tests/test_data/fr_hubeau_1011000101_QmnJ_padded.recording.json",
    "tests/test_data/fr_hubeau_hydrometrie.html",
    "tests/test_data/fr_hubeau_openapi_v2.json",
    "tests/test_data/fr_hydroportail_H_padded.recording.json",
    "tests/test_data/fr_hydroportail_station_Q_padded.recording.json",
    "tests/test_data/fr_hydroportail_variants/REPORT.md",
    "tests/test_data/jp_mlit_discharge_daily_2023_dat.recording.json",
    "tests/test_data/jp_mlit_discharge_daily_2023_html.recording.json",
    "tests/test_data/jp_mlit_discharge_hourly_2023_dat.recording.json",
    "tests/test_data/jp_mlit_discharge_hourly_2023_html.recording.json",
    "tests/test_data/jp_mlit_stage_daily_2023_dat.recording.json",
    "tests/test_data/jp_mlit_stage_daily_2023_html.recording.json",
    "tests/test_data/jp_mlit_stage_hourly_2023_dat.recording.json",
    "tests/test_data/jp_mlit_stage_hourly_2023_html.recording.json",
    "tests/test_data/lt_lhmt_terms_licence.html",
    "tests/test_data/th_thaiwater_official_app.chunk-2026-09-02.js",
    "tests/test_data/th_thaiwater_official_evidence_manifest-2026-09-02.json",
)
def test_all_mapped_builtin_facts_have_publisher_evidence_and_content_identity(retained_evidence_root: Path):
    from importlib import import_module

    from rivretrieve._internal.source_series import stable_id

    for provider in ("jp_mlit", "cz_chmi", "lt_lhmt", "th_thaiwater", "fr_hubeau", "fr_hydroportail", "ba_fhmzbih"):
        mappings = import_module(f"rivretrieve._internal.providers.{provider}.config").SERIES_MAPPINGS
        for mapping in mappings.values():
            assert mapping.evidence
            assert any("tests/test_data/" in citation for citation in mapping.evidence)
            for citation in mapping.evidence:
                if citation.startswith("tests/test_data/"):
                    assert (retained_evidence_root / citation.split(":", 1)[0]).is_file()
            facts = mapping.physical_facts()
            assert facts.facts_id == stable_id(facts.model_dump_json(exclude={"facts_id"}))
            assert all("config.py" not in citation for citation in facts.quantity.evidence)


@pytest.mark.recorded("tests/test_data/cz_chmi_0-203-1-000400_DQ_2023.recording.json")
@pytest.mark.parametrize("repetition", ("equal", "conflicting", "disjoint"))
def test_czech_repeated_code_is_identified_unsupported_without_losing_siblings(
    retained_evidence_root: Path, repetition
):
    """Negative derivatives are not claims that these blocks occur in publisher data."""
    import copy
    import json
    from dataclasses import replace
    from datetime import datetime

    from rivretrieve._internal.engine import RenderedWindow, WindowEndpoint, _make_fetch_window
    from rivretrieve._internal.primitives import ProductId
    from rivretrieve._internal.providers.cz_chmi.declaration import declaration

    stages = declaration.observations.stages
    products = tuple(
        ProductId(value) for value in ("discharge_daily_mean", "stage_daily_mean", "water_temperature_daily_mean")
    )
    recording = read_recording(
        retained_evidence_root / "tests/test_data" / "cz_chmi_0-203-1-000400_DQ_2023.recording.json"
    )
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2023, 1, 1)), WindowEndpoint.from_datetime(datetime(2023, 12, 31))
    )
    payload = stages.fetch(
        ("0-203-1-000400",),
        products,
        {product: (RenderedWindow("2023", None, window),) for product in products},
        window,
        stages.config,
        ReplayTransport((recording,)),
    ).value[0]
    document = json.loads(payload.content)
    source = next(series for series in document["tsList"] if series["tsConID"] == "QD")
    duplicate = copy.deepcopy(source)
    if repetition == "conflicting":
        duplicate["tsData"]["data"]["values"][0][1] = 999.0
    elif repetition == "disjoint":
        duplicate["tsData"]["data"]["values"][0][0] = "2024-01-01T00:00:00Z"
    document["tsList"].append(duplicate)
    result = stages.parse(replace(payload, content=json.dumps(document).encode()), stages.config)
    assert {outcome.product_id: outcome.status.value for outcome in result.outcomes} == {
        "discharge_daily_mean": "unsupported",
        "stage_daily_mean": "success",
        "water_temperature_daily_mean": "success",
    }
    assert set(result.rows["product_id"]) == {"stage_daily_mean", "water_temperature_daily_mean"}
    assert result.rows.height == 730
    assert "exactly once" in result.issues[0].message


def test_product_tables_project_source_facts_without_independent_scientific_claims():
    from importlib import import_module

    from rivretrieve._internal.source_series import admission

    for provider in ("jp_mlit", "cz_chmi", "lt_lhmt", "th_thaiwater"):
        module = import_module(f"rivretrieve._internal.providers.{provider}.generate_catalogue")
        mappings = import_module(f"rivretrieve._internal.providers.{provider}.config").SERIES_MAPPINGS
        for product in module.build_products().iter_rows(named=True):
            facts = mappings[product["product_id"]].physical_facts()
            assert product["frequency"] == (facts.frequency.value or "unknown")
            assert product["statistic"] == (facts.statistic.value or "unknown")
            assert product["period_type"] == (facts.temporal_support.value or "unknown")
            assert product["period_anchor"] == (facts.timestamp_anchor.value or "unknown")
            assert product["unit"] == admission(facts).target_unit


@pytest.mark.recorded(
    "tests/test_data/cz_chmi_0-203-1-000400_DQ_2023.recording.json",
    "tests/test_data/cz_chmi_0-203-1-000400_HQ_2023.recording.json",
    "tests/test_data/jp_mlit_discharge_daily_2023_dat.recording.json",
    "tests/test_data/jp_mlit_discharge_daily_2023_html.recording.json",
    "tests/test_data/jp_mlit_discharge_hourly_2023_dat.recording.json",
    "tests/test_data/jp_mlit_discharge_hourly_2023_html.recording.json",
    "tests/test_data/jp_mlit_stage_daily_2023_dat.recording.json",
    "tests/test_data/jp_mlit_stage_daily_2023_html.recording.json",
    "tests/test_data/jp_mlit_stage_hourly_2023_dat.recording.json",
    "tests/test_data/jp_mlit_stage_hourly_2023_html.recording.json",
    "tests/test_data/lt_lhmt_anyksciu-vms_2023-06.recording.json",
    "tests/test_data/th_thaiwater_1373273_2026-07-30_2026-08-04.recording.json",
)
@pytest.mark.parametrize(("provider", "station", "recordings", "start", "end"), CASES)
def test_unestablished_singleton_variant_never_substitutes_known_series(
    retained_evidence_root: Path, monkeypatch, provider, station, recordings, start, end
):
    envelopes = tuple(read_recording(retained_evidence_root / "tests/test_data" / name) for name in recordings)
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(envelopes))
    selection = rr.find(provider=provider, station=station)
    restricted = rr.pick(selection, variant="unpublished-variant", on_issue="ignore")
    assert not restricted.series
    assert restricted.issues
    result = rr.fetch(restricted, start=start, end=end, on_issue="ignore")
    assert result.data.is_empty()
    assert result.issues
    assert not any(outcome.status.value in ("success", "empty") for outcome in result.outcomes)
