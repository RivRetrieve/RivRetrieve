"""Generate EVIDENCE_INDEX.md: every preserved response, its integrity fields, and what it establishes.

Two kinds of evidence, kept separate on purpose:

  * Response-shape examples (recordings/) illustrate a route or a response shape. An example
    cannot substantiate a different station's result and is never cited as one.
  * Per-pair evidence (evidence/) supports one station and one product. Each inventory row
    links to its own file.
"""

from __future__ import annotations

import base64
import json
import pathlib

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
RECORDINGS = HERE / "recordings"
EVIDENCE = HERE / "evidence"

ESTABLISHES = {
    "layers_manifest": "The publisher's own list of ten layers; the authoritative product-to-layer mapping.",
    "layer_10": "Vodostaj (H) layer membership - 99 hydrological stations.",
    "layer_20": "Proticaj (Q) layer membership - 60 stations; identical to the committed baseline.",
    "layer_30": "Temperatura vode (WT) layer membership - 13 stations.",
    "layer_40": "GroundWaterLevel layer; object type 'Stanica podzemnih voda' - a different object type.",
    "layer_50": "GroundWaterTemp layer; object type 'Stanica podzemnih voda' - a different object type.",
    "layer_60": "Precipitation layer; object type 'Meteorološka stanica' - a different object type.",
    "layer_70": "AirTemp layer; object type 'Meteorološka stanica' - a different object type.",
    "layer_80": (
        "EPPWaterLevel layer - 81 stations of object type 'General;Hidrološka stanica', the same "
        "type as the surveyed population. Excluded by layer alias, not by object type: see "
        "UNRESOLVED.md §7."
    ),
    "layer_90": (
        "EPPFlow layer - 40 stations of object type 'General;Hidrološka stanica', the same type as "
        "the surveyed population. Excluded by layer alias, not by object type: see UNRESOLVED.md §7."
    ),
    "portal_root": "Portal identity: page title names Agencija za vodno području rijeke Save.",
    "boundary_4060_WT_headeronly": "Response shape: no data rows, parameter and unit still declared.",
    "boundary_1020_WT_populated": "Response shape: a fully populated workbook, every data row carrying a value.",
    "boundary_4110_Q_smallest": "Response shape: populated Q workbook; unit m³/s.",
    "boundary_4110_H_smallest": "Response shape: populated H workbook; unit cm.",
    "absent_4228_H_404": "Response shape: station declared in the H layer, workbook route returns 404.",
    "absent_9025_H_404": "Response shape: station declared in the H layer, workbook route returns 404.",
    "absent_4109_WT_404": "Response shape: WT workbook route returns 404.",
    "horizon_4024_Q_1M_exists": "Response shape: a one-month workbook period exists.",
    "horizon_4024_Q_5Y_absent": "Response shape: a _5Y filename returns 404 for this station and product.",
    "horizon_directory_listing_403": "Directory listing refused with 403; recorded, not bypassed.",
}
LOWROW = (
    "Timestamped rows with every measurement cell published empty. Establishes that the "
    "publisher's '#Rows' header counts timestamped rows, not measurements, and therefore cannot "
    "classify availability."
)


def digest_of(document: dict) -> str:
    response = document["response"]
    return response.get("response_sha256") or response.get("sha256", "")


def main() -> None:
    lines = [
        "# ba_fhmzbih — evidence index",
        "",
        "Every preserved response, with its integrity fields and what it establishes.",
        "",
        "Two kinds, deliberately separate:",
        "",
        "- **Response-shape examples** (`recordings/`) illustrate a route or a response shape. An",
        "  example cannot substantiate a different station's result, and none is cited as one.",
        "- **Per-station-per-product evidence** (`evidence/`) supports exactly one inventory row.",
        "",
        "## Response-shape examples",
        "",
        "| Recording | Status | Retrieved (UTC) | Bytes | SHA-256 | Establishes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for path in sorted(RECORDINGS.glob("*.recording.json")):
        document = json.loads(path.read_text())
        stem = path.name.removesuffix(".recording.json")
        note = ESTABLISHES.get(stem) or (LOWROW if stem.startswith("lowrow_") else "")
        response = document["response"]
        size = response.get("byte_size")
        if size is None and response.get("content_base64"):
            size = len(base64.b64decode(response["content_base64"]))
        lines.append(
            f"| `{path.name}` | {response['status_code']} | {response['retrieved_at']} "
            f"| {size:,} | `{digest_of(document)[:16]}…` | {note} |"
        )

    inventory = pd.read_csv(HERE / "inventory" / "station_product_evidence.csv", dtype=str)
    counts = inventory.status.value_counts()
    retained = sum(
        1
        for path in EVIDENCE.rglob("*.evidence.json")
        if json.loads(path.read_text())["response"].get("content_base64") is not None
    )
    total = len(list(EVIDENCE.rglob("*.evidence.json")))

    lines += [
        "",
        "## Per-station-per-product evidence",
        "",
        f"`evidence/` holds **{total}** files: one per station × product pair, plus the historical-access",
        "attempts. Every inventory row links to its own file, and `verify_evidence.py` checks that the",
        "file's station, product, URL, acquisition instant and digest match the row citing it.",
        "",
        "Each file records the exact request URL, HTTP status, media type, UTC acquisition instant,",
        "byte size and the SHA-256 **of the full publisher response**.",
        "",
        f"**{retained}** of them retain the complete response bytes — every response that carries no",
        "observation values does, which covers all four non-measurement categories:",
        "",
        "| Status | Rows | Bytes retained |",
        "| --- | --- | --- |",
        f"| `timestamped_without_measurements` | {counts.get('timestamped_without_measurements', 0)} | full |",
        f"| `no_data_rows` | {counts.get('no_data_rows', 0)} | full |",
        f"| `access_failed` | {counts.get('access_failed', 0)} | full |",
        f"| `measurements_present` | {counts.get('measurements_present', 0)} | header, window and excerpt; see below |",
        "",
        "For workbooks that do carry observations, the complete bytes are a year of the agency's",
        "measurements. Issue #223 directs that whole observation histories are not to be downloaded",
        "merely to prove access, and the source records no redistribution grant, so those files keep the",
        "full-response digest plus a bounded excerpt: opening rows, and witness rows carrying real",
        "values. One populated cell establishes the classification, which is what the excerpt preserves.",
        "The excerpt carries its own separate digest and is never presented as the response digest.",
        "",
        "**Limitation, stated plainly:** a digest over bytes that are not retained cannot be recomputed",
        "later. The source serves a rolling window, so a re-fetch returns different bytes. The digest",
        "fixes what was received at the recorded instant; it is not a re-verification route.",
        "",
        "## Historical-access attempts",
        "",
        "`evidence/horizon/` holds every attempted period suffix and format variant, with its own",
        "response preserved and its station and product named. See `inventory/horizon_probe.csv`.",
    ]

    (HERE / "EVIDENCE_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"wrote EVIDENCE_INDEX.md — {len(list(RECORDINGS.glob('*.recording.json')))} examples, {total} evidence files"
    )


if __name__ == "__main__":
    main()
