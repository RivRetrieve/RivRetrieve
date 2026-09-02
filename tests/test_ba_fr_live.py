"""Bosnia and France live probes : exact recordings → source-wall-clock rows."""

from datetime import datetime
from pathlib import Path

import polars as pl

from rivretrieve._internal.boundary_probes import (
    FIRST_WALL_CLOCK_TIME,
    LAST_WALL_CLOCK_TIME,
    READING_COUNT,
    BoundaryProbe,
    WallClockExpectation,
    run_boundary_probes,
)
from rivretrieve._internal.engine import RenderedWindow, WindowEndpoint, _make_fetch_window
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.ba_fhmzbih.declaration import declaration as ba_declaration
from rivretrieve._internal.providers.fr_hubeau.declaration import declaration as fr_declaration
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.recordings import ReplayTransport, read_recording

DATA = Path(__file__).parent / "test_data"
assert isinstance(ba_declaration.observations, LiveStages)
assert isinstance(fr_declaration.observations, LiveStages)


def _probe(provider, station, product, start, stop, paths, expected):
    pid = ProviderId(provider)
    product_id = ProductId(product)
    stages = (ba_declaration if provider == "ba_fhmzbih" else fr_declaration).observations.stages
    recordings = tuple(read_recording(DATA / path) for path in paths)

    def run(replay: ReplayTransport):
        window = _make_fetch_window(
            WindowEndpoint.from_datetime(datetime.fromisoformat(start)),
            WindowEndpoint.from_datetime(datetime.fromisoformat(stop)),
        )
        rendered = () if provider == "ba_fhmzbih" else (RenderedWindow(start, stop),)
        if provider == "fr_hubeau" and product in {"discharge_instantaneous", "stage_instantaneous"}:
            rendered = (
                RenderedWindow(
                    datetime.fromisoformat(start).strftime("%d/%m/%Y"),
                    datetime.fromisoformat(stop).strftime("%d/%m/%Y"),
                ),
            )
        fetched = stages.fetch((station,), (product_id,), {product_id: rendered}, window, stages.config, replay)
        return pl.concat([stages.parse(payload, stages.config).value for payload in fetched.value])

    return BoundaryProbe(
        pid,
        product_id,
        recordings,
        {
            READING_COUNT: expected[0],
            FIRST_WALL_CLOCK_TIME: WallClockExpectation(expected[1], expected[3]),
            LAST_WALL_CLOCK_TIME: WallClockExpectation(expected[2], expected[3]),
        },
        run,
    )


PROBES = (
    _probe(
        "ba_fhmzbih",
        "4024",
        "discharge_instantaneous",
        "2025-09-03",
        "2026-09-02T12:00:00",
        ("ba_fhmzbih_metadata_index.recording.json", "ba_fhmzbih_4024_Q_1Y.recording.json"),
        (8347, "2025-09-03T00:00:00", "2026-09-02T12:00:00", "unknown"),
    ),
    _probe(
        "ba_fhmzbih",
        "4024",
        "stage_instantaneous",
        "2025-09-03",
        "2026-09-02T12:00:00",
        ("ba_fhmzbih_metadata_index.recording.json", "ba_fhmzbih_4024_H_1Y.recording.json"),
        (8348, "2025-09-03T00:00:00", "2026-09-02T12:00:00", "unknown"),
    ),
    _probe(
        "ba_fhmzbih",
        "4110",
        "water_temperature_instantaneous",
        "2025-09-03",
        "2025-11-30T01:00:00",
        ("ba_fhmzbih_metadata_index.recording.json", "ba_fhmzbih_4110_Tvode_1Y.recording.json"),
        (1995, "2025-09-03T00:00:00", "2025-11-30T01:00:00", "unknown"),
    ),
    _probe(
        "fr_hubeau",
        "1011000101",
        "discharge_daily_mean",
        "2025-01-01",
        "2025-01-03",
        ("fr_hubeau_1011000101_QmnJ_2025-01-01_03.recording.json",),
        (3, "2025-01-01T00:00:00", "2025-01-03T00:00:00", "unknown"),
    ),
    _probe(
        "fr_hubeau",
        "1011000101",
        "discharge_daily_max",
        "2025-01-01",
        "2025-01-03",
        ("fr_hubeau_1011000101_QIXnJ_2025-01-01_03.recording.json",),
        (3, "2025-01-01T00:00:00", "2025-01-03T00:00:00", "unknown"),
    ),
    _probe(
        "fr_hubeau",
        "1011000101",
        "stage_daily_max",
        "2025-01-01",
        "2025-01-03",
        ("fr_hubeau_1011000101_HIXnJ_2025-01-01_03.recording.json",),
        (3, "2025-01-01T00:00:00", "2025-01-03T00:00:00", "unknown"),
    ),
    _probe(
        "fr_hubeau",
        "01001336",
        "water_temperature_instantaneous",
        "2008-07-09",
        "2008-07-10",
        (
            "fr_hubeau_01001336_temp_2008-07-09_10_p1.recording.json",
            "fr_hubeau_01001336_temp_2008-07-09_10_p2.recording.json",
        ),
        (37, "2008-07-09T11:00:00", "2008-07-10T23:00:00", "unknown"),
    ),
    _probe(
        "fr_hubeau",
        "Y251002001",
        "stage_instantaneous",
        "2020-01-01",
        "2020-01-02",
        ("fr_hydroportail_historical_H.recording.json",),
        (576, "2020-01-01T00:00:00", "2020-01-02T23:55:00", "+00:00"),
    ),
    _probe(
        "fr_hubeau",
        "Y251002001",
        "discharge_instantaneous",
        "2020-01-01",
        "2020-01-02",
        ("fr_hydroportail_historical_Q.recording.json",),
        (576, "2020-01-01T00:00:00", "2020-01-02T23:55:00", "+00:00"),
    ),
)


def test_every_bosnia_and_france_product_has_exact_live_probe():
    obligations = tuple((p.provider_id, p.product_id) for p in PROBES)
    results = run_boundary_probes(obligations, PROBES)
    assert len(results) == 9


def test_france_uses_current_daily_parameter_names_and_next_url_without_original_parameters():
    first = read_recording(DATA / "fr_hubeau_01001336_temp_2008-07-09_10_p1.recording.json")
    second = read_recording(DATA / "fr_hubeau_01001336_temp_2008-07-09_10_p2.recording.json")
    assert set(first.request.parameters or {}) == {"code_station", "date_debut_mesure", "date_fin_mesure", "size"}
    assert second.request.parameters is None
    for name in ("QmnJ", "QIXnJ", "HIXnJ"):
        request = read_recording(DATA / f"fr_hubeau_1011000101_{name}_2025-01-01_03.recording.json").request
        assert set(request.parameters or {}) == {
            "code_entite",
            "date_debut_obs_elab",
            "date_fin_obs_elab",
            "grandeur_hydro_elab",
            "size",
        }
