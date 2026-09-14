"""Workbook certification : recorded source bodies × acquisition claims → verified accounting.

The public check verifies retained survey bodies and ledger structure. Only the explicit
--evidence-root check certifies all 180 baseline workbook classifications. Neither check
performs acquisition. Derived summaries and occupancy witnesses are never a source oracle.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import math
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

import polars as pl

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
PRODUCTS = {
    "discharge_reported": ("Q", "Q_1Y.xlsx", "Proticaj", "m³/s"),
    "stage_reported": ("H", "H_1Y.xlsx", "Vodostaj", "cm"),
    "water_temperature_reported": ("WT", "Tvode_1Y.xlsx", "Temperatura vode", "°C"),
}


class EvidenceError(ValueError):
    """An acquisition claim disagrees with its evidence."""


class WorkbookStatus(StrEnum):
    MEASUREMENTS = "measurements_present"
    BLANK = "timestamped_without_measurements"
    EMPTY = "no_data_rows"


@dataclass(frozen=True)
class WorkbookFacts:
    station: str
    station_name: str
    parameter: str
    unit: str
    data_rows: int
    numerical_rows: int
    first_timestamp: str | None
    last_timestamp: str | None

    @property
    def status(self) -> WorkbookStatus:
        if self.numerical_rows:
            return WorkbookStatus.MEASUREMENTS
        return WorkbookStatus.BLANK if self.data_rows else WorkbookStatus.EMPTY


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def read_workbook_facts(raw: bytes) -> WorkbookFacts:
    """Read finite numerical cells independently of the survey's workbook parser."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        strings = ["".join(node.itertext()) for node in ET.fromstring(archive.read("xl/sharedStrings.xml"))]

    def text(cell: ET.Element | None) -> str:
        if cell is None:
            return ""
        value = cell.find("m:v", NS)
        if value is None or value.text is None:
            return ""
        return strings[int(value.text)] if cell.get("t") == "s" else value.text

    header: dict[str, str] = {}
    timestamps: list[datetime] = []
    numerical = 0
    in_data = False
    for row in sheet.findall(".//m:sheetData/m:row", NS):
        cells = {"".join(filter(str.isalpha, cell.attrib["r"])): cell for cell in row}
        a, b = text(cells.get("A")), text(cells.get("B"))
        if a == "#Timestamp":
            require(b == "Value", "workbook has unexpected value column")
            in_data = True
            continue
        if not in_data:
            header[a] = b
            continue
        require(bool(a), "workbook data row has no timestamp")
        serial = float(a)
        require(math.isfinite(serial), "workbook timestamp is not finite")
        timestamps.append(datetime(1899, 12, 30) + timedelta(milliseconds=round(serial * 86400000)))
        if b:
            cell = cells["B"]
            require(cell.get("t") in (None, "n") and math.isfinite(float(b)), "measurement cell is not finite numeric")
            numerical += 1
    require(in_data, "workbook lacks timestamp header")
    require(float(header["#Rows"]) == len(timestamps), "workbook declared row count differs from source rows")
    require(header["#Timeseries Name"] == "81 Web Kontinuirani", "workbook timeseries differs")
    return WorkbookFacts(
        header["#Station Number"],
        header["#Station Name"],
        header["#Station Parameter Name"],
        header["#Unit Symbol"],
        len(timestamps),
        numerical,
        min(timestamps).isoformat() if timestamps else None,
        max(timestamps).isoformat() if timestamps else None,
    )


def checked_response(document: dict) -> bytes | None:
    response = document["response"]
    request = document["request"]
    require(request["method"] == "GET", "unexpected acquisition method")
    require(bool(request["url"]), "acquisition URL absent")
    require(
        not any(key in request["url"].lower() for key in ("token=", "password=", "apikey=", "api_key=")),
        "credential-like URL",
    )
    instant = datetime.fromisoformat(response["retrieved_at"].replace("Z", "+00:00"))
    require(instant.utcoffset() == timedelta(0), "acquisition instant must be UTC")
    require(bool(response["content_type"]), "response media type absent")
    digest = response["response_sha256"] if "response_sha256" in response else response["sha256"]
    require(len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), "invalid response digest")
    if "content_base64" not in response:
        require(response["byte_size"] > 0, "response size absent")
        return None
    raw = base64.b64decode(response["content_base64"], validate=True)
    require(hashlib.sha256(raw).hexdigest() == digest, "source response digest mismatch")
    if "byte_size" in response:
        require(len(raw) == response["byte_size"], "source response byte size mismatch")
    return raw


def verify_survey(rows: list[dict], documents: dict[str, dict], baseline: set[str]) -> dict:
    keys = [(row["station_no"], row["product_id"]) for row in rows]
    stations = {station for station, _ in keys}
    require(len(keys) == len(set(keys)), "duplicate survey pair")
    require(
        set(keys) == {(station, product) for station in stations for product in PRODUCTS}, "incomplete survey pairs"
    )
    require({row["station_no"] for row in rows if row["in_baseline"] == "True"} == baseline, "survey baseline differs")
    require(len({row["evidence_ref"] for row in rows}) == len(rows), "survey reuses pair evidence")
    checked = 0
    unattested = 0
    for row in rows:
        document = documents[row["evidence_ref"]]
        response = document["response"]
        code, workbook, parameter, unit = PRODUCTS[row["product_id"]]
        url = f"https://vodostaji.voda.ba/data/internet/stations/{row['site_no']}/{row['station_no']}/{code}/{workbook}"
        require(row["url"] == document["request"]["url"] == url, "survey route mismatch")
        require(
            document["station_no"] == row["station_no"] and document["product_id"] == row["product_id"],
            "survey identity mismatch",
        )
        require(
            response["retrieved_at"] == row["retrieved_at"] and response["response_sha256"] == row["response_sha256"],
            "survey acquisition mismatch",
        )
        require(str(response["status_code"]) == row["http_status"], "survey HTTP status mismatch")
        raw = checked_response(document)
        if response["status_code"] != 200:
            require(row["status"] == "access_failed" and raw is not None, "source failure must retain its body")
            continue
        if raw is None:
            require(row["status"] == "measurements_present", "non-positive survey result lacks source body")
            unattested += 1
            continue
        facts = read_workbook_facts(raw)
        require(
            (facts.station, facts.parameter, facts.unit) == (row["station_no"], parameter, unit),
            "source workbook identity or physics mismatch",
        )
        require(
            str(facts.status) == row["status"]
            and facts.numerical_rows == int(row["populated_measurements"])
            and facts.data_rows == int(row["data_rows"]),
            f"source workbook classification mismatch: {row['station_no']}/{row['product_id']}",
        )
        checked += 1
    return {"workbooks_checked_from_public_bodies": checked, "positive_survey_summaries_without_bodies": unattested}


def verify_horizon(rows: list[dict], documents: dict[str, dict]) -> None:
    """Bind each historical filename attempt to its own retained response."""
    require(len({row["evidence_ref"] for row in rows}) == len(rows), "reused horizon evidence")
    for row in rows:
        document = documents[row["evidence_ref"]]
        response = document["response"]
        require(
            document["station_no"] == row["station_no"]
            and document["product_code"] == row["product_code"]
            and document["request"]["url"] == row["url"]
            and str(response["status_code"]) == row["http_status"]
            and response["retrieved_at"] == row["retrieved_at"],
            "horizon acquisition mismatch",
        )
        raw = checked_response(document)
        if response["status_code"] != 200:
            require(raw is not None, "horizon refusal body absent")


def baseline_pair(selection: dict, document: dict, site: str) -> dict:
    raw = checked_response(document)
    if raw is None:
        raise EvidenceError("governing baseline response body is absent")
    require(document["response"]["status_code"] == 200, "governing baseline response is not HTTP200")
    station, product = selection["station_no"], selection["product_id"]
    code, workbook, parameter, unit = PRODUCTS[product]
    url = f"https://vodostaji.voda.ba/data/internet/stations/{site}/{station}/{code}/{workbook}"
    require(
        selection["site_no"] == site and selection["url"] == document["request"]["url"] == url,
        "baseline route/site mismatch",
    )
    require(document["request"]["parameters"] in (None, {}), "source-fixed workbook has unexpected request parameters")
    facts = read_workbook_facts(raw)
    require(
        (facts.station, facts.parameter, facts.unit) == (station, parameter, unit),
        "baseline source identity/physics mismatch",
    )
    return {
        "station_no": station,
        "site_no": site,
        "product_id": product,
        "source_code": code,
        "workbook": workbook,
        "method": "GET",
        "url": url,
        "parameters": document["request"]["parameters"],
        "response_file": selection["response_file"],
        "evidence_basis": selection["evidence_basis"],
        "retrieved_at": document["response"]["retrieved_at"],
        "http_status": document["response"]["status_code"],
        "media_type": document["response"]["content_type"],
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "byte_size": len(raw),
        "station_name": facts.station_name,
        "parameter": facts.parameter,
        "source_unit": facts.unit,
        "status": str(facts.status),
        "availability": "available" if facts.numerical_rows else "unknown",
        "data_rows": facts.data_rows,
        "numerical_rows": facts.numerical_rows,
        "blank_rows": facts.data_rows - facts.numerical_rows,
        "observed_window_start": facts.first_timestamp,
        "observed_window_end": facts.last_timestamp,
    }


def validate_ledger(ledger: dict, sites: dict[str, str], native_digest: str) -> None:
    require(
        ledger["schema_version"] == 1 and ledger["baseline_native_sha256"] == native_digest,
        "baseline ledger/native identity mismatch",
    )
    pairs = ledger["pairs"]
    keys = [(row["station_no"], row["product_id"]) for row in pairs]
    require(
        len(keys) == len(set(keys)) and set(keys) == {(station, product) for station in sites for product in PRODUCTS},
        "baseline ledger must account for each original station/product exactly once",
    )
    for row in pairs:
        require(
            all(type(row[field]) is int and row[field] >= 0 for field in ("data_rows", "numerical_rows", "blank_rows")),
            "ledger counts must be nonnegative integers",
        )
        require(
            row["http_status"] == 200 and row["method"] == "GET" and row["parameters"] in (None, {}),
            "ledger request/response contract mismatch",
        )
        require(
            row["byte_size"] > 0
            and len(row["response_sha256"]) == 64
            and all(c in "0123456789abcdef" for c in row["response_sha256"]),
            "ledger response identity invalid",
        )
        instant = datetime.fromisoformat(row["retrieved_at"].replace("Z", "+00:00"))
        require(instant.utcoffset() == timedelta(0), "ledger acquisition instant must be UTC")
        require(bool(row["media_type"]), "ledger media type absent")
        require(
            (row["observed_window_start"] is None) == (row["data_rows"] == 0)
            and (row["observed_window_end"] is None) == (row["data_rows"] == 0),
            "ledger observed window disagrees with row presence",
        )
        code, workbook, parameter, unit = PRODUCTS[row["product_id"]]
        require(row["site_no"] == sites[row["station_no"]], "ledger metadata site mismatch")
        require(
            row["url"]
            == f"https://vodostaji.voda.ba/data/internet/stations/{row['site_no']}/{row['station_no']}/{code}/{workbook}",
            "ledger URL mismatch",
        )
        require(
            (row["source_code"], row["workbook"], row["parameter"], row["source_unit"])
            == (code, workbook, parameter, unit),
            "ledger source coordinates mismatch",
        )
        require(
            row["availability"] == ("available" if row["numerical_rows"] else "unknown"),
            "ledger availability disagrees with accounting",
        )
        status = (
            WorkbookStatus.MEASUREMENTS
            if row["numerical_rows"]
            else WorkbookStatus.BLANK
            if row["data_rows"]
            else WorkbookStatus.EMPTY
        )
        require(
            row["status"] == status and row["data_rows"] == row["numerical_rows"] + row["blank_rows"],
            "ledger row accounting mismatch",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--baseline-native",
        type=Path,
        default=Path(__file__).resolve().parents[4]
        / "src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet",
    )
    parser.add_argument(
        "--evidence-root", type=Path, help="Controlled private Bosnia corpus; absence never triggers acquisition"
    )
    parser.add_argument("--certificate-out", type=Path, help="Derived accounting only; requires --evidence-root")
    args = parser.parse_args()
    try:
        require(
            args.certificate_out is None or args.evidence_root is not None,
            "certificate requires complete source-body verification",
        )
        native_bytes = args.baseline_native.read_bytes()
        native = pl.read_parquet(args.baseline_native)
        sites = dict(native.select("metadata_station_no", "metadata_site_no").iter_rows())
        require(len(sites) == native.height == 60, "expected original60 native identities")
        documents = {
            str(path.relative_to(args.research_root)): json.loads(path.read_text())
            for path in [
                *sorted((args.research_root / "recordings").glob("*.json")),
                *sorted((args.research_root / "evidence").rglob("*.json")),
            ]
        }
        for document in documents.values():
            checked_response(document)
        with (args.research_root / "inventory/station_product_evidence.csv").open() as handle:
            survey = verify_survey(list(csv.DictReader(handle)), documents, set(sites))
        with (args.research_root / "inventory/horizon_probe.csv").open() as handle:
            verify_horizon(list(csv.DictReader(handle)), documents)
        layer_bytes = checked_response(documents["recordings/layer_20.recording.json"])
        if layer_bytes is None:
            raise EvidenceError("recorded routing metadata body absent")
        layer = json.loads(layer_bytes)
        recorded_sites = {row["metadata_station_no"]: row["metadata_site_no"] for row in layer}
        require(
            len(layer) == len(recorded_sites) and recorded_sites == sites,
            "recorded metadata routing differs from native baseline",
        )
        ledger_path = args.research_root / "inventory/baseline_workbook_access.json"
        ledger = json.loads(ledger_path.read_text())
        validate_ledger(ledger, sites, hashlib.sha256(native_bytes).hexdigest())
        if args.evidence_root is None:
            print(
                json.dumps(
                    {
                        "check": "public-accounting",
                        **survey,
                        "baseline_pairs": len(ledger["pairs"]),
                        "private_baseline_bodies_checked": 0,
                    },
                    sort_keys=True,
                )
            )
            print("Private workbook classifications are NOT certified by this public-only check.")
            return
        manifest_bytes = (args.evidence_root / "FILE_HASHES.json").read_bytes()
        require(
            hashlib.sha256(manifest_bytes).hexdigest() == ledger["evidence_manifest_sha256"],
            "private evidence manifest identity mismatch",
        )
        for item in json.loads(manifest_bytes)["files"]:
            path = (args.evidence_root / item["path"]).resolve()
            require(path.is_relative_to(args.evidence_root.resolve()), "manifest path escapes evidence root")
            raw = path.read_bytes()
            require(
                len(raw) == item["byte_size"] and hashlib.sha256(raw).hexdigest() == item["sha256"],
                f"private file integrity mismatch: {item['path']}",
            )
        selection = json.loads((args.evidence_root / "baseline-source-selection.json").read_text())
        actual = []
        for selected in selection:
            path = (args.evidence_root / selected["response_file"]).resolve()
            require(path.is_relative_to(args.evidence_root.resolve()), "response path escapes evidence root")
            actual.append(baseline_pair(selected, json.loads(path.read_text()), sites[selected["station_no"]]))
        actual.sort(key=lambda row: (row["station_no"], row["product_id"]))
        require(actual == ledger["pairs"], "baseline source bodies disagree with published ledger")
        certificate = {
            "check": "complete-baseline-source-bodies",
            "baseline_native_sha256": ledger["baseline_native_sha256"],
            "ledger_sha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
            "evidence_manifest_sha256": ledger["evidence_manifest_sha256"],
            "baseline_stations": len(sites),
            "baseline_pairs": len(actual),
            "availability": dict(Counter(row["availability"] for row in actual)),
            "numerical_rows": sum(row["numerical_rows"] for row in actual),
            "blank_rows": sum(row["blank_rows"] for row in actual),
            "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "verified_at": datetime.now(UTC).isoformat(),
        }
        print(json.dumps(certificate, sort_keys=True))
        if args.certificate_out is not None:
            args.certificate_out.write_text(json.dumps(certificate, indent=2) + "\n")
    except (EvidenceError, OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
