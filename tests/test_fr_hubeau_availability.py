"""Public ledger decoding checks source identity and conclusions, not private bytes."""

import copy
import json
import lzma
from pathlib import Path

import pytest
from pydantic import ValidationError

from rivretrieve._internal.providers.fr_hubeau.availability import FranceAvailability, StationProductAvailability

_LEDGER_PATH = Path(__file__).parents[1] / "research/station-coverage/fr_hubeau/inventory/governing_evidence.json.xz"
_DOCUMENT = json.loads(lzma.decompress(_LEDGER_PATH.read_bytes()))


def test_reviewed_ledger_retains_complete_status_partition() -> None:
    ledger = FranceAvailability.model_validate_json(json.dumps(_DOCUMENT))
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
def test_pair_decoder_rejects_inconsistent_or_untyped_conclusions(field: str, value: object) -> None:
    row = copy.deepcopy(_DOCUMENT["pairs"][0])
    row[field] = value
    with pytest.raises(ValidationError):
        StationProductAvailability.model_validate_json(json.dumps(row))


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
def test_pair_decoder_rejects_invalid_acquisition_identity(field: str, value: object) -> None:
    row = copy.deepcopy(_DOCUMENT["pairs"][0])
    row["acquisitions"][0][field] = value
    with pytest.raises(ValidationError):
        StationProductAvailability.model_validate_json(json.dumps(row))


@pytest.mark.parametrize("value", [True, "475", 0, -1])
def test_material_size_is_not_coerced(value: object) -> None:
    row = copy.deepcopy(_DOCUMENT["pairs"][0])
    row["acquisitions"][0]["material"]["byte_count"] = value
    with pytest.raises(ValidationError):
        StationProductAvailability.model_validate_json(json.dumps(row))


def test_duplicate_pair_cannot_enter_the_typed_ledger() -> None:
    document = copy.deepcopy(_DOCUMENT)
    document["pairs"].append(copy.deepcopy(document["pairs"][0]))
    with pytest.raises(ValidationError, match="duplicate station/product"):
        FranceAvailability.model_validate_json(json.dumps(document))


def test_historical_query_rejects_an_extra_source_filter() -> None:
    row = copy.deepcopy(next(row for row in _DOCUMENT["pairs"] if row["basis"] == "historical_positive_witness"))
    row["acquisitions"][1]["requested_from"][0] += "&extra_filter=changed"
    with pytest.raises(ValidationError, match="unexpected historical request parameters"):
        StationProductAvailability.model_validate_json(json.dumps(row))


def test_ledger_requires_explicit_build_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import main

    with pytest.raises(SystemExit, match="2"):
        main(["--native", "native.parquet", "--out", str(tmp_path)])
    assert "--availability-ledger is required for canonical build" in capsys.readouterr().err
