"""Ledger decoding checks source identity and conclusions, not source bytes."""

import copy
import json
import lzma
from pathlib import Path

import pytest

from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import (
    decode_availability,
    parse_station_product_availability,
)

_LEDGER_PATH = Path("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")


@pytest.fixture
def pair():
    """Synthetic successful publisher count, with explicit request identity."""
    return {
        "code_station": "EXAMPLE",
        "product_id": "discharge_instantaneous",
        "availability": "available",
        "basis": "publisher_count",
        "status": "available",
        "published_count_or_new_witness_points": 1,
        "acquisitions": [
            {
                "http_status": 200,
                "material": {"filename": "example.body", "byte_count": 1, "sha256": "a" * 64},
                "media_type": "application/json",
                "method": "http_request",
                "reference": "example.receipt.json",
                "requested_from": [
                    "https://hubeau.eaufrance.fr/api/v2/hydrometrie/observations_tr?"
                    "code_entite=EXAMPLE&size=1&fields=code_station&grandeur_hydro=Q"
                ],
                "retrieved_at_start": "2026-01-01T00:00:00+00:00",
                "role": "publisher_count",
            }
        ],
    }


@pytest.fixture
def document(pair):
    return {
        "native_table": {"filename": "native.parquet", "byte_count": 1, "sha256": "b" * 64},
        "pairs": [pair],
        "research_head": "c" * 40,
        "schema_version": 1,
        "scope": "synthetic",
        "summary": {"available": 1, "by_status": {"available": 1}, "pairs": 1, "stations": 1, "unknown": 0},
    }


@pytest.mark.derived(str(_LEDGER_PATH))
def test_reviewed_ledger_retains_complete_status_partition(retained_evidence_root) -> None:
    ledger = decode_availability(lzma.decompress((retained_evidence_root / _LEDGER_PATH).read_bytes()))
    assert ledger.summary.by_status == {
        "available": 20966,
        "empty_no_data_published": 4948,
        "empty_in_both_history_windows": 524,
        "history_check_failed": 97,
        "recent_window_empty_history_unchecked": 6604,
    }
    failed = next(
        pair
        for pair in ledger.pairs
        if pair.code_station == "J783301020" and pair.product_id == "discharge_instantaneous"
    )
    assert failed.status == "history_check_failed"
    assert failed.basis == "replacement_window_failure_prior_empty_claim_unverified"
    assert [acquisition.http_status for acquisition in failed.acquisitions] == [200, 500, 200]
    assert failed.availability == "unknown"


@pytest.mark.parametrize(
    "field,value",
    [
        ("availability", "unavailable"),
        ("status", "unsupported"),
        ("published_count_or_new_witness_points", True),
        ("published_count_or_new_witness_points", -1),
        ("code_station", "another-station"),
        ("product_id", "discharge_daily_mean"),
        ("basis", "historical_positive_witness"),
    ],
)
def test_pair_decoder_rejects_inconsistent_or_untyped_conclusions(pair, field: str, value: object) -> None:
    parse_station_product_availability(pair)
    row = copy.deepcopy(pair)
    row[field] = value
    with pytest.raises(ValueError):
        parse_station_product_availability(row)


@pytest.mark.parametrize(
    "field,value",
    [
        ("http_status", True),
        ("http_status", 500),
        ("retrieved_at_start", "2026-09-12T12:00:00"),
        ("role", "historical_check"),
        ("reference", "../untrusted.body"),
    ],
)
def test_pair_decoder_rejects_invalid_acquisition_identity(pair, field: str, value: object) -> None:
    parse_station_product_availability(pair)
    row = copy.deepcopy(pair)
    row["acquisitions"][0][field] = value
    with pytest.raises(ValueError):
        parse_station_product_availability(row)


@pytest.mark.parametrize("value", [True, "475", 0, -1])
def test_material_size_is_not_coerced(pair, value: object) -> None:
    parse_station_product_availability(pair)
    row = copy.deepcopy(pair)
    row["acquisitions"][0]["material"]["byte_count"] = value
    with pytest.raises(ValueError):
        parse_station_product_availability(row)


def test_duplicate_pair_cannot_enter_the_typed_ledger(document) -> None:
    decode_availability(json.dumps(document))
    document = copy.deepcopy(document)
    document["pairs"].append(copy.deepcopy(document["pairs"][0]))
    with pytest.raises(ValueError, match="duplicate station/product"):
        decode_availability(json.dumps(document))


def test_historical_query_rejects_an_extra_source_filter(pair) -> None:
    parse_station_product_availability(pair)
    row = copy.deepcopy(pair)
    row["basis"] = "historical_positive_witness"
    historical = copy.deepcopy(row["acquisitions"][0])
    historical["role"] = "historical_check"
    historical["requested_from"] = [
        "https://hydro.eaufrance.fr/stationhydro/ajax/EXAMPLE/series?"
        "hydro_series[startAt]=01/01/2026&hydro_series[endAt]=01/01/2026&"
        "hydro_series[variableType]=simple_and_interpolated_and_hourly_variable&"
        "hydro_series[simpleAndInterpolatedAndHourlyVariable]=Q&hydro_series[statusData]=raw"
    ]
    row["acquisitions"].append(historical)
    parse_station_product_availability(row)
    row["acquisitions"][1]["requested_from"][0] += "&extra_filter=changed"
    with pytest.raises(ValueError, match="unexpected historical request parameters"):
        parse_station_product_availability(row)


def test_ledger_requires_explicit_build_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import main

    with pytest.raises(SystemExit, match="2"):
        main(["--native", "native.parquet", "--out", str(tmp_path)])
    assert "--availability-ledger is required for canonical build" in capsys.readouterr().err


@pytest.mark.parametrize("level", ["pair", "acquisition", "material"])
def test_decoder_rejects_undeclared_fields(pair, level: str) -> None:
    parse_station_product_availability(pair)
    row = copy.deepcopy(pair)
    target = row if level == "pair" else row["acquisitions"][0]
    if level == "material":
        target = target["material"]
    target["extra"] = "not in the source contract"
    with pytest.raises(ValueError):
        parse_station_product_availability(row)


def test_decoded_availability_is_immutable(pair) -> None:
    from dataclasses import FrozenInstanceError

    pair = parse_station_product_availability(pair)
    attribute = "availability"
    with pytest.raises(FrozenInstanceError):
        setattr(pair, attribute, "unknown")
