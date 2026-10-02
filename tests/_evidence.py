"""Resolve explicitly supplied local test evidence without archive access."""

from pathlib import Path


def resolve_retained_evidence_root(configured: str | None) -> Path:
    if not configured:
        raise ValueError("RIVRETRIEVE_TEST_EVIDENCE_ROOT is required for the retained-input checks")
    root = Path(configured).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("RIVRETRIEVE_TEST_EVIDENCE_ROOT must name an existing directory")
    if any((parent / ".git").exists() for parent in (root, *root.parents)):
        raise ValueError("RIVRETRIEVE_TEST_EVIDENCE_ROOT must be outside source checkouts")
    return root
