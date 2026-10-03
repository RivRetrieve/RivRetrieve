"""Rebuild HydroPortail from external retained inputs and the authored history ledger."""

import argparse
from pathlib import Path

from rivretrieve._internal.providers.fr_hydroportail.generate_catalogue import main as generate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument(
        "--availability-ledger",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "fr_hubeau/inventory/governing_evidence.json.xz",
    )
    parser.add_argument("--build-inputs", type=Path, required=True, help="Reviewed adopted CatalogueBuildInputs JSON.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out = args.out.resolve()
    if any((parent / ".git").exists() for parent in (args.out, *args.out.parents)):
        parser.error("Output must be outside source checkouts")
    evidence_root = args.evidence_root.resolve()
    if args.out.is_relative_to(evidence_root):
        parser.error("Output must be separate from retained evidence")
    return generate(
        [
            "--build-inputs",
            str(args.build_inputs.resolve()),
            "--evidence-root",
            str(evidence_root),
            "--native",
            str(evidence_root / "src/rivretrieve/_internal/providers/fr_hydroportail/catalogue/native.parquet"),
            "--native-revision",
            "eb2b4fcb3a38875329225b7dbe5f949216c01599",
            "--evidence",
            str(evidence_root / "maintenance/catalogue/fr_hydroportail/evidence"),
            "--availability-ledger",
            str(args.availability_ledger.resolve()),
            "--out",
            str(args.out.resolve()),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
