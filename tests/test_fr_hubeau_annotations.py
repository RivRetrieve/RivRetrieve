"""Tests for Hub'Eau observation annotations (#818)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.discovery import _merge_provider_results
from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ObservationDataSchema, ReceiptAuthorship
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.fr_hubeau.config import FrHubeauSourceCoordinates, config
from rivretrieve._internal.providers.fr_hubeau.parse import parse
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.source_annotations import CATALOG_SCHEMA, AnnotationScope
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportRequest, TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_OBS_ELAB_ORIGIN = SourceCallOrigin(
    "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab",
    {},
    200,
    datetime(2026, 9, 21, tzinfo=UTC),
    "application/json",
    UnknownOriginFact(),
    UnknownOriginFact(),
)
_TEMP_ORIGIN = SourceCallOrigin(
    "https://hubeau.eaufrance.fr/api/v1/temperature/chronique",
    {},
    200,
    datetime(2026, 9, 21, tzinfo=UTC),
    "application/json",
    UnknownOriginFact(),
    UnknownOriginFact(),
)


def _daily_payload(
    rows: list[dict[str, object]],
    *,
    station: str = "1011000101",
    product: str = "discharge_daily_mean",
    field: str = "QmnJ",
) -> Payload:
    return Payload(
        SourceCoordinates(FrHubeauSourceCoordinates("daily", field)),
        ((station, ProductId(product)),),
        _make_fetch_window(WindowEndpoint(2025, 1, 1, 0, 0, 0, 0), WindowEndpoint(2025, 1, 5, 0, 0, 0, 0)),
        json.dumps({"count": len(rows), "next": None, "data": rows}).encode(),
        _OBS_ELAB_ORIGIN,
        (),
    )


def _temp_payload(
    rows: list[dict[str, object]],
    *,
    station: str = "01001336",
) -> Payload:
    return Payload(
        SourceCoordinates(FrHubeauSourceCoordinates("temperature", "resultat")),
        ((station, ProductId("water_temperature_reported")),),
        _make_fetch_window(WindowEndpoint(2008, 7, 9, 0, 0, 0, 0), WindowEndpoint(2008, 7, 10, 23, 59, 59, 0)),
        json.dumps({"count": len(rows), "next": None, "data": rows}).encode(),
        _TEMP_ORIGIN,
        (),
    )


def test_fr_hubeau_annotation_schemas_define_verified_fields_and_urls() -> None:
    from rivretrieve._internal.providers.fr_hubeau.annotations import (
        FR_HUBEAU_HYDROMETRIE_URL,
        FR_HUBEAU_OBS_ELAB_SCHEMA,
        FR_HUBEAU_TEMPERATURE_SCHEMA,
        FR_HUBEAU_TEMPERATURE_URL,
    )

    assert FR_HUBEAU_OBS_ELAB_SCHEMA.schema_id == "fr_hubeau.obs_elab"
    assert FR_HUBEAU_OBS_ELAB_SCHEMA.provider_id == "fr_hubeau"
    assert FR_HUBEAU_OBS_ELAB_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert [field.name for field in FR_HUBEAU_OBS_ELAB_SCHEMA.fields] == [
        "code_statut",
        "libelle_statut",
        "code_qualification",
        "libelle_qualification",
        "code_methode",
        "libelle_methode",
    ]
    assert [field.dtype for field in FR_HUBEAU_OBS_ELAB_SCHEMA.fields] == [
        "Int64",
        "String",
        "Int64",
        "String",
        "Int64",
        "String",
    ]
    for field in FR_HUBEAU_OBS_ELAB_SCHEMA.fields:
        assert field.description
        assert field.reference_url == FR_HUBEAU_HYDROMETRIE_URL

    assert FR_HUBEAU_TEMPERATURE_SCHEMA.schema_id == "fr_hubeau.temperature_chronique"
    assert FR_HUBEAU_TEMPERATURE_SCHEMA.provider_id == "fr_hubeau"
    assert FR_HUBEAU_TEMPERATURE_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert [field.name for field in FR_HUBEAU_TEMPERATURE_SCHEMA.fields] == [
        "code_qualification",
        "libelle_qualification",
    ]
    assert [field.dtype for field in FR_HUBEAU_TEMPERATURE_SCHEMA.fields] == ["String", "String"]
    for field in FR_HUBEAU_TEMPERATURE_SCHEMA.fields:
        assert field.description
        assert field.reference_url == FR_HUBEAU_TEMPERATURE_URL


@pytest.mark.parametrize(
    ("product", "field"),
    [
        ("discharge_daily_mean", "QmnJ"),
        ("discharge_daily_max", "QIXnJ"),
        ("stage_daily_max", "HIXnJ"),
    ],
)
def test_fr_hubeau_obs_elab_sorts_paired_annotations_across_duplicates_and_optional_nulls(
    product: str, field: str
) -> None:
    parsed = parse(
        _daily_payload(
            [
                {
                    "code_station": "1011000101",
                    "grandeur_hydro_elab": field,
                    "date_obs_elab": "2025-01-03",
                    "resultat_obs_elab": 300.0,
                    "code_statut": 16,
                    "libelle_statut": "Donnée validée",
                    "code_qualification": 20,
                    "libelle_qualification": "Bonne",
                    "code_methode": 8,
                    "libelle_methode": "Calculée",
                },
                {
                    "code_station": "1011000101",
                    "grandeur_hydro_elab": field,
                    "date_obs_elab": "2025-01-01",
                    "resultat_obs_elab": 100.0,
                },
                {
                    "code_station": "1011000101",
                    "grandeur_hydro_elab": field,
                    "date_obs_elab": "2025-01-03",
                    "resultat_obs_elab": 200.0,
                    "code_statut": 4,
                    "libelle_statut": "Donnée brute",
                    "code_qualification": 12,
                    "libelle_qualification": "Douteuse",
                    "code_methode": 0,
                    "libelle_methode": "Mesurée",
                },
            ],
            product=product,
            field=field,
        ),
        config(),
    )

    assert [o.status for o in parsed.outcomes] == [OutcomeStatus.SUCCESS]
    assert not parsed.issues
    assert parsed.rows["value"].to_list() == [100.0, 300.0, 200.0]
    table = parsed.annotations.schema_table("fr_hubeau.obs_elab")
    assert table["measured"].to_list() == [True, True, True]
    assert table["code_statut"].to_list() == [None, 16, 4]
    assert table["libelle_statut"].to_list() == [None, "Donnée validée", "Donnée brute"]
    assert table["code_qualification"].to_list() == [None, 20, 12]
    assert table["libelle_qualification"].to_list() == [None, "Bonne", "Douteuse"]
    assert table["code_methode"].to_list() == [None, 8, 0]
    assert table["libelle_methode"].to_list() == [None, "Calculée", "Mesurée"]

    empty = parse(_daily_payload([], product=product, field=field), config())
    assert [o.status for o in empty.outcomes] == [OutcomeStatus.EMPTY]
    assert empty.annotations.is_empty


def test_fr_hubeau_temperature_sorts_paired_annotations_and_handles_empty() -> None:
    parsed = parse(
        _temp_payload(
            [
                {
                    "code_station": "01001336",
                    "code_parametre": "1301",
                    "code_unite": "27",
                    "symbole_unite": "°C",
                    "date_mesure_temp": "2008-07-09",
                    "heure_mesure_temp": "12:00:00",
                    "resultat": 15.5,
                    "code_qualification": "4",
                    "libelle_qualification": "Non qualifié",
                },
                {
                    "code_station": "01001336",
                    "code_parametre": "1301",
                    "code_unite": "27",
                    "symbole_unite": "°C",
                    "date_mesure_temp": "2008-07-09",
                    "heure_mesure_temp": "11:00:00",
                    "resultat": 14.2,
                },
            ]
        ),
        config(),
    )
    assert [o.status for o in parsed.outcomes] == [OutcomeStatus.SUCCESS]
    assert parsed.rows["value"].to_list() == [14.2, 15.5]
    table = parsed.annotations.schema_table("fr_hubeau.temperature_chronique")
    assert table["code_qualification"].to_list() == [None, "4"]
    assert table["libelle_qualification"].to_list() == [None, "Non qualifié"]

    empty = parse(_temp_payload([]), config())
    assert [o.status for o in empty.outcomes] == [OutcomeStatus.EMPTY]
    assert empty.annotations.is_empty


@pytest.mark.parametrize(
    "bad_fields",
    [
        {"code_statut": True},
        {"code_statut": "4"},
        {"code_qualification": 1 << 63},
        {"code_methode": 8.0},
        {"libelle_statut": 16},
        {"libelle_qualification": False},
        {"libelle_methode": 0},
    ],
)
def test_fr_hubeau_obs_elab_rejects_invalid_annotation_field_types(bad_fields: dict[str, object]) -> None:
    row: dict[str, object] = {
        "code_station": "1011000101",
        "grandeur_hydro_elab": "QmnJ",
        "date_obs_elab": "2025-01-01",
        "resultat_obs_elab": 764.0,
        **bad_fields,
    }
    parsed = parse(_daily_payload([row]), config())
    assert [o.status for o in parsed.outcomes] == [OutcomeStatus.UNSUPPORTED]
    assert parsed.rows.is_empty()
    assert parsed.annotations.is_empty


@pytest.mark.parametrize(
    "bad_fields",
    [
        {"code_qualification": 4},
        {"code_qualification": True},
        {"libelle_qualification": 4},
    ],
)
def test_fr_hubeau_temperature_rejects_non_string_annotations(bad_fields: dict[str, object]) -> None:
    row: dict[str, object] = {
        "code_station": "01001336",
        "code_parametre": "1301",
        "code_unite": "27",
        "symbole_unite": "°C",
        "date_mesure_temp": "2008-07-09",
        "heure_mesure_temp": "11:00:00",
        "resultat": 14.2,
        **bad_fields,
    }
    parsed = parse(_temp_payload([row]), config())
    assert [o.status for o in parsed.outcomes] == [OutcomeStatus.UNSUPPORTED]
    assert parsed.rows.is_empty()
    assert parsed.annotations.is_empty


def test_fr_hubeau_public_fetch_cache_reuse_pick_and_bundle_roundtrip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)

    obs_body = json.dumps(
        {
            "count": 2,
            "next": None,
            "data": [
                {
                    "code_station": "1011000101",
                    "grandeur_hydro_elab": "QmnJ",
                    "date_obs_elab": "2025-01-02",
                    "resultat_obs_elab": 500.0,
                    "code_statut": 12,
                    "libelle_statut": "Donnée pré-validée",
                    "code_qualification": 20,
                    "libelle_qualification": "Bonne",
                    "code_methode": 8,
                    "libelle_methode": "Calculée",
                },
                {
                    "code_station": "1011000101",
                    "grandeur_hydro_elab": "QmnJ",
                    "date_obs_elab": "2025-01-01",
                    "resultat_obs_elab": 250.0,
                    "code_statut": 4,
                    "libelle_statut": "Donnée brute",
                    "code_qualification": 16,
                    "libelle_qualification": "Non qualifiée",
                    "code_methode": 0,
                    "libelle_methode": "Mesurée",
                },
            ],
        }
    ).encode()
    temp_body = json.dumps(
        {
            "count": 1,
            "next": None,
            "data": [
                {
                    "code_station": "01001336",
                    "code_parametre": "1301",
                    "code_unite": "27",
                    "symbole_unite": "°C",
                    "date_mesure_temp": "2008-07-09",
                    "heure_mesure_temp": "11:00:00",
                    "resultat": 14.5,
                    "code_qualification": "4",
                    "libelle_qualification": "Non qualifié",
                }
            ],
        }
    ).encode()

    updated_obs_body = json.dumps(
        {
            "count": 2,
            "next": None,
            "data": [
                {
                    "code_station": "1011000101",
                    "grandeur_hydro_elab": "QmnJ",
                    "date_obs_elab": "2025-01-02",
                    "resultat_obs_elab": 500.0,
                    "code_statut": 12,
                    "libelle_statut": "Donnée pré-validée",
                    "code_qualification": 20,
                    "libelle_qualification": "Bonne",
                    "code_methode": 8,
                    "libelle_methode": "Calculée",
                },
                {
                    "code_station": "1011000101",
                    "grandeur_hydro_elab": "QmnJ",
                    "date_obs_elab": "2025-01-01",
                    "resultat_obs_elab": 250.0,
                    "code_statut": 16,
                    "libelle_statut": "Donnée validée",
                    "code_qualification": 16,
                    "libelle_qualification": "Non qualifiée",
                    "code_methode": 0,
                    "libelle_methode": "Mesurée",
                },
            ],
        }
    ).encode()

    class _RoutingClient:
        calls = 0
        obs_status = 200
        obs_content = obs_body

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls += 1
            is_temp = "temperature/chronique" in request.url
            return TransportResponse(
                content=temp_body if is_temp else self.obs_content,
                status_code=200 if is_temp else self.obs_status,
                retrieved_at=datetime(2026, 9, 21, tzinfo=UTC),
                content_type="application/json",
                url=request.url,
                request_parameters=request.params,
            )

    client = _RoutingClient()
    monkeypatch.setattr(discovery, "HttpClient", lambda: client)

    q_sel = rr.find(
        provider="fr_hubeau", station="1011000101", quantity="discharge", frequency="daily", statistic="mean"
    )
    assert rr.annotations(q_sel).is_empty()

    q_fresh = rr.fetch(q_sel, start="2025-01-01", end="2025-01-02", cache="reuse", receipts=True, on_issue="raise")
    assert client.calls == 1
    assert not q_fresh.issues
    assert q_fresh.receipts.entries[0].authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD

    catalog = rr.annotations(q_fresh)
    assert catalog.schema == CATALOG_SCHEMA
    assert catalog["schema"].to_list() == ["fr_hubeau.obs_elab"] * 6
    assert catalog["row_count"].to_list() == [2] * 6
    assert catalog["unmeasured_count"].to_list() == [0] * 6

    projected = q_fresh.to_polars(annotations=True)
    assert list(projected.columns) == [
        *ObservationDataSchema.polars_schema,
        "code_statut",
        "libelle_statut",
        "code_qualification",
        "libelle_qualification",
        "code_methode",
        "libelle_methode",
    ]
    assert projected["value"].to_list() == [0.25, 0.5]
    assert projected["code_statut"].to_list() == [4, 12]
    assert projected["libelle_statut"].to_list() == ["Donnée brute", "Donnée pré-validée"]
    assert isinstance(q_fresh.to_pandas(annotations="code_qualification"), pd.DataFrame)

    q_closed = rr.pick(q_sel, series_id=rr.series(q_fresh)["series_id"][0])
    q_cached = rr.fetch(q_closed, start="2025-01-01", end="2025-01-02", cache="reuse", receipts=True, on_issue="raise")
    assert client.calls == 1
    assert q_cached.receipts.entries[0].authorship is ReceiptAuthorship.STORE_EXCERPT
    pl_testing.assert_frame_equal(
        rr.annotations(q_cached, schema="fr_hubeau.obs_elab"),
        rr.annotations(q_fresh, schema="fr_hubeau.obs_elab"),
    )

    bundle_path = tmp_path / "fr_hubeau.rr"
    bundle_path.write_bytes(rr.to_bundle(q_cached))
    restored = rr.from_bundle(bundle_path.read_bytes())
    pl_testing.assert_frame_equal(restored.to_polars(annotations=True), projected)

    client.obs_content = updated_obs_body
    q_refreshed = rr.fetch(
        q_closed, start="2025-01-01", end="2025-01-02", cache="refresh", receipts=True, on_issue="raise"
    )
    assert client.calls == 2
    assert q_refreshed.to_polars(annotations=True)["code_statut"].to_list() == [16, 12]
    assert q_refreshed.to_polars(annotations=True)["libelle_statut"].to_list() == [
        "Donnée validée",
        "Donnée pré-validée",
    ]
    assert q_refreshed.to_polars(annotations=True)["value"].to_list() == [0.25, 0.5]

    q_cached_updated = rr.fetch(
        q_closed, start="2025-01-01", end="2025-01-02", cache="reuse", receipts=True, on_issue="raise"
    )
    assert client.calls == 2
    assert q_cached_updated.receipts.entries[0].authorship is ReceiptAuthorship.STORE_EXCERPT
    assert q_cached_updated.to_polars(annotations=True)["code_statut"].to_list() == [16, 12]

    client.obs_status = 503
    client.obs_content = b"{}"
    q_failed = rr.fetch(q_closed, start="2025-01-01", end="2025-01-02", cache="refresh", receipts=True)
    assert client.calls == 3
    assert any(issue.code == "source.request_failed" for issue in q_failed.issues)
    assert q_failed.to_polars(annotations=True)["code_statut"].to_list() == [16, 12]
    assert q_failed.to_polars(annotations=True)["value"].to_list() == [0.25, 0.5]

    q_preserved = rr.fetch(
        q_closed, start="2025-01-01", end="2025-01-02", cache="reuse", receipts=True, on_issue="ignore"
    )
    assert client.calls == 3
    assert q_preserved.receipts.entries[0].authorship is ReceiptAuthorship.STORE_EXCERPT
    assert q_preserved.to_polars(annotations=True)["code_statut"].to_list() == [16, 12]
    assert q_preserved.to_polars(annotations=True)["value"].to_list() == [0.25, 0.5]

    t_sel = rr.find(provider="fr_hubeau", station="01001336", quantity="temperature")
    t_fresh = rr.fetch(t_sel, start="2008-07-09", end="2008-07-09T23:59:59", on_issue="raise")
    assert rr.annotations(t_fresh)["schema"].to_list() == ["fr_hubeau.temperature_chronique"] * 2
    assert t_fresh.to_polars(annotations=True)["code_qualification"].to_list() == ["4"]

    both_sel = rr.find(provider="fr_hubeau", station=("1011000101", "01001336"))
    mixed = _merge_provider_results(
        (q_fresh.model_copy(update={"scope": both_sel.scope}), t_fresh),
        (*q_fresh.source_series, *t_fresh.source_series),
    )
    assert set(rr.annotations(mixed)["schema"].to_list()) == {
        "fr_hubeau.obs_elab",
        "fr_hubeau.temperature_chronique",
    }
    assert rr.annotations(mixed, schema="fr_hubeau.obs_elab").height == 2
    assert rr.annotations(mixed, schema="fr_hubeau.temperature_chronique").height == 1
    with pytest.raises(ValueError, match="Incompatible annotation field 'code_qualification'"):
        mixed.to_polars(annotations=True)
    pl_testing.assert_frame_equal(rr.pick(mixed, quantity="discharge").to_polars(annotations=True), projected)


@pytest.mark.recorded(
    "tests/test_data/fr_hubeau_size2500/fr_hubeau_1011000101_QmnJ_padded.recording.json",
    "tests/test_data/fr_hubeau_size2500/fr_hubeau_1011000101_QIXnJ_padded.recording.json",
    "tests/test_data/fr_hubeau_size2500/fr_hubeau_1011000101_HIXnJ_padded.recording.json",
    "tests/test_data/fr_hubeau_size2500/fr_hubeau_01001336_temp_padded.recording.json",
)
def test_fr_hubeau_recorded_routes_attach_exact_source_annotations(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)
    data_dir = retained_evidence_root / "tests/test_data/fr_hubeau_size2500"

    hydrometry = ReplayTransport(
        [
            read_recording(data_dir / "fr_hubeau_1011000101_QmnJ_padded.recording.json"),
            read_recording(data_dir / "fr_hubeau_1011000101_QIXnJ_padded.recording.json"),
            read_recording(data_dir / "fr_hubeau_1011000101_HIXnJ_padded.recording.json"),
        ]
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: hydrometry)

    hydro_sel = rr.find(provider="fr_hubeau", station="1011000101")
    hydro_res = rr.fetch(hydro_sel, start="2025-01-03", end="2025-01-03", cache="reuse", on_issue="raise")
    assert not hydro_res.issues
    assert hydro_res.data.height == 3
    projected = hydro_res.to_polars(annotations=True).sort("product_id")
    assert projected["product_id"].to_list() == ["discharge_daily_max", "discharge_daily_mean", "stage_daily_max"]
    assert projected["code_statut"].to_list() == [4, 4, 4]
    assert projected["libelle_statut"].to_list() == ["Donnée brute"] * 3
    assert projected["code_qualification"].to_list() == [16, 16, 16]
    assert projected["libelle_qualification"].to_list() == ["Non qualifiée"] * 3
    assert projected["code_methode"].to_list() == [8, 8, 0]
    assert projected["libelle_methode"].to_list() == ["Calculée", "Calculée", "Mesurée"]

    temp_recordings = [read_recording(data_dir / "fr_hubeau_01001336_temp_padded.recording.json")]
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(temp_recordings))
    temp_sel = rr.find(provider="fr_hubeau", station="01001336", quantity="temperature")
    temp_res = rr.fetch(temp_sel, start="2008-07-09", end="2008-07-10T23:59:59", cache="reuse", on_issue="raise")
    assert not temp_res.issues
    assert temp_res.data.height == 37
    temp_proj = temp_res.to_polars(annotations=True)
    assert temp_proj["code_qualification"].to_list() == ["4"] * 37
    assert temp_proj["libelle_qualification"].to_list() == ["Non qualifié"] * 37
