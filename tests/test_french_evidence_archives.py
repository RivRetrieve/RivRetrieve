"""Lossless evidence packaging retains exact capture identities and reproducible reports."""

import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).parents[1]
VERIFICATION = ROOT / "maintenance/verification/french-publication-services"
EVIDENCE = Path("maintenance/catalogue/fr_hydroportail/evidence")
MANIFEST = json.loads((VERIFICATION / "evidence-archives.json").read_text())


@pytest.mark.parametrize("identity", MANIFEST["archives"], ids=lambda item: Path(item["path"]).name)
@pytest.mark.governing(
    "maintenance/catalogue/fr_hydroportail/evidence",
    "maintenance/verification/french-publication-services",
)
def test_archive_members_keep_original_bytes_and_safe_paths(retained_evidence_root, identity):
    path = retained_evidence_root / identity["path"]
    content = path.read_bytes()
    assert len(content) == identity["bytes"]
    assert hashlib.sha256(content).hexdigest() == identity["sha256"]
    if path.name == "supporting-captures.tar.xz":
        expected = {}
        for receipt_path in (retained_evidence_root / EVIDENCE).glob("*.receipt.json"):
            name = receipt_path.name.removesuffix(".receipt.json")
            if (name.startswith("missing-") and name != "missing-site-search") or name.startswith("gap-"):
                receipt = json.loads(receipt_path.read_bytes())
                assert receipt["status"] == 404
                assert receipt["url"].startswith("https://hydro.eaufrance.fr/")
                assert receipt["retrieved_at"]
                expected[name + ".body"] = receipt
    elif path.name == "publisher-payloads.tar.xz":
        results = json.loads(
            (retained_evidence_root / "maintenance/verification/french-publication-services/results.json").read_bytes()
        )
        expected = {receipt["path"]: receipt for result in results for receipt in result["receipts"]}
    else:
        expected = {member["name"]: member for member in identity["members"]}
    with tarfile.open(path, "r:xz") as archive:
        members = archive.getmembers()
        assert len({member.name for member in members}) == len(members)
        assert set(archive.getnames()) == set(expected)
        for member in members:
            name = PurePosixPath(member.name)
            assert member.isfile() and not member.issym() and not member.islnk()
            assert not name.is_absolute() and len(name.parts) == 1 and ".." not in name.parts
            source = archive.extractfile(member)
            assert source is not None
            body = source.read()
            assert len(body) == expected[member.name]["bytes"]
            assert hashlib.sha256(body).hexdigest() == expected[member.name]["sha256"]
        assert sum(member.size for member in members) == identity["original_bytes"]


@pytest.mark.governing(
    "maintenance/catalogue/fr_hydroportail/evidence",
    "maintenance/verification/french-publication-services",
)
def test_reconciliation_reports_regenerate_byte_for_byte(retained_evidence_root, tmp_path):
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
            assert (tmp_path / member.name).read_bytes() == source.read()
    assert (tmp_path / "summary.json").read_bytes() == (retained_evidence_root / EVIDENCE / "summary.json").read_bytes()
