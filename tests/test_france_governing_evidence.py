"""Source-backed negative contracts for France governing evidence, not boundary oracles."""

import csv
import importlib.util
import io
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "maintenance/catalogue/fr_hubeau/scripts/verify_governing_evidence.py"


@pytest.fixture(scope="module")
def verifier():
    spec = importlib.util.spec_from_file_location("france_governing", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=["hubeau_counts", "hydroportail_history"])
def source(retained_evidence_root, request):
    with tarfile.open(
        retained_evidence_root / f"maintenance/catalogue/fr_hubeau/evidence/{request.param}.tar.xz"
    ) as archive:
        receipt_file = archive.extractfile("receipts.csv")
        assert receipt_file is not None
        receipts = list(csv.DictReader(io.StringIO(receipt_file.read().decode())))
        receipt = next(row for row in receipts if row["http_status"] == "200" and row["body_retained"] == "True")
        body_file = archive.extractfile(f"bodies/{receipt['request_id']}.body")
        assert body_file is not None
        body = body_file.read()
    return receipt, body


@pytest.mark.governing(
    "maintenance/catalogue/fr_hubeau/evidence/hubeau_counts.tar.xz",
    "maintenance/catalogue/fr_hubeau/evidence/hydroportail_history.tar.xz",
    full_verification=("fr_hubeau",),
)
def test_actual_body_accepts_exact_receipt(verifier, source):
    receipt, body = source
    result = verifier.check_source(
        receipt["code_station"], receipt["product_id"], receipt["request_url"], int(receipt["http_status"]), body
    )
    assert result.count == 0


@pytest.mark.governing(
    "maintenance/catalogue/fr_hubeau/evidence/hubeau_counts.tar.xz",
    "maintenance/catalogue/fr_hubeau/evidence/hydroportail_history.tar.xz",
    full_verification=("fr_hubeau",),
)
@pytest.mark.parametrize("mutation", ["station", "product", "window"])
def test_actual_body_rejects_wrong_request(verifier, source, mutation):
    receipt, body = source
    station, product, url = receipt["code_station"], receipt["product_id"], receipt["request_url"]
    if mutation == "station":
        station = "NOT_THE_RECORDED_STATION"
    elif mutation == "product":
        product = "discharge_instantaneous"
    elif "hydro.eaufrance.fr" in url:
        url = url.replace("08%2F06%2F2026", "01%2F06%2F2026")
    else:
        url += "&date_debut_obs=2026-06-01"
    with pytest.raises(ValueError):
        verifier.check_source(station, product, url, 200, body)


@pytest.fixture(scope="module")
def document():
    import json
    import lzma

    return json.loads(
        lzma.decompress((ROOT / "maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz").read_bytes())
    )


@pytest.fixture(scope="module")
def native(retained_evidence_root):
    import pandas as pd

    return pd.read_parquet(
        retained_evidence_root / "maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet"
    )


@pytest.mark.governing(
    "maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet",
    full_verification=("fr_hubeau",),
)
def test_public_consistency_is_not_body_certification(verifier, document, native):
    assert verifier.verify_public(native, document) == document["summary"]


@pytest.mark.governing(
    "maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet",
    full_verification=("fr_hubeau",),
)
@pytest.mark.parametrize(
    "mutation",
    ["summary", "station", "duplicate", "missing", "product", "unavailable", "failed_as_empty", "old_witness_window"],
)
def test_public_mutations_fail(verifier, document, native, mutation):
    from copy import deepcopy

    changed = deepcopy(document)
    first = changed["pairs"][0]
    if mutation == "summary":
        changed["summary"]["available"] += 1
    elif mutation == "station":
        first["code_station"] = "NOT_BASELINE"
    elif mutation == "duplicate":
        changed["pairs"].append(deepcopy(first))
    elif mutation == "missing":
        changed["pairs"].pop()
    elif mutation == "product":
        first["product_id"] = "stage_instantaneous"
    elif mutation == "unavailable":
        first["availability"] = "unavailable"
    elif mutation == "failed_as_empty":
        row = next(
            r
            for r in changed["pairs"]
            if r["code_station"] == "J783301020" and r["product_id"] == "discharge_instantaneous"
        )
        row.update(status="empty_in_both_history_windows", basis="two_exact_windows_empty")
    elif mutation == "old_witness_window":
        row = next(r for r in changed["pairs"] if r["basis"] == "historical_positive_witness")
        acquisition = row["acquisitions"][1]
        acquisition["requested_from"][0] = acquisition["requested_from"][0].replace(
            "endAt%5D=01%2F06", "endAt%5D=08%2F06"
        )
    with pytest.raises(ValueError):
        verifier.verify_public(native, changed)


@pytest.fixture(scope="module")
def retained_bundles(retained_evidence_root, verifier):
    return {
        f"reused-pr231-head46b2fde/evidence/{name}.tar.xz": verifier.read_bundle(
            retained_evidence_root / f"maintenance/catalogue/fr_hubeau/evidence/{name}.tar.xz"
        )
        for name in ("hubeau_counts", "hydroportail_history")
    }


@pytest.mark.governing(
    "maintenance/catalogue/fr_hubeau/evidence/hubeau_counts.tar.xz",
    "maintenance/catalogue/fr_hubeau/evidence/hydroportail_history.tar.xz",
    full_verification=("fr_hubeau",),
)
@pytest.mark.parametrize("mutation", [None, "count", "hash", "bytes", "date", "url", "status", "reference"])
def test_private_primary_uses_actual_bytes_and_receipt(
    retained_evidence_root, verifier, document, retained_bundles, mutation
):
    from copy import deepcopy

    row = deepcopy(document["pairs"][0])
    acquisition = row["acquisitions"][0]
    if mutation == "count":
        row["published_count_or_new_witness_points"] += 1
    elif mutation == "hash":
        acquisition["material"]["sha256"] = "0" * 64
    elif mutation == "bytes":
        acquisition["material"]["byte_count"] += 1
    elif mutation == "date":
        acquisition["retrieved_at_start"] = "2020-01-01T00:00:00Z"
    elif mutation == "url":
        acquisition["requested_from"][0] += "&date_debut_obs=2026-06-01"
    elif mutation == "status":
        acquisition["http_status"] = 500
    elif mutation == "reference":
        acquisition["reference"] = document["pairs"][1]["acquisitions"][0]["reference"]
    if mutation is None:
        assert verifier.verify_private([row], retained_evidence_root, retained_bundles)["available"] == 1
    else:
        with pytest.raises(ValueError):
            verifier.verify_private([row], retained_evidence_root, retained_bundles)


@pytest.mark.governing(
    "maintenance/catalogue/fr_hubeau/evidence/hubeau_counts.tar.xz",
    "maintenance/catalogue/fr_hubeau/evidence/hydroportail_history.tar.xz",
    full_verification=("fr_hubeau",),
)
def test_history_empty_envelope_is_not_a_positive_witness(retained_evidence_root, verifier, document, retained_bundles):
    from copy import deepcopy

    row = deepcopy(
        next(
            r
            for r in document["pairs"]
            if r["basis"] == "two_exact_windows_empty" and all("!" in a["reference"] for a in r["acquisitions"])
        )
    )
    assert verifier.verify_private([row], retained_evidence_root, retained_bundles)["unknown"] == 1
    row.update(
        status="available",
        availability="available",
        basis="historical_positive_witness",
        published_count_or_new_witness_points=1,
    )
    with pytest.raises(ValueError, match="source classification mismatch"):
        verifier.verify_private([row], retained_evidence_root, retained_bundles)


@pytest.mark.governing(
    "maintenance/catalogue/fr_hubeau/evidence/hubeau_counts.tar.xz",
    "maintenance/catalogue/fr_hubeau/evidence/hydroportail_history.tar.xz",
    full_verification=("fr_hubeau",),
)
def test_history_failure_cannot_be_restored_as_empty(retained_evidence_root, verifier, document, retained_bundles):
    from copy import deepcopy

    row = deepcopy(next(r for r in document["pairs"] if r["basis"] == "preserved_history_failure"))
    assert verifier.verify_private([row], retained_evidence_root, retained_bundles)["unknown"] == 1
    row.update(status="empty_in_both_history_windows", basis="two_exact_windows_empty")
    with pytest.raises(ValueError, match="source classification mismatch"):
        verifier.verify_private([row], retained_evidence_root, retained_bundles)


@pytest.mark.parametrize("mutation", [None, "digest", "date", "quote", "status"])
def test_official_public_index_structure(verifier, mutation):
    import json
    from copy import deepcopy

    document = json.loads((ROOT / "maintenance/catalogue/fr_hubeau/evidence/official_publication.json").read_bytes())
    changed = deepcopy(document)
    entry = changed["source_documents"][0]
    if mutation == "digest":
        entry["acquisition"]["material"]["sha256"] = "bad"
    elif mutation == "date":
        entry["acquisition"]["retrieved_at_start"] = "2026-09-13"
    elif mutation == "quote":
        entry["quoted_source_words"] = ""
    elif mutation == "status":
        entry["acquisition"]["http_status"] = 500
    if mutation is None:
        verifier.verify_official_public(changed)
    else:
        with pytest.raises(ValueError):
            verifier.verify_official_public(changed)


@pytest.mark.governing(
    "maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet",
    full_verification=("fr_hubeau",),
)
def test_public_primary_failure_is_not_available(verifier, document, native):
    from copy import deepcopy

    changed = deepcopy(document)
    changed["pairs"][0]["acquisitions"][0]["http_status"] = 500
    with pytest.raises(ValueError, match="primary status"):
        verifier.verify_public(native, changed)


@pytest.mark.governing(
    "maintenance/catalogue/fr_hubeau/evidence/hubeau_counts.tar.xz",
    "maintenance/catalogue/fr_hubeau/evidence/hydroportail_history.tar.xz",
    full_verification=("fr_hubeau",),
)
@pytest.mark.parametrize("field,value", [("metric", "Q"), ("unit", "m"), ("code", "OTHER"), ("statuses", "validated")])
def test_empty_envelope_mismatch_fails_without_rows(verifier, retained_bundles, field, value):
    import json

    receipts, bodies = retained_bundles["reused-pr231-head46b2fde/evidence/hydroportail_history.tar.xz"]
    receipt = receipts["1120000201_H_w1_a1"]
    document = json.loads(bodies["bodies/1120000201_H_w1_a1.body"])
    assert document["series"]["data"] == []
    document["series"][field] = value
    with pytest.raises(ValueError):
        verifier.check_source(
            receipt["code_station"], receipt["product_id"], receipt["request_url"], 200, json.dumps(document).encode()
        )


@pytest.mark.governing(
    "maintenance/catalogue/fr_hubeau/inventory/native-2026-08-02.parquet",
    full_verification=("fr_hubeau",),
)
@pytest.mark.parametrize("mutation", ["reference", "receipt_id", "material_filename"])
def test_public_acquisition_reference_is_bound(verifier, document, native, mutation):
    from copy import deepcopy

    changed = deepcopy(document)
    acquisition = changed["pairs"][0]["acquisitions"][0]
    if mutation == "material_filename":
        acquisition["material"]["filename"] = "../outside.body"
    else:
        acquisition[mutation] = "unbound"
    with pytest.raises(ValueError):
        verifier.verify_public(native, changed)
