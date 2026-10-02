"""Public ANA verification: owner-local credentials x public selection -> safe audit summary."""

import argparse
import hashlib
import json
from pathlib import Path

import rivretrieve as rr
from rivretrieve._internal.discovery import _resolve_credentials


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Private output file outside the checkout")
    args = parser.parse_args()
    rr.providers()
    secrets = tuple(_resolve_credentials(("br_ana",), require_all=True)["br_ana"].values())
    selection = rr.find(provider="br_ana", station="15400000")
    result = rr.fetch(
        selection, start="2024-01-01T23:30:00", end="2024-01-02T00:30:00", receipts=True, on_issue="ignore"
    )
    summary = {
        "selection": rr.as_frame(selection).to_dicts(),
        "rows": result.data.to_dicts(),
        "issues": [{"severity": i.severity, "code": i.code, "message": i.message} for i in result.issues],
        "endpoints": result.provenance.endpoints,
        "source_call_count": len(result.provenance.calls_made),
        "receipts": [
            {"byte_count": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest()}
            for r in result.receipts.entries
        ],
    }
    encoded = json.dumps(summary, default=str, indent=2)
    if any(secret in encoded for secret in secrets):
        raise RuntimeError("unsafe audit output refused")
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded + "\n")
    print(
        json.dumps(
            {
                "row_count": result.data.height,
                "receipt_count": len(result.receipts.entries),
                "issue_codes": [i.code for i in result.issues],
            }
        )
    )
    if any(i.severity == "error" for i in result.issues):
        return 1
    if result.data.height == 0:
        return 1
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as error:
        print(json.dumps({"verification_failed_type": type(error).__name__}))
        code = 1
    raise SystemExit(code)
