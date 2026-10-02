"""Check external input configuration without opening retained evidence."""

from pathlib import Path

import pytest

from tests._evidence import resolve_retained_evidence_root


@pytest.mark.parametrize("configured", [None, ""])
def test_missing_evidence_configuration_fails(configured: str | None) -> None:
    with pytest.raises(ValueError, match="is required"):
        resolve_retained_evidence_root(configured)


def test_missing_evidence_directory_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="existing directory"):
        resolve_retained_evidence_root(str(tmp_path / "missing"))


@pytest.mark.parametrize("worktree", [False, True])
def test_evidence_inside_source_checkout_fails(tmp_path: Path, worktree: bool) -> None:
    marker = tmp_path / ".git"
    if worktree:
        marker.write_text("gitdir: unused")
    else:
        marker.mkdir()
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    with pytest.raises(ValueError, match="outside source checkouts"):
        resolve_retained_evidence_root(str(inputs))


def test_explicit_external_directory_is_resolved(tmp_path: Path) -> None:
    assert resolve_retained_evidence_root(str(tmp_path)) == tmp_path.resolve()
