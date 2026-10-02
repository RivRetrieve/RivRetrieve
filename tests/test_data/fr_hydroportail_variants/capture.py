"""Capture bounded source evidence into a new, explicitly selected directory."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests

from rivretrieve._internal.recordings import RecordingEnvelope, write_recording
from rivretrieve._internal.transport import HttpClient, HttpMethod, TransportRequest

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--out-dir", type=Path, required=True)
args = parser.parse_args()
OUT = args.out_dir.resolve()
if any((parent / ".git").exists() for parent in (OUT, *OUT.parents)):
    parser.error("Output must be outside source checkouts")
OUT.mkdir(parents=True, exist_ok=False)
ROOT = "https://hydro.eaufrance.fr"
current = None
attempt = 0
manifest = []


def sender(request, timeout_seconds):
    global attempt
    attempt += 1
    session = requests.Session()
    prepared = session.prepare_request(
        requests.Request(
            request.method.value, request.url, params=request.params, headers=dict(request.headers), data=request.body
        )
    )
    parsed = urlsplit(prepared.url)
    target = parsed.path + ("?" + parsed.query if parsed.query else "")
    headers = {"Host": parsed.netloc, **dict(prepared.headers)}
    body = prepared.body or b""
    if isinstance(body, str):
        body = body.encode()
    request_bytes = (
        f"{prepared.method} {target} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n"
    ).encode("latin1") + body
    (OUT / f"{current}.attempt{attempt}.request.http").write_bytes(request_bytes)
    response = session.send(prepared, timeout=timeout_seconds)
    (OUT / f"{current}.attempt{attempt}.response.body").write_bytes(response.content)
    metadata = {
        "acquired_at": datetime.now(UTC).isoformat(),
        "status_code": response.status_code,
        "url": response.url,
        "response_headers": dict(response.headers),
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "response_sha256": hashlib.sha256(response.content).hexdigest(),
        "body_semantics": "requests decoded response entity bytes; not TLS or compressed wire bytes",
    }
    (OUT / f"{current}.attempt{attempt}.exchange.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return response.content, response.status_code, response.headers.get("Content-Type")


client = HttpClient(sender=sender)


def capture(name, url, params=None):
    global current, attempt
    current, attempt = name, 0
    request = TransportRequest(HttpMethod.GET, url, params, {"Accept": "application/json"} if params else {})
    response = client.send(request)
    if params:
        write_recording(RecordingEnvelope.from_transport(request, response), OUT / f"{name}.recording.json")
    entry = {
        "name": name,
        "status_code": response.status_code,
        "retrieved_at": response.retrieved_at.isoformat(),
        "sha256": hashlib.sha256(response.content).hexdigest(),
    }
    if params and response.status_code == 200:
        document = json.loads(response.content)
        series = document["series"]
        data = series["data"]
        entry.update(
            metadata={k: v for k, v in series.items() if k != "data"},
            timezone=document.get("timezone"),
            rows=len(data),
            statuses=sorted({str(row.get("s")) for row in data}),
            first=data[0] if data else None,
            last=data[-1] if data else None,
            nulls=sum(row.get("v") is None for row in data),
        )
    manifest.append(entry)
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(name, response.status_code, entry.get("rows"), flush=True)


for station, start, end, label in [
    ("Y251002001", "30/12/2019", "04/01/2020", "padded"),
    ("1232000101", "30/05/2026", "04/06/2026", "padded"),
    ("Y251002001", "01/01/2020", "02/01/2020", "direct"),
    ("1232000101", "01/06/2026", "02/06/2026", "direct"),
]:
    for metric in ("Q", "H"):
        for variant in ("raw", "validated", "pre_validated_and_validated", "most_valid"):
            capture(
                f"{station}_{metric}_{label}_{variant}",
                f"{ROOT}/stationhydro/ajax/{station}/series",
                {
                    "hydro_series[startAt]": start,
                    "hydro_series[endAt]": end,
                    "hydro_series[variableType]": "simple_and_interpolated_and_hourly_variable",
                    "hydro_series[simpleAndInterpolatedAndHourlyVariable]": metric,
                    "hydro_series[statusData]": variant,
                },
            )
for name, path in [
    ("station-form", "/stationhydro/1232000101/series"),
    ("glossaire", "/glossaire"),
    ("hydro-series", "/build/hydro-series.6104cd00.js"),
    ("graph-measures", "/build/graph-measures.cfa55bcd.js"),
    ("unit-selector", "/build/4210.e6896d9b.js"),
    ("unit-label", "/build/5621.4ab47ec9.js"),
]:
    capture(name, ROOT + path)
