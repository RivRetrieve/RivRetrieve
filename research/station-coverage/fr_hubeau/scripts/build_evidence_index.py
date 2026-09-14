"""Generate a historical index, not the accepted EVIDENCE_INDEX.md: every piece of evidence, grouped by what it may be used to establish.

    render : (Bundles, Recordings) -> Markdown   (pure)

Population availability evidence (the two bundles) is kept apart from identity and organisation
metadata, from station/site semantics, from route behaviour and from illustrative samples, so a
sample can never be read as support for a population-wide conclusion. Every recording must be
assigned a group here; an unassigned recording stops the build.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from evidence_bundle import bodies, receipts  # noqa: E402

GROUPS = (
    ("identity", "Identity and organisation metadata"),
    ("station_site", "Station-level and site-level instantaneous discharge"),
    ("routes", "Route behaviour"),
    ("samples", "Illustrative samples — not evidence for any population-wide conclusion"),
)
RECORDINGS: dict[str, tuple[str, str]] = {
    "sandre_wfs_stationhydro_all": ("identity", "Sandre `sa:StationHydro`: identity, position and `NomIntervenant` for the hydrometry stations it lists."),
    "sandre_wfs_stationmesure_producers": ("identity", "Sandre `sa:StationMesureEauxSurface`: `ProducteurDuJeu` for all 869 temperature stations."),
    "sandre_wfs_hyd_describe_stationhydro": ("identity", "Schema of `sa:StationHydro`: `NomIntervenant` is a bare string; no role is declared."),
    "sandre_wfs_stq_describe_stationmesure": ("identity", "Schema of `sa:StationMesureEauxSurface`: `ProducteurDuJeu` sits beside `DateDuJeuDeDonnee`, a dataset attribute."),
    "doc_sandre_hyd_layer_metadata": ("identity", "Sandre metadata for the hydrometric layers: collected yearly from SCHAPI; no definition of `NomIntervenant`'s role."),
    "doc_sandre_stq_dataset_metadata": ("identity", "Sandre metadata for the STQ referential: collected from its producers (Agences and Offices de l'Eau); station information falls under the measurement-network owners."),
    "doc_sandre_nomintervenant": ("identity", "Sandre dictionary: `NomIntervenant` is an organisation's name, with no role attached."),
    "doc_hydroportail_responsabilites_administratives": ("identity", "HydroPortail: an administrative responsibility is a collection arrangement under which an entity's data is communicated."),
    "doc_hydroportail_glossaire": ("identity", "HydroPortail glossary: an intervenant is an organisation; station managers (generally UH) administer the station referential."),
    "referentiel_stations_code_site": ("identity", "`code_site` is published alongside `code_station`: Y251002001 maps to Y2510020."),
    "hubeau_sites_grandeur_declaration": ("identity", "`grandeur_hydro` is `Q` for all 9,284 sites and `date_premiere_donnee_dispo_site` is empty for all: this metadata cannot establish availability."),
    "doc_hydroportail_station_hydrometrique": ("station_site", "HydroPortail: a site may carry several stations, at most one active at a time, and that one produces the site's discharge."),
    "doc_hydroportail_calendrier_site": ("station_site", "HydroPortail: stations on a site may succeed or alternate; the activation table traces which station supplies the site's data."),
    "doc_hubeau_api_hydrometrie": ("station_site", "Hub'Eau: a site is the carrier of discharge data; a station may carry stage and/or discharge. Receipted: the page embeds example observations."),
    "doc_sandre_stationhydro": ("station_site", "Sandre dictionary: a station's code is attached to its hydrometric site."),
    "hydroportail_Q_site_25210001_both_stations_report": ("station_site", "Site 25210001 Q series, 1–2 Sep 2026: 576 points."),
    "hydroportail_Q_station_2521000101_both_stations_report": ("station_site", "Station 2521000101 Q, same window: 576 points; equal to the site series at 1 of 576 instants."),
    "hydroportail_Q_station_2521000102_both_stations_report": ("station_site", "Station 2521000102 Q, same window: 576 points; equal to the site series at all 576 instants."),
    "hydroportail_Q_site_12320001_review_example": ("station_site", "Site 12320001 Q series, 1–8 Jun 2026: no point."),
    "hydroportail_Q_station_1232000101_review_example": ("station_site", "Station 1232000101 Q, same window: 282 points although the site series has none."),
    "hydroportail_Q_station_1232000102_review_example": ("station_site", "Station 1232000102 Q, same window: no point."),
    "observations_tr_Q_site_25210001_identities": ("station_site", "observations_tr addressed by site 25210001 returns rows for both stations and rows with a null `code_station`."),
    "observations_tr_Q_station_2521000101_identities": ("station_site", "observations_tr addressed by station 2521000101 returns that station only."),
    "observations_tr_Q_station_2521000102_identities": ("station_site", "observations_tr addressed by station 2521000102 returns that station only."),
    "observations_tr_Q_site_12320001_identities": ("station_site", "observations_tr addressed by site 12320001: count 0 in its 30 days."),
    "observations_tr_Q_station_1232000101_identities": ("station_site", "observations_tr addressed by station 1232000101: count 0 in its 30 days."),
    "observations_tr_Q_station_1232000102_identities": ("station_site", "observations_tr addressed by station 1232000102: count 0 in its 30 days."),
    "observations_tr_Y251002001_H": ("routes", "observations_tr answers for H, contrary to the port notes' record of a reproducible HTTP 500."),
    "observations_tr_Y251002001_Q": ("routes", "One captured HTTP 503 from observations_tr."),
    "observations_tr_Y251002001_Q_working": ("routes", "observations_tr answers for Q, with UTC timestamps and both `code_site` and `code_station`."),
    "observations_tr_horizon_30d_ok": ("routes", "A 30-day window is served."),
    "observations_tr_horizon_31d_rejected": ("routes", "Day 31 is refused with HTTP 400 `ValidateDateMin`."),
    "observations_tr_latest_H": ("routes", "Latest H instant on observations_tr at capture: 2026-09-08T12:15:00Z."),
    "hydroportail_recent_H": ("routes", "Latest H instant on HydroPortail at capture: 2026-09-08T12:15:00Z — the same instant as observations_tr."),
    "hydroportail_historical_2020_H": ("routes", "HydroPortail serves January 2020, beyond observations_tr's 30 days."),
    "obs_elab_QmnJ_count_1011000101": ("samples", "The count request shape: `size=1`, `fields=code_station`, no date filter."),
    "obs_elab_QmnJ_zero_count_valid_hydrometry_station": ("samples", "A count of 0 for QmnJ at hydrometry station 1232000102, in service."),
    "obs_elab_HIXnJ_count_same_station_entity_recognised": ("samples", "The same station, HIXnJ: count 237 and its own code returned — obs_elab recognises the entity."),
    "referentiel_stations_zero_count_station": ("samples", "The referential lists 1232000102 as a hydrometry station on site 12320001."),
    "obs_elab_QmnJ_zero_count": ("samples", "WRONG ENTITY, kept as a warning: `01004000` is a temperature station; the empty obs_elab answer shows an unknown entity also reads 0."),
    "obs_elab_batch_aggregate_count": ("samples", "`code_entite` accepts several codes but the count is their aggregate."),
    "obs_elab_sample_rows": ("samples", "obs_elab response fields for the daily products."),
    "temperature_chronique_count_01001336": ("samples", "The count request shape on the temperature route."),
    "temperature_chronique_sample_rows": ("samples", "temperature/chronique response fields."),
}  # fmt: skip


def main() -> None:
    here = pathlib.Path(__file__).resolve().parents[1]
    recordings = sorted((here / "recordings").glob("*.recording.json"))
    unassigned = sorted({p.name.removesuffix(".recording.json") for p in recordings} - set(RECORDINGS))
    if unassigned:
        raise SystemExit(f"recordings with no evidence group: {unassigned}")
    lines = [
        "# fr_hubeau — evidence index",
        "",
        "Generated by `scripts/build_evidence_index.py`. Every route surveyed is public and unauthenticated;",
        "no credentials, cookies or tokens were sent or stored.",
        "",
        "**Retention.** This project does not redistribute source observations. Every response is recorded",
        "with its exact request URL, HTTP status, media type, UTC acquisition instant, byte size and SHA-256",
        "of the full bytes. Bytes are kept whole only when the response carries no observation value; a",
        "response carrying observations keeps its receipt and derived readings (counts, identities,",
        "first and last instants) and its bytes are not kept. `scripts/observation_scan.py` enforces this",
        "and `tests/test_fr_hubeau_research_stores_no_observation_values.py` runs it in the suite.",
        "",
        "## 1. Population availability evidence",
        "",
        "Each inventory row names, in `evidence_refs`, the receipts it rests on (`hubeau:<id>`,",
        "`hydroportail:<id>`). Each bundle holds `receipts.csv` (every attempt, failed ones included) and",
        "the kept bodies. `scripts/verify_evidence.py` re-derives every reading and re-classifies every row.",
        "",
        "| Bundle | Receipts | Bodies kept | Size | Covers |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, covers in (
        (
            "hubeau_counts.tar.xz",
            "whole-record counts (daily, temperature) and 30-day counts (instantaneous), every baseline pair",
        ),
        (
            "hydroportail_history.tar.xz",
            "the fixed 682-pair HydroPortail station-series sample, one receipt per window per attempt",
        ),
    ):
        path = here / "evidence" / name
        lines.append(
            f"| [`evidence/{name}`](evidence/{name}) | {len(receipts(path)):,} | {len(bodies(path)):,} "
            f"| {path.stat().st_size:,} B | {covers} |"
        )
    lines += [
        "| [`evidence/station_site_comparison.json`](evidence/station_site_comparison.json) | — | — | "
        f"{(here / 'evidence' / 'station_site_comparison.json').stat().st_size:,} B | derived comparison of site and station Q series (§3 below) |",
        "",
    ]
    documents = {p.name.removesuffix(".recording.json"): json.loads(p.read_text(encoding="utf-8")) for p in recordings}
    for number, (group, title) in enumerate(GROUPS, start=2):
        lines += [
            f"## {number}. {title}",
            "",
            "| Recording | Status | Bytes | Kept | SHA-256 (first 16) | Retrieved (UTC) | Establishes |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for recording_id, (assigned, establishes) in RECORDINGS.items():
            if assigned != group:
                continue
            response = documents[recording_id]["response"]
            kept = "whole" if response["body_retained"] else "receipt + readings"
            lines.append(
                f"| [`{recording_id}`](recordings/{recording_id}.recording.json) | {response['status_code']} "
                f"| {response['response_bytes']:,} | {kept} | `{response['sha256'][:16]}` "
                f"| {response['retrieved_at'][:19]}Z | {establishes} |"
            )
        lines.append("")
    lines += [
        "## Historical procedure (not current verification or authority to acquire)",
        "",
        "```bash",
        "uv run python research/station-coverage/fr_hubeau/scripts/acquire_hubeau_counts.py <staging.zip>",
        "uv run python research/station-coverage/fr_hubeau/scripts/acquire_hydroportail_history.py <staging.zip>",
        "uv run python research/station-coverage/fr_hubeau/scripts/pack_evidence.py <hubeau_staging.zip> <hydroportail_staging.zip>",
        "uv run python research/station-coverage/fr_hubeau/scripts/capture_semantics_evidence.py",
        "uv run python research/station-coverage/fr_hubeau/scripts/build_inventory.py",
        "uv run python research/station-coverage/fr_hubeau/scripts/build_station_table.py",
        "uv run python research/station-coverage/fr_hubeau/scripts/build_evidence_index.py",
        "uv run python research/station-coverage/fr_hubeau/scripts/verify_evidence.py",
        "```",
        "",
        "Do not rerun these acquisition steps for delivery. Use verify_governing_evidence.py with the retained corpus.",
        "Historically, both acquisition scripts resumed from the packed bundle. A request settled only when answered",
        "(HTTP 200/206 with a parseable count, or HTTP 200 with a parseable series); every other attempt",
        "stays in the receipts as evidence and is attempted again on the next run.",
    ]
    (here / "evidence/HISTORICAL_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote evidence/HISTORICAL_INDEX.md covering {len(recordings)} recordings and 2 bundles")


if __name__ == "__main__":
    main()
