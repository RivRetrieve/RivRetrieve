"""verify : NativeBaseline × GoverningLedger × Optional[RetainedEvidence] → Accounting.

Read-only, offline catalogue evidence verification. Public mode checks derived-ledger consistency,
not private response bytes. --evidence-root is mandatory for body-backed acceptance.
No availability conclusion establishes permanent absence or measurement authorship.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import lzma
import math
import tarfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qsl, urlsplit  # noqa: TID251 -- offline parsing only

import pandas as pd

ROUTES = {
    "discharge_daily_mean": ("obs_elab", "grandeur_hydro_elab", "QmnJ"),
    "discharge_daily_max": ("obs_elab", "grandeur_hydro_elab", "QIXnJ"),
    "stage_daily_max": ("obs_elab", "grandeur_hydro_elab", "HIXnJ"),
    "stage_instantaneous": ("observations_tr", "grandeur_hydro", "H"),
    "discharge_instantaneous": ("observations_tr", "grandeur_hydro", "Q"),
    "water_temperature_reported": ("chronique", None, None),
}
WINDOWS = {("01/06/2026", "08/06/2026"), ("01/06/2023", "08/06/2023")}
STATUSES = {
    "available",
    "empty_no_data_published",
    "empty_in_both_history_windows",
    "history_check_failed",
    "recent_window_empty_history_unchecked",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


@dataclass(frozen=True)
class SourceResult:
    kind: str
    count: int | None
    numeric: int
    window: tuple[str, str] | None


def check_request(station, product, url):
    require(product in ROUTES, "unknown product")
    parsed = urlsplit(url)
    params = parse_qsl(parsed.query, keep_blank_values=True)
    query = dict(params)
    require(len(params) == len(query), "duplicate request parameter")
    require(parsed.scheme == "https" and not parsed.fragment, "invalid source URL")
    route, field, metric = ROUTES[product]
    if parsed.netloc == "hydro.eaufrance.fr":
        require(product in {"stage_instantaneous", "discharge_instantaneous"}, "history product")
        require(parsed.path == f"/stationhydro/ajax/{station}/series", "history station route")
        require(query["hydro_series[simpleAndInterpolatedAndHourlyVariable]"] == metric, "history metric")
        require(query["hydro_series[statusData]"] == "raw", "history status filter")
        require(
            query["hydro_series[variableType]"] == "simple_and_interpolated_and_hourly_variable",
            "history variable type",
        )
        window = query["hydro_series[startAt]"], query["hydro_series[endAt]"]
        require(
            datetime.strptime(window[0], "%d/%m/%Y") <= datetime.strptime(window[1], "%d/%m/%Y"),
            "reversed history window",
        )
        return "history", metric, window
    require(parsed.netloc == "hubeau.eaufrance.fr", "count host")
    temperature = product == "water_temperature_reported"
    expected = "/api/v1/temperature/chronique" if temperature else f"/api/v2/hydrometrie/{route}"
    require(parsed.path == expected, "count product route")
    require(query["code_station" if temperature else "code_entite"] == station, "count station filter")
    if field:
        require(query[field] == metric, "count product filter")
    require(query["size"] == "1" and query["fields"] == "code_station", "count projection")
    require(not any(key.startswith("date") for key in query), "count date filter")
    allowed = {"code_station" if temperature else "code_entite", "size", "fields"}
    if field:
        allowed.add(field)
    require(set(query) == allowed, "unexpected count filter")
    return "count", metric, None


def check_source(station, product, url, status, body):
    """Read actual counts and series envelopes, including empty envelopes."""
    kind, metric, window = check_request(station, product, url)
    if kind == "count":
        require(status in (200, 206), "failed publisher count")
        document = json.loads(body)
        count = document["count"]
        require(type(count) is int and count >= 0, "invalid publisher count")
        rows = document["data"]
        require(isinstance(rows, list) and len(rows) == (1 if count else 0), "count projection rows")
        require({row["code_station"] for row in rows} == ({station} if count else set()), "returned count station")
        return SourceResult(kind, count, 0, None)
    if status != 200:
        require(400 <= status <= 599 and len(body) > 0, "invalid retained failure")
        return SourceResult(kind, None, 0, window)
    document = json.loads(body)
    series = document["series"]
    require(series["code"] == station, "series station")
    require(series["metric"] == metric, "series metric")
    require(series["unit"] == ("l" if metric == "Q" else "mm"), "series physical unit")
    require(series["statuses"] == "raw" and document["timezone"] == "UTC", "series status or zone")
    start, end = [datetime.strptime(value, "%d/%m/%Y").date() for value in window]
    bounds = document["range"]
    require(len(bounds) == 2 and all(value.endswith("Z") for value in bounds), "series range zone")
    require([datetime.fromisoformat(value).date() for value in bounds] == [start, end], "series request range")
    rows = series["data"]
    require(isinstance(rows, list), "series data")
    seen = set()
    numeric = 0
    for row in rows:
        timestamp, value = row["t"], row["v"]
        require(timestamp.endswith("Z") and start <= datetime.fromisoformat(timestamp).date() <= end, "reading range")
        require(timestamp not in seen, "duplicate reading")
        seen.add(timestamp)
        require(value is None or (type(value) in (int, float) and math.isfinite(value)), "nonnumeric reading")
        numeric += value is not None
    return SourceResult(kind, len(rows), numeric, window)


def check_material(material, body):
    require(set(material) == {"filename", "byte_count", "sha256"}, "MaterialIdentity shape")
    require(len(body) == material["byte_count"], "body byte count")
    require(hashlib.sha256(body).hexdigest() == material["sha256"], "body SHA-256")


def classify(product, results):
    primary, *history = results
    require(primary.kind == "count" and all(r.kind == "history" for r in history), "acquisition roles")
    if primary.count:
        require(not history, "history attached to positive publisher count")
        return "available", "publisher_count", primary.count
    if not history:
        status = (
            "recent_window_empty_history_unchecked" if product.endswith("_instantaneous") else "empty_no_data_published"
        )
        return status, "publisher_count", 0
    positives = [r for r in history if r.numeric > 0]
    if positives:
        require(len(history) == 1, "positive witness scope")
        require(
            positives[0].window[0] == positives[0].window[1], "historical witness must retain actual one-day request"
        )
        return "available", "historical_positive_witness", positives[0].count
    require({r.window for r in history} == WINDOWS, "historical two-window scope")
    require(all(r.count in (None, 0) for r in history), "null-only rows cannot certify empty windows")
    if all(r.count == 0 for r in history):
        require(len(history) == 2, "duplicate empty windows")
        return "empty_in_both_history_windows", "two_exact_windows_empty", 0
    basis = (
        "preserved_history_failure"
        if all(r.count is None for r in history)
        else "replacement_window_failure_prior_empty_claim_unverified"
    )
    return "history_check_failed", basis, 0


def accounting(pairs):
    statuses = Counter(row["status"] for row in pairs)
    available = statuses["available"]
    return {
        "stations": len({r["code_station"] for r in pairs}),
        "pairs": len(pairs),
        "available": available,
        "unknown": len(pairs) - available,
        "by_status": dict(statuses),
    }


def verify_public(native, ledger):
    require(ledger["schema_version"] == 1, "ledger revision")
    require(not native["code_station"].duplicated().any(), "duplicate baseline station")
    expected = set()
    for row in native[["code_station", "source_endpoint"]].itertuples(index=False):
        require(row.source_endpoint in {"temperature/station", "hydrometrie/referentiel/stations"}, "native population")
        products = (
            {"water_temperature_reported"}
            if row.source_endpoint == "temperature/station"
            else set(ROUTES) - {"water_temperature_reported"}
        )
        expected.update((str(row.code_station), product) for product in products)
    pairs = ledger["pairs"]
    keys = [(r["code_station"], r["product_id"]) for r in pairs]
    require(len(keys) == len(set(keys)) and set(keys) == expected, "baseline pair coverage")
    for row in pairs:
        require(row["status"] in STATUSES, "unknown research status")
        require(
            row["availability"] == ("available" if row["status"] == "available" else "unknown"),
            "availability is not exclusion",
        )
        require(
            type(row["published_count_or_new_witness_points"]) is int
            and row["published_count_or_new_witness_points"] >= 0,
            "invalid ledger count",
        )
        acquisitions = row["acquisitions"]
        require(acquisitions and acquisitions[0]["role"] == "publisher_count", "missing primary acquisition")
        require(acquisitions[0]["http_status"] in (200, 206), "primary status")
        require(all(a["role"] == "historical_check" for a in acquisitions[1:]), "history role")
        for acquisition in acquisitions:
            require(
                acquisition["method"] == "http_request" and len(acquisition["requested_from"]) == 1, "request identity"
            )
            require(
                datetime.fromisoformat(acquisition["retrieved_at_start"]).utcoffset() is not None,
                "acquisition date zone",
            )
            require(type(acquisition["http_status"]) is int, "HTTP status type")
            kind, _, _ = check_request(row["code_station"], row["product_id"], acquisition["requested_from"][0])
            require(kind == ("count" if acquisition["role"] == "publisher_count" else "history"), "role route")
            reference = acquisition["reference"]
            for location in (reference, acquisition["material"]["filename"]):
                for part in location.split("!"):
                    path = PurePosixPath(part)
                    require(not path.is_absolute() and ".." not in path.parts, "nonrelative evidence reference")
            if "!" in reference:
                archive, member = reference.split("!", 1)
                require(archive.endswith(".tar.xz"), "archive reference")
                require(member == f"bodies/{acquisition['receipt_id']}.body", "public receipt member binding")
                require(acquisition["material"]["filename"] == reference, "public material member binding")
            else:
                require(reference.endswith(".receipt.json"), "sidecar reference")
                require(
                    acquisition["material"]["filename"] == reference.removesuffix(".receipt.json") + ".body",
                    "public sidecar body binding",
                )
            material = acquisition["material"]
            require(set(material) == {"filename", "byte_count", "sha256"}, "MaterialIdentity shape")
            require(type(material["byte_count"]) is int and material["byte_count"] > 0, "material size")
            require(
                len(material["sha256"]) == 64 and all(c in "0123456789abcdef" for c in material["sha256"]),
                "material digest",
            )
        # Consistency only: counts here remain assertions until private body replay.
        primary_count = row["published_count_or_new_witness_points"] if row["basis"] == "publisher_count" else 0
        results = [SourceResult("count", primary_count, 0, None)]
        for acquisition in acquisitions[1:]:
            _, _, window = check_request(row["code_station"], row["product_id"], acquisition["requested_from"][0])
            positive = row["basis"] == "historical_positive_witness"
            count = row["published_count_or_new_witness_points"] if positive else 0
            results.append(
                SourceResult(
                    "history", count if acquisition["http_status"] == 200 else None, count if positive else 0, window
                )
            )
        require(
            classify(row["product_id"], results)
            == (row["status"], row["basis"], row["published_count_or_new_witness_points"]),
            "ledger classification consistency",
        )
    summary = accounting(pairs)
    require(summary == ledger["summary"], "ledger summary mismatch")
    return summary


def safe_path(root, reference):
    path = (root / reference).resolve()
    require(path.is_relative_to(root), "evidence reference escapes root")
    return path


def archive_bytes(archive: tarfile.TarFile, member: str | tarfile.TarInfo) -> bytes:
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError(f"not a regular archive member: {member}")
    return stream.read()


def read_bundle(path):
    with tarfile.open(path) as archive:
        receipts = list(csv.DictReader(io.StringIO(archive_bytes(archive, "receipts.csv").decode())))
        require(len({r["request_id"] for r in receipts}) == len(receipts), "duplicate receipt id")
        bodies = {
            member.name: archive_bytes(archive, member)
            for member in archive
            if member.isfile() and member.name.startswith("bodies/")
        }
    for receipt in receipts:
        if "count" in receipt:
            check_request(receipt["code_station"], receipt["product_id"], receipt["request_url"])
            require(receipt["entity_code"] == receipt["code_station"], "count receipt station identity")
            if receipt["response_sha256"] or receipt["http_status"] in ("200", "206"):
                require(receipt["body_retained"] == "True", "answered count body is required")
    by_id = {r["request_id"]: r for r in receipts}
    expected = {f"bodies/{r['request_id']}.body" for r in receipts if r["body_retained"] == "True"}
    require(set(bodies) == expected, "bundle retained body membership")
    for member, body in bodies.items():
        receipt = by_id[member.removeprefix("bodies/").removesuffix(".body")]
        require(hashlib.sha256(body).hexdigest() == receipt["response_sha256"], "bundle body SHA-256")
        require(str(len(body)) == receipt["response_bytes"], "bundle body byte count")
        if receipt["http_status"] not in ("200", "206"):
            continue
        document = json.loads(body)
        if "count" in receipt:
            require(not receipt["request_error"], "successful count receipt has request error")
            check_source(
                receipt["code_station"],
                receipt["product_id"],
                receipt["request_url"],
                int(receipt["http_status"]),
                body,
            )
            codes = " ".join(sorted({str(row.get("code_station")) for row in document.get("data") or []}))
            require(str(document.get("count")) == receipt["count"], "bundle count summary")
            require(codes == receipt["returned_codes"], "bundle returned station summary")
        elif "points" in receipt:
            check_source(receipt["code_station"], receipt["product_id"], receipt["request_url"], 200, body)
            series = document["series"]
            require(str(len(series["data"])) == receipt["points"], "bundle point summary")
            require(str(series["code"]) == receipt["series_code"], "bundle station summary")
            require(str(series["metric"]) == receipt["series_metric"], "bundle metric summary")
    return by_id, bodies


def resolve_acquisition(root, acquisition, bundles):
    reference = acquisition["reference"]
    if "!" in reference:
        name, member = reference.split("!", 1)
        receipts, bodies = bundles[name]
        receipt = receipts[acquisition["receipt_id"]]
        require(member == f"bodies/{receipt['request_id']}.body", "receipt member identity")
        require(receipt["body_retained"] == "True", "retained receipt")
        require(
            not receipt["request_error"] or int(receipt["http_status"]) >= 400, "successful receipt has request error"
        )
        expected = (
            receipt["request_url"],
            receipt["retrieved_at"],
            int(receipt["http_status"]),
            receipt["content_type"],
            reference,
            int(receipt["response_bytes"]),
            receipt["response_sha256"],
        )
        body = bodies[member]
    else:
        receipt_path = safe_path(root, reference)
        receipt = json.loads(receipt_path.read_bytes())
        response = receipt["response"]
        body_path = safe_path(root, str(receipt_path.parent.relative_to(root) / response["body_file"]))
        expected = (
            receipt["request"]["url"],
            response["retrieved_at"],
            response["status"],
            response["media_type"],
            str(body_path.relative_to(root)),
            response["byte_size"],
            response["sha256"],
        )
        require(receipt["request"]["method"] == "GET", "receipt request method")
        if "final_url" in response:
            require(response["final_url"] == receipt["request"]["url"], "receipt final URL")
        body = body_path.read_bytes()
    material = acquisition["material"]
    actual = (
        acquisition["requested_from"][0],
        acquisition["retrieved_at_start"],
        acquisition["http_status"],
        acquisition["media_type"],
        material["filename"],
        material["byte_count"],
        material["sha256"],
    )
    require(actual == expected, f"acquisition differs from retained receipt: {reference}")
    check_material(material, body)
    return body


def verify_private(pairs, root, bundles):
    verified = []
    for row in pairs:
        results = []
        for acquisition in row["acquisitions"]:
            body = resolve_acquisition(root, acquisition, bundles)
            results.append(
                check_source(
                    row["code_station"],
                    row["product_id"],
                    acquisition["requested_from"][0],
                    acquisition["http_status"],
                    body,
                )
            )
        status, basis, count = classify(row["product_id"], results)
        require(
            (status, basis, count) == (row["status"], row["basis"], row["published_count_or_new_witness_points"]),
            f"source classification mismatch: {row['code_station']} {row['product_id']}",
        )
        verified.append({"code_station": row["code_station"], "status": status})
    return accounting(verified)


class VisibleText(HTMLParser):
    """HTML document → visible text fragments (script/style excluded)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fragments = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.fragments.append(data)


def verify_official_public(document):
    require(document["schema_version"] == 1, "official index revision")
    require(document["source_documents"], "official index has no documents")
    for entry in document["source_documents"]:
        require(
            entry["quoted_source_words"].strip() and entry["scope"].strip() and entry["limitation"].strip(),
            "official source words and scope",
        )
        acquisition = entry["acquisition"]
        require(acquisition["method"] == "http_request" and len(acquisition["requested_from"]) == 1, "official request")
        url = urlsplit(acquisition["requested_from"][0])
        require(url.scheme == "https" and url.netloc in {"hydro.eaufrance.fr", "hubeau.eaufrance.fr"}, "official host")
        require(
            datetime.fromisoformat(acquisition["retrieved_at_start"]).utcoffset() is not None,
            "official acquisition date",
        )
        require(
            acquisition["http_status"] == 200 and acquisition["media_type"].startswith("text/html"),
            "official response status/type",
        )
        material = acquisition["material"]
        require(set(material) == {"filename", "sha256", "byte_count"}, "official MaterialIdentity")
        require(
            material["filename"].endswith(".body")
            and type(material["byte_count"]) is int
            and material["byte_count"] > 0,
            "official material",
        )
        require(
            len(material["sha256"]) == 64 and all(c in "0123456789abcdef" for c in material["sha256"]),
            "official digest",
        )
    require(
        document["citation_limit"] and document["citation_source"] and document["citation_interpretation_limit"],
        "citation scope",
    )


def verify_official_private(document, root):
    verify_official_public(document)
    for entry in document["source_documents"]:
        acquisition = dict(entry["acquisition"])
        acquisition["reference"] = acquisition["material"]["filename"].removesuffix(".body") + ".receipt.json"
        body = resolve_acquisition(root, acquisition, {})
        parser = VisibleText()
        parser.feed(body.decode("utf-8"))
        visible = " ".join(" ".join(parser.fragments).split())
        quote = " ".join(entry["quoted_source_words"].split())
        require(quote in visible, "official quoted source words differ from body")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--official-index", type=Path)
    parser.add_argument("--bundle", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.output:
        args.output = args.output.resolve()
        if any((parent / ".git").exists() for parent in (args.output, *args.output.parents)):
            parser.error("Output must be outside source checkouts")
    for bundle in args.bundle:
        read_bundle(bundle)
    raw = args.ledger.read_bytes()
    ledger = json.loads(lzma.decompress(raw) if args.ledger.suffix == ".xz" else raw)
    official_path = args.official_index or args.ledger.parent.parent / "evidence" / "official_publication.json"
    official = json.loads(official_path.read_bytes())
    verify_official_public(official)
    native_bytes = args.native.read_bytes()
    check_material(ledger["native_table"], native_bytes)
    summary = verify_public(pd.read_parquet(io.BytesIO(native_bytes)), ledger)
    mode = "public-derived-ledger-consistency-only"
    if args.evidence_root:
        evidence_root = args.evidence_root.resolve(strict=True)
        names = {
            a["reference"].split("!", 1)[0] for r in ledger["pairs"] for a in r["acquisitions"] if "!" in a["reference"]
        }
        bundles = {name: read_bundle(safe_path(evidence_root, name)) for name in names}
        summary = verify_private(ledger["pairs"], evidence_root, bundles)
        verify_official_private(official, evidence_root)
        require(summary == ledger["summary"], "source-derived summary mismatch")
        mode = "private-body-backed-offline-verification"
    result = json.dumps({"mode": mode, "summary": summary}, indent=2) + "\n"
    if args.output:
        require(not args.output.exists(), "output already exists; trusted evidence is never overwritten")
        args.output.write_text(result)
    print(result, end="")


if __name__ == "__main__":
    main()
