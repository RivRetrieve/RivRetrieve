"""Workbook verification : unchanged publisher bytes × altered acquisition claims → rejection."""

import json
import runpy
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

CATALOGUE = Path(__file__).parents[1] / "maintenance/catalogue/ba_fhmzbih"
NATIVE = Path("src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet")
RETAINED_CATALOGUE = Path("maintenance/catalogue/ba_fhmzbih")


@pytest.mark.parametrize("alter_reading_too", [False, True])
@pytest.mark.governing(
    "maintenance/catalogue/ba_fhmzbih",
    "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet",
    full_verification=("ba_fhmzbih",),
)
def test_verifier_rejects_false_positive_over_unchanged_blank_source(
    retained_evidence_root, tmp_path, monkeypatch, capsys, alter_reading_too
):
    """1110/Q is a real captured blank workbook, not an invented observation."""
    target = tmp_path / "catalogue"
    shutil.copytree(retained_evidence_root / RETAINED_CATALOGUE, target / RETAINED_CATALOGUE)
    shutil.copy2(
        CATALOGUE / "inventory/baseline_workbook_access.json",
        target / RETAINED_CATALOGUE / "inventory/baseline_workbook_access.json",
    )
    inventory = target / RETAINED_CATALOGUE / "inventory/workbook_cases.csv"
    frame = pd.read_csv(inventory, dtype=str)
    selected = (frame.station_no == "1110") & (frame.product_id == "discharge_reported")
    assert selected.sum() == 1
    frame.loc[selected, "status"] = "measurements_present"
    frame.loc[selected, "populated_measurements"] = "1"
    frame.to_csv(inventory, index=False)
    evidence = target / RETAINED_CATALOGUE / "evidence/1110_discharge_reported.evidence.json"
    document = json.loads(evidence.read_text())
    original_response = dict(document["response"])
    if alter_reading_too:
        document["reading"]["status"] = "measurements_present"
        document["reading"]["populated_measurements"] = 1
    document["excerpt"]["witness"] = [{"timestamp": "2026-09-09 00:00:00", "has_value": True}]
    evidence.write_text(json.dumps(document))
    assert document["response"] == original_response
    with pytest.raises(SystemExit) as raised:
        run_verifier(monkeypatch, retained_evidence_root, target)
    assert raised.value.code == 1
    assert "source workbook classification mismatch: 1110/discharge_reported" in capsys.readouterr().err


def run_verifier(monkeypatch, retained_evidence_root, catalogue_root=None, *arguments):
    namespace = runpy.run_path(str(CATALOGUE / "scripts/verify_evidence.py"))
    ledger = (
        CATALOGUE if catalogue_root is None else catalogue_root / RETAINED_CATALOGUE
    ) / "inventory/baseline_workbook_access.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_evidence.py",
            "--retained-evidence-root",
            str(catalogue_root or retained_evidence_root),
            "--baseline-native",
            str(retained_evidence_root / NATIVE),
            "--workbook-access-ledger",
            str(ledger),
            *arguments,
        ],
    )
    namespace["main"]()


@pytest.mark.governing(
    "maintenance/catalogue/ba_fhmzbih",
    "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet",
    full_verification=("ba_fhmzbih",),
)
def test_public_verification_does_not_claim_private_source_certification(retained_evidence_root, monkeypatch, capsys):
    run_verifier(monkeypatch, retained_evidence_root, None)
    output = capsys.readouterr().out
    assert '"private_baseline_bodies_checked": 0' in output
    assert "NOT certified" in output


@pytest.mark.governing(
    "maintenance/catalogue/ba_fhmzbih",
    "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet",
    full_verification=("ba_fhmzbih",),
)
def test_explicit_missing_private_corpus_fails_not_skips(retained_evidence_root, tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as raised:
        run_verifier(monkeypatch, retained_evidence_root, None, "--evidence-root", str(tmp_path / "absent"))
    assert raised.value.code == 1
    assert "FAIL:" in capsys.readouterr().err


@pytest.mark.parametrize("mutation", ["digest", "body_absent", "identity", "ledger_route", "ledger_omission"])
@pytest.mark.governing(
    "maintenance/catalogue/ba_fhmzbih",
    "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet",
    full_verification=("ba_fhmzbih",),
)
def test_source_and_ledger_corruption_fails(retained_evidence_root, tmp_path, monkeypatch, mutation):
    target = tmp_path / "catalogue"
    shutil.copytree(retained_evidence_root / RETAINED_CATALOGUE, target / RETAINED_CATALOGUE)
    shutil.copy2(
        CATALOGUE / "inventory/baseline_workbook_access.json",
        target / RETAINED_CATALOGUE / "inventory/baseline_workbook_access.json",
    )
    if mutation.startswith("ledger"):
        path = target / RETAINED_CATALOGUE / "inventory/baseline_workbook_access.json"
        document = json.loads(path.read_text())
        if mutation == "ledger_route":
            document["pairs"][0]["site_no"] = "DOES_NOT_MATCH_METADATA"
        else:
            document["pairs"].pop()
    else:
        path = target / RETAINED_CATALOGUE / "evidence/1110_discharge_reported.evidence.json"
        document = json.loads(path.read_text())
        if mutation == "digest":
            document["response"]["response_sha256"] = "0" * 64
        elif mutation == "body_absent":
            del document["response"]["content_base64"]
        else:
            document["station_no"] = "2101-B"
    path.write_text(json.dumps(document))
    with pytest.raises(SystemExit) as raised:
        run_verifier(monkeypatch, retained_evidence_root, target)
    assert raised.value.code == 1


@pytest.mark.recorded("maintenance/catalogue/ba_fhmzbih/evidence/1010_water_temperature_reported.evidence.json")
def test_recorded_empty_workbook_has_no_numerical_witness(retained_evidence_root):
    namespace = runpy.run_path(str(CATALOGUE / "scripts/verify_evidence.py"))
    document = json.loads(
        (
            retained_evidence_root / RETAINED_CATALOGUE / "evidence/1010_water_temperature_reported.evidence.json"
        ).read_text()
    )
    facts = namespace["read_workbook_facts"](namespace["checked_response"](document))
    assert (facts.station, facts.parameter, facts.unit) == ("1010", "Temperatura vode", "°C")
    assert facts.data_rows == facts.numerical_rows == 0
    assert facts.status == "no_data_rows"
    assert facts.first_timestamp is facts.last_timestamp is None


@pytest.mark.parametrize("mutation", ["unit", "parameter", "url", "availability", "accounting"])
@pytest.mark.governing(
    "maintenance/catalogue/ba_fhmzbih",
    "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet",
    full_verification=("ba_fhmzbih",),
)
def test_baseline_ledger_rejects_false_source_claims(retained_evidence_root, tmp_path, monkeypatch, mutation):
    target = tmp_path / "catalogue"
    shutil.copytree(retained_evidence_root / RETAINED_CATALOGUE, target / RETAINED_CATALOGUE)
    shutil.copy2(
        CATALOGUE / "inventory/baseline_workbook_access.json",
        target / RETAINED_CATALOGUE / "inventory/baseline_workbook_access.json",
    )
    path = target / RETAINED_CATALOGUE / "inventory/baseline_workbook_access.json"
    document = json.loads(path.read_text())
    row = document["pairs"][0]
    if mutation == "unit":
        row["source_unit"] = "invented unit"
    elif mutation == "parameter":
        row["parameter"] = "invented parameter"
    elif mutation == "url":
        row["url"] += "?different-source"
    elif mutation == "availability":
        row["availability"] = "unknown" if row["availability"] == "available" else "available"
    else:
        row["blank_rows"] += 1
    path.write_text(json.dumps(document))
    with pytest.raises(SystemExit) as raised:
        run_verifier(monkeypatch, retained_evidence_root, target)
    assert raised.value.code == 1


@pytest.mark.governing(
    "maintenance/catalogue/ba_fhmzbih",
    "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet",
    full_verification=("ba_fhmzbih",),
)
def test_certificate_requires_private_source_bodies(retained_evidence_root, tmp_path, monkeypatch, capsys):
    certificate = tmp_path / "certificate.json"
    with pytest.raises(SystemExit) as raised:
        run_verifier(monkeypatch, retained_evidence_root, None, "--certificate-out", str(certificate))
    assert raised.value.code == 1
    assert "certificate requires complete source-body verification" in capsys.readouterr().err
    assert not certificate.exists()


@pytest.mark.governing(
    "maintenance/catalogue/ba_fhmzbih",
    "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet",
    full_verification=("ba_fhmzbih",),
)
def test_public_cases_cannot_be_omitted(retained_evidence_root, tmp_path, monkeypatch, capsys):
    target = tmp_path / "catalogue"
    shutil.copytree(retained_evidence_root / RETAINED_CATALOGUE, target / RETAINED_CATALOGUE)
    shutil.copy2(
        CATALOGUE / "inventory/baseline_workbook_access.json",
        target / RETAINED_CATALOGUE / "inventory/baseline_workbook_access.json",
    )
    path = target / RETAINED_CATALOGUE / "inventory/workbook_cases.csv"
    frame = pd.read_csv(path, dtype=str)
    frame.iloc[1:].to_csv(path, index=False)
    with pytest.raises(SystemExit) as raised:
        run_verifier(monkeypatch, retained_evidence_root, target)
    assert raised.value.code == 1
    assert "recorded workbook case set differs" in capsys.readouterr().err


@pytest.mark.parametrize("missing", ["--retained-evidence-root", "--baseline-native"])
def test_verifier_requires_explicit_retained_inputs(tmp_path, monkeypatch, capsys, missing):
    """A clean checkout must not supply either retained input implicitly."""
    namespace = runpy.run_path(str(CATALOGUE / "scripts/verify_evidence.py"))
    supplied = "--baseline-native" if missing == "--retained-evidence-root" else "--retained-evidence-root"
    monkeypatch.setattr(sys, "argv", ["verify_evidence.py", supplied, str(tmp_path / "absent")])
    with pytest.raises(SystemExit) as raised:
        namespace["main"]()
    assert raised.value.code == 2
    assert missing in capsys.readouterr().err
