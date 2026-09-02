from __future__ import annotations

import json
from pathlib import Path

import pytest

from rivretrieve._internal.acquisition_provenance import verify_recorded_statement
from rivretrieve._internal.issues import FatalContractError

_DATA = Path("tests/test_data")
_LICENSE = "水文水質データベースをご利用いただく際、掲載しているデータの利用について、許可等は必要ありません。 「公共データ利用規約（第1.0版）」に従い、データをご利用ください。"
_CITATION = "出典： 国土交通省 水文水質データベース （https://www1.river.go.jp/）（○年○月○日に参 照）、PDL1.0（http://www1.river.go.jp/）"


def _verify(stem: str, text: str) -> None:
    meta = json.loads((_DATA / f"{stem}.json").read_text())
    suffix = ".pdf" if "pdf" in meta["content_type"] else ".html"
    verify_recorded_statement(
        recording_name=stem,
        body=(_DATA / f"{stem}{suffix}").read_bytes(),
        expected_sha256=meta["sha256"],
        media_type=meta["content_type"],
        exact_text=text,
    )


def test_euc_jp_source_statement_is_verified_from_recorded_bytes() -> None:
    _verify("jp_mlit_terms_licence_euc_jp", _LICENSE)


def test_pdf_source_statement_is_verified_from_recorded_bytes() -> None:
    _verify("jp_mlit_terms_citation", _CITATION)


def test_absent_source_statement_is_rejected_by_recording_name() -> None:
    with pytest.raises(
        FatalContractError,
        match="jp_mlit_terms_licence_euc_jp: quotation is absent from recorded bytes",
    ):
        _verify("jp_mlit_terms_licence_euc_jp", "この引用は記録に存在しません。")
