"""Explicit maintainer CLI; no runtime cache or private repository discovery."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .acquisition import acquire_collection
from .index import EvidenceError, read_index
from .intake import prepare_collection
from .publication import publish_collection


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
    """Validate, retrieve, prepare or publish exact inputs without echoing private facts."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate the public provider evidence index offline")
    validate.add_argument("--index", required=True, type=Path)
    fetch = commands.add_parser("fetch", help="download and verify one explicit provider collection")
    fetch.add_argument("--index", required=True, type=Path)
    fetch.add_argument("--provider", required=True)
    fetch.add_argument("--collection", required=True)
    fetch.add_argument("--destination", required=True, type=Path)
    intake = commands.add_parser("intake", help="verify retained files and prepare a new private collection offline")
    intake.add_argument("--manifest", required=True, type=Path)
    intake.add_argument("--source", required=True, type=Path)
    intake.add_argument("--destination", required=True, type=Path)
    publish = commands.add_parser("publish", help="publish a prepared collection to a new private GitHub release")
    publish.add_argument("--prepared", required=True, type=Path)
    publish.add_argument("--release-tag", required=True)
    publish.add_argument("--output", required=True, type=Path)
    publish.add_argument("--purpose", required=True, help="reviewed public purpose, excluding private facts")
    publish.add_argument("--limitation", action="append", default=[], help="reviewed public limitation (repeatable)")
    args = parser.parse_args(argv)
    try:
        if args.command in ("validate", "fetch"):
            index = read_index(args.index)
            if args.command == "validate":
                result = {"providers": len(index.providers), "collections": len(index.collections)}
            else:
                inputs = acquire_collection(
                    index, args.provider, args.collection, args.destination, source_roots=_source_roots()
                )
                selected = inputs.collection
                result = {
                    "collection_id": selected.collection_id,
                    "release_id": selected.release_id,
                    "input_roots": selected.input_roots,
                    "asset_ids": [asset.asset_id for asset in selected.assets],
                    "sha256": [asset.sha256 for asset in selected.assets],
                }
        elif args.command == "intake":
            prepare_collection(args.manifest, args.source, args.destination, source_roots=_source_roots())
            result = {"prepared": True, "acceptance": "not_evaluated"}
        else:
            publish_collection(
                args.prepared,
                args.release_tag,
                args.output,
                purpose=args.purpose,
                limitations=args.limitation,
                source_roots=_source_roots(),
            )
            result = {"published": True, "acceptance": "not_evaluated"}
        print(json.dumps(result))
        return 0
    except EvidenceError as error:
        print(f"Evidence unavailable: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
