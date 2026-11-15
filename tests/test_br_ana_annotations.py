"""Tests for ANA source annotation extraction, alignment, storage, and public workflows."""

from __future__ import annotations

import hashlib
import io
import json
import re
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.authentication import ExchangeSpec
from rivretrieve._internal.engine import (
    Payload,
    RowsSchema,
    SourceCallOrigin,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ObservationDataSchema, ReceiptAuthorship
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.br_ana.annotations import (
    BR_ANA_DAILY_COTAS_SCHEMA,
    BR_ANA_DAILY_VAZAO_SCHEMA,
    BR_ANA_MANUAL_URL,
    BR_ANA_SWAGGER_URL,
    BR_ANA_TELEMETRY_COTA_SCHEMA,
    BR_ANA_TELEMETRY_VAZAO_SCHEMA,
)
from rivretrieve._internal.providers.br_ana.config import BrAnaDailySourceCoordinates, config
from rivretrieve._internal.providers.br_ana.parse import parse
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.source_annotations import CATALOG_SCHEMA, OBSERVATION_STRUCTURAL_SCHEMA, AnnotationScope
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import HttpClient, TransportRequest, TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_STATION = "15400000"
_IDENTIFIER = "protocol-identifier-sentinel"
_PASSWORD = "protocol-password-sentinel"


@pytest.fixture(autouse=True)
def isolated_public_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    for name in ("ANA_IDENTIFICADOR", "ANA_SENHA", "NVE_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    def forbidden_client():
        raise AssertionError("offline public tests must inject their transport")

    monkeypatch.setattr(discovery, "HttpClient", forbidden_client)


def _envelope(items: list[dict[str, object]]) -> dict[str, object]:
    return {"status": "OK", "code": 200, "items": items}


def _payload(
    product: str,
    body: dict[str, object] | list[dict[str, object]],
    *,
    start: datetime = datetime(2024, 1, 1),
    end: datetime = datetime(2024, 2, 29, 23, 59, 59, 999999),
) -> Payload:
    raw = json.dumps(body).encode()
    coords = config().products[ProductId(product)].coordinates
    endpoint = (
        coords.value.endpoint
        if isinstance(coords.value, BrAnaDailySourceCoordinates)
        else "HidroinfoanaSerieTelemetricaAdotada"
    )
    return Payload(
        source_coordinates=coords,
        station_products=((_STATION, ProductId(product)),),
        fetch_window=_make_fetch_window(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end)),
        content=raw,
        origin=SourceCallOrigin(
            url=f"https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/{endpoint}/v1",
            request_parameters={},
            status_code=200,
            retrieved_at=datetime(2026, 9, 21, tzinfo=UTC),
            content_type="application/json",
            source_path=UnknownOriginFact(),
            query=UnknownOriginFact(),
        ),
        prerequisite_calls=(),
        acquisition_id=hashlib.sha256(raw).hexdigest(),
    )


def _daily_item(
    *,
    station: str = _STATION,
    prefix: str = "Cota",
    consistency: str = "1",
    mean: str = "1",
    header: str = "2024-02-01 00:00:00.0",
    method_value: str | None = "2",
    day_values: dict[int, tuple[str | None, str | None]] | None = None,
) -> dict[str, object]:
    consistency_field = "nivelconsistencia" if prefix == "Cota" else "Nivel_Consistencia"
    method_field = "Tipo_Medicao_Cotas" if prefix == "Cota" else "Metodo_Obtencao_Vazoes"
    item: dict[str, object] = {
        "codigoestacao": station,
        "Mediadiaria": mean,
        consistency_field: consistency,
        "Data_Hora_Dado": header,
        method_field: method_value,
    }
    overrides = day_values or {}
    for day in range(1, 32):
        val, status = overrides.get(day, (None, None))
        item[f"{prefix}_{day:02d}"] = val
        item[f"{prefix}_{day:02d}_Status"] = status
    return item


def test_br_ana_annotation_schema_definitions() -> None:
    assert BR_ANA_DAILY_COTAS_SCHEMA.schema_id == "br_ana.daily_cotas"
    assert BR_ANA_DAILY_COTAS_SCHEMA.provider_id == "br_ana"
    assert BR_ANA_DAILY_COTAS_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert [(f.name, f.dtype, f.reference_url) for f in BR_ANA_DAILY_COTAS_SCHEMA.fields] == [
        ("Cota_Status", "String", BR_ANA_SWAGGER_URL),
        ("Tipo_Medicao_Cotas", "String", BR_ANA_SWAGGER_URL),
    ]

    assert BR_ANA_DAILY_VAZAO_SCHEMA.schema_id == "br_ana.daily_vazao"
    assert BR_ANA_DAILY_VAZAO_SCHEMA.provider_id == "br_ana"
    assert BR_ANA_DAILY_VAZAO_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert [(f.name, f.dtype, f.reference_url) for f in BR_ANA_DAILY_VAZAO_SCHEMA.fields] == [
        ("Vazao_Status", "String", BR_ANA_SWAGGER_URL),
        ("Metodo_Obtencao_Vazoes", "String", BR_ANA_SWAGGER_URL),
    ]

    assert BR_ANA_TELEMETRY_COTA_SCHEMA.schema_id == "br_ana.telemetry_cota"
    assert BR_ANA_TELEMETRY_COTA_SCHEMA.provider_id == "br_ana"
    assert BR_ANA_TELEMETRY_COTA_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert [(f.name, f.dtype, f.reference_url) for f in BR_ANA_TELEMETRY_COTA_SCHEMA.fields] == [
        ("Cota_Adotada_Status", "String", BR_ANA_MANUAL_URL),
    ]

    assert BR_ANA_TELEMETRY_VAZAO_SCHEMA.schema_id == "br_ana.telemetry_vazao"
    assert BR_ANA_TELEMETRY_VAZAO_SCHEMA.provider_id == "br_ana"
    assert BR_ANA_TELEMETRY_VAZAO_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert [(f.name, f.dtype, f.reference_url) for f in BR_ANA_TELEMETRY_VAZAO_SCHEMA.fields] == [
        ("Vazao_Adotada_Status", "String", BR_ANA_MANUAL_URL),
    ]


def test_br_ana_daily_multimonth_padding_method_propagation_and_duplicates() -> None:
    jan_first = _daily_item(
        prefix="Cota",
        consistency="1",
        header="2024-01-01 00:00:00.0",
        method_value="1",
        day_values={2: ("10.0", "2"), 1: ("9.5", "0"), 31: ("11.0", None)},
    )
    feb_second = _daily_item(
        prefix="Cota",
        consistency="1",
        header="2024-02-01 00:00:00.0",
        method_value="4",
        day_values={29: ("12.5", "3")},
    )
    jan_dup = _daily_item(
        prefix="Cota",
        consistency="1",
        header="2024-01-01 00:00:00.0",
        method_value=None,
        day_values={1: ("8.5", "4"), 2: ("10.5", "1")},
    )
    consistido_feb = _daily_item(
        prefix="Cota",
        consistency="2",
        header="2024-02-01 00:00:00.0",
        method_value="2",
        day_values={1: ("20.0", "1")},
    )
    payload = _payload("stage_daily_mean_bruto", _envelope([feb_second, jan_first, jan_dup, consistido_feb]))
    parsed = parse(payload, config())

    assert list(parsed.rows.columns) == list(RowsSchema.polars_schema)
    assert not any(issue.code == "source_status" for issue in parsed.issues)

    # Jan (31 * 2) + Feb 2024 leap (29 * 1) for bruto + Feb 2024 leap (29 * 1) for consistido = 120 rows; padding days excluded.
    assert parsed.rows.height == 31 * 2 + 29 + 29
    table = parsed.annotations.observation_tables["br_ana.daily_cotas"]
    assert table.rows.height == parsed.rows.height
    assert table.rows.schema == {
        **OBSERVATION_STRUCTURAL_SCHEMA,
        "Cota_Status": pl.String(),
        "Tipo_Medicao_Cotas": pl.String(),
    }

    combined = pl.concat(
        [
            parsed.rows.select("product_id", "time", "value"),
            table.rows.select("Cota_Status", "Tipo_Medicao_Cotas"),
        ],
        how="horizontal",
    )
    jan1_bruto = combined.filter(
        (pl.col("product_id") == "stage_daily_mean_bruto") & (pl.col("time") == datetime(2024, 1, 1))
    )
    assert jan1_bruto["value"].to_list() == [9.5, 8.5]
    assert jan1_bruto["Cota_Status"].to_list() == ["0", "4"]
    assert jan1_bruto["Tipo_Medicao_Cotas"].to_list() == ["1", None]

    jan31_bruto = combined.filter(
        (pl.col("product_id") == "stage_daily_mean_bruto") & (pl.col("time") == datetime(2024, 1, 31))
    )
    assert jan31_bruto["Cota_Status"].to_list() == [None, None]
    assert jan31_bruto["Tipo_Medicao_Cotas"].to_list() == ["1", None]

    feb29_bruto = combined.filter(
        (pl.col("product_id") == "stage_daily_mean_bruto") & (pl.col("time") == datetime(2024, 2, 29))
    )
    assert feb29_bruto["value"].to_list() == [12.5]
    assert feb29_bruto["Cota_Status"].to_list() == ["3"]
    assert feb29_bruto["Tipo_Medicao_Cotas"].to_list() == ["4"]

    feb1_cons = combined.filter(
        (pl.col("product_id") == "stage_daily_mean_consistido") & (pl.col("time") == datetime(2024, 2, 1))
    )
    assert feb1_cons["value"].to_list() == [20.0]
    assert feb1_cons["Cota_Status"].to_list() == ["1"]
    assert feb1_cons["Tipo_Medicao_Cotas"].to_list() == ["2"]


@pytest.mark.parametrize(
    ("product", "consistency", "schema_id", "status_col", "method_col"),
    [
        ("discharge_daily_mean_bruto", "1", "br_ana.daily_vazao", "Vazao_Status", "Metodo_Obtencao_Vazoes"),
        ("discharge_daily_mean_consistido", "2", "br_ana.daily_vazao", "Vazao_Status", "Metodo_Obtencao_Vazoes"),
        ("stage_daily_mean_bruto", "1", "br_ana.daily_cotas", "Cota_Status", "Tipo_Medicao_Cotas"),
        ("stage_daily_mean_consistido", "2", "br_ana.daily_cotas", "Cota_Status", "Tipo_Medicao_Cotas"),
    ],
)
def test_br_ana_all_daily_products_emit_verbatim_annotations(
    product: str,
    consistency: str,
    schema_id: str,
    status_col: str,
    method_col: str,
) -> None:
    prefix = "Cota" if product.startswith("stage") else "Vazao"
    item = _daily_item(
        prefix=prefix,
        consistency=consistency,
        header="2023-04-01 00:00:00.0",
        method_value="3",
        day_values={10: ("4.2", "2")},
    )
    parsed = parse(
        _payload(product, _envelope([item]), start=datetime(2023, 4, 1), end=datetime(2023, 4, 30)), config()
    )
    assert parsed.rows.height == 30
    assert not parsed.issues
    ann = parsed.annotations.observation_tables[schema_id]
    assert ann.rows.height == 30
    day10 = pl.concat(
        [
            parsed.rows.select("time", "value"),
            ann.rows.select(status_col, method_col),
        ],
        how="horizontal",
    ).filter(pl.col("time") == datetime(2023, 4, 10))
    assert day10[status_col].to_list() == ["2"]
    assert day10[method_col].to_list() == ["3"]


@pytest.mark.parametrize(
    ("product", "field", "schema_id", "status_col"),
    [
        ("stage_instantaneous", "Cota_Adotada", "br_ana.telemetry_cota", "Cota_Adotada_Status"),
        ("discharge_instantaneous", "Vazao_Adotada", "br_ana.telemetry_vazao", "Vazao_Adotada_Status"),
    ],
)
def test_br_ana_telemetry_pair_sorts_duplicates_and_null_values(
    product: str,
    field: str,
    schema_id: str,
    status_col: str,
) -> None:
    status_field = f"{field}_Status"
    body = _envelope(
        [
            {"codigoestacao": _STATION, "Data_Hora_Medicao": "2024-01-02 01:00:00", field: "1.50", status_field: "2"},
            {"codigoestacao": _STATION, "Data_Hora_Medicao": "2024-01-02 00:00:00", field: None, status_field: "4"},
            {"codigoestacao": _STATION, "Data_Hora_Medicao": "2024-01-02 00:00:00", field: "2.25", status_field: None},
        ]
    )
    parsed = parse(_payload(product, body), config())
    assert list(parsed.rows.columns) == list(RowsSchema.polars_schema)
    assert not parsed.issues
    ann = parsed.annotations.observation_tables[schema_id]
    assert ann.rows.schema == {**OBSERVATION_STRUCTURAL_SCHEMA, status_col: pl.String()}
    assert parsed.rows["value"].to_list() == [None, 2.25, 1.5]
    assert ann.rows[status_col].to_list() == ["4", None, "2"]


def test_br_ana_empty_responses_emit_empty_bundle_and_keep_missing_data_issue() -> None:
    daily_only_flag0 = _daily_item(mean="0", header="2024-01-01 07:00:00.0")
    daily_empty = parse(_payload("stage_daily_mean_bruto", _envelope([daily_only_flag0])), config())
    assert daily_empty.annotations.is_empty
    assert any(outcome.status is OutcomeStatus.UNRESOLVED for outcome in daily_empty.outcomes)

    telem_empty = parse(_payload("discharge_instantaneous", _envelope([])), config())
    assert telem_empty.annotations.is_empty
    assert [issue.code for issue in telem_empty.issues] == ["missing_data"]


@pytest.mark.parametrize("bad_method", ["missing", 1])
def test_br_ana_rejects_missing_or_non_string_daily_method_structurally(bad_method: object) -> None:
    item = _daily_item(prefix="Vazao", consistency="1", header="2024-01-01 00:00:00.0")
    if bad_method == "missing":
        del item["Metodo_Obtencao_Vazoes"]
    else:
        item["Metodo_Obtencao_Vazoes"] = bad_method
    parsed = parse(_payload("discharge_daily_mean_bruto", _envelope([item])), config())
    assert parsed.annotations.is_empty
    assert any(outcome.status is OutcomeStatus.UNSUPPORTED for outcome in parsed.outcomes)
    assert any(issue.code == "source.unsupported_series" for issue in parsed.issues)


def test_br_ana_partial_daily_rejection_preserves_valid_sibling_annotations() -> None:
    valid_bruto = _daily_item(
        prefix="Cota",
        consistency="1",
        header="2024-01-01 00:00:00.0",
        method_value="1",
        day_values={1: ("5.0", "2")},
    )
    bad_consistido = _daily_item(
        prefix="Cota",
        consistency="2",
        header="2024-01-01 00:00:00.0",
        method_value="1",
        day_values={1: ("6.0", "2")},
    )
    del bad_consistido["Tipo_Medicao_Cotas"]
    parsed = parse(_payload("stage_daily_mean_bruto", _envelope([valid_bruto, bad_consistido])), config())
    statuses = {outcome.product_id: outcome.status for outcome in parsed.outcomes}
    assert statuses[ProductId("stage_daily_mean_bruto")] is OutcomeStatus.SUCCESS
    assert statuses[ProductId("stage_daily_mean_consistido")] is OutcomeStatus.UNSUPPORTED
    ann = parsed.annotations.observation_tables["br_ana.daily_cotas"]
    assert ann.rows.height == parsed.rows.height == 31


def test_br_ana_rejects_non_string_telemetry_status_structurally() -> None:
    body = _envelope(
        [
            {
                "codigoestacao": _STATION,
                "Data_Hora_Medicao": "2024-01-02 00:00:00",
                "Cota_Adotada": "1.2",
                "Cota_Adotada_Status": 2,
            }
        ]
    )
    parsed = parse(_payload("stage_instantaneous", body), config())
    assert parsed.annotations.is_empty
    assert [outcome.status for outcome in parsed.outcomes] == [OutcomeStatus.UNSUPPORTED]


def test_br_ana_public_fetch_cache_reuse_refresh_and_bundle_roundtrip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANA_IDENTIFICADOR", _IDENTIFIER)
    monkeypatch.setenv("ANA_SENHA", _PASSWORD)

    cota_initial = _envelope(
        [
            _daily_item(
                prefix="Cota",
                consistency="1",
                header="2020-01-01 00:00:00.0",
                method_value="2",
                day_values={10: ("100.0", "0"), 11: ("110.0", "1")},
            )
        ]
    )
    cota_updated = _envelope(
        [
            _daily_item(
                prefix="Cota",
                consistency="1",
                header="2020-01-01 00:00:00.0",
                method_value="1",
                day_values={10: ("100.0", "2"), 11: ("110.0", "1")},
            )
        ]
    )
    telem_body = _envelope(
        [
            {
                "codigoestacao": _STATION,
                "Data_Hora_Medicao": "2024-01-02 00:00:00",
                "Cota_Adotada": "95.0",
                "Cota_Adotada_Status": None,
            }
        ]
    )

    class _RoutingTransport:
        exchange_calls = 0
        obs_calls = 0
        cota_status = 200
        cota_body: bytes = json.dumps(cota_initial).encode()

        def send(self, request: TransportRequest) -> TransportResponse:
            if request.url == ExchangeSpec.ana().exchange_url:
                self.exchange_calls += 1

                def token_sender(req: TransportRequest, timeout_seconds: float) -> tuple[bytes, int, str]:
                    return b'{"items":{"tokenautenticacao":"protocol-bearer-sentinel"}}', 200, "application/json"

                return HttpClient(sender=token_sender).send(request)
            self.obs_calls += 1
            if "HidroSerieCotas" in request.url:
                content = self.cota_body
                status = self.cota_status
            else:
                content = json.dumps(telem_body).encode()
                status = 200
            return TransportResponse(
                content=content,
                status_code=status,
                retrieved_at=datetime(2026, 9, 21, tzinfo=UTC),
                content_type="application/json",
                url=request.url,
                request_parameters=request.params,
            )

    transport = _RoutingTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    sel = rr.pick(
        rr.find(provider="br_ana", station=_STATION, quantity="stage", frequency="daily", statistic="mean"),
        variant="bruto",
    )
    assert rr.annotations(sel).is_empty()

    fresh = rr.fetch(sel, start="2020-01-10", end="2020-01-11", cache="reuse", receipts=True, on_issue="raise")
    assert transport.obs_calls == 1
    assert {(i.severity, i.code) for i in fresh.issues} == {("info", "provenance.citation_not_established")}
    assert fresh.receipts.entries[0].authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD

    catalog = rr.annotations(fresh)
    assert catalog.schema == CATALOG_SCHEMA
    assert catalog["schema"].to_list() == ["br_ana.daily_cotas"] * 2

    projected = fresh.to_polars(annotations=True)
    assert list(projected.columns) == [
        *ObservationDataSchema.polars_schema,
        "Cota_Status",
        "Tipo_Medicao_Cotas",
    ]
    assert projected["value"].to_list() == [1.0, 1.1]
    assert projected["Cota_Status"].to_list() == ["0", "1"]
    assert projected["Tipo_Medicao_Cotas"].to_list() == ["2", "2"]
    assert isinstance(fresh.to_pandas(annotations="Cota_Status"), pd.DataFrame)

    closed = rr.pick(sel, series_id=rr.series(fresh)["series_id"][0])
    cached = rr.fetch(closed, start="2020-01-10", end="2020-01-11", cache="reuse", receipts=True, on_issue="raise")
    assert transport.obs_calls == 1
    assert cached.receipts.entries[0].authorship is ReceiptAuthorship.STORE_EXCERPT
    pl_testing.assert_frame_equal(
        rr.annotations(cached, schema="br_ana.daily_cotas"),
        rr.annotations(fresh, schema="br_ana.daily_cotas"),
    )

    bundle_path = tmp_path / "br_ana.rr"
    bundle_path.write_bytes(rr.to_bundle(cached))
    restored = rr.from_bundle(bundle_path.read_bytes())
    pl_testing.assert_frame_equal(restored.to_polars(annotations=True), projected)

    transport.cota_body = json.dumps(cota_updated).encode()
    refreshed = rr.fetch(closed, start="2020-01-10", end="2020-01-11", cache="refresh", receipts=True, on_issue="raise")
    assert transport.obs_calls == 2
    assert refreshed.to_polars(annotations=True)["Cota_Status"].to_list() == ["2", "1"]
    assert refreshed.to_polars(annotations=True)["Tipo_Medicao_Cotas"].to_list() == ["1", "1"]
    assert refreshed.to_polars(annotations=True)["value"].to_list() == [1.0, 1.1]

    transport.cota_status = 503
    transport.cota_body = b"{}"
    failed = rr.fetch(closed, start="2020-01-10", end="2020-01-11", cache="refresh", receipts=True)
    assert transport.obs_calls == 3
    assert any(issue.code == "source.request_failed" for issue in failed.issues)
    assert failed.to_polars(annotations=True)["Cota_Status"].to_list() == ["2", "1"]

    preserved = rr.fetch(closed, start="2020-01-10", end="2020-01-11", cache="reuse", receipts=True, on_issue="ignore")
    assert transport.obs_calls == 3
    assert preserved.receipts.entries[0].authorship is ReceiptAuthorship.STORE_EXCERPT
    assert preserved.to_polars(annotations=True)["Cota_Status"].to_list() == ["2", "1"]


@pytest.mark.recorded("tests/recordings/br_ana")
def test_br_ana_recorded_daily_replay_emits_annotations(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANA_IDENTIFICADOR", _IDENTIFIER)
    monkeypatch.setenv("ANA_SENHA", _PASSWORD)
    recordings = [
        read_recording(retained_evidence_root / "tests/recordings/br_ana" / name)
        for name in (
            "HidroSerieCotas_15400000_2020-01-01_2020-01-31.recording.json",
            "HidroSerieVazao_15400000_2020-01-01_2020-01-31.recording.json",
            "HidroSerieVazao_15400000_2024-01-01_2024-01-31.recording.json",
        )
    ]
    replay = ReplayTransport(recordings)

    class _ReplayWrapper:
        def send(self, request: TransportRequest) -> TransportResponse:
            if request.url == ExchangeSpec.ana().exchange_url:
                return HttpClient(
                    sender=lambda req, timeout: (
                        b'{"items":{"tokenautenticacao":"protocol-bearer-sentinel"}}',
                        200,
                        "application/json",
                    )
                ).send(request)
            return replay.send(request)

    monkeypatch.setattr(discovery, "HttpClient", lambda: _ReplayWrapper())

    stage_res = rr.fetch(
        rr.pick(
            rr.find(provider="br_ana", station=_STATION, quantity="stage", frequency="daily", statistic="mean"),
            variant="bruto",
        ),
        start="2020-01-10",
        end="2020-01-12",
        on_issue="raise",
    )
    assert rr.annotations(stage_res)["schema"].to_list() == ["br_ana.daily_cotas"] * 2
    assert not any(issue.code == "source_status" for issue in stage_res.issues)
    assert stage_res.to_polars(annotations=True)["Tipo_Medicao_Cotas"].null_count() == 0

    flow_res = rr.fetch(
        rr.pick(
            rr.find(provider="br_ana", station=_STATION, quantity="discharge", frequency="daily", statistic="mean"),
            variant="consistido",
        ),
        start="2020-01-10",
        end="2020-01-12",
        on_issue="raise",
    )
    assert rr.annotations(flow_res)["schema"].to_list() == ["br_ana.daily_vazao"] * 2
    assert flow_res.to_polars(annotations=True)["Vazao_Status"].to_list() == ["1", "1", "1"]
    assert flow_res.to_polars(annotations=True)["Metodo_Obtencao_Vazoes"].to_list() == ["1", "1", "1"]

    flow_bruto = rr.fetch(
        rr.pick(
            rr.find(provider="br_ana", station=_STATION, quantity="discharge", frequency="daily", statistic="mean"),
            variant="bruto",
        ),
        start="2024-01-15",
        end="2024-01-16",
        on_issue="raise",
    )
    assert rr.annotations(flow_bruto)["schema"].to_list() == ["br_ana.daily_vazao"] * 2
    assert not any(issue.code == "source_status" for issue in flow_bruto.issues)

    page = (Path(__file__).resolve().parents[1] / "docs/providers/br_ana.md").read_text()
    code, expected_output = re.findall(r"```python\n(.*?)```\n\nOutput:\n\n```text\n(.*?)```", page, re.DOTALL)[0]
    output = io.StringIO()
    with redirect_stdout(output):
        exec(compile(code, "br_ana.md:block-1", "exec"), {})
    assert output.getvalue() == expected_output


@pytest.mark.recorded("tests/recordings/br_ana/telemetry_15400000_2024-01-04_DIAS_30.recording.json")
def test_br_ana_recorded_telemetry_replay_emits_annotations(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANA_IDENTIFICADOR", _IDENTIFIER)
    monkeypatch.setenv("ANA_SENHA", _PASSWORD)
    replay = ReplayTransport(
        (
            read_recording(
                retained_evidence_root / "tests/recordings/br_ana/telemetry_15400000_2024-01-04_DIAS_30.recording.json"
            ),
        )
    )

    class _ReplayWrapper:
        def send(self, request: TransportRequest) -> TransportResponse:
            if request.url == ExchangeSpec.ana().exchange_url:
                return HttpClient(
                    sender=lambda req, timeout: (
                        b'{"items":{"tokenautenticacao":"protocol-bearer-sentinel"}}',
                        200,
                        "application/json",
                    )
                ).send(request)
            return replay.send(request)

    monkeypatch.setattr(discovery, "HttpClient", lambda: _ReplayWrapper())

    stage_res = rr.fetch(
        rr.pick(rr.find(provider="br_ana", station=_STATION, quantity="stage"), variant="Cota_Adotada"),
        start="2024-01-01T23:30:00",
        end="2024-01-02T00:30:00",
        on_issue="raise",
    )
    assert rr.annotations(stage_res)["schema"].to_list() == ["br_ana.telemetry_cota"]
    assert "Cota_Adotada_Status" in stage_res.to_polars(annotations=True).columns
    assert not any(issue.code == "source_status" for issue in stage_res.issues)

    flow_res = rr.fetch(
        rr.pick(
            rr.find(provider="br_ana", station=_STATION, quantity="discharge"),
            variant="Vazao_Adotada",
        ),
        start="2024-01-01T23:30:00",
        end="2024-01-02T00:30:00",
        on_issue="raise",
    )
    assert rr.annotations(flow_res)["schema"].to_list() == ["br_ana.telemetry_vazao"]
    assert "Vazao_Adotada_Status" in flow_res.to_polars(annotations=True).columns
    assert not any(issue.code == "source_status" for issue in flow_res.issues)


def test_br_ana_provider_page_documents_annotation_schemas_and_drops_source_status() -> None:
    page = (Path(__file__).resolve().parents[1] / "docs/providers/br_ana.md").read_text()
    assert "source_status" not in page
    for token in (
        "br_ana.daily_cotas",
        "Cota_Status",
        "Tipo_Medicao_Cotas",
        "br_ana.daily_vazao",
        "Vazao_Status",
        "Metodo_Obtencao_Vazoes",
        "br_ana.telemetry_cota",
        "Cota_Adotada_Status",
        "br_ana.telemetry_vazao",
        "Vazao_Adotada_Status",
    ):
        assert token in page
