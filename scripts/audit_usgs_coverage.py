"""Reproducible USGS catalogue coverage evidence acquisition (not provider retrieval)."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError  # noqa: TID251
from urllib.parse import parse_qs, urlparse  # noqa: TID251
from urllib.request import urlopen  # noqa: TID251 -- standalone evidence acquisition

import polars as pl

BASE = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/time-series-metadata/items"
CATALOGUE = Path("src/rivretrieve/_internal/providers/usgs_nwis/catalogue")
REVISION = "9c05cf933bd1ad04e2e77ae7733cd0caf757e487"


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")


def freeze(out):
    out.mkdir(parents=True, exist_ok=True)
    if (out / "baseline.json").exists():
        baseline = json.loads((out / "baseline.json").read_text())
        expected = baseline["artifacts"]["native.parquet"]["sha256"]
        if hashlib.sha256((CATALOGUE / "native.parquet").read_bytes()).hexdigest() != expected:
            raise ValueError("Frozen native baseline changed")
        if not (out / "baseline_stations.parquet").exists():
            pl.read_parquet(CATALOGUE / "native.parquet").select("agency_cd", "site_no").write_parquet(
                out / "baseline_stations.parquet"
            )
        return
    native = pl.read_parquet(CATALOGUE / "native.parquet")
    native.select("agency_cd", "site_no").write_parquet(out / "baseline_stations.parquet")
    products = pl.read_parquet(CATALOGUE / "station_products.parquet")
    artifacts = {
        p.name: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
        for p in sorted(CATALOGUE.iterdir())
        if p.is_file()
    }
    dump(
        out / "baseline.json",
        {
            "revision": REVISION,
            "artifacts": artifacts,
            "native_stations": native.height,
            "native_series_claims": native["ts_id"].list.len().sum(),
            "vintage": native["retrieved_at"].unique().to_list(),
            "station_products": products.height,
            "availability_counts": products.group_by("availability").len().to_dicts(),
            "source_acquisitions": pl.read_parquet(CATALOGUE / "provenance_acquisitions.parquet").to_dicts(),
        },
    )
    products.write_parquet(out / "baseline_station_products.parquet")
    fields = ["data_type_cd", "parm_cd", "stat_cd", "ts_id", "begin_date", "end_date", "loc_web_ds"]
    claims = (
        native.select("agency_cd", "site_no", *fields)
        .explode(fields)
        .filter(pl.col("parm_cd").is_in(["00060", "00065"]) & pl.col("data_type_cd").is_in(["dv", "uv"]))
    )
    claims.write_parquet(out / "baseline_claims.parquet")


def capture(url, out, name):
    path = out / (name + ".json.gz")
    receipt = out / (name + ".receipt.json")
    if receipt.exists():
        record = json.loads(receipt.read_text())
        if record["url"] != url:
            raise ValueError("Cached receipt request mismatch")
        raw = gzip.decompress(path.read_bytes()) if path.exists() else b""
        if hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise ValueError("Receipt hash mismatch")
        return record, raw
    record = {"url": url, "retrieved_at": datetime.now(UTC).isoformat()}
    raw = b""
    try:
        try:
            response = urlopen(url, timeout=90)
        except HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            record.update(status=response.status, final_url=response.url, headers=dict(response.headers))
    except Exception as exc:
        record["error"] = repr(exc)
    record.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), file=path.name)
    path.write_bytes(gzip.compress(raw, mtime=0))
    dump(receipt, record)
    print(name, record.get("status"), len(raw), flush=True)
    return record, raw


def acquire(out, max_pages):
    for parameter in ("00060", "00065"):
        url = f"{BASE}?f=json&parameter_code={parameter}&limit=10000"
        seen = set()
        page = 0
        count = 0
        status = "unresolved"
        reason = "page budget exhausted"
        while page < max_pages:
            if url in seen:
                reason = "pagination cycle"
                break
            query = parse_qs(urlparse(url).query)
            if (
                not url.startswith(BASE + "?")
                or query.get("parameter_code") != [parameter]
                or query.get("f") != ["json"]
                or set(query) - {"parameter_code", "f", "limit", "cursor"}
            ):
                reason = "unexpected pagination origin or collection"
                break
            seen.add(url)
            receipt, raw = capture(url, out, f"metadata-{parameter}-{page:04d}")
            if receipt.get("status") != 200:
                reason = "source access failure"
                break
            try:
                data = json.loads(raw)
                features = data["features"]
                if not isinstance(features, list) or data["numberReturned"] != len(features):
                    raise ValueError("Invalid feature count")
                for feature in features:
                    if feature["properties"]["parameter_code"] != parameter:
                        raise ValueError("Contradictory parameter")
                links = [link["href"] for link in data["links"] if link["rel"] == "next"]
                if len(links) > 1:
                    raise ValueError("Multiple next links")
            except (ValueError, KeyError, AssertionError, TypeError) as exc:
                reason = f"invalid page: {exc!r}"
                break
            page += 1
            count += len(features)
            if not links:
                status, reason = "complete", "publisher next-link chain terminated"
                break
            url = links[0]
        dump(
            out / f"metadata-{parameter}-completion.json",
            {
                "parameter_code": parameter,
                "status": status,
                "reason": reason,
                "pages": page,
                "features": count,
                "last_url": url,
                "sorting": False,
                "active_filter": None,
            },
        )


PRODUCTS = {
    "discharge_daily_mean": ("00060", "Daily", "00003"),
    "stage_daily_mean": ("00065", "Daily", "00003"),
    "stage_daily_max": ("00065", "Daily", "00001"),
    "stage_daily_min": ("00065", "Daily", "00002"),
    "discharge_instantaneous": ("00060", "Points", "00011"),
    "stage_instantaneous": ("00065", "Points", "00011"),
}


def compare(out):
    """Account for every baseline row without equating series across namespaces."""
    from collections import Counter, defaultdict

    metadata = defaultdict(list)
    station_ids = set()
    complete = {}
    duplicate_ids = []
    observed_ids = set()
    for parameter in ("00060", "00065"):
        completion = json.loads((out / f"metadata-{parameter}-completion.json").read_text())
        complete[parameter] = completion["status"] == "complete"
        expected_url = f"{BASE}?f=json&parameter_code={parameter}&limit=10000"
        feature_count = 0
        for page in range(completion["pages"]):
            name = f"metadata-{parameter}-{page:04d}"
            receipt = json.loads((out / (name + ".receipt.json")).read_text())
            raw = gzip.decompress((out / (name + ".json.gz")).read_bytes())
            if hashlib.sha256(raw).hexdigest() != receipt["sha256"]:
                raise ValueError("Metadata hash mismatch")
            if receipt["url"] != expected_url or receipt.get("status") != 200:
                raise ValueError("Receipt chain mismatch")
            data = json.loads(raw)
            features = data["features"]
            if data["numberReturned"] != len(features):
                raise ValueError("Feature count mismatch")
            feature_count += len(features)
            next_links = [link["href"] for link in data["links"] if link["rel"] == "next"]
            if len(next_links) > 1:
                raise ValueError("Ambiguous pagination")
            expected_url = next_links[0] if next_links else None
            for feature in features:
                props = feature["properties"]
                if props["parameter_code"] != parameter or feature["id"] != props["id"]:
                    raise ValueError("Contradictory metadata identity")
                identity = props["id"]
                if identity in observed_ids:
                    duplicate_ids.append(identity)
                observed_ids.add(identity)
                location = props["monitoring_location_id"]
                station_ids.add(location)
                key = (location, props["parameter_code"], props["computation_period_identifier"], props["statistic_id"])
                metadata[key].append(
                    {
                        "id": identity,
                        "begin": props["begin"],
                        "end": props["end"],
                        "statistic_id": props["statistic_id"],
                        "computation_identifier": props["computation_identifier"],
                        "unit_of_measure": props["unit_of_measure"],
                        "evidence": name + ".receipt.json",
                    }
                )
        if feature_count != completion["features"] or (complete[parameter] and expected_url is not None):
            raise ValueError("False metadata completeness")
    if duplicate_ids:
        complete = dict.fromkeys(complete, False)
    claims = defaultdict(list)
    for row in pl.read_parquet(out / "baseline_claims.parquet").to_dicts():
        claims[(row["site_no"], row["parm_cd"], row["data_type_cd"], row["stat_cd"])].append(
            {k: row[k] for k in ("ts_id", "begin_date", "end_date", "loc_web_ds")}
        )
    locations = {
        row["site_no"]: row["agency_cd"] + "-" + row["site_no"]
        for row in pl.read_parquet(out / "baseline_stations.parquet").to_dicts()
    }
    rows = []
    for row in pl.read_parquet(out / "baseline_station_products.parquet").to_dicts():
        parameter, period, statistic = PRODUCTS[row["product_id"]]
        location = locations[row["station_id"]]
        matches = metadata.get((location, parameter, period, statistic), [])
        alternatives = metadata.get((location, parameter, period, None), [])
        supported = row["availability"] != "unavailable"
        if not supported:
            status, reason = "not_in_baseline", "baseline publishes no matching supported series"
        elif matches:
            status, reason = (
                "matched",
                "exact agency/site, parameter, computation period and statistic metadata match; not historical parity",
            )
        elif not complete[parameter]:
            status, reason = "unresolved", "incomplete or duplicate-bearing national metadata acquisition"
        else:
            status, reason = "unresolved", "candidate metadata gap; identity and bounded modern/legacy checks required"
        rows.append(
            {
                "station_id": row["station_id"],
                "monitoring_location_id": location,
                "source_agency": location.split("-", 1)[0],
                "product_id": row["product_id"],
                "parameter_code": parameter,
                "computation_period_identifier": period,
                "statistic_id": statistic,
                "baseline_availability": row["availability"],
                "status": status,
                "reason": reason,
                "station_has_supported_parameter_metadata": location in station_ids,
                "baseline_period_start": str(row["published_record_start_date"])
                if row["published_record_start_date"]
                else None,
                "baseline_period_end": str(row["published_record_end_date"])
                if row["published_record_end_date"]
                else None,
                "legacy_claims": claims.get(
                    (
                        row["station_id"],
                        parameter,
                        "dv" if period == "Daily" else "uv",
                        statistic if period == "Daily" else "",
                    ),
                    [],
                ),
                "modern_series": matches,
                "unknown_statistic_series": alternatives,
                "national_evidence": f"metadata-{parameter}-completion.json",
            }
        )
    finalize_rows(out, rows)
    with gzip.GzipFile(str(out / "comparison.jsonl.gz"), "wb", mtime=0) as stream:
        for row in rows:
            stream.write((json.dumps(row) + "\n").encode())
    gaps = [row for row in rows if row["status"] == "unresolved"]
    dump(out / "unresolved.json", gaps)
    dump(out / "missing.json", [row for row in rows if row["status"] == "confirmed_missing"])
    stations = []
    for station in sorted({row["station_id"] for row in rows}):
        found = locations[station] in station_ids
        evidence = out / "probes" / f"location-{station}.json.gz"
        if not found and evidence.exists():
            source = json.loads(gzip.decompress(evidence.read_bytes()))
            found = source.get("id") == locations[station]
        stations.append(
            {
                "station_id": station,
                "status": "matched" if found else "unresolved",
                "reason": "publisher station identity present (metadata or monitoring-location item)"
                if found
                else "no supported-parameter metadata; monitoring-location identity requires separate check",
            }
        )
    dump(out / "stations.json", stations)
    summary = {
        "baseline_stations": len(stations),
        "baseline_station_products": len(rows),
        "station_counts": dict(Counter(row["status"] for row in stations)),
        "product_counts": dict(Counter(row["status"] for row in rows)),
        "per_product": {
            product: dict(Counter(row["status"] for row in rows if row["product_id"] == product))
            for product in PRODUCTS
        },
        "metadata_unique_ids": len(observed_ids),
        "duplicate_ids": duplicate_ids,
        "complete_parameters": complete,
        "confirmed_missing": sum(row["status"] == "confirmed_missing" for row in rows),
        "historical_parity": "not established by metadata or finite samples",
    }
    dump(out / "summary.json", summary)
    print(json.dumps(summary, indent=2))


def read_probe(out, name):
    directory = out / "probes"
    receipt_path = directory / (name + ".receipt.json")
    if not receipt_path.exists():
        return None
    receipt = json.loads(receipt_path.read_text())
    raw = gzip.decompress((directory / receipt["file"]).read_bytes())
    if hashlib.sha256(raw).hexdigest() != receipt["sha256"]:
        raise ValueError("Probe hash mismatch")
    if receipt.get("status") != 200:
        return {"status": "unresolved", "receipt": "probes/" + receipt_path.name, "reason": "source access failure"}
    data = json.loads(raw)
    if name.startswith("modern-") or name.startswith("metadata-"):
        next_links = [link for link in data["links"] if link["rel"] == "next"]
        if data["numberReturned"] != len(data["features"]):
            raise ValueError("Probe numberReturned mismatch")
        return {
            "status": "unresolved" if next_links else "complete",
            "rows": len(data["features"]),
            "receipt": "probes/" + receipt_path.name,
            "request": receipt["url"],
            "statistic_ids": sorted({str(feature["properties"].get("statistic_id")) for feature in data["features"]}),
        }
    if name.startswith("legacy-"):
        series = data["value"]["timeSeries"]
        values = [value for ts in series for block in ts["values"] for value in block["value"]]
        return {
            "status": "complete",
            "rows": len(values),
            "receipt": "probes/" + receipt_path.name,
            "request": receipt["url"],
            "agencies": sorted({code["agencyCode"] for ts in series for code in ts["sourceInfo"]["siteCode"]}),
        }
    return None


def finalize_rows(out, rows):
    for row in rows:
        if row["status"] != "unresolved":
            continue
        station, product = row["station_id"], row["product_id"]
        checks = {}
        for side in ("start", "end"):
            for source in ("modern", "legacy"):
                check = read_probe(out, f"{source}-{station}-{product}-{side}")
                if check:
                    checks[f"{source}_{side}"] = check
        row["bounded_checks"] = checks
        if row["unknown_statistic_series"]:
            row["reason"] = (
                "Points metadata and observations preserve null statistic_id / Unknown computation; precise instantaneous match unresolved, not missing observations"
            )
            continue
        station_metadata = read_probe(out, f"metadata-{station}")
        if (
            station_metadata
            and station_metadata["status"] == "complete"
            and len(checks) == 4
            and all(check["status"] == "complete" and check["rows"] == 0 for check in checks.values())
            and json.loads((out / row["national_evidence"]).read_text())["status"] == "complete"
        ):
            row["status"] = "confirmed_missing"
            row["reason"] = (
                "supported product absent from complete modern metadata; both finite observation windows empty on modern and legacy; historical unavailability NOT established"
            )
            row["station_metadata_evidence"] = station_metadata


def probe_gaps(out):
    """Two seven-day windows per candidate, plus station metadata and identity."""
    from datetime import date, timedelta
    from urllib.parse import urlencode  # noqa: TID251

    gaps = json.loads((out / "unresolved.json").read_text())
    probe_dir = out / "probes"
    probe_dir.mkdir(exist_ok=True)
    locations = {row["station_id"]: row["monitoring_location_id"] for row in gaps}
    for station in sorted(locations):
        location = locations[station]
        capture(
            f"{BASE}?" + urlencode({"f": "json", "monitoring_location_id": location, "limit": 10000}),
            probe_dir,
            f"metadata-{station}",
        )
        capture(
            "https://api.waterdata.usgs.gov/ogcapi/v1/collections/monitoring-locations/items/" + location + "?f=json",
            probe_dir,
            f"location-{station}",
        )
    for row in gaps:
        daily = row["computation_period_identifier"] == "Daily"
        station, product = row["station_id"], row["product_id"]
        for side in ("start", "end"):
            bound = row["baseline_period_" + side]
            if bound is None:
                continue
            start = date.fromisoformat(bound)
            if side == "end":
                start -= timedelta(days=6)
            end = start + timedelta(days=6)
            window = f"{start}/{end}" if daily else f"{start}T00:00:00Z/{end}T23:59:59Z"
            modern = {
                "f": "json",
                "monitoring_location_id": row["monitoring_location_id"],
                "parameter_code": row["parameter_code"],
                "datetime": window,
                "limit": 10000,
            }
            legacy = {
                "format": "json",
                "sites": station,
                "parameterCd": row["parameter_code"],
                "startDT": str(start),
                "endDT": str(end),
                "siteStatus": "all",
            }
            if daily:
                modern["statistic_id"] = row["statistic_id"]
                legacy["statCd"] = row["statistic_id"]
            collection = "daily" if daily else "continuous"
            endpoint = "dv" if daily else "iv"
            capture(
                f"https://api.waterdata.usgs.gov/ogcapi/v1/collections/{collection}/items?" + urlencode(modern),
                probe_dir,
                f"modern-{station}-{product}-{side}",
            )
            capture(
                f"https://waterservices.usgs.gov/nwis/{endpoint}/?" + urlencode(legacy),
                probe_dir,
                f"legacy-{station}-{product}-{side}",
            )


def probe_agencies(out):
    """Verify the two non-USGS source agencies; retain earlier wrong-prefix controls."""
    from datetime import timedelta
    from urllib.parse import urlencode  # noqa: TID251

    probe_dir = out / "probes"
    baseline = pl.read_parquet(out / "baseline_station_products.parquet")
    stations = pl.read_parquet(out / "baseline_stations.parquet").filter(pl.col("agency_cd") != "USGS")
    for station in stations.to_dicts():
        location = station["agency_cd"] + "-" + station["site_no"]
        capture(
            "https://api.waterdata.usgs.gov/ogcapi/v1/collections/monitoring-locations/items/" + location + "?f=json",
            probe_dir,
            f"location-{location}",
        )
        capture(
            f"{BASE}?" + urlencode({"f": "json", "monitoring_location_id": location, "limit": 10000}),
            probe_dir,
            f"metadata-{location}",
        )
        for row in baseline.filter(
            (pl.col("station_id") == station["site_no"]) & (pl.col("availability") == "available")
        ).to_dicts():
            parameter, period, statistic = PRODUCTS[row["product_id"]]
            daily = period == "Daily"
            for side in ("start", "end"):
                start = row["published_record_" + side + "_date"]
                if not start:
                    continue
                if side == "end":
                    start -= timedelta(days=6)
                end = start + timedelta(days=6)
                window = f"{start}/{end}" if daily else f"{start}T00:00:00Z/{end}T23:59:59Z"
                params = {
                    "f": "json",
                    "monitoring_location_id": location,
                    "parameter_code": parameter,
                    "datetime": window,
                    "limit": 10000,
                }
                if daily:
                    params["statistic_id"] = statistic
                collection = "daily" if daily else "continuous"
                capture(
                    f"https://api.waterdata.usgs.gov/ogcapi/v1/collections/{collection}/items?" + urlencode(params),
                    probe_dir,
                    f"modern-{location}-{row['product_id']}-{side}",
                )


def report(out):
    summary = json.loads((out / "summary.json").read_text())
    baseline = json.loads((out / "baseline.json").read_text())
    if summary["product_counts"] != {
        "matched": 57950,
        "not_in_baseline": 99587,
        "unresolved": 6,
        "confirmed_missing": 5,
    }:
        (out / "REPORT.md").write_text(
            "# Coverage acquisition not yet reviewed\n\nSee summary.json for current accounting. The dated narrative is not applicable to these results.\n"
        )
        return
    receipts = []
    for path in sorted(out.rglob("*.receipt.json")):
        receipt = json.loads(path.read_text())
        receipt["receipt"] = str(path.relative_to(out))
        raw = gzip.decompress((path.parent / receipt["file"]).read_bytes())
        if hashlib.sha256(raw).hexdigest() != receipt["sha256"]:
            raise ValueError("Manifest hash mismatch")
        receipts.append(receipt)
    dump(out / "requests.json", receipts)
    missing = json.loads((out / "missing.json").read_text())
    unresolved = json.loads((out / "unresolved.json").read_text())
    lines = [
        "# USGS modern catalogue coverage audit",
        "",
        "Related: #331. Evidence acquired 2026-09-22. This is an audit, not migration acceptance.",
        "",
        "## Result",
        "",
        f"All {summary['baseline_stations']:,} baseline stations have publisher identity evidence. None is confirmed entirely missing.",
        "Of 57,961 supported station/product combinations, **57,950 match**, **5 are missing from modern metadata**, and **6 remain unresolved for a precise instantaneous-statistic match**.",
        "The complete 157,548-row denominator also includes 99,587 baseline-unavailable combinations; these are not coverage gaps.",
        "",
        "Missing means absent from the completed metadata acquisition, not proof of historical observation unavailability. No confirmed historical observation loss remains in the valid bounded probes. Neither matched metadata nor finite samples prove historical parity.",
        "",
        "## Frozen baseline",
        "",
        f"Revision: `{baseline['revision']}`. Native vintage: `2026-08-02T01:14:11Z`.",
        "Scope: original 50 states plus DC; Site Service filters `siteType=ST`, `hasDataTypeCd=dv`, `parameterCd=00060,00065`. No scope expansion or active-only filtering.",
        f"Native table: 26,258 stations, {baseline['native_series_claims']:,} series claims. SHA256 `{baseline['artifacts']['native.parquet']['sha256']}`.",
        "`baseline.json` freezes every native/packaged artifact hash, bytes, source acquisition coordinates and availability counts. `baseline_stations.parquet`, `baseline_station_products.parquet` and `baseline_claims.parquet` preserve station agency, all product rows, and relevant source period/ts_id claims. Native numeric ts_id is never mapped to a modern series ID.",
        "",
        "## Acquisition and completeness",
        "",
        f"Actual request count: **{len(receipts)}** ({sum('/probes/' not in '/' + r['receipt'] for r in receipts)} national pages; {sum(r['receipt'].startswith('probes/') for r in receipts)} bounded investigation requests). Sequential requests, limit 10,000, no sorting, no API key, no active/discontinued exclusion.",
        "National metadata has 129,710 distinct IDs across 8 discharge and 6 stage pages. Each cursor chain terminated with no next link; no duplicate IDs occurred. `metadata-*-completion.json` records counts and termination. The service does not give a transactional national snapshot or an independent numberMatched total; acquisitions span their recorded UTC instants.",
        "All national requests succeeded. One deliberately retained wrong-prefix monitoring-location request returned NotFound; that is not an access failure or evidence that the correct station is absent. No rate-limit failure occurred.",
        "`requests.json` indexes exact request/final URLs, UTC acquisition times, status, headers, raw SHA256, byte counts and receipt paths. `.json.gz` files losslessly retain exact response bodies. Each body hash covers decompressed bytes. `comparison.jsonl.gz` accounts for every baseline product row and links source claims, modern IDs, evidence and reasons. `stations.json` accounts for every station. `missing.json` and `unresolved.json` enumerate all exceptions.",
        "",
        "## Every missing or unresolved product",
        "",
        "Counts below are first/last seven-day source-coordinate windows, not time-aligned parity comparisons. Exact date bounds and URLs are in each exception's `bounded_checks`; legacy requests use source-calendar dates, modern continuous requests use explicit UTC bounds. Different counts alone are not a discrepancy.",
        "",
        "| Station | Product | Classification | Modern rows first/last | Legacy rows first/last |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for row in sorted(missing + unresolved, key=lambda r: (r["station_id"], r["product_id"])):
        checks = row["bounded_checks"]

        def counts(source, checks=checks):
            return "/".join(
                str(checks.get(source + "_" + side, {}).get("rows", "unresolved")) for side in ("start", "end")
            )

        lines.append(
            f"| {row['station_id']} | {row['product_id']} | {row['status']} | {counts('modern')} | {counts('legacy')} |"
        )
    lines.extend(
        [
            "",
            "The five metadata gaps have successful empty modern AND legacy responses in both checked windows. This does not prove that legacy has no relevant observations elsewhere in its claimed record. One station, 09385701, has no 00060/00065 metadata but its monitoring-location item exists; the other four missing products are at stations with other matching products.",
            "",
            "The six unresolved products publish `computation_period_identifier=Points`, `computation_identifier=Unknown`, and null `statistic_id`. Every observed modern row in their probes also has null `statistic_id`. Numerical continuous data exists, but the audit does not silently assign `00011` or claim a precise instantaneous match. Original descriptions and unknowns remain in the receipts.",
            "",
            "## Source agency correction and invalid controls",
            "",
            "All 26,258 identities were recomputed from native `agency_cd` plus `site_no`: 26,256 USGS, one USFS (09489082), one CA574 (09527500). Legacy sourceInfo.siteCode.agencyCode and modern monitoring-location agency_code independently confirm the two non-USGS identities. This is published identity, not a heuristic rename or legacy-method alias.",
            "",
            "Initial investigator queries incorrectly used USGS-09489082 and USGS-09527500. Those metadata/location/modern probe files remain as **invalid-coordinate controls**, excluded from gap and discrepancy conclusions. Correct-prefix files contain `USFS-09489082` or `CA574-09527500` in their filenames. Both stations and all three formerly suspected products match national metadata and have modern observations in both corrected finite windows. Preliminary 14-candidate/2-station conclusions are superseded by this full recomputation. `probes/location-number-09489082` records the publisher's USFS identifier.",
            "",
            "## Reproduce offline",
            "",
            "```sh",
            "uv run python scripts/audit_usgs_coverage.py --compare-only",
            "uv run pytest -q tests/test_usgs_coverage_audit.py",
            "```",
            "",
            "Existing receipts are reused and hash checked. Online acquisition in a new output directory: `uv run python scripts/audit_usgs_coverage.py --output PATH --max-pages 40`. Bounded checks: `--probe-gaps` and `--probe-agencies`. Do not overwrite retained evidence to refresh a vintage; use a new directory. Authored test controls are explicitly synthetic, not publisher recordings.",
            "",
            "## Decision and limits",
            "",
            "No production catalogue was replaced. Migration acceptance remains blocked pending owner treatment of the five metadata gaps and six unresolved precise-product matches. A fallback is not implemented or authorized. A future legacy fallback needs its own issue and an explicit decision, and must account for announced WaterServices retirement on 2027-02-22 (delays from 2026-11-16): https://waterdata.usgs.gov/blog/wdfn-waterservices-degradation/.",
            "",
            "No issue is closed by this report. Independent review is required before relying on these conclusions.",
            "",
        ]
    )
    (out / "REPORT.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--output", type=Path, default=Path("research/usgs-modern-coverage"))
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--compare-only", action="store_true")
    parser.add_argument("--probe-gaps", action="store_true")
    parser.add_argument("--probe-agencies", action="store_true")
    args = parser.parse_args()
    if args.probe_agencies:
        probe_agencies(args.output)
        return
    if args.probe_gaps:
        probe_gaps(args.output)
        return
    if not args.compare_only:
        freeze(args.output)
        acquire(args.output, args.max_pages)
    compare(args.output)
    report(args.output)


if __name__ == "__main__":
    main()
