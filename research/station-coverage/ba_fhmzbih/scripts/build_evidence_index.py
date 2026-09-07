"""Generate EVIDENCE_INDEX.md: every recording, its integrity fields, and what it establishes."""

from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]
RECORDINGS = HERE / "recordings"

ESTABLISHES = {
    "layers_manifest": "The publisher's own list of ten layers; the authoritative product-to-layer mapping.",
    "layer_10": "Vodostaj (H) layer membership - 99 hydrological stations.",
    "layer_20": "Proticaj (Q) layer membership - 60 stations; identical to the committed baseline.",
    "layer_30": "Temperatura vode (WT) layer membership - 13 stations.",
    "layer_40": "GroundWaterLevel layer; object type 'Stanica podzemnih voda' - evidences out-of-scope.",
    "layer_50": "GroundWaterTemp layer; object type 'Stanica podzemnih voda' - evidences out-of-scope.",
    "layer_60": "Precipitation layer; object type 'Meteorološka stanica' - evidences out-of-scope.",
    "layer_70": "AirTemp layer; object type 'Meteorološka stanica' - evidences out-of-scope.",
    "layer_80": "EPPWaterLevel layer - evidences out-of-scope.",
    "layer_90": "EPPFlow layer - evidences out-of-scope.",
    "portal_root": "Portal identity: page title names Agencija za vodno području rijeke Save.",
    "boundary_4060_WT_headeronly": "Boundary: #Rows = 0 with parameter and unit still declared (0 data rows verified).",
    "boundary_1020_WT_populated": "Boundary: #Rows = 7251, 7251 data rows verified; one-year span 2025-09-07 to 2026-09-06.",
    "boundary_4110_Q_smallest": "Smallest populated Q workbook; 5189 data rows verified; unit m³/s.",
    "boundary_4110_H_smallest": "Smallest populated H workbook; 5189 data rows verified; unit cm.",
    "absent_4228_H_404": "Access block: station declared in the H layer, workbook route returns 404.",
    "absent_9025_H_404": "Access block: station declared in the H layer, workbook route returns 404.",
    "absent_4109_WT_404": "Access block: WT workbook route returns 404.",
    "horizon_4024_Q_1M_exists": "A one-month workbook period exists (span 2026-08-08 to 2026-09-07).",
    "horizon_4024_Q_5Y_absent": "No multi-year period: _5Y returns 404 (as do _2Y, _10Y, _ALL and others).",
    "lowrow_1110_Q_1rows": "Content-Length 3740 B but publisher declares #Rows = 1: evidences why file size cannot classify availability.",
    "lowrow_4023_Q_164rows": "Content-Length 5614 B but publisher declares #Rows = 164: evidences why file size cannot classify availability.",
    "lowrow_4911_Q_338rows": "Content-Length 7628 B but publisher declares #Rows = 338: evidences why file size cannot classify availability.",
    "lowrow_9001_Q_1rows": "Content-Length 3758 B but publisher declares #Rows = 1: evidences why file size cannot classify availability.",
    "lowrow_9020_Q_1rows": "Content-Length 3740 B but publisher declares #Rows = 1: evidences why file size cannot classify availability.",
    "lowrow_9043_Q_1rows": "Content-Length 3742 B but publisher declares #Rows = 1: evidences why file size cannot classify availability.",
    "lowrow_9130_Q_1rows": "Content-Length 3744 B but publisher declares #Rows = 1: evidences why file size cannot classify availability.",
    "horizon_directory_listing_403": "Directory listing refused with 403; recorded, not bypassed.",
}


def main() -> None:
    lines = [
        "# ba_fhmzbih — evidence index",
        "",
        "Every recording captured by this survey, with the integrity fields required by issue #223",
        "(exact request URL, HTTP status, media type, UTC retrieval instant, response bytes, SHA-256)",
        "and the finding it supports. Recordings are stored in the repository's existing convention;",
        "regenerate any of them with `scripts/capture.py <url> <recording_id>`.",
        "",
        "No credentials, cookies or tokens were sent or stored: every route surveyed is public and",
        "unauthenticated.",
        "",
        "| Recording | Status | Bytes | SHA-256 (first 16) | Retrieved (UTC) | Establishes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for path in sorted(RECORDINGS.glob("*.recording.json")):
        recording_id = path.name.replace(".recording.json", "")
        document = json.loads(path.read_text())
        response, request = document["response"], document["request"]
        size = len(document["response"]["content_base64"]) * 3 // 4
        lines.append(
            f"| [`{recording_id}`](recordings/{path.name})<br><sub>{request['url']}</sub> "
            f"| {response['status_code']} | {size:,} | `{response['sha256'][:16]}` "
            f"| {response['retrieved_at'][:19]}Z | {ESTABLISHES.get(recording_id, '')} |"
        )
    lines += [
        "",
        "## Derived inventories",
        "",
        "| File | Rows | Contents |",
        "| --- | --- | --- |",
        "| [`inventory/station_product_evidence.csv`](inventory/station_product_evidence.csv) | 297 | Final inventory: every station x product with status, basis and linked recording. |",
        "| [`STATION_TABLE.md`](STATION_TABLE.md) | 99 | Readable station list: one row per station, per-product status. |",
        "| [`inventory/declared_rows_population.csv`](inventory/declared_rows_population.csv) | 297 | The publisher's `#Rows`, unit, parameter and timeseries name per pair. |",
        "| [`inventory/population_probe.csv`](inventory/population_probe.csv) | 297 | HEAD probe: HTTP status, Content-Length, layer membership, baseline membership. |",
        "| [`inventory/workbook_probe.csv`](inventory/workbook_probe.csv) | 180 | First-pass probe over the committed 60-station baseline only. |",
        "| [`inventory/declared_rows.csv`](inventory/declared_rows.csv) | 48 | First-pass `#Rows` read of the baseline's empty WT candidates. |",
        "",
        "## Reproduction",
        "",
        "```bash",
        "uv run python research/station-coverage/ba_fhmzbih/scripts/probe_population.py",
        "uv run python research/station-coverage/ba_fhmzbih/scripts/read_all_declared_rows.py",
        "uv run python research/station-coverage/ba_fhmzbih/scripts/build_final_inventory.py",
        "uv run python research/station-coverage/ba_fhmzbih/scripts/build_station_table.py",
        "uv run python research/station-coverage/ba_fhmzbih/scripts/build_evidence_index.py",
        "```",
        "",
        "`verify_evidence.py` re-hashes every recording and re-checks the inventory's completeness",
        "assertions without touching the network.",
    ]
    (HERE / "EVIDENCE_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote EVIDENCE_INDEX.md covering {len(list(RECORDINGS.glob('*.recording.json')))} recordings")


if __name__ == "__main__":
    main()
