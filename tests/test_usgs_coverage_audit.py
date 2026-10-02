"""USGS audit tests with mixed inputs.

Authored controls use synthetic inputs. Other tests use retained publisher
responses, acquisition receipts, frozen baseline data and derived audit outputs.
"""

import gzip
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "coverage_audit", Path(__file__).parents[1] / "scripts/audit_usgs_coverage.py"
)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def page(parameter, links=()):
    return json.dumps(
        {"features": [{"properties": {"parameter_code": parameter}}], "numberReturned": 1, "links": list(links)}
    ).encode()


def test_exhausts_publisher_pages_without_active_filter(tmp_path, monkeypatch):
    calls = []

    def capture(url, out, name):
        parameter = "00060" if "00060" in url else "00065"
        calls.append(url)
        links = (
            []
            if "cursor=" in url
            else [{"rel": "next", "href": f"{audit.BASE}?f=json&parameter_code={parameter}&cursor=next"}]
        )
        return {"status": 200}, page(parameter, links)

    monkeypatch.setattr(audit, "capture", capture)
    audit.acquire(tmp_path, 3)
    for parameter in ("00060", "00065"):
        result = json.loads((tmp_path / f"metadata-{parameter}-completion.json").read_text())
        assert result["status"] == "complete"
        assert result["pages"] == 2
    assert len(calls) == 4
    assert all("sortby" not in url and "active" not in url for url in calls)


@pytest.mark.parametrize("failure", ["access", "cycle", "scope", "malformed", "budget"])
def test_incomplete_acquisition_is_unresolved(tmp_path, monkeypatch, failure):
    def capture(url, out, name):
        if failure == "access":
            return {"status": 429}, b"rate limited"
        if failure == "malformed":
            return {"status": 200}, b"{}"
        parameter = "00060" if "00060" in url else "00065"
        next_url = url if failure == "cycle" else f"{audit.BASE}?f=json&parameter_code={parameter}&cursor=more"
        if failure == "scope":
            next_url = "https://elsewhere.example/items?f=json"
        return {"status": 200}, page(parameter, [{"rel": "next", "href": next_url}])

    monkeypatch.setattr(audit, "capture", capture)
    audit.acquire(tmp_path, 1 if failure == "budget" else 3)
    assert json.loads((tmp_path / "metadata-00060-completion.json").read_text())["status"] == "unresolved"


def test_cached_receipt_must_match_request_and_hash(tmp_path):
    (tmp_path / "page.json.gz").write_bytes(gzip.compress(b"{}"))
    receipt = {"url": "https://example.org", "sha256": "wrong"}
    (tmp_path / "page.receipt.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="request mismatch"):
        audit.capture("https://other.example", tmp_path, "page")
    with pytest.raises(ValueError, match="hash mismatch"):
        audit.capture(receipt["url"], tmp_path, "page")


@pytest.mark.governing("research/usgs-modern-coverage")
@pytest.mark.parametrize("station,agency", [("09489082", "USFS"), ("09527500", "CA574")])
def test_frozen_non_usgs_identity_matches_publisher_evidence(retained_evidence_root, station, agency):
    directory = retained_evidence_root / "research/usgs-modern-coverage"
    native = audit.pl.read_parquet(directory / "baseline_stations.parquet")
    source = native.filter(audit.pl.col("site_no") == station).to_dicts()[0]
    assert source["agency_cd"] == agency
    location = agency + "-" + station
    published = json.loads(gzip.decompress((directory / "probes" / f"location-{location}.json.gz").read_bytes()))
    assert published["properties"]["agency_code"] == agency
    assert published["id"] == location
    with gzip.open(directory / "comparison.jsonl.gz", "rt") as stream:
        rows = [json.loads(line) for line in stream if f'"station_id": "{station}"' in line]
    supported = [row for row in rows if row["baseline_availability"] == "available"]
    assert supported
    assert all(row["monitoring_location_id"] == location and row["status"] == "matched" for row in supported)
    legacy = audit.read_probe(directory, f"legacy-{station}-discharge_daily_mean-start")
    assert legacy["agencies"] == [agency]


@pytest.mark.governing("research/usgs-modern-coverage")
def test_frozen_full_denominator_and_receipt_hashes(
    retained_evidence_root,
):
    import hashlib

    directory = retained_evidence_root / "research/usgs-modern-coverage"
    summary = json.loads((directory / "summary.json").read_text())
    assert summary["baseline_stations"] == 26258
    assert sum(summary["product_counts"].values()) == 26258 * 6
    assert summary["product_counts"] == {
        "matched": 57950,
        "not_in_baseline": 99587,
        "unresolved": 6,
        "confirmed_missing": 5,
    }
    receipts = json.loads((directory / "requests.json").read_text())
    assert len(receipts) == 105
    for receipt in receipts:
        path = directory / receipt["receipt"]
        raw = gzip.decompress((path.parent / receipt["file"]).read_bytes())
        assert hashlib.sha256(raw).hexdigest() == receipt["sha256"]


@pytest.mark.governing("research/usgs-modern-coverage")
def test_unknown_statistic_with_observations_is_not_missing(
    retained_evidence_root,
):
    directory = retained_evidence_root / "research/usgs-modern-coverage"
    unresolved = json.loads((directory / "unresolved.json").read_text())
    assert len(unresolved) == 6
    for row in unresolved:
        assert row["status"] == "unresolved"
        assert row["unknown_statistic_series"]
        assert all(series["statistic_id"] is None for series in row["unknown_statistic_series"])
        assert row["bounded_checks"]["modern_start"]["rows"] > 0
        assert row["bounded_checks"]["modern_start"]["statistic_ids"] == ["None"]


def test_access_failure_cannot_confirm_missing(tmp_path, monkeypatch):
    row = {
        "status": "unresolved",
        "station_id": "test",
        "product_id": "discharge_daily_mean",
        "unknown_statistic_series": [],
        "national_evidence": "national.json",
    }
    (tmp_path / "national.json").write_text('{"status":"complete"}')
    monkeypatch.setattr(audit, "read_probe", lambda *args: {"status": "unresolved", "reason": "source access failure"})
    audit.finalize_rows(tmp_path, [row])
    assert row["status"] == "unresolved"
