"""Governing graph verification rejects coordinated derived-count forgery."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _governing_module(root: Path):
    spec = importlib.util.spec_from_file_location(
        "governing_graph_evidence", root / "maintenance/catalogue/th_thaiwater/scripts/verify_governing_evidence.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_body_rejects_false_positive_even_when_derived_facts_agree(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    import json

    root = Path(__file__).resolve().parents[1]
    research = root / "maintenance/catalogue/th_thaiwater"
    module = _governing_module(root)
    ledger = module.read_ledger(research / "inventory/governing_station_product_evidence.csv")
    row = next(dict(row) for row in ledger if row["station_id"] == "11688546" and row["product_id"] == "stage_reported")
    receipts = module.read_ledger(
        retained_evidence_root / "maintenance/catalogue/th_thaiwater/evidence/graph_receipts.csv"
    )
    original = next(receipt for receipt in receipts if receipt["request_id"] == row["request_id"])
    body = (
        retained_evidence_root / "maintenance/catalogue/th_thaiwater/recordings" / f"{row['request_id']}.body"
    ).read_bytes()
    body_path = tmp_path / row["evidence_body"]
    body_path.parent.mkdir(parents=True)
    body_path.write_bytes(body)
    receipt_path = tmp_path / row["evidence_receipt"]
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps({"body_path": row["evidence_body"], "original_receipt": original}))
    module.verify_bodies([row], tmp_path)
    with pytest.raises(ValueError, match="source body digest/size mismatch"):
        module.verify_response(row, {"body_path": row["evidence_body"], "original_receipt": original}, body[:-1])
    forged_receipt = dict(original, request_url=original["request_url"].replace("station_id=11688546", "station_id=1"))
    with pytest.raises(ValueError, match="receipt acquisition facts disagree"):
        module.verify_response(row, {"body_path": row["evidence_body"], "original_receipt": forged_receipt}, body)
    row.update(nonnull_observations="1", status="available", availability="available")
    # The exact recorded null bytes remain unchanged. Only the derived conclusion is forged.
    with pytest.raises(ValueError, match="source measurement count disagrees"):
        module.verify_bodies([row], tmp_path)


def test_governing_ledger_preserves_every_baseline_pair_and_agency(retained_evidence_root: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    module = _governing_module(root)
    rows = module.read_ledger(
        root / "maintenance/catalogue/th_thaiwater/inventory/governing_station_product_evidence.csv"
    )
    agencies = module.station_agencies(
        retained_evidence_root / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
    )
    module.verify_ledger(rows, agencies)
    assert len(agencies) == 825
    assert len(rows) == 1650
    assert sum(row["availability"] == "available" for row in rows) == 1096
    assert sum(row["availability"] == "unknown" for row in rows) == 554


def test_each_station_acquisition_is_verified_when_body_path_is_reused(retained_evidence_root: Path) -> None:
    """Reproduce the independent review's coordinated second-station receipt forgery."""
    import os

    configured = os.environ.get("THAIWATER_REVIEW_EVIDENCE_ROOT")
    if configured is None:
        pytest.fail("THAIWATER_REVIEW_EVIDENCE_ROOT is required for the controlled-input acceptance check")
    evidence_root = Path(configured)
    root = Path(__file__).resolve().parents[1]
    module = _governing_module(root)
    rows = module.read_ledger(
        root / "maintenance/catalogue/th_thaiwater/inventory/governing_station_product_evidence.csv"
    )
    agencies = module.station_agencies(
        retained_evidence_root / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
    )
    first_station = rows[0]["station_id"]
    second_station = next(row["station_id"] for row in rows if row["station_id"] != first_station)
    first = [dict(row) for row in rows if row["station_id"] == first_station]
    second = [dict(row) for row in rows if row["station_id"] == second_station]
    for row in second:
        source = next(item for item in first if item["product_id"] == row["product_id"])
        for field in (
            "evidence_body",
            "nonnull_observations",
            "grid_rows",
            "window_dates",
            "window_start",
            "window_end",
            "status",
            "availability",
            "grid_first",
            "grid_last",
        ):
            row[field] = source[field]
        row["evidence_receipt"] = "receipts/NONEXISTENT-FORGED.json"
        row["request_url"] = source["request_url"].replace(
            f"station_id={first_station}&", f"station_id={second_station}&"
        )
    forged = first + second
    module.verify_ledger(forged, {station: agencies[station] for station in (first_station, second_station)})
    # Each station's own acquisition must be checked even when bytes are cached.
    with pytest.raises((FileNotFoundError, ValueError)):
        module.verify_bodies(forged, evidence_root)


def test_governing_body_verification_requires_each_acquisition_receipt(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    module = _governing_module(root)
    rows = module.read_ledger(
        root / "maintenance/catalogue/th_thaiwater/inventory/governing_station_product_evidence.csv"
    )
    with pytest.raises(FileNotFoundError):
        module.verify_bodies(rows[:1], tmp_path)


def test_retained_source_bodies_preserve_archive_member_identity(retained_evidence_root: Path) -> None:
    import hashlib
    import json

    root = Path(__file__).resolve().parents[1] / "maintenance/catalogue/th_thaiwater"
    provenance = json.loads((root / "evidence/recording_provenance.json").read_text())
    assert provenance["source_commit"] == "dfe2de3bb7371dfd3eb9bef5604b6f3eac52aae3"
    assert (
        provenance["source_path"]
        == "research/station-coverage/th_thaiwater/evidence/graph_bodies_without_observations.zip"
    )
    assert provenance["archive_sha256"] == "03f4c2704ef6852a2360e0d5a5a5d56d1a2477e8b5c9e872a002de6f80d0b0f9"
    expected = {
        "11688546_2026-06-08_2026-09-06_a1.body": "710e5649afedcd48c99e76a44c568f1edd223921c28ed79aa45f03f8075a945f",
        "1109499_2026-06-08_2026-09-06_a1.body": "f20373431a6f611cb0f013d4b9ec405315344bb9157c17dd9f85586ae63c86df",
    }
    assert {member["archive_member"]: member["sha256"] for member in provenance["members"]} == expected
    for member in provenance["members"]:
        assert member["retained_path"] == f"recordings/{member['archive_member']}"
        assert (
            hashlib.sha256(
                (retained_evidence_root / "maintenance/catalogue/th_thaiwater" / member["retained_path"]).read_bytes()
            ).hexdigest()
            == member["sha256"]
        )
