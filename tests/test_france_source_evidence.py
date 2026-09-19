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

FOLDER = Path(__file__).resolve().parents[1] / "maintenance/catalogue/fr_hubeau"


def load_verifier():
    scripts = FOLDER / "scripts"
    spec = importlib.util.spec_from_file_location("france_source_verifier", scripts / "verify_governing_evidence.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "defect",
    [
        "metric_summary",
        "malformed_success",
        "wrong_unit",
        "wrong_zone",
        "hash",
        "size",
        "duplicate",
        "missing",
        "extra",
    ],
)
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
    elif defect in {"malformed_success", "wrong_unit", "wrong_zone"}:
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
    elif defect == "hash":
        row["response_sha256"] = "0" * 64
    elif defect == "size":
        row["response_bytes"] = str(len(raw) + 1)
    csv_bytes = io.StringIO()
    writer = csv.DictWriter(csv_bytes, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    if defect == "duplicate":
        writer.writerow(row)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    with tarfile.open(evidence / "history.tar.xz", "w:xz") as target:
        members = [("receipts.csv", csv_bytes.getvalue().encode())]
        if defect != "missing":
            members.append((f"bodies/{row['request_id']}.body", raw))
        if defect == "extra":
            members.append(("bodies/unreceipted.body", raw))
        for name, content in members:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            target.addfile(info, io.BytesIO(content))
    with pytest.raises(ValueError):
        verifier.read_bundle(evidence / "history.tar.xz")


@pytest.mark.parametrize("defect", ["missing_answered_body", "request_url"])
@pytest.mark.parametrize("status", ["200", "500"])
def test_answered_count_requires_body_and_request_identity(tmp_path, defect, status):
    verifier = load_verifier()
    with tarfile.open(FOLDER / "evidence/hubeau_counts.tar.xz") as source:
        stream = source.extractfile("receipts.csv")
        assert stream is not None
        rows = list(csv.DictReader(io.StringIO(stream.read().decode())))
        row = next(r for r in rows if r["http_status"] == status and r["body_retained"] == "True")
        stream = source.extractfile(f"bodies/{row['request_id']}.body")
        assert stream is not None
        body = stream.read()
    if defect == "missing_answered_body":
        row["body_retained"] = "False"
    else:
        row["request_url"] = row["request_url"].replace(row["code_station"], "WRONG")
    content = io.StringIO()
    writer = csv.DictWriter(content, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    path = tmp_path / "counts.tar.xz"
    with tarfile.open(path, "w:xz") as target:
        members = [("receipts.csv", content.getvalue().encode())]
        if defect != "missing_answered_body":
            members.append((f"bodies/{row['request_id']}.body", body))
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            target.addfile(info, io.BytesIO(data))
    with pytest.raises((ValueError, KeyError)):
        verifier.read_bundle(path)
