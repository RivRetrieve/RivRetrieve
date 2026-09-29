"""Explicit maintainer CLI; no runtime cache or private repository discovery."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .acquisition import acquire_collection
from .index import EvidenceError, read_index


def _source_roots() -> tuple[Path, ...]:
    checkout = Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=checkout,
            capture_output=True,
            check=True,
            timeout=10,
        )
        common = Path(result.stdout.decode().strip())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise EvidenceError(
            "Cannot identify the source checkout; run from a Git checkout with git installed."
        ) from error
    return checkout, common.parent


def main(argv: list[str] | None = None) -> int:
    """Validate metadata or fetch one explicit collection; never execute indexed commands."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate the public provider evidence index offline")
    validate.add_argument("--index", required=True, type=Path)
    fetch = commands.add_parser("fetch", help="download and check an exact provider collection with authenticated gh")
    fetch.add_argument("--index", required=True, type=Path)
    fetch.add_argument("--provider", required=True)
    fetch.add_argument("--collection", required=True)
    fetch.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        index = read_index(args.index)
        if args.command == "validate":
            print(json.dumps({"providers": len(index.providers), "collections": len(index.collections)}))
        else:
            acquire_collection(index, args.provider, args.collection, args.destination, source_roots=_source_roots())
            selected = next(item for item in index.collections if item.collection_id == args.collection)
            print(
                json.dumps(
                    {
                        "collection_id": selected.collection_id,
                        "release_id": selected.release_id,
                        "verification_root": selected.verification_root,
                        "asset_ids": [asset.asset_id for asset in selected.assets],
                        "sha256": [asset.sha256 for asset in selected.assets],
                    }
                )
            )
        return 0
    except EvidenceError as error:
        print(f"Evidence unavailable: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
