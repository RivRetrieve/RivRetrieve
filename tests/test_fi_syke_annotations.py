"""Source-independent tests for fi_syke observation annotations (#819)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ObservationDataSchema, ReceiptAuthorship
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.fi_syke.config import config
from rivretrieve._internal.providers.fi_syke.parse import parse
from rivretrieve._internal.source_annotations import CATALOG_SCHEMA, AnnotationScope
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_STATION = "1721"
_RETRIEVED_AT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
_ORIGIN = SourceCallOrigin(
    "https://rajapinnat.ymparisto.fi/api/Hydrologiarajapinta/1.1/odata/Virtaama",
    {},
    200,
    _RETRIEVED_AT,
    "application/json",
    UnknownOriginFact(),
    UnknownOriginFact(),
)


def _payload(product: str, rows: list[dict[str, object]]) -> Payload:
    return Payload(
        config().products[ProductId(product)].coordinates,
        ((_STATION, ProductId(product)),),
        _make_fetch_window(WindowEndpoint(2026, 9, 1, 0, 0, 0, 0), WindowEndpoint(2026, 9, 5, 0, 0, 0, 0)),
        json.dumps({"odata.metadata": "x", "value": rows}).encode(),
        _ORIGIN,
        (),
    )


def _row(day: int, value: object, *, flag: object = None) -> dict[str, object]:
    return {
        "Paikka_Id": int(_STATION),
        "Aika": f"2026-09-{day:02d}T00:00:00",
        "Arvo": value,
        "ArvoMin": None,
        "ArvoMax": None,
        "Lippu_id": flag,
        "huomautus": None,
    }


def test_fi_syke_annotation_schema_and_official_reference() -> None:
    from rivretrieve._internal.providers.fi_syke.annotations import FI_SYKE_OBSERVATIONS_SCHEMA, FI_SYKE_URL

    assert FI_SYKE_OBSERVATIONS_SCHEMA.schema_id == "fi_syke.observations"
    assert FI_SYKE_OBSERVATIONS_SCHEMA.provider_id == "fi_syke"
    assert FI_SYKE_OBSERVATIONS_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert [field.name for field in FI_SYKE_OBSERVATIONS_SCHEMA.fields] == ["Lippu_id"]
    assert [field.dtype for field in FI_SYKE_OBSERVATIONS_SCHEMA.fields] == ["Int64"]
    field = FI_SYKE_OBSERVATIONS_SCHEMA.fields[0]
    assert field.description
    assert field.reference_url == FI_SYKE_URL
    assert "Lippu" in field.description


@pytest.mark.parametrize("product", ["discharge_reported", "stage_reported"])
def test_fi_syke_discharge_and_stage_preserve_lippu_id_and_retire_flag_issues(product: str) -> None:
    rows = [
        _row(1, 12.5, flag=None),
        _row(2, 13.0, flag=1),
        _row(3, None, flag=108),
        _row(4, 14.0, flag=-(1 << 63)),
        _row(5, 15.0, flag=(1 << 63) - 1),
    ]
    parsed = parse(_payload(product, rows), config())

    assert parsed.outcomes[0].status is OutcomeStatus.SUCCESS
    assert parsed.issues == ()
    assert parsed.rows.height == 5
    assert set(parsed.annotations.observation_tables) == {"fi_syke.observations"}
    assert not parsed.annotations.series_tables

    table = parsed.annotations.observation_tables["fi_syke.observations"]
    assert table.measurement_indices == (0, 1, 2, 3, 4)
    assert table.rows["Lippu_id"].dtype == pl.Int64()
    assert table.rows["Lippu_id"].to_list() == [None, 1, 108, -(1 << 63), (1 << 63) - 1]
    assert table.rows["measured"].to_list() == [True] * 5


def test_fi_syke_temperature_route_emits_empty_annotations() -> None:
    rows = [{"Paikka_Id": int(_STATION), "Aika": "2026-09-01T00:00:00", "Arvo": 14.2}]
    parsed = parse(_payload("water_temperature_reported", rows), config())

    assert parsed.outcomes[0].status is OutcomeStatus.SUCCESS
    assert parsed.issues == ()
    assert parsed.rows.height == 1
    assert parsed.annotations.is_empty


def test_fi_syke_empty_discharge_emits_empty_annotations() -> None:
    parsed = parse(_payload("discharge_reported", []), config())
    assert parsed.outcomes[0].status is OutcomeStatus.EMPTY
    assert parsed.rows.is_empty()
    assert parsed.annotations.is_empty


@pytest.mark.parametrize("bad_flag", [True, False, "1", 1.5, [1], {"id": 1}, 1 << 63, -(1 << 63) - 1])
def test_fi_syke_rejects_boolean_or_non_int64_lippu_id(bad_flag: object) -> None:
    with pytest.raises(UnsupportedSourceStructureError, match="Lippu_id"):
        parse(_payload("discharge_reported", [_row(1, 12.5, flag=bad_flag)]), config())


def test_fi_syke_public_mixed_routes_clipping_refresh_and_bundles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    phase = {"step": "initial"}

    class _Transport:
        def __init__(self, handler: Callable[[str], list[dict[str, object]]]) -> None:
            self.handler = handler
            self.calls: list[str] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            entity_set = request.url.rsplit("/", 1)[-1]
            self.calls.append(entity_set)
            if phase["step"] == "fail_stage" and entity_set == "Vedenkorkeus":
                raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
            rows = self.handler(entity_set)
            return TransportResponse(
                json.dumps({"odata.metadata": "x", "value": rows}).encode(),
                200,
                _RETRIEVED_AT,
                "application/json",
                request.url,
                dict(request.params),
            )

    def handler(entity_set: str) -> list[dict[str, object]]:
        if entity_set == "LampoPintavesi":
            return [{"Paikka_Id": 1721, "Aika": "2026-09-02T00:00:00", "Arvo": 11.5}]
        flag = 108 if phase["step"] == "reannotated" else (1 if entity_set == "Virtaama" else None)
        return [
            _row(1, 900.0, flag=115),
            _row(2, 100.0 if entity_set == "Virtaama" else 200.0, flag=flag),
            _row(4, 901.0, flag=116),
        ]

    transport = _Transport(handler)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    selection = rr.find(provider="fi_syke", station=_STATION)
    assert rr.annotations(selection).is_empty()
    base_series = rr.series(selection)

    result = rr.fetch(selection, start="2026-09-02", end="2026-09-03", cache="reuse", receipts=True, on_issue="ignore")
    assert set(transport.calls) == {"Virtaama", "Vedenkorkeus", "LampoPintavesi"}
    assert result.issues == ()
    assert list(result.data.columns) == list(ObservationDataSchema.polars_schema)
    assert rr.series(result).columns == base_series.columns
    assert result.data.height == 3

    catalog = rr.annotations(result)
    assert list(catalog.columns) == list(CATALOG_SCHEMA)
    assert catalog["schema"].to_list() == ["fi_syke.observations"]
    assert catalog["name"].to_list() == ["Lippu_id"]
    assert catalog["row_count"].to_list() == [2]

    direct = rr.annotations(result, schema="fi_syke.observations").sort("product_id")
    assert direct["product_id"].to_list() == ["discharge_reported", "stage_reported"]
    assert direct["Lippu_id"].to_list() == [1, None]

    projected = result.to_polars(annotations=True).sort("product_id")
    assert projected.columns == [*result.data.columns, "Lippu_id"]
    assert projected["product_id"].to_list() == ["discharge_reported", "stage_reported", "water_temperature_reported"]
    assert projected["Lippu_id"].to_list() == [1, None, None]
    pandas_df = result.to_pandas(annotations=True)
    assert isinstance(pandas_df, pd.DataFrame)
    assert list(pandas_df.columns) == [*result.data.columns, "Lippu_id"]

    call_count_before_reuse = len(transport.calls)
    reused = rr.fetch(selection, start="2026-09-02", end="2026-09-03", cache="reuse", receipts=True, on_issue="ignore")
    assert len(transport.calls) == call_count_before_reuse
    assert all(entry.authorship is ReceiptAuthorship.STORE_EXCERPT for entry in reused.receipts.entries)
    pl_testing.assert_frame_equal(reused.to_polars(annotations=True).sort("product_id"), projected)

    restored = rr.from_bundle(rr.to_bundle(result))
    pl_testing.assert_frame_equal(rr.annotations(restored), rr.annotations(result))
    pl_testing.assert_frame_equal(restored.to_polars(annotations=True).sort("product_id"), projected)

    # Status-only refresh updates Lippu_id while values stay unchanged; failed refresh preserves held Lippu_id.
    phase["step"] = "reannotated"
    refreshed = rr.fetch(selection, start="2026-09-02", end="2026-09-03", cache="refresh", on_issue="ignore")
    assert refreshed.to_polars(annotations=True).sort("product_id")["Lippu_id"].to_list() == [108, 108, None]

    phase["step"] = "fail_stage"
    partial = rr.fetch(selection, start="2026-09-02", end="2026-09-03", cache="refresh", on_issue="ignore")
    outcomes = {o.product_id: o.status for o in partial.outcomes}
    assert outcomes["discharge_reported"] is OutcomeStatus.SUCCESS
    assert outcomes["stage_reported"] is OutcomeStatus.FAILED
    held = rr.fetch(selection, start="2026-09-02", end="2026-09-03", cache="reuse", on_issue="ignore")
    assert held.to_polars(annotations=True).sort("product_id")["Lippu_id"].to_list() == [1, 108, None]
