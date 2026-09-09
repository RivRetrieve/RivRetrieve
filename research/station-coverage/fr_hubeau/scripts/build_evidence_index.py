"""Generate EVIDENCE_INDEX.md: every recording, its integrity fields, and what it establishes."""

from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]
RECORDINGS = HERE / "recordings"

ESTABLISHES = {
    "sandre_wfs_stationhydro_all": "Producer (NomIntervenant) for 5,366 of 6,454 hydrometry stations in one request; the same properties the per-station id.eaufrance.fr lookups return.",
    "sandre_wfs_stationmesure_producers": "Producer (ProducteurDuJeu) for all 869 temperature stations.",
    "hubeau_sites_grandeur_declaration": "grandeur_hydro is 'Q' for all 9,284 sites and date_premiere_donnee_dispo_site is empty for all: the metadata cannot establish availability.",
    "obs_elab_QmnJ_count_1011000101": "The whole-record count instrument: size=1 with no date filter returns the station's total (4,078) for that product.",
    "obs_elab_QmnJ_zero_count": "A published total of zero: the basis for every empty_no_data_published row.",
    "obs_elab_sample_rows": "obs_elab response shape and fields for the daily products.",
    "obs_elab_batch_aggregate_count": "code_entite accepts comma-separated codes, but the count returned is the aggregate across them, so batching cannot attribute rows to a station.",
    "temperature_chronique_count_01001336": "The same count instrument on the temperature route.",
    "temperature_chronique_sample_rows": "temperature/chronique response shape and fields.",
    "referentiel_stations_code_site": "code_site is published alongside code_station: Y251002001 maps to Y2510020, the value fetch.py hard-codes.",
    "observations_tr_Y251002001_H": "observations_tr answers for H today, contradicting the port notes' record of a reproducible HTTP 500.",
    "observations_tr_Y251002001_Q": "A captured transient 503 from observations_tr: the route is intermittently unavailable.",
    "observations_tr_Y251002001_Q_working": "observations_tr answers for Q, with UTC timestamps and both code_site and code_station.",
    "observations_tr_horizon_30d_ok": "A 30-day window is served.",
    "observations_tr_horizon_31d_rejected": "Day 31 is refused with HTTP 400 ValidateDateMin, the publisher stating its own limit explicitly.",
    "observations_tr_latest_H": "Freshest observation from observations_tr (12:10:00Z), for the freshness comparison.",
    "hydroportail_recent_H": "HydroPortail serves the current month and was the fresher route (12:15:00Z).",
    "hydroportail_historical_2020_H": "HydroPortail serves January 2020, history observations_tr cannot reach.",
}


def main() -> None:
    lines = [
        "# fr_hubeau — evidence index",
        "",
        "Every recording captured by this survey, with the integrity fields required by issue #222",
        "(exact request URL and parameters, HTTP status, media type, UTC retrieval instant, response bytes,",
        "SHA-256) and the finding it supports. Regenerate any with",
        "`scripts/capture.py <recording_id> <url> [key=value ...]`.",
        "",
        "Every route surveyed is public and unauthenticated. No credentials, cookies or tokens were sent",
        "or stored.",
        "",
        "| Recording | Status | Bytes | SHA-256 (first 16) | Retrieved (UTC) | Establishes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for path in sorted(RECORDINGS.glob("*.recording.json")):
        recording_id = path.name.replace(".recording.json", "")
        document = json.loads(path.read_text())
        response, request = document["response"], document["request"]
        size = len(response["content_base64"]) * 3 // 4
        parameters = request.get("parameters") or {}
        detail = " ".join(
            f"{k}={v}"
            for k, v in parameters.items()
            if k
            in {
                "code_entite",
                "grandeur_hydro",
                "typeNames",
                "date_debut_obs",
                "hydro_series[startAt]",
                "hydro_series[endAt]",
            }
        )
        lines.append(
            f"| [`{recording_id}`](recordings/{path.name})<br><sub>{detail or request['url']}</sub> "
            f"| {response['status_code']} | {size:,} | `{response['sha256'][:16]}` "
            f"| {response['retrieved_at'][:19]}Z | {ESTABLISHES.get(recording_id, '')} |"
        )
    lines += [
        "",
        "## Derived inventories",
        "",
        "| File | Rows | Contents |",
        "| --- | --- | --- |",
        "| [`inventory/station_product_evidence.csv`](inventory/station_product_evidence.csv) | 33,139 | Final inventory: every station x product with status, basis, producer and window. |",
        "| [`STATION_TABLE.md`](STATION_TABLE.md) | 7,323 | Readable station list, one row per station. |",
        "| [`inventory/hubeau_counts.csv`](inventory/hubeau_counts.csv) | 20,245 | Whole-record counts for the daily and temperature products. |",
        "| [`inventory/instantaneous_counts.csv`](inventory/instantaneous_counts.csv) | 12,908 | observations_tr counts over its rolling 30-day window. |",
        "| [`inventory/instantaneous_history.csv`](inventory/instantaneous_history.csv) | 682 | Bounded HydroPortail probe of in-service zeros, over two windows outside the real-time horizon. |",
        "",
        "## Reproduction",
        "",
        "```bash",
        "uv run python research/station-coverage/fr_hubeau/scripts/sweep_daily_availability.py",
        "uv run python research/station-coverage/fr_hubeau/scripts/sweep_instantaneous.py",
        "uv run python research/station-coverage/fr_hubeau/scripts/probe_instantaneous_history.py",
        "uv run python research/station-coverage/fr_hubeau/scripts/build_inventory.py",
        "uv run python research/station-coverage/fr_hubeau/scripts/build_station_table.py",
        "uv run python research/station-coverage/fr_hubeau/scripts/build_evidence_index.py",
        "```",
        "",
        "Every sweep resumes: pairs already carrying a result are skipped, and rows that failed transport",
        "are retried rather than settled. `verify_evidence.py` re-hashes every recording and re-checks the",
        "inventory's completeness assertions without touching the network.",
    ]
    (HERE / "EVIDENCE_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote EVIDENCE_INDEX.md covering {len(list(RECORDINGS.glob('*.recording.json')))} recordings")


if __name__ == "__main__":
    main()
