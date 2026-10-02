from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from rivretrieve._internal.catalogues.native import read_native_table
from rivretrieve._internal.issues import FatalContractError

_NATIVE = Path("src/rivretrieve/_internal/providers/jp_mlit/catalogue/native.parquet")
_EXPECTED = "ec892e4bc5bee3e8d5435190f4163ecddd80d2d244a71c810b9cf666d06b5aad"


def test_japan_native_table_refuses_one_byte_substitution(tmp_path: Path, retained_evidence_root: Path) -> None:
    content = bytearray((retained_evidence_root / _NATIVE).read_bytes())
    content[-200] ^= 1
    substituted = tmp_path / "native.parquet"
    substituted.write_bytes(content)

    assert hashlib.sha256(content).hexdigest() != _EXPECTED
    with pytest.raises(
        FatalContractError,
        match=rf"native table digest mismatch: expected {_EXPECTED}, observed [0-9a-f]{{64}}",
    ):
        read_native_table(substituted, expected_sha256=_EXPECTED)


def test_native_table_refuses_wrong_declared_byte_size(retained_evidence_root: Path) -> None:
    native = retained_evidence_root / _NATIVE
    byte_size = native.stat().st_size
    with pytest.raises(
        FatalContractError,
        match=rf"native table byte-size mismatch: expected {byte_size + 1}, observed {byte_size}",
    ):
        read_native_table(
            native,
            expected_sha256=_EXPECTED,
            expected_byte_size=byte_size + 1,
        )
