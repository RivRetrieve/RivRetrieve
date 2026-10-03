"""Lossless evidence packaging retains exact capture identities and reproducible reports."""

import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
EVIDENCE = Path("maintenance/catalogue/fr_hydroportail/evidence")


@pytest.mark.governing(
    "maintenance/catalogue/fr_hydroportail/evidence",
    "maintenance/verification/french-publication-services",
)
def test_missing_station_receipts_record_publisher_failures(retained_evidence_root: Path) -> None:
    receipts = []
    for path in (retained_evidence_root / EVIDENCE).glob("*.receipt.json"):
        name = path.name.removesuffix(".receipt.json")
        if (name.startswith("missing-") and name != "missing-site-search") or name.startswith("gap-"):
            receipts.append(json.loads(path.read_bytes()))

    assert receipts
    for receipt in receipts:
        assert receipt["status"] == 404
        assert receipt["url"].startswith("https://hydro.eaufrance.fr/")
        assert receipt["retrieved_at"]


@pytest.mark.governing(
    "maintenance/catalogue/fr_hydroportail/evidence",
    "maintenance/verification/french-publication-services",
)
def test_reconciliation_regenerates_reviewed_report_contents(retained_evidence_root, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "maintenance/catalogue/fr_hydroportail/scripts/reconcile.py"),
            "--evidence-root",
            str(retained_evidence_root),
            "--availability-ledger",
            str(ROOT / "maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz"),
            "--out",
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    with tarfile.open(retained_evidence_root / EVIDENCE / "reconciliation.tar.xz", "r:xz") as archive:
        for member in archive.getmembers():
            source = archive.extractfile(member)
            assert source is not None
            assert json.loads((tmp_path / member.name).read_bytes()) == json.loads(source.read())
    assert json.loads((tmp_path / "summary.json").read_bytes()) == json.loads(
        (retained_evidence_root / EVIDENCE / "summary.json").read_bytes()
    )
