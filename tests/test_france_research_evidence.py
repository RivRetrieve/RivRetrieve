"""France evidence checks compare claims with genuine retained source bytes."""

import csv
import hashlib
import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parents[1] / "research/station-coverage/fr_hubeau"


def load_verifier():
    scripts = FOLDER / "scripts"
    spec = importlib.util.spec_from_file_location("france_research_verifier", scripts / "verify_evidence.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(scripts))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(scripts))
    return module


@pytest.mark.parametrize("defect", ["metric_summary", "malformed_success", "wrong_unit", "wrong_zone"])
def test_history_claim_must_match_recorded_body(tmp_path, defect):
    verifier = load_verifier()
    original = FOLDER / "evidence/hydroportail_history.tar.xz"
    with tarfile.open(original) as source:
        receipt_stream = source.extractfile("receipts.csv")
        assert receipt_stream is not None
        rows = list(csv.DictReader(io.StringIO(receipt_stream.read().decode())))
        row = next(r for r in rows if r["http_status"] == "200" and r["body_retained"] == "True")
        body_stream = source.extractfile(f"bodies/{row['request_id']}.body")
        assert body_stream is not None
        raw = body_stream.read()
    if defect == "metric_summary":
        row["series_metric"] = "Q" if row["series_metric"] == "H" else "H"
    else:
        # Deliberately corrupt a genuine retained empty body. These negative inputs
        # are not observation recordings or a source of positive expectations.
        if defect == "malformed_success":
            raw = raw.rstrip()[:-1]
        else:
            document = json.loads(raw)
            if defect == "wrong_unit":
                document["series"]["unit"] = "unsupported-unit"
            else:
                document["timezone"] = "unsupported-zone"
            raw = json.dumps(document).encode()
        row["response_sha256"] = hashlib.sha256(raw).hexdigest()
        row["response_bytes"] = str(len(raw))
    csv_bytes = io.StringIO()
    writer = csv.DictWriter(csv_bytes, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    with tarfile.open(evidence / "history.tar.xz", "w:xz") as target:
        for name, content in [
            ("receipts.csv", csv_bytes.getvalue().encode()),
            (f"bodies/{row['request_id']}.body", raw),
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            target.addfile(info, io.BytesIO(content))
    checks = verifier.Checks()
    verifier.verify_bundle(tmp_path, "history.tar.xz", checks)
    assert checks.failures, f"Recorded empty-body contract defect was accepted: {defect}"
