from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from rivretrieve._internal.acquisition_provenance import verify_recorded_statement
from rivretrieve._internal.issues import FatalContractError

_LICENSE = "水文水質データベースをご利用いただく際、掲載しているデータの利用について、許可等は必要ありません。 「公共データ利用規約（第1.0版）」に従い、データをご利用ください。"
_CITATION = "出典： 国土交通省 水文水質データベース （https://www1.river.go.jp/）（○年○月○日に参 照）、PDL1.0（http://www1.river.go.jp/）"


def test_unreadable_pdf_statement_is_a_fatal_contract_error() -> None:
    body = b"not a PDF"
    with pytest.raises(FatalContractError, match="synthetic-unreadable: PDF text cannot be read") as raised:
        verify_recorded_statement(
            recording_name="synthetic-unreadable",
            body=body,
            expected_sha256=hashlib.sha256(body).hexdigest(),
            media_type="application/pdf",
            exact_text="A source statement",
        )
    assert raised.value.__cause__ is not None


def test_absent_statement_in_readable_pdf_is_rejected() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    output = io.BytesIO()
    writer.write(output)
    body = output.getvalue()
    with pytest.raises(FatalContractError, match="synthetic-blank: quotation is absent from recorded bytes"):
        verify_recorded_statement(
            recording_name="synthetic-blank",
            body=body,
            expected_sha256=hashlib.sha256(body).hexdigest(),
            media_type="application/pdf",
            exact_text="A source statement",
        )


def _verify(retained_evidence_root: Path, stem: str, text: str) -> None:
    meta = json.loads((retained_evidence_root / "tests/test_data" / f"{stem}.json").read_text())
    suffix = ".pdf" if "pdf" in meta["content_type"] else ".html"
    verify_recorded_statement(
        recording_name=stem,
        body=(retained_evidence_root / "tests/test_data" / f"{stem}{suffix}").read_bytes(),
        expected_sha256=meta["sha256"],
        media_type=meta["content_type"],
        exact_text=text,
    )


@pytest.mark.governing(
    "tests/test_data/jp_mlit_terms_licence_euc_jp.html",
    "tests/test_data/jp_mlit_terms_licence_euc_jp.json",
)
def test_euc_jp_source_statement_is_verified_from_recorded_bytes(retained_evidence_root: Path) -> None:
    _verify(retained_evidence_root, "jp_mlit_terms_licence_euc_jp", _LICENSE)


@pytest.mark.governing("tests/test_data/jp_mlit_terms_citation.json", "tests/test_data/jp_mlit_terms_citation.pdf")
def test_pdf_source_statement_is_verified_from_recorded_bytes(retained_evidence_root: Path) -> None:
    _verify(retained_evidence_root, "jp_mlit_terms_citation", _CITATION)


@pytest.mark.governing(
    "tests/test_data/jp_mlit_terms_licence_euc_jp.html",
    "tests/test_data/jp_mlit_terms_licence_euc_jp.json",
)
def test_absent_source_statement_is_rejected_by_recording_name(retained_evidence_root: Path) -> None:
    with pytest.raises(
        FatalContractError,
        match="jp_mlit_terms_licence_euc_jp: quotation is absent from recorded bytes",
    ):
        _verify(retained_evidence_root, "jp_mlit_terms_licence_euc_jp", "この引用は記録に存在しません。")
