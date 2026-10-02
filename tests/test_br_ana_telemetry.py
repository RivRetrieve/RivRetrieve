"""Tests for internal ANA adopted telemetry stages using exact recordings.

Boundary literals were authored independently from source bytes. See the retained
recording README and independent-expectations.md. No conventional daily claim is made.
"""

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
from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    ObservationRequest,
    ProductWindowDeclarations,
    RequestedWindow,
    StopConvention,
    WindowDeclaration,
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
)
from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.br_ana.config import BrAnaSourceCoordinates, config, window_declarations
from rivretrieve._internal.providers.br_ana.fetch import fetch
from rivretrieve._internal.providers.br_ana.parse import parse
from rivretrieve._internal.recordings import ReplayTransport, UnmatchedRequestError, read_recording
from rivretrieve._internal.store import StoreRoot

_PRODUCTS = tuple(
    product
    for product, definition in config().products.items()
    if isinstance(definition.coordinates.value, BrAnaSourceCoordinates)
)
_PROVIDER = ProviderId("br_ana")


class _Stages:
    config = config()
    window_declarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


def _recording(retained_evidence_root, anchor: str) -> Path:
    return (retained_evidence_root / "tests/recordings/br_ana") / f"telemetry_15400000_{anchor}_DIAS_30.recording.json"


def _request(product: ProductId, start: str, end: str) -> ObservationRequest:
    return ObservationRequest(
        _PROVIDER,
        ("15400000",),
        (product,),
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime.fromisoformat(start)),
            WindowEndpoint.from_datetime(datetime.fromisoformat(end)),
        ),
    )


def _run(
    retained_evidence_root,
    product: ProductId,
    start: str,
    end: str,
    anchors: tuple[str, ...],
    *,
    explicit_adopted: bool = False,
    **kwargs,
):
    request = _request(product, start, end)
    if explicit_adopted:
        from rivretrieve._internal.providers.br_ana.series import describe_series
        from rivretrieve._internal.source_series import RestrictionKind, SeriesScope

        coordinates = config().products[product].coordinates.value
        assert isinstance(coordinates, BrAnaSourceCoordinates)
        definition = describe_series("15400000", product, coordinates)
        request = replace(
            request,
            known_series=(definition,),
            scope=SeriesScope(
                provider_ids=("br_ana",),
                station_ids=("15400000",),
                product_ids=(product,),
                restriction=RestrictionKind.EXPLICIT,
                variants=(coordinates.field,),
            ),
        )
    return drive(
        request,
        _Stages(),
        provenance=ObservationProvenance(source="test-internal-stages", provider_id=_PROVIDER),
        transport=ReplayTransport([_recording(retained_evidence_root, anchor) for anchor in anchors]),
        **kwargs,
    )


@pytest.mark.parametrize("product", _PRODUCTS)
def test_independent_midnight_probe_through_actual_engine(retained_evidence_root, product: ProductId) -> None:
    # Independent author did not see the port or its output. Exactly three assertions.
    harness = BoundaryProbeHarness(((_PROVIDER, product),))
    harness.register(
        LiveBoundaryProbe(
            provider_id=_PROVIDER,
            product_id=product,
            recordings=(read_recording(_recording(retained_evidence_root, "2024-01-04")),),
            assertions={
                READING_COUNT: 5,
                FIRST_WALL_CLOCK_TIME: WallClockExpectation("2024-01-01T23:30:00", "unknown"),
                LAST_WALL_CLOCK_TIME: WallClockExpectation("2024-01-02T00:30:00", "unknown"),
            },
            run=lambda replay: (
                drive(
                    _request(product, "2024-01-01T23:30:00", "2024-01-02T00:30:00"),
                    _Stages(),
                    provenance=ObservationProvenance(source="test-internal-stages", provider_id=_PROVIDER),
                    transport=replay,
                ).canonical_rows
            ),
        )
    )
    harness.run()


@pytest.mark.parametrize("product", _PRODUCTS)
@pytest.mark.parametrize(
    ("start", "end", "anchors"),
    [
        ("2023-12-05", "2024-01-02", ("2023-12-05", "2024-01-04")),
        ("2023-12-05", "2024-01-29", ("2024-01-01", "2024-01-31")),
        ("2023-11-17", "2023-12-03", ("2023-12-05",)),
    ],
)
def test_fixed_spans_match_recorded_native_values_and_preserve_nulls(
    retained_evidence_root, product, start, end, anchors
) -> None:
    result = _run(retained_evidence_root, product, start, end, anchors, receipts=ReceiptMode.INCLUDE)
    coordinate = config().products[product].coordinates.value
    assert isinstance(coordinate, BrAnaSourceCoordinates)
    # Interior fidelity assertion, not an independently authored boundary probe.
    # Decode exact bytes directly; do not reuse the production decoder or conversion.
    rows = []
    for anchor in anchors:
        envelope = read_recording(_recording(retained_evidence_root, anchor))
        for row in json.loads(envelope.content)["items"]:
            label = datetime.fromisoformat(row["Data_Hora_Medicao"])
            if datetime.fromisoformat(start) <= label <= datetime.fromisoformat(end):
                raw = row[coordinate.field]
                value = None if raw is None else float(raw)
                if value is not None and coordinate.field == "Cota_Adotada":
                    value /= 100
                rows.append((label, "unknown", "15400000", product, value))
    expected = pl.DataFrame(
        rows,
        schema={
            name: result.canonical_rows.schema[name]
            for name in ("time", "time_zone", "station_id", "product_id", "value")
        },
        orient="row",
    ).sort("time")
    pl_testing.assert_frame_equal(result.canonical_rows.select(expected.columns).sort("time"), expected)
    assert not result.canonical_rows.is_duplicated().any()
    assert [entry.content for entry in result.receipts.entries] == [
        read_recording(_recording(retained_evidence_root, a)).content for a in anchors
    ]
    calls = [
        call for call in result.provenance.calls_made if "request_parameters" in call and call["request_parameters"]
    ]
    assert [call["request_parameters"]["Data de Busca (yyyy-MM-dd)"] for call in calls] == list(anchors)


@pytest.mark.parametrize("product", _PRODUCTS)
def test_original_capped_span_reproduces_real_overlapping_rows(retained_evidence_root, product: ProductId) -> None:
    class CappedStages(_Stages):
        window_declarations = ProductWindowDeclarations(
            {
                product: WindowDeclaration(
                    WindowGranularity("capped-span"),
                    WindowRenderingVocabulary.DATE,
                    StopConvention.INCLUSIVE,
                    30,
                )
            }
        )

    result = drive(
        _request(product, "2023-12-05", "2024-01-02"),
        CappedStages(),
        provenance=ObservationProvenance(source="test-old-window-contract", provider_id=_PROVIDER),
        transport=ReplayTransport([_recording(retained_evidence_root, a) for a in ("2024-01-01", "2024-01-04")]),
    )
    assert result.canonical_rows.is_duplicated().any()


@pytest.mark.parametrize("product", _PRODUCTS)
def test_cache_reuses_native_values_without_double_conversion(
    retained_evidence_root, product: ProductId, tmp_path: Path
) -> None:
    store = StoreRoot(tmp_path / "store")
    live = _run(
        retained_evidence_root,
        product,
        "2024-01-01T23:30:00",
        "2024-01-02T00:30:00",
        ("2024-01-04",),
        cache="reuse",
        store=store,
        explicit_adopted=True,
    )
    cached = _run(
        retained_evidence_root,
        product,
        "2024-01-01T23:30:00",
        "2024-01-02T00:30:00",
        (),
        cache="reuse",
        store=store,
        explicit_adopted=True,
    )
    pl_testing.assert_frame_equal(live.canonical_rows, cached.canonical_rows)
    assert live.receipts.entries == cached.receipts.entries == ()


def test_wrong_anchor_fails_exact_replay(retained_evidence_root) -> None:
    with pytest.raises(UnmatchedRequestError):
        _run(retained_evidence_root, _PRODUCTS[0], "2024-01-02T23:30:00", "2024-01-03T00:30:00", ("2024-01-04",))


def _payload(retained_evidence_root, product: ProductId, anchor: str = "2024-01-04"):
    # Capture payload from real fetch, preserving its exact source tags and origin.
    from rivretrieve._internal.coverage import RequestedInterval
    from rivretrieve._internal.driver import _padded_interval
    from rivretrieve._internal.window_planning import plan_windows

    window = _padded_interval(RequestedInterval(datetime(2024, 1, 1), datetime(2024, 1, 2)))
    declaration = window_declarations().products[product]
    return fetch(
        ("15400000",),
        (product,),
        {product: plan_windows(window, declaration)},
        window,
        config(),
        ReplayTransport([_recording(retained_evidence_root, anchor)]),
    ).value[0]


@pytest.mark.parametrize("field", ["Cota_Adotada", "Vazao_Adotada", "Data_Hora_Medicao", "codigoestacao"])
def test_missing_required_fields_fail_loud_from_corrupted_recording(retained_evidence_root, field: str) -> None:
    # Adversarial corruption only: not a source observation fixture or boundary expectation.
    product = ProductId("stage_instantaneous" if field == "Cota_Adotada" else "discharge_instantaneous")
    payload = _payload(retained_evidence_root, product)
    document = json.loads(payload.content)
    del document["items"][0][field]
    result = parse(replace(payload, content=json.dumps(document).encode()), config())
    assert any(outcome.status.value == "unsupported" for outcome in result.outcomes)
    assert any(issue.code.startswith("source.unsupported") for issue in result.issues)


@pytest.mark.parametrize("bad_value", ["", "NaN", "Infinity", "not-a-number", True, 1, "9" * 400])
def test_invalid_values_fail_loud_from_corrupted_recording(retained_evidence_root, bad_value: object) -> None:
    payload = _payload(retained_evidence_root, ProductId("stage_instantaneous"))
    document = json.loads(payload.content)
    document["items"][0]["Cota_Adotada"] = bad_value
    result = parse(replace(payload, content=json.dumps(document).encode()), config())
    assert any(outcome.status.value == "unsupported" for outcome in result.outcomes)
    assert any(issue.code.startswith("source.unsupported") for issue in result.issues)


def test_real_null_values_and_status_are_retained(retained_evidence_root) -> None:
    result = _run(retained_evidence_root, ProductId("stage_instantaneous"), "2023-11-18", "2023-12-03", ("2023-12-05",))
    assert result.canonical_rows["value"].null_count() > 0
    assert any(issue.details["source_status"] is None for issue in result.issues if issue.code == "source_status")


def test_duplicate_multiplicity_is_not_a_quality_selection_rule(retained_evidence_root) -> None:
    # Deliberately repeated *real* source bytes challenge multiplicity handling only.
    payload = _payload(retained_evidence_root, ProductId("stage_instantaneous"))
    document = json.loads(payload.content)
    document["items"].append(document["items"][0])
    original = parse(payload, config()).rows
    repeated = parse(replace(payload, content=json.dumps(document).encode()), config()).rows
    pl_testing.assert_frame_equal(
        repeated,
        pl.concat(
            [
                original,
                original.filter(pl.col("time") == datetime.fromisoformat(document["items"][0]["Data_Hora_Medicao"])),
            ]
        ).sort("time", maintain_order=True),
    )


def test_exact_detailed_recording_does_not_establish_adopted_equivalence(retained_evidence_root) -> None:
    recording = read_recording(
        (retained_evidence_root / "tests/recordings/br_ana")
        / "HidroinfoanaSerieTelemetricaDetalhada_15400000_2024-01-02_HORA_24.recording.json"
    )
    assert recording.sha256 == "8f4049713c0b2e46b886052092191ae9d42a0def9047543a74b17eb1bf620feb"
    rows = json.loads(recording.content)["items"]
    assert len(rows) == 96
    sensor = [row for row in rows if row["Cota_Sensor"] is not None]
    assert len(sensor) == 92
    assert sum(float(row["Cota_Sensor"]) != float(row["Cota_Adotada"]) for row in sensor) == 20
    assert all(row["Cota_Manual"] is None and row["Cota_Display"] is None for row in rows)
    # Numeric comparison disproves equality; it does not establish units, datum,
    # temporal support, or general absence of the all-null manual/display fields.
