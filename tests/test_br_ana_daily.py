"""Daily ANA stage contracts over exact modern monthly source recordings."""

import calendar
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.boundary_probes import (
    FIRST_WALL_CLOCK_TIME,
    LAST_WALL_CLOCK_TIME,
    READING_COUNT,
    BoundaryProbeHarness,
    LiveBoundaryProbe,
    WallClockExpectation,
)
from rivretrieve._internal.coverage import RequestedInterval
from rivretrieve._internal.driver import _padded_interval, drive
from rivretrieve._internal.engine import (
    Daily,
    ObservationRequest,
    RequestedWindow,
    StopConvention,
    WindowEndpoint,
    WindowRenderingVocabulary,
)
from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.br_ana.config import config, window_declarations
from rivretrieve._internal.providers.br_ana.fetch import fetch
from rivretrieve._internal.providers.br_ana.parse import parse
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.window_planning import plan_windows

_PRODUCTS = (
    "discharge_daily_mean_bruto",
    "discharge_daily_mean_consistido",
    "stage_daily_mean_bruto",
    "stage_daily_mean_consistido",
)


def test_daily_products_are_registered_without_replacing_telemetry() -> None:
    assert set(config().products) == {
        *_PRODUCTS,
        "discharge_instantaneous",
        "stage_instantaneous",
    }


_PROVIDER = ProviderId("br_ana")


class _Stages:
    config = config()
    window_declarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


def _recording(retained_evidence_root, product: str, month: str) -> Path:
    endpoint = "HidroSerieCotas" if product.startswith("stage") else "HidroSerieVazao"
    year, number = map(int, month.split("-"))
    last = calendar.monthrange(year, number)[1]
    return (
        retained_evidence_root / "tests/recordings/br_ana"
    ) / f"{endpoint}_15400000_{month}-01_{month}-{last}.recording.json"


def _run(retained_evidence_root, product: str, start: str, end: str, months: tuple[str, ...], **kwargs):
    request = ObservationRequest(
        _PROVIDER,
        ("15400000",),
        (ProductId(product),),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime.fromisoformat(start)),
            WindowEndpoint.from_datetime(datetime.fromisoformat(end)),
        ),
    )
    return drive(
        request,
        _Stages(),
        provenance=ObservationProvenance(source="recording", provider_id=_PROVIDER),
        transport=ReplayTransport([_recording(retained_evidence_root, product, month) for month in months]),
        **kwargs,
    )


def _payload(retained_evidence_root, product: str, month: str = "2024-01"):
    product_id = ProductId(product)
    window = _padded_interval(
        RequestedInterval(datetime.fromisoformat(month + "-10"), datetime.fromisoformat(month + "-20"))
    )
    return fetch(
        ("15400000",),
        (product_id,),
        {product_id: plan_windows(window, window_declarations().products[product_id])},
        window,
        config(),
        ReplayTransport([_recording(retained_evidence_root, product, month)]),
    ).value[0]


@pytest.mark.parametrize("product", _PRODUCTS)
def test_daily_semantics_and_engine_month_declaration(product: str) -> None:
    definition = config().products[ProductId(product)]
    assert isinstance(definition.semantics, Daily)
    assert definition.semantics.day_definition.value == "unknown"
    assert definition.semantics.label_time.components == (0, 0, 0, 0)
    assert config().zone.value == "unknown"
    window = window_declarations().products[ProductId(product)]
    assert window.granularity == "year-month"
    assert window.rendering == WindowRenderingVocabulary.DATE
    assert window.stop_convention == StopConvention.INCLUSIVE


@pytest.mark.recorded("tests/recordings/br_ana")
@pytest.mark.parametrize("product", _PRODUCTS)
@pytest.mark.parametrize("month", ("2020-01", "2023-02", "2023-12", "2024-01", "2024-02"))
def test_midmonth_exact_replay_preserves_modern_interior_values(
    retained_evidence_root, product: str, month: str
) -> None:
    result = _run(retained_evidence_root, product, month + "-10", month + "-20", (month,), receipts=ReceiptMode.INCLUDE)
    recording = read_recording(_recording(retained_evidence_root, product, month))
    prefix = "Cota" if product.startswith("stage") else "Vazao"
    consistency_field = "nivelconsistencia" if prefix == "Cota" else "Nivel_Consistencia"
    consistency = "1" if product.endswith("bruto") else "2"
    # Interior fidelity, independently decoded from publisher bytes, not a boundary probe.
    rows = []
    for row in json.loads(recording.content)["items"]:
        if row["Mediadiaria"] != "1" or row[consistency_field] != consistency:
            continue
        for day in range(10, 21):
            raw = row[f"{prefix}_{day:02}"]
            value = None if raw is None or raw.strip() == "" else float(raw)
            if value is not None and prefix == "Cota":
                value /= 100
            rows.append((datetime.fromisoformat(f"{month}-{day}"), "unknown", "15400000", product, value))
    expected = pl.DataFrame(
        rows,
        schema={
            name: result.canonical_rows.schema[name]
            for name in ("time", "time_zone", "station_id", "product_id", "value")
        },
        orient="row",
    )
    pl_testing.assert_frame_equal(result.canonical_rows.select(expected.columns), expected)
    assert result.receipts.entries[0].content == recording.content
    assert result.receipts.entries[0].origin.request_parameters == recording.request.parameters


@pytest.mark.recorded("tests/recordings/br_ana")
@pytest.mark.parametrize("product", ("stage_daily_mean_consistido", "discharge_daily_mean_consistido"))
def test_absent_variant_is_not_replaced_by_bruto(retained_evidence_root, product: str) -> None:
    result = _run(retained_evidence_root, product, "2024-01-10", "2024-01-20", ("2024-01",))
    assert result.canonical_rows.is_empty()
    assert any(issue.code == "source.unresolved_inventory" for issue in result.issues)


@pytest.mark.recorded("tests/recordings/br_ana")
@pytest.mark.parametrize("product", ("stage_daily_mean_bruto", "discharge_daily_mean_bruto"))
def test_month_transition_uses_both_exact_recordings(retained_evidence_root, product: str) -> None:
    result = _run(
        retained_evidence_root,
        product,
        "2024-01-30",
        "2024-02-02",
        ("2024-01", "2024-02"),
        receipts=ReceiptMode.INCLUDE,
    )
    assert [entry.content for entry in result.receipts.entries] == [
        read_recording(_recording(retained_evidence_root, product, month)).content for month in ("2024-01", "2024-02")
    ]
    assert not result.canonical_rows.is_duplicated().any()


@pytest.mark.recorded("tests/recordings/br_ana")
@pytest.mark.parametrize("product", ("stage_daily_mean_bruto", "discharge_daily_mean_consistido"))
def test_repeated_exact_variant_preserves_multiplicity(retained_evidence_root, product: str) -> None:
    # Adversarial repeated real monthly row, never an invented observation fixture.
    payload = _payload(retained_evidence_root, product, "2020-01")
    document = json.loads(payload.content)
    selected = next(row for row in document["items"] if row["Mediadiaria"] == "1")
    document["items"].append(selected)
    original = parse(payload, config()).rows.filter(pl.col("product_id") == product)
    repeated = parse(replace(payload, content=json.dumps(document).encode()), config()).rows.filter(
        pl.col("product_id") == product
    )
    pl_testing.assert_frame_equal(repeated, pl.concat([original, original]).sort("time", maintain_order=True))


@pytest.mark.recorded("tests/recordings/br_ana")
@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("Mediadiaria", "2"),
        ("nivelconsistencia", "3"),
        ("codigoestacao", "99999999"),
        ("Data_Hora_Dado", "2024-01-01 01:00:00.0"),
        ("Data_Hora_Dado", "2024-01-02 00:00:00.0"),
        ("Cota_15", "NaN"),
        ("Cota_15", " "),
        ("Cota_15", True),
    ],
)
def test_adversarial_modified_recording_rejects_invalid_identity_or_value(
    retained_evidence_root, field: str, bad: object
) -> None:
    payload = _payload(retained_evidence_root, "stage_daily_mean_bruto")
    document = json.loads(payload.content)
    selected = next(row for row in document["items"] if row["Mediadiaria"] == "1")
    selected[field] = bad
    result = parse(replace(payload, content=json.dumps(document).encode()), config())
    assert any(outcome.status.value == "unsupported" for outcome in result.outcomes)
    assert any(issue.code.startswith("source.unsupported") for issue in result.issues)


@pytest.mark.recorded("tests/recordings/br_ana")
@pytest.mark.parametrize(("field", "bad"), [("Cota_30", "1"), ("Cota_30_Status", "1")])
def test_adversarial_nonempty_slot_outside_calendar_month_is_rejected(
    retained_evidence_root, field: str, bad: str
) -> None:
    payload = _payload(retained_evidence_root, "stage_daily_mean_bruto", "2024-02")
    document = json.loads(payload.content)
    selected = next(row for row in document["items"] if row["Mediadiaria"] == "1")
    selected[field] = bad
    result = parse(replace(payload, content=json.dumps(document).encode()), config())
    assert any(outcome.status.value == "unsupported" for outcome in result.outcomes)
    assert any(issue.code.startswith("source.unsupported") for issue in result.issues)


@pytest.mark.recorded("tests/recordings/br_ana")
@pytest.mark.parametrize("blank", [None, ""])
def test_adversarial_published_blank_is_null_not_zero(retained_evidence_root, blank: object) -> None:
    payload = _payload(retained_evidence_root, "stage_daily_mean_bruto")
    document = json.loads(payload.content)
    selected = next(row for row in document["items"] if row["Mediadiaria"] == "1")
    selected["Cota_15"] = blank
    result = parse(replace(payload, content=json.dumps(document).encode()), config()).rows
    assert result.filter(pl.col("time") == datetime(2024, 1, 15)).item(0, "value") is None


@pytest.mark.recorded("tests/recordings/br_ana")
@pytest.mark.parametrize("field", ["Mediadiaria", "nivelconsistencia", "Data_Hora_Dado", "Cota_15", "Cota_15_Status"])
def test_adversarial_missing_daily_fields_fail_loud(retained_evidence_root, field: str) -> None:
    payload = _payload(retained_evidence_root, "stage_daily_mean_bruto")
    document = json.loads(payload.content)
    selected = next(row for row in document["items"] if row["Mediadiaria"] == "1")
    del selected[field]
    result = parse(replace(payload, content=json.dumps(document).encode()), config())
    assert any(outcome.status.value == "unsupported" for outcome in result.outcomes)
    assert any(issue.code.startswith("source.unsupported") for issue in result.issues)


@pytest.mark.recorded("tests/recordings/br_ana")
def test_daily_status_does_not_select_or_discard_a_published_value(retained_evidence_root) -> None:
    # Adversarial status-only mutation of the original recording. Numeric values stay untouched.
    payload = _payload(retained_evidence_root, "stage_daily_mean_bruto")
    document = json.loads(payload.content)
    selected = next(row for row in document["items"] if row["Mediadiaria"] == "1")
    selected["Cota_15_Status"] = "3"
    original = parse(payload, config()).rows
    changed = parse(replace(payload, content=json.dumps(document).encode()), config())
    pl_testing.assert_frame_equal(original, changed.rows)
    assert any(issue.details is not None and issue.details.get("source_status") == "3" for issue in changed.issues)


@pytest.mark.recorded("tests/recordings/br_ana")
@pytest.mark.parametrize(
    ("product", "month", "first", "last"),
    [
        ("stage_daily_mean_bruto", "2020-01", "2020-01-15T00:00:00", "2020-01-16T00:00:00"),
        ("stage_daily_mean_consistido", "2020-01", "2020-01-15T00:00:00", "2020-01-16T00:00:00"),
        ("discharge_daily_mean_consistido", "2020-01", "2020-01-15T00:00:00", "2020-01-16T00:00:00"),
        ("discharge_daily_mean_bruto", "2024-01", "2024-01-15T00:00:00", "2024-01-16T00:00:00"),
    ],
)
def test_independent_daily_boundary_probe(
    retained_evidence_root, product: str, month: str, first: str, last: str
) -> None:
    # Authored source-only before implementation output access; retained independent report.
    product_id = ProductId(product)
    request = ObservationRequest(
        _PROVIDER,
        ("15400000",),
        (product_id,),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime.fromisoformat(first)),
            WindowEndpoint.from_datetime(datetime.fromisoformat(last)),
        ),
    )
    harness = BoundaryProbeHarness(((_PROVIDER, product_id),))
    harness.register(
        LiveBoundaryProbe(
            provider_id=_PROVIDER,
            product_id=product_id,
            recordings=(read_recording(_recording(retained_evidence_root, product, month)),),
            assertions={
                READING_COUNT: 2,
                FIRST_WALL_CLOCK_TIME: WallClockExpectation(first, "unknown"),
                LAST_WALL_CLOCK_TIME: WallClockExpectation(last, "unknown"),
            },
            run=lambda replay: (
                drive(
                    request,
                    _Stages(),
                    provenance=ObservationProvenance(source="recording", provider_id=_PROVIDER),
                    transport=replay,
                ).canonical_rows
            ),
        )
    )
    harness.run()


@pytest.mark.recorded("tests/recordings/br_ana")
@pytest.mark.parametrize(
    ("product", "values"),
    [
        ("stage_daily_mean_bruto", [1375.0, 1396.0]),
        ("discharge_daily_mean_bruto", [29893.217, 30559.402]),
    ],
)
def test_real_leap_day_slots_are_native_labels_not_march_rollover(
    retained_evidence_root, product: str, values: list[float]
) -> None:
    # Parse seam deliberately: a padded public Feb29 request would require an unrecorded March request.
    rows = (
        parse(_payload(retained_evidence_root, product, "2024-02"), config())
        .rows.filter(pl.col("product_id") == product)
        .select("station_id", "product_id", "time", "value", "time_zone")
    )
    actual = rows.filter(pl.col("time") >= datetime(2024, 2, 28))
    expected = pl.DataFrame(
        {
            "station_id": ["15400000", "15400000"],
            "product_id": [product, product],
            "time": [datetime(2024, 2, 28), datetime(2024, 2, 29)],
            "value": values,
            "time_zone": ["unknown", "unknown"],
        },
        schema=rows.schema,
    )
    pl_testing.assert_frame_equal(actual, expected)


@pytest.mark.recorded("tests/recordings/br_ana")
@pytest.mark.parametrize("product", _PRODUCTS)
def test_real_year_transition_preserves_each_variant_without_fallback(retained_evidence_root, product: str) -> None:
    result = _run(
        retained_evidence_root,
        product,
        "2023-12-30",
        "2024-01-02",
        ("2023-12", "2024-01"),
        receipts=ReceiptMode.INCLUDE,
    )
    prefix = "Cota" if product.startswith("stage") else "Vazao"
    level_field = "nivelconsistencia" if prefix == "Cota" else "Nivel_Consistencia"
    level = "1" if product.endswith("bruto") else "2"
    rows = []
    for month, days in (("2023-12", (30, 31)), ("2024-01", (1, 2))):
        recording = read_recording(_recording(retained_evidence_root, product, month))
        for row in json.loads(recording.content)["items"]:
            if row["Mediadiaria"] != "1" or row[level_field] != level:
                continue
            for day in days:
                raw = row[f"{prefix}_{day:02}"]
                value = None if raw in (None, "") else float(raw)
                if value is not None and prefix == "Cota":
                    value /= 100
                rows.append((datetime.fromisoformat(f"{month}-{day:02}"), "unknown", "15400000", product, value))
    expected = pl.DataFrame(
        rows,
        schema={
            name: result.canonical_rows.schema[name]
            for name in ("time", "time_zone", "station_id", "product_id", "value")
        },
        orient="row",
    )
    pl_testing.assert_frame_equal(result.canonical_rows.select(expected.columns), expected)
    assert len(result.receipts.entries) == 2


@pytest.mark.recorded("tests/recordings/br_ana")
@pytest.mark.parametrize("product", _PRODUCTS)
def test_real_nonleap_february_has_no_march_rollover(retained_evidence_root, product: str) -> None:
    payload = _payload(retained_evidence_root, product, "2023-02")
    rows = (
        parse(payload, config())
        .rows.filter(pl.col("product_id") == product)
        .select("station_id", "product_id", "time", "value", "time_zone")
    )
    prefix = "Cota" if product.startswith("stage") else "Vazao"
    level_field = "nivelconsistencia" if prefix == "Cota" else "Nivel_Consistencia"
    level = "1" if product.endswith("bruto") else "2"
    expected_rows = []
    for row in json.loads(payload.content)["items"]:
        if row["Mediadiaria"] != "1" or row[level_field] != level:
            continue
        for day in range(1, 29):
            value = row[f"{prefix}_{day:02}"]
            expected_rows.append(
                ("15400000", product, datetime(2023, 2, day), None if value in (None, "") else float(value), "unknown")
            )
    expected = pl.DataFrame(expected_rows, schema=rows.schema, orient="row")
    pl_testing.assert_frame_equal(rows, expected)


@pytest.mark.recorded("tests/recordings/br_ana")
@pytest.mark.parametrize(
    ("product", "count", "first", "last"),
    [
        ("stage_daily_mean_bruto", 2, "2023-12-31T00:00:00", "2024-01-01T00:00:00"),
        ("stage_daily_mean_consistido", 1, "2023-12-31T00:00:00", "2023-12-31T00:00:00"),
        ("discharge_daily_mean_bruto", 1, "2024-01-01T00:00:00", "2024-01-01T00:00:00"),
        ("discharge_daily_mean_consistido", 1, "2023-12-31T00:00:00", "2023-12-31T00:00:00"),
    ],
)
def test_independent_year_boundary_no_variant_fallback(
    retained_evidence_root, product: str, count: int, first: str, last: str
) -> None:
    # Literals from the independent source-only extension, not this port's output.
    result = _run(retained_evidence_root, product, "2023-12-31T00:00:00", "2024-01-01T00:00:00", ("2023-12", "2024-01"))
    assert result.canonical_rows.height == count
    assert result.canonical_rows.item(0, "time") == datetime.fromisoformat(first)
    assert result.canonical_rows.item(-1, "time") == datetime.fromisoformat(last)


@pytest.mark.recorded("tests/recordings/br_ana")
def test_real_null_daily_status_does_not_discard_published_value(retained_evidence_root) -> None:
    result = _run(retained_evidence_root, "stage_daily_mean_bruto", "2023-12-31", "2024-01-01", ("2023-12", "2024-01"))
    assert result.canonical_rows.filter(pl.col("time") == datetime(2023, 12, 31)).item(0, "value") == 7.595
    assert any(
        issue.code == "source_status" and issue.details is not None and issue.details["source_status"] is None
        for issue in result.issues
    )


@pytest.mark.recorded("tests/recordings/br_ana")
def test_daily_label_is_not_an_established_interval_anchor(retained_evidence_root) -> None:
    parsed = parse(_payload(retained_evidence_root, "stage_daily_mean_bruto", "2020-01"), config())
    assert {item.variant for item in parsed.series} == {"bruto", "consistido"}
    for series in parsed.series:
        facts = series.facts[0]
        assert facts.label_time == "00:00"
        assert facts.timestamp_anchor.value is None
        assert facts.timestamp_anchor.evidence == ()
