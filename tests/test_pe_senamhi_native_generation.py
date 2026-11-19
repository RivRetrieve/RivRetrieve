"""Reviewed, retained-original generation of the SENAMHI native derivative."""

import os
from pathlib import Path

import pytest

from rivretrieve._internal.catalogues.native import read_native_table
from rivretrieve._internal.providers.pe_senamhi.generate_catalogue import main, read_native_sources


@pytest.mark.governing(
    "maintenance/catalogue/pe_senamhi/official",
    "maintenance/catalogue/pe_senamhi/official/selection.json",
)
def test_generate_retained_native_candidate(retained_evidence_root, catalogue_input_receipt, tmp_path):
    configured = os.environ.get("RIVRETRIEVE_CATALOGUE_PRODUCT_OUTPUT")
    if not configured:
        pytest.fail("Reviewed native generation requires restricted product output.", pytrace=False)
    output = Path(configured).resolve() / "pe_senamhi-native"
    receipt_path = tmp_path / "input-receipt.json"
    receipt_path.write_text(catalogue_input_receipt.model_dump_json())
    selection = "maintenance/catalogue/pe_senamhi/official/selection.json"
    assert (
        main(
            [
                "--evidence-root",
                str(retained_evidence_root),
                "--selection",
                selection,
                "--input-receipt",
                str(receipt_path),
                "--native-only",
                "--out",
                str(output),
            ]
        )
        == 0
    )
    reproduced = read_native_sources(
        retained_evidence_root, selection_path=selection, input_receipt=catalogue_input_receipt
    )
    assert read_native_table(output / "native.parquet").data.equals(reproduced.data)
