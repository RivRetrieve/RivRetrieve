"""Generate EVIDENCE_INDEX.md: every preserved response, its integrity fields, and what it establishes.

Two kinds of evidence, kept separate on purpose:

  * Response-shape examples (recordings/) illustrate a route or a response shape. An example
    cannot substantiate a different station's result and is never cited as one.
  * Per-pair survey accounting (evidence/) links one historical station/product row.
    Positive summaries without bodies do not certify numerical classifications.
  * Governing baseline accounting identifies complete privately retained source responses;
    public accounting is not raw-body proof.
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
    "layer_20": "Proticaj (Q) layer membership - same 60 station IDs as the committed baseline, not byte equality.",
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
    "portal_root": "Portal identity: page title names Agencija za vodno područje rijeke Save.",
    "boundary_4060_WT_headeronly": "Response shape: no data rows, parameter and unit still declared.",
    "boundary_1020_WT_populated": "Historical summary: populated workbook; full positive body absent from this public file.",
    "boundary_4110_Q_smallest": "Historical summary: populated Q workbook, unit m³/s; full body absent from this public file.",
    "boundary_4110_H_smallest": "Historical summary: populated H workbook, unit cm; full body absent from this public file.",
    "absent_4228_H_404": "Response shape: station declared in the H layer, workbook route returns 404.",
    "absent_9025_H_404": "Response shape: station declared in the H layer, workbook route returns 404.",
    "absent_4109_WT_404": "Response shape: WT workbook route returns 404.",
    "horizon_4024_Q_1M_exists": "Historical monthly-example accounting; full positive body absent from this public file.",
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
        "Historical survey response accounting, with integrity fields and limits.",
        "",
        "Public survey records are separate from the governing private baseline corpus:",
        "",
        "- **Response-shape examples** (`recordings/`) illustrate a route or a response shape. An",
        "  example cannot substantiate a different station's result, and none is cited as one.",
        "- **Per-pair survey accounting** (`evidence/`) links one historical inventory row; positive summaries lack bodies.",
        "",
        "The governing 180-pair account is [inventory/baseline_workbook_access.json](inventory/baseline_workbook_access.json).",
        "All 180 governing bodies are retained privately: 132 numerical-positive and 48 empty WT.",
        "Dates: 3 pairs September 2, 3 September 7, 48 September 9, 126 September 13, 2026.",
        "All 60 baseline stations / 180 applicable pairs remain selectable after integration;",
        "48 empty WT pairs have unknown availability, not unsupported products.",
        "The public ledger is derived accounting, not raw-body proof. Keep the whole controlled",
        "corpus private and out of distributed artifacts; arrange an authorised handoff if needed.",
        "The historical 99-station / 297-pair survey does not expand the baseline or certify its",
        "41 nonbaseline positive summaries. The records below retain their original dates.",
        "",
        "## Response-shape examples and historical summaries",
        "",
        "| Recording/account | Status | Retrieved (UTC) | Bytes | SHA-256 | Evidence scope |",
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
        "observation values does: three nonpositive pair categories plus 56 retained horizon refusals.",
        "",
        "| Historical survey status | Pairs | Bytes retained |",
        "| --- | --- | --- |",
        f"| `timestamped_without_measurements` | {counts.get('timestamped_without_measurements', 0)} | full |",
        f"| `no_data_rows` | {counts.get('no_data_rows', 0)} | full |",
        f"| `access_failed` | {counts.get('access_failed', 0)} | full |",
        f"| `measurements_present` | {counts.get('measurements_present', 0)} | header, window and excerpt; see below |",
        "",
        "Historical positive workbooks retain a full-response digest and derived header/window",
        "summaries. Bounded excerpts hold opening rows and witness rows with `has_value` booleans,",
        "not actual measurement values. A populated-cell flag does not prove a finite numerical",
        "value. An excerpt digest authenticates the excerpt only, not the absent source body.",
        "",
        "The original positive bodies were discarded. A later rolling download cannot recover",
        "them. Governing baseline replacements retain their own actual acquisition dates.",
        "There is no approved blanket measurement-value ban. Layer JSON contains `L1_ts_value`",
        "snapshots. No legal classification or redistribution permission is inferred here;",
        "any needed representative recording publication follows normal review.",
        "",
        "## Verification limits",
        "",
        "The old 25/25 result accepted a false positive summary despite unchanged blank bytes.",
        "It is retired as acceptance evidence. Default no-root mode verifies retained public",
        "survey bytes and correspondence, but cannot prove positives whose bodies are absent.",
        "Protected source certification requires all 180 governing bodies and explicit paths:",
        "",
        "```sh",
        "uv run python research/station-coverage/ba_fhmzbih/scripts/verify_evidence.py --evidence-root <controlled-ba-directory> --baseline-native src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet",
        "```",
        "",
        "Missing required bodies must fail. Public derived accounting alone is not certification.",
        "See FINDINGS.md §13 for the verification and independent-expectation boundaries.",
        "",
        "## Historical-access attempts",
        "",
        "`evidence/horizon/` holds every attempted period suffix and format variant, with its own",
        "request/response accounting and its station and product named. Of 64 attempts, 56 refusals retain bodies;",
        "8 positive attempts retain summaries without bodies. See `inventory/horizon_probe.csv`.",
    ]

    (HERE / "EVIDENCE_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"wrote EVIDENCE_INDEX.md — {len(list(RECORDINGS.glob('*.recording.json')))} examples, {total} evidence files"
    )


if __name__ == "__main__":
    main()
