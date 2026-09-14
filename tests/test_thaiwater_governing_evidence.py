"""Governing graph verification rejects coordinated derived-count forgery."""

from __future__ import annotations

import csv
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest


def test_verifier_rejects_a_forged_count_in_both_receipt_and_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "research/station-coverage/th_thaiwater"
    copied = tmp_path / "research"
    shutil.copytree(source, copied)
    for name, key in [
        ("evidence/graph_receipts.csv", "nonnull_value"),
        ("inventory/station_product_evidence.csv", "nonnull_observations"),
    ]:
        path = copied / name
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            fields = reader.fieldnames
            rows = list(reader)
        assert fields is not None
        for row in rows:
            if (
                row["station_id"] == "1"
                and row["window_start"] == "2026-06-08"
                and ("product_id" not in row or row["product_id"] == "stage_reported")
            ):
                row[key] = str(int(row[key]) + 1)
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    spec = importlib.util.spec_from_file_location("thaiwater_verification", source / "scripts/verify_evidence.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HERE", copied)
    monkeypatch.setattr(sys, "argv", ["verify_evidence.py"])
    with pytest.raises(SystemExit):
        module.main()


def _governing_module(root: Path):
    spec = importlib.util.spec_from_file_location(
        "governing_graph_evidence", root / "research/station-coverage/th_thaiwater/scripts/verify_governing_evidence.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_body_rejects_false_positive_even_when_derived_facts_agree(tmp_path: Path) -> None:
    import json
    import zipfile

    root = Path(__file__).resolve().parents[1]
    research = root / "research/station-coverage/th_thaiwater"
    module = _governing_module(root)
    ledger = module.read_ledger(research / "inventory/governing_station_product_evidence.csv")
    row = next(dict(row) for row in ledger if row["station_id"] == "11688546" and row["product_id"] == "stage_reported")
    receipts = module.read_ledger(research / "evidence/graph_receipts.csv")
    original = next(receipt for receipt in receipts if receipt["request_id"] == row["request_id"])
    with zipfile.ZipFile(research / "evidence/graph_bodies_without_observations.zip") as bundle:
        body = bundle.read(f"{row['request_id']}.body")
    body_path = tmp_path / row["evidence_body"]
    body_path.parent.mkdir(parents=True)
    body_path.write_bytes(body)
    receipt_path = tmp_path / row["evidence_receipt"]
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps({"body_path": row["evidence_body"], "original_receipt": original}))
    module.verify_bodies([row], tmp_path)
    row.update(nonnull_observations="1", status="available", availability="available")
    # The exact recorded null bytes remain unchanged. Only the derived conclusion is forged.
    with pytest.raises(ValueError, match="source measurement count disagrees"):
        module.verify_bodies([row], tmp_path)


def test_governing_ledger_preserves_every_baseline_pair_and_agency() -> None:
    root = Path(__file__).resolve().parents[1]
    module = _governing_module(root)
    rows = module.read_ledger(
        root / "research/station-coverage/th_thaiwater/inventory/governing_station_product_evidence.csv"
    )
    agencies = module.station_agencies(
        root / "src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet"
    )
    module.verify_ledger(rows, agencies)
    assert len(agencies) == 825
    assert len(rows) == 1650
    assert sum(row["availability"] == "available" for row in rows) == 1096
    assert sum(row["availability"] == "unknown" for row in rows) == 554


def test_historical_truncation_script_is_retired_before_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "research/station-coverage/th_thaiwater/scripts/reproduce_window_truncation.py"
    spec = importlib.util.spec_from_file_location("historical_truncation", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import rivretrieve as rr

    original_find = rr.find
    calls = []

    def counted_find(*args, **kwargs):
        calls.append(kwargs)
        return original_find(*args, **kwargs)

    def forbid_fetch(*args, **kwargs):
        raise RuntimeError("historical script reached live fetch")

    monkeypatch.setattr(rr, "find", counted_find)
    monkeypatch.setattr(rr, "fetch", forbid_fetch)
    with pytest.raises(SystemExit, match="retired"):
        module.main()
    assert calls == []


def test_station_table_does_not_label_general_source_failure_as_http404() -> None:
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "historical_station_table", root / "research/station-coverage/th_thaiwater/scripts/build_station_table.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.LABEL["access_failed"] == "access failed"
