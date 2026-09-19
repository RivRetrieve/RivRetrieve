"""Source-series regressions over exact publisher captures, not fabricated response blocks."""

from datetime import datetime

import polars as pl
import polars.testing as pl_testing

from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.br_ana.config import config as ana_config
from rivretrieve._internal.providers.br_ana.parse import parse as ana_parse
from rivretrieve._internal.providers.ch_foen.config import config as ch_config
from rivretrieve._internal.providers.ch_foen.parse import parse as ch_parse
from rivretrieve._internal.providers.no_nve.config import config as nve_config
from rivretrieve._internal.providers.no_nve.parse import parse as nve_parse
from rivretrieve._internal.recordings import read_recording


def payload(path, station, product, config, start, end):
    recording = read_recording(path)
    product = ProductId(product)
    unknown = UnknownOriginFact()
    return Payload(
        source_coordinates=config.products[product].coordinates,
        station_products=((station, product),),
        fetch_window=_make_fetch_window(
            WindowEndpoint.from_datetime(datetime.fromisoformat(start)),
            WindowEndpoint.from_datetime(datetime.fromisoformat(end)),
        ),
        content=recording.content,
        prerequisite_calls=recording.prerequisite_calls,
        origin=SourceCallOrigin(
            recording.request.url,
            recording.request.parameters,
            recording.status_code,
            recording.retrieved_at,
            recording.content_type,
            unknown,
            unknown,
        ),
    )


def test_ana_one_daily_response_preserves_both_published_consistencies():
    config = ana_config()
    response = payload(
        "tests/recordings/br_ana/HidroSerieCotas_15400000_2020-01-01_2020-01-31.recording.json",
        "15400000",
        "stage_daily_mean_bruto",
        config,
        "2020-01-01",
        "2020-01-31",
    )
    parsed = ana_parse(response, config)
    rows = parsed.rows if hasattr(parsed, "rows") else parsed.value
    assert rows.height == 62  # Both recorded January monthly mean headers, 31 slots each.
    assert {item.variant for item in parsed.series} == {"bruto", "consistido"}
    assert {item.identity.published_id for item in parsed.series} == {"1", "2"}
    assert parsed.rows["series_id"].n_unique() == 2
    assert all(item.facts[0].statistic.value == "mean" for item in parsed.series)
    assert all(item.facts[0].day_definition.value is None for item in parsed.series)


def test_nve_real_hourly_instantaneous_temperature_is_not_a_mean():
    config = nve_config()
    response = payload(
        "tests/test_data/no_nve_103.3.0_1003_60_2025-07-08_2025-07-14.recording.json",
        "103.3.0",
        "water_temperature_hourly_mean",
        config,
        "2025-07-08",
        "2025-07-14",
    )
    parsed = nve_parse(response, config)
    assert parsed.rows.height > 0
    assert len(parsed.series) == 1
    facts = parsed.series[0].facts[0]
    assert facts.statistic.value == "instantaneous"
    assert facts.frequency.value == "hourly"
    assert facts.temporal_support.value is None
    assert facts.source_unit.value == "°C"


def test_swiss_flow_ls_is_admitted_with_native_litre_unit():
    config = ch_config()
    response = payload(
        "tests/test_data/ch_foen_2251_rest_2026-09-19.recording.json",
        "2251",
        "discharge_reported",
        config,
        "2026-09-19",
        "2026-09-19T03:00:00",
    )
    parsed = ch_parse(response, config)
    observed = [item for item in parsed.series if item.identity.origin == "response"]
    assert len(observed) == 1
    series = observed[0]
    assert series.identity.published_id == "flow_ls"
    assert series.facts[0].quantity.value == "discharge"
    assert series.facts[0].source_unit.value == "l/s"
    assert series.facts[0].frequency.value is None
    pl_testing.assert_frame_equal(parsed.rows.select("value"), pl.DataFrame({"value": [2.64, 2.64, 2.64, 2.73]}))


def test_nve_explicit_version_is_sent_instead_of_upstream_default():
    from dataclasses import replace

    from rivretrieve._internal.engine import RenderedWindow, SourceCoordinates
    from rivretrieve._internal.providers.no_nve.fetch import fetch
    from rivretrieve._internal.recordings import ReplayTransport

    config = nve_config()
    product = ProductId("discharge_daily_mean")
    definition = config.products[product]
    versioned = replace(
        definition, coordinates=SourceCoordinates(replace(definition.coordinates.value, version_number=1))
    )
    config = replace(config, products={product: versioned})
    recordings = [
        read_recording(
            f"tests/test_data/no_nve_109.42.0_1001_1440_version-{version}_2024-01-01_2024-01-03.recording.json"
        )
        for version in (1, "omitted")
    ]
    response = fetch(
        ("109.42.0",),
        (product,),
        {product: (RenderedWindow("2024-01-01", "2024-01-03"),)},
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)), WindowEndpoint.from_datetime(datetime(2024, 1, 3))
        ),
        config,
        ReplayTransport(recordings),
    )
    assert len(response.value) == 1
    assert response.value[0].origin.request_parameters["VersionNumber"] == 1
    parsed = nve_parse(response.value[0], config)
    assert parsed.series[0].identity.published_id == "1"
    assert parsed.rows.height == 2
    assert parsed.rows["value"].null_count() == 2


def test_ana_unrepresentable_consistency_preserves_its_representable_sibling():
    import json
    from dataclasses import replace

    config = ana_config()
    original = payload(
        "tests/recordings/br_ana/HidroSerieCotas_15400000_2020-01-01_2020-01-31.recording.json",
        "15400000",
        "stage_daily_mean_bruto",
        config,
        "2020-01-01",
        "2020-01-31",
    )
    document = json.loads(original.content)
    # Explicit structural mutation of real bytes, not a new publisher capture.
    for item in document["items"]:
        if item["Mediadiaria"] == "1" and item["nivelconsistencia"] == "1":
            item["Cota_01"] = "unrepresentable"
    result = ana_parse(replace(original, content=json.dumps(document).encode()), config)
    assert result.rows.height == 31
    assert {outcome.status.value for outcome in result.outcomes} == {"success", "unsupported"}
    assert len(result.series) == 2
    assert result.issues


def test_nve_all_known_versions_are_requested_separately_with_null_series_preserved():
    from rivretrieve._internal.engine import RenderedWindow
    from rivretrieve._internal.providers.no_nve.fetch import fetch
    from rivretrieve._internal.recordings import ReplayTransport
    from rivretrieve._internal.source_series import SeriesScope

    config = nve_config()
    product = ProductId("discharge_daily_mean")
    recordings = []
    known = []
    for version in (1, 2, 3):
        path = f"tests/test_data/no_nve_109.42.0_1001_1440_version-{version}_2024-01-01_2024-01-03.recording.json"
        recordings.append(read_recording(path))
        known.extend(nve_parse(payload(path, "109.42.0", product, config, "2024-01-01", "2024-01-03"), config).series)
    scope = SeriesScope(provider_ids=("no_nve",), station_ids=("109.42.0",), product_ids=(product,))
    acquired = fetch(
        ("109.42.0",),
        (product,),
        {product: (RenderedWindow("2024-01-01", "2024-01-03"),)},
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)), WindowEndpoint.from_datetime(datetime(2024, 1, 3))
        ),
        config,
        ReplayTransport(recordings),
        scope=scope,
        known_series=tuple(known),
    )
    assert [item.origin.request_parameters["VersionNumber"] for item in acquired.value] == [1, 2, 3]
    parsed = [nve_parse(item, config) for item in acquired.value]
    assert [item.rows["value"].to_list() for item in parsed] == [
        [None, None],
        [57.93944, 74.33918],
        [20.30248, 26.9778],
    ]
    assert all(item.outcomes[0].status.value == "success" for item in parsed)
    assert any(issue.code == "source.inventory_unresolved" for issue in acquired.issues)


def test_swiss_stage_reference_is_not_inferred_from_field_name():
    from rivretrieve._internal.providers.ch_foen.series import field_series

    above = field_series("2251", "height")
    unspecified = field_series("2251", "height_abs")
    assert above.facts[0].vertical_reference.value == "above_sea_level"
    assert above.facts[0].vertical_datum.value is None
    assert unspecified.facts[0].vertical_reference.value is None
    assert unspecified.facts[0].vertical_datum.value is None
    assert above.series_id != unspecified.series_id


def test_nve_one_failed_explicit_version_does_not_discard_successful_sibling():
    from rivretrieve._internal.driver import _SourceResponseTransport
    from rivretrieve._internal.engine import RenderedWindow
    from rivretrieve._internal.providers.no_nve.fetch import fetch
    from rivretrieve._internal.recordings import ReplayTransport
    from rivretrieve._internal.source_series import RestrictionKind, SeriesScope

    config = nve_config()
    product = ProductId("discharge_daily_mean")
    good_path = "tests/test_data/no_nve_109.42.0_1001_1440_version-1_2024-01-01_2024-01-03.recording.json"
    failed_path = "tests/test_data/no_nve_109.42.0_1001_1440_version-99999_2024-01-01_2024-01-03.recording.json"
    known = nve_parse(payload(good_path, "109.42.0", product, config, "2024-01-01", "2024-01-03"), config).series
    scope = SeriesScope(
        provider_ids=("no_nve",),
        station_ids=("109.42.0",),
        product_ids=(product,),
        restriction=RestrictionKind.EXPLICIT,
        variants=("1", "99999"),
    )
    acquired = fetch(
        ("109.42.0",),
        (product,),
        {product: (RenderedWindow("2024-01-01", "2024-01-03"),)},
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)), WindowEndpoint.from_datetime(datetime(2024, 1, 3))
        ),
        config,
        _SourceResponseTransport(ReplayTransport((read_recording(good_path), read_recording(failed_path)))),
        scope=scope,
        known_series=known,
    )
    assert len(acquired.value) == 1
    assert acquired.value[0].origin.request_parameters["VersionNumber"] == 1
    assert len(acquired.failed_requests) == 1
    failed = acquired.failed_requests[0]
    assert failed.series.variant == "99999"
    assert failed.series.identity.published_id is None
    assert failed.failure.status_code == 404
    assert failed.request.params["VersionNumber"] == 99999


def test_swiss_missing_sibling_field_has_unresolved_outcome_not_empty_success():
    config = ch_config()
    response = payload(
        "tests/test_data/ch_foen_2251_rest_2026-09-19.recording.json",
        "2251",
        "discharge_reported",
        config,
        "2026-09-19",
        "2026-09-19T03:00:00",
    )
    result = ch_parse(response, config)
    by_id = {item.series_id: item.identity.published_id for item in result.series}
    assert {by_id[outcome.series_id]: outcome.status.value for outcome in result.outcomes} == {
        "flow_ls": "success",
        "flow": "unresolved",
    }


def test_ana_unobserved_requested_consistency_remains_unresolved():
    config = ana_config()
    response = payload(
        "tests/recordings/br_ana/HidroSerieCotas_15400000_2024-01-01_2024-01-31.recording.json",
        "15400000",
        "stage_daily_mean_consistido",
        config,
        "2024-01-01",
        "2024-01-31",
    )
    result = ana_parse(response, config)
    by_id = {item.series_id: item.variant for item in result.series}
    assert any(
        outcome.status.value == "unresolved" and by_id[outcome.series_id] == "consistido" for outcome in result.outcomes
    )
    assert result.rows["product_id"].unique().to_list() == ["stage_daily_mean_bruto"]


def test_nve_blank_unit_is_isolated_before_fact_validation():
    import json
    from dataclasses import replace

    config = nve_config()
    path1 = "tests/test_data/no_nve_109.42.0_1001_1440_version-1_2024-01-01_2024-01-03.recording.json"
    path2 = "tests/test_data/no_nve_109.42.0_1001_1440_version-2_2024-01-01_2024-01-03.recording.json"
    source = payload(path1, "109.42.0", "discharge_daily_mean", config, "2024-01-01", "2024-01-03")
    document = json.loads(source.content)
    document["data"][0]["unit"] = ""
    document["data"].extend(json.loads(read_recording(path2).content)["data"])
    result = nve_parse(replace(source, content=json.dumps(document).encode()), config)
    identities = {item.series_id: item.identity.published_id for item in result.series}
    assert {identities[outcome.series_id]: outcome.status.value for outcome in result.outcomes} == {
        "1": "unsupported",
        "2": "success",
    }
    assert result.rows["value"].to_list() == [57.93944, 74.33918]
    assert any("empty" in issue.message and issue.details["series_id"] for issue in result.issues)
