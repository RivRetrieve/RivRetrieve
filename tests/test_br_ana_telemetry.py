"""Adopted ANA telemetry stages over exact recordings, not yet public registration.

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
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.br_ana.config import BrAnaSourceCoordinates, config, window_declarations
from rivretrieve._internal.providers.br_ana.fetch import fetch
from rivretrieve._internal.providers.br_ana.parse import parse
from rivretrieve._internal.recordings import ReplayTransport, UnmatchedRequestError, read_recording
from rivretrieve._internal.store import StoreRoot

_DATA = Path(__file__).parent / "recordings" / "br_ana"
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


def _recording(anchor: str) -> Path:
    return _DATA / f"telemetry_15400000_{anchor}_DIAS_30.recording.json"


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


def _run(product: ProductId, start: str, end: str, anchors: tuple[str, ...], **kwargs):
    return drive(
        _request(product, start, end),
        _Stages(),
        provenance=ObservationProvenance(source="test-internal-stages", provider_id=_PROVIDER),
        transport=ReplayTransport([_recording(anchor) for anchor in anchors]),
        **kwargs,
    )


@pytest.mark.parametrize("product", _PRODUCTS)
def test_independent_midnight_probe_through_actual_engine(product: ProductId) -> None:
    # Independent author did not see the port or its output. Exactly three assertions.
    harness = BoundaryProbeHarness(((_PROVIDER, product),))
    harness.register(
        LiveBoundaryProbe(
            provider_id=_PROVIDER,
            product_id=product,
            recordings=(read_recording(_recording("2024-01-04")),),
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
def test_fixed_spans_match_recorded_native_values_and_preserve_nulls(product, start, end, anchors) -> None:
    result = _run(product, start, end, anchors, receipts=ReceiptMode.INCLUDE)
    coordinate = config().products[product].coordinates.value
    assert isinstance(coordinate, BrAnaSourceCoordinates)
    # Interior fidelity assertion, not an independently authored boundary probe.
    # Decode exact bytes directly; do not reuse the production decoder or conversion.
    rows = []
    for anchor in anchors:
        envelope = read_recording(_recording(anchor))
        for row in json.loads(envelope.content)["items"]:
            label = datetime.fromisoformat(row["Data_Hora_Medicao"])
            if datetime.fromisoformat(start) <= label <= datetime.fromisoformat(end):
                raw = row[coordinate.field]
                value = None if raw is None else float(raw)
                if value is not None and coordinate.field == "Cota_Adotada":
                    value /= 100
                rows.append((label, "unknown", "15400000", product, value))
    expected = pl.DataFrame(rows, schema=result.canonical_rows.schema, orient="row").sort("time")
    pl_testing.assert_frame_equal(result.canonical_rows.sort("time"), expected)
    assert not result.canonical_rows.is_duplicated().any()
    assert [entry.content for entry in result.receipts.entries] == [
        read_recording(_recording(a)).content for a in anchors
    ]
    calls = [
        call for call in result.provenance.calls_made if "request_parameters" in call and call["request_parameters"]
    ]
    assert [call["request_parameters"]["Data de Busca (yyyy-MM-dd)"] for call in calls] == list(anchors)


@pytest.mark.parametrize("product", _PRODUCTS)
def test_original_capped_span_reproduces_real_overlapping_rows(product: ProductId) -> None:
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
        transport=ReplayTransport([_recording(a) for a in ("2024-01-01", "2024-01-04")]),
    )
    assert result.canonical_rows.is_duplicated().any()


@pytest.mark.parametrize("product", _PRODUCTS)
def test_cache_reuses_native_values_without_double_conversion(product: ProductId, tmp_path: Path) -> None:
    store = StoreRoot(tmp_path / "store")
    live = _run(product, "2024-01-01T23:30:00", "2024-01-02T00:30:00", ("2024-01-04",), cache="reuse", store=store)
    cached = _run(product, "2024-01-01T23:30:00", "2024-01-02T00:30:00", (), cache="reuse", store=store)
    pl_testing.assert_frame_equal(live.canonical_rows, cached.canonical_rows)
    assert live.receipts.entries == cached.receipts.entries == ()


def test_wrong_anchor_fails_exact_replay() -> None:
    with pytest.raises(UnmatchedRequestError):
        _run(_PRODUCTS[0], "2024-01-02T23:30:00", "2024-01-03T00:30:00", ("2024-01-04",))


def _payload(product: ProductId, anchor: str = "2024-01-04"):
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
        ReplayTransport([_recording(anchor)]),
    ).value[0]


@pytest.mark.parametrize("field", ["Cota_Adotada", "Vazao_Adotada", "Data_Hora_Medicao", "codigoestacao"])
def test_missing_required_fields_fail_loud_from_corrupted_recording(field: str) -> None:
    # Adversarial corruption only: not a source observation fixture or boundary expectation.
    product = ProductId("stage_instantaneous" if field == "Cota_Adotada" else "discharge_instantaneous")
    payload = _payload(product)
    document = json.loads(payload.content)
    del document["items"][0][field]
    with pytest.raises(FatalContractError):
        parse(replace(payload, content=json.dumps(document).encode()), config())


@pytest.mark.parametrize("bad_value", ["", "NaN", "Infinity", "not-a-number", True, 1, "9" * 400])
def test_invalid_values_fail_loud_from_corrupted_recording(bad_value: object) -> None:
    payload = _payload(ProductId("stage_instantaneous"))
    document = json.loads(payload.content)
    document["items"][0]["Cota_Adotada"] = bad_value
    with pytest.raises(FatalContractError):
        parse(replace(payload, content=json.dumps(document).encode()), config())


def test_real_null_values_and_status_are_retained() -> None:
    result = _run(ProductId("stage_instantaneous"), "2023-11-18", "2023-12-03", ("2023-12-05",))
    assert result.canonical_rows["value"].null_count() > 0
    assert any(issue.details["source_status"] is None for issue in result.issues if issue.code == "source_status")


def test_duplicate_multiplicity_is_not_a_quality_selection_rule() -> None:
    # Deliberately repeated *real* source bytes challenge multiplicity handling only.
    payload = _payload(ProductId("stage_instantaneous"))
    document = json.loads(payload.content)
    document["items"].append(document["items"][0])
    original = parse(payload, config()).value
    repeated = parse(replace(payload, content=json.dumps(document).encode()), config()).value
    pl_testing.assert_frame_equal(
        repeated,
        pl.concat(
            [
                original,
                original.filter(pl.col("time") == datetime.fromisoformat(document["items"][0]["Data_Hora_Medicao"])),
            ]
        ).sort("time", maintain_order=True),
    )
