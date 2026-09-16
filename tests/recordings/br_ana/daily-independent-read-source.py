"""audit : SourceRecording × PublisherDefinitions → IndependentDailyExpectations.
Offline source-only reader. No RivRetrieve imports or implementation outputs.
"""

import argparse
import base64
import calendar
import hashlib
import json
import zipfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--verify-originals", action="store_true", help="Validate private original software/PDF/SQL chain"
    )
    args = parser.parse_args()
    evidence = args.evidence
    verified = {}
    recording_root = evidence
    if args.verify_originals:
        recording_root = evidence / "modern-monthly"
        identity = json.loads((evidence / "hidro-distribution-identity.json").read_text())
        archive = evidence / "hidro-build-1.4.0.81-original.zip"
        assert digest(archive.read_bytes()) == identity["sha256"]
        manifest = json.loads((evidence / "hidro-static-documents/extraction-manifest.json").read_text())
        installer = (evidence / "hidro-installer-original.exe").read_bytes()
        assert digest(installer) == manifest["installer_sha256"]
        with zipfile.ZipFile(archive) as z:
            assert z.read("Instalador Hidro Build 1.4.0.exe") == installer
        verified = {"zip": identity["sha256"], "installer": digest(installer)}
        for name in ["Hidro 1.4 - Novidades do Sistema.pdf", "Hidro SQLSERVER 2008.sql"]:
            entry = next(x for x in manifest["files"] if x["filename"] == name)
            data = (evidence / "hidro-static-documents" / name).read_bytes()
            assert digest(data) == entry["sha256"] and len(data) == entry["byte_count"]
            verified[name] = digest(data)
        sql = (evidence / "hidro-static-documents/Hidro SQLSERVER 2008.sql").read_text(encoding="utf-16")
        selected = json.loads((evidence / "hidro-sqlserver-selected-views-derived.json").read_text())
        assert selected["source_sha256"] == verified["Hidro SQLSERVER 2008.sql"]
        for view in selected["views"].values():
            assert view in sql
    result = {"verified_source_hash_chain": verified, "recordings": [], "probes": {}}
    if not args.verify_originals:
        # Maintenance adaptation: these are derived excerpts, not original materials.
        dictionary = json.loads((evidence / "hidro-1.4-conventional-dictionary-derived.json").read_text())
        selected = json.loads((evidence / "hidro-sqlserver-selected-views-derived.json").read_text())
        assert dictionary["source_sha256"] == "d098fe733740299c25ef3fc33ac7e96d6b21ff01925150d6b1d74791914e24f8"
        assert selected["source_sha256"] == "6136dd163ba52d5863ffd6b70c9f3aace5d5551abdd1599c5f2972f0a4f9fb98"
        assert {page["pdf_page"] for page in dictionary["pages"]} >= {21, 22, 23, 24}
        assert "C.Cota15" in selected["views"]["vwCotaMedia"]
        result["original_chain_validation"] = {
            "status": "not performed; retained derived excerpts and observation bodies only"
        }
    # Retention change: freeze the ten recordings inspected by the independent author.
    # Later captures in the research directory must not broaden that authorship claim.
    recordings = (
        "HidroSerieCotas_15400000_2020-01-01_2020-01-31.recording.json",
        "HidroSerieCotas_15400000_2023-02-01_2023-02-28.recording.json",
        "HidroSerieCotas_15400000_2023-12-01_2023-12-31.recording.json",
        "HidroSerieCotas_15400000_2024-01-01_2024-01-31.recording.json",
        "HidroSerieCotas_15400000_2024-02-01_2024-02-29.recording.json",
        "HidroSerieVazao_15400000_2020-01-01_2020-01-31.recording.json",
        "HidroSerieVazao_15400000_2023-02-01_2023-02-28.recording.json",
        "HidroSerieVazao_15400000_2023-12-01_2023-12-31.recording.json",
        "HidroSerieVazao_15400000_2024-01-01_2024-01-31.recording.json",
        "HidroSerieVazao_15400000_2024-02-01_2024-02-29.recording.json",
    )
    for path in sorted(recording_root / name for name in recordings):
        recording = json.loads(path.read_text())
        req, response = recording["request"], recording["response"]
        body_bytes = base64.b64decode(response["content_base64"], validate=True)
        assert digest(body_bytes) == response["sha256"]
        assert recording["format_version"] == 2
        assert req["method"] == "GET" and req["body"] is None
        assert req["ordinary_headers"] == {"User-Agent": "RivRetrieve"}
        assert req["credential_header_names"] == ["Authorization"]
        assert response["status_code"] == 200 and response["content_type"] == "application/json"
        for call in response["prerequisite_calls"]:
            assert call["response_disposition"] == "secret_response_withheld"
            assert call["ordinary_headers"] == {"User-Agent": "RivRetrieve"}
        body = json.loads(body_bytes)
        assert {k: v for k, v in body.items() if k != "items"} == {"status": "OK", "code": 200, "message": "Sucesso"}
        stage = "HidroSerieCotas" in path.name
        prefix = "Cota" if stage else "Vazao"
        level_key = "nivelconsistencia" if stage else "Nivel_Consistencia"
        audit = {
            "filename": path.name,
            "body_sha256": digest(body_bytes),
            "request": req,
            "retrieved_at": response["retrieved_at"],
            "source_row_count": len(body["items"]),
            "rows": [],
        }
        for index, row in enumerate(body["items"]):
            header = {k: v for k, v in row.items() if not k.startswith(prefix + "_")}
            dt = datetime.fromisoformat(row["Data_Hora_Dado"])
            assert dt.day == 1 and dt.tzinfo is None
            assert row["codigoestacao"] == "15400000"
            valid_days = calendar.monthrange(dt.year, dt.month)[1]
            slots = []
            for day in range(1, 32):
                key = f"{prefix}_{day:02d}"
                assert key in row and key + "_Status" in row
                value, status = row[key], row[key + "_Status"]
                assert value is None or isinstance(value, str)
                assert status is None or isinstance(status, str)
                slots.append(
                    {
                        "day": day,
                        "field": key,
                        "source_value": value,
                        "source_status": status,
                        "valid_calendar_day": day <= valid_days,
                        "label": (dt + timedelta(days=day - 1)).isoformat() if day <= valid_days else None,
                        "canonical_value": str(Decimal(value) / (100 if stage else 1))
                        if value not in (None, "")
                        else None,
                    }
                )
            audit["rows"].append(
                {
                    "index": index,
                    "header": header,
                    "header_types": {k: type(v).__name__ for k, v in header.items()},
                    "slots": slots,
                    "valid_day_nulls": [
                        s["day"] for s in slots if s["valid_calendar_day"] and s["source_value"] is None
                    ],
                    "blank_days": [s["day"] for s in slots if s["source_value"] == ""],
                }
            )
            target = (
                (not stage and dt.year == 2024 and dt.month == 1 and row[level_key] == "1")
                or (not stage and dt.year == 2020 and row[level_key] == "2")
                or (stage and dt.year == 2020)
            )
            if target and row["Mediadiaria"] == "1":
                assert dt.hour == dt.minute == dt.second == dt.microsecond == 0
                variant = "bruto" if row[level_key] == "1" else "consistido"
                name = ("stage" if stage else "discharge") + "_daily_mean_" + variant
                assert name not in result["probes"]
                start = dt.replace(day=15).isoformat()
                end = dt.replace(day=16).isoformat()
                hits = [s for s in slots if s["label"] is not None and start <= s["label"] <= end]
                assert all(s["source_value"] not in (None, "") for s in hits)
                result["probes"][name] = {
                    "recording": path.name,
                    "row_index": index,
                    "header": header,
                    "window": [start, end],
                    "count": len(hits),
                    "first": hits[0]["label"],
                    "last": hits[-1]["label"],
                    "readings": hits,
                }
        result["recordings"].append(audit)
    assert len(result["recordings"]) == 10 and len(result["probes"]) == 4
    result["year_boundary_probes"] = {}
    start, end = "2023-12-31T00:00:00", "2024-01-01T00:00:00"
    for parameter, endpoint, level_key in [
        ("stage", "HidroSerieCotas", "nivelconsistencia"),
        ("discharge", "HidroSerieVazao", "Nivel_Consistencia"),
    ]:
        for level, variant in [("1", "bruto"), ("2", "consistido")]:
            hits = []
            for recording in result["recordings"]:
                if not recording["filename"].startswith(endpoint):
                    continue
                if not any(month in recording["filename"] for month in ["2023-12", "2024-01"]):
                    continue
                for row in recording["rows"]:
                    if row["header"]["Mediadiaria"] != "1" or row["header"][level_key] != level:
                        continue
                    for slot in row["slots"]:
                        if slot["label"] is not None and start <= slot["label"] <= end:
                            hits.append(
                                {
                                    "recording": recording["filename"],
                                    "row_index": row["index"],
                                    "header": row["header"],
                                    **slot,
                                }
                            )
            hits.sort(key=lambda slot: slot["label"])
            assert all(slot["source_value"] not in (None, "") for slot in hits)
            result["year_boundary_probes"][parameter + "_daily_mean_" + variant] = {
                "window": [start, end],
                "count": len(hits),
                "first": hits[0]["label"],
                "last": hits[-1]["label"],
                "readings": hits,
            }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
