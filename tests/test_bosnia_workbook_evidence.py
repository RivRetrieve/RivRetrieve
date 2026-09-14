"""Workbook verification : unchanged publisher bytes × altered research claims → rejection."""

import json
import runpy
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

RESEARCH = Path(__file__).parents[1] / "research/station-coverage/ba_fhmzbih"
NATIVE = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet"


@pytest.mark.parametrize("alter_reading_too", [False, True])
def test_verifier_rejects_false_positive_over_unchanged_blank_source(tmp_path, monkeypatch, capsys, alter_reading_too):
    """1110/Q is a real captured blank workbook, not an invented observation."""
    target = tmp_path / "research"
    shutil.copytree(RESEARCH, target)
    inventory = target / "inventory/station_product_evidence.csv"
    frame = pd.read_csv(inventory, dtype=str)
    selected = (frame.station_no == "1110") & (frame.product_id == "discharge_reported")
    assert selected.sum() == 1
    frame.loc[selected, "status"] = "measurements_present"
    frame.loc[selected, "populated_measurements"] = "1"
    frame.to_csv(inventory, index=False)
    evidence = target / "evidence/1110_discharge_reported.evidence.json"
    document = json.loads(evidence.read_text())
    original_response = dict(document["response"])
    if alter_reading_too:
        document["reading"]["status"] = "measurements_present"
        document["reading"]["populated_measurements"] = 1
    document["excerpt"]["witness"] = [{"timestamp": "2026-09-09 00:00:00", "has_value": True}]
    evidence.write_text(json.dumps(document))
    assert document["response"] == original_response
    namespace = runpy.run_path(str(RESEARCH / "scripts/verify_evidence.py"))
    # Legacy globals keep this regression on the original verifier's real main path.
    namespace["main"].__globals__["HERE"] = target
    namespace["main"].__globals__["NATIVE"] = NATIVE
    monkeypatch.setattr(
        sys, "argv", ["verify_evidence.py", "--research-root", str(target), "--baseline-native", str(NATIVE)]
    )
    with pytest.raises(SystemExit) as raised:
        namespace["main"]()
    assert raised.value.code == 1
    assert "source workbook classification mismatch: 1110/discharge_reported" in capsys.readouterr().err


def run_verifier(monkeypatch, research_root, *arguments):
    namespace = runpy.run_path(str(RESEARCH / "scripts/verify_evidence.py"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify_evidence.py", "--research-root", str(research_root), "--baseline-native", str(NATIVE), *arguments],
    )
    namespace["main"]()


def test_public_verification_does_not_claim_private_source_certification(monkeypatch, capsys):
    run_verifier(monkeypatch, RESEARCH)
    output = capsys.readouterr().out
    assert '"private_baseline_bodies_checked": 0' in output
    assert "NOT certified" in output


def test_explicit_missing_private_corpus_fails_not_skips(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as raised:
        run_verifier(monkeypatch, RESEARCH, "--evidence-root", str(tmp_path / "absent"))
    assert raised.value.code == 1
    assert "FAIL:" in capsys.readouterr().err


@pytest.mark.parametrize("mutation", ["digest", "body_absent", "identity", "ledger_route", "ledger_omission"])
def test_source_and_ledger_corruption_fails(tmp_path, monkeypatch, mutation):
    target = tmp_path / "research"
    shutil.copytree(RESEARCH, target)
    if mutation.startswith("ledger"):
        path = target / "inventory/baseline_workbook_access.json"
        document = json.loads(path.read_text())
        if mutation == "ledger_route":
            document["pairs"][0]["site_no"] = "DOES_NOT_MATCH_METADATA"
        else:
            document["pairs"].pop()
    else:
        path = target / "evidence/1110_discharge_reported.evidence.json"
        document = json.loads(path.read_text())
        if mutation == "digest":
            document["response"]["response_sha256"] = "0" * 64
        elif mutation == "body_absent":
            del document["response"]["content_base64"]
        else:
            document["station_no"] = "2101-B"
    path.write_text(json.dumps(document))
    with pytest.raises(SystemExit) as raised:
        run_verifier(monkeypatch, target)
    assert raised.value.code == 1


def test_recorded_empty_workbook_has_no_numerical_witness():
    namespace = runpy.run_path(str(RESEARCH / "scripts/verify_evidence.py"))
    document = json.loads((RESEARCH / "evidence/1010_water_temperature_reported.evidence.json").read_text())
    facts = namespace["read_workbook_facts"](namespace["checked_response"](document))
    assert (facts.station, facts.parameter, facts.unit) == ("1010", "Temperatura vode", "°C")
    assert facts.data_rows == facts.numerical_rows == 0
    assert facts.status == "no_data_rows"
    assert facts.first_timestamp is facts.last_timestamp is None
