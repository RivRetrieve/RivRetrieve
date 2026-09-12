"""Capture the official evidence for station/site discharge, organisation fields and a valid zero count.

    capture_all : () -> Recordings + evidence/station_site_comparison.json   (network)

Three groups, each answering a review question from the publisher's own responses and pages:

1. Station-level vs site-level instantaneous discharge. For shared sites, the site series
   (`/sitehydro/ajax/{code_site}/series`, the production route) and each linked station's series
   (`/stationhydro/ajax/{code_station}/series`) over the same window, plus `observations_tr` addressed
   by site and by station with identity fields only. The series bodies carry observations, so they
   are receipted; their comparison - points, shared instants, instants whose values are equal - is
   computed in memory and written as a derived reading. No value is written.
2. Official explanations: HydroPortail help pages, the Hub'Eau hydrometry page, Sandre dictionary
   entries, the Sandre layer metadata and WFS schemas, each with the exact passages relied on.
3. A zero count for a valid hydrometry station and an applicable measurement, with the same station's
   positive count on another daily measurement showing that the route recognises the entity.

Usage: uv run python research/station-coverage/fr_hubeau/scripts/capture_semantics_evidence.py
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from capture import capture  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parents[1]
HYDROPORTAIL = "https://hydro.eaufrance.fr"
HUBEAU = "https://hubeau.eaufrance.fr/api/v2/hydrometrie"
SANDRE_ATLAS = "https://www.sandre.eaufrance.fr/atlas/srv/api/records"

# (label, window, code_site, linked stations) - both sites carry two stations in the committed baseline.
SHARED_SITES = (
    ("both_stations_report", ("01/09/2026", "02/09/2026"), "25210001", ("2521000101", "2521000102")),
    ("review_example", ("01/06/2026", "08/06/2026"), "12320001", ("1232000101", "1232000102")),
)
ZERO_COUNT_STATION = "1232000102"

DOCUMENTS = (
    (
        "doc_hydroportail_station_hydrometrique",
        f"{HYDROPORTAIL}/aide/la-station-hydrometrique",
        None,
        (
            "Un site peut comporter plusieurs stations, dont l'une au plus est active à un instant donné : c'est elle qui produit le débit du site.",
            "Les organismes gestionnaires de la station sont accessibles via le menu Responsabilités administratives",
        ),
    ),
    (
        "doc_hydroportail_calendrier_site",
        f"{HYDROPORTAIL}/aide/le-calendrier-du-site-hydrometrique",
        None,
        (
            "Un site peut-être équipé de plusieurs stations se succédant dans le temps, ou fonctionnement alternativement (ex : lors de débordements et de contournements).",
            "Le tableau des périodes d’activations permet de suivre les conditions de production de données, en retraçant la station utilisée pour remonter les données au niveau du site.",
        ),
    ),
    (
        "doc_hydroportail_responsabilites_administratives",
        f"{HYDROPORTAIL}/aide/responsabilites-administratives",
        None,
        (
            "Une responsabilité administrative correspond à un dispositif de collecte (organisme ou réseau).",
            "La donnée mentionnée dans les propriétés de l'entité (menu à gauche de la page) est communiquée sous la responsabilité du dispositif de collecte sélectionné.",
        ),
    ),
    (
        "doc_hydroportail_glossaire",
        f"{HYDROPORTAIL}/glossaire",
        None,
        (
            "Dans la terminologie utilisée dans HydroPortail, l'intervenant désigne les organismes ou sociétés.",
            "le rôle d'administrateur le droit aux gestionnaires (généralement UH) de gérer le référentiel de la station",
        ),
    ),
    (
        "doc_hubeau_api_hydrometrie",
        "https://hubeau.eaufrance.fr/page/api-hydrometrie",
        None,
        (
            "Un site peut posséder une ou plusieurs stations ; il est support de données de débit (Q).",
            "Une station peut porter des observations de hauteur et/ou de débit (directement mesurés ou calculés à partir d'une courbe de tarage).",
        ),
    ),
    (
        "doc_sandre_stationhydro",
        "https://www.sandre.eaufrance.fr/definition/HYD/2.3/StationHydro",
        None,
        ("La station est identifiée par un code rattaché au site hydrométrique.",),
    ),
    (
        "doc_sandre_nomintervenant",
        "https://www.sandre.eaufrance.fr/definition/INT/2.0/NomIntervenant",
        None,
        ("Le nom de l'intervenant est son appellation courante ou sa dénomination sociale intégrale.",),
    ),
    (
        "doc_sandre_hyd_layer_metadata",
        f"{SANDRE_ATLAS}/cae2a6c7-4429-4c89-9da2-44ada7735520",
        None,
        ("Les données diffusée sont collectées chaque année par le SANDRE auprès du SCHAPI",),
    ),
    (
        "doc_sandre_stq_dataset_metadata",
        f"{SANDRE_ATLAS}/daccef28-6b30-4441-a641-b04afe15e82f",
        None,
        (
            "Les données diffusées sont collectées au moins une fois par mois par le SANDRE auprès des producteurs (Agences de l'eau et Offices de l'Eau).",
            "Ces informations sont administrées par les Agences de l'Eau et les Offices de l'Eau et relèvent de la responsabilité du ou des maîtres d'ouvrages des réseaux de mesure ou utilisations auxquelles la station est rattachée.",
        ),
    ),
    (
        "sandre_wfs_hyd_describe_stationhydro",
        "https://services.sandre.eaufrance.fr/geo/hyd",
        {"service": "WFS", "version": "2.0.0", "request": "DescribeFeatureType", "typeNames": "sa:StationHydro"},
        (),
    ),
    (
        "sandre_wfs_stq_describe_stationmesure",
        "https://services.sandre.eaufrance.fr/geo/stq",
        {"service": "WFS", "version": "2.0.0", "request": "DescribeFeatureType", "typeNames": "sa:StationMesureEauxSurface"},
        (),
    ),
)  # fmt: skip


def series_params(window: tuple[str, str]) -> dict[str, str]:
    return {
        "hydro_series[startAt]": window[0],
        "hydro_series[endAt]": window[1],
        "hydro_series[variableType]": "simple_and_interpolated_and_hourly_variable",
        "hydro_series[simpleAndInterpolatedAndHourlyVariable]": "Q",
        "hydro_series[statusData]": "raw",
    }


def points(raw: bytes) -> dict[str, object]:
    return {row["t"]: row["v"] for row in (json.loads(raw).get("series") or {}).get("data") or []}


def recorded(path: pathlib.Path) -> dict[str, object]:
    response = json.loads(path.read_text(encoding="utf-8"))["response"]
    return {"recording": path.name, "sha256": response["sha256"], "status_code": response["status_code"]}


def shared_sites() -> list[dict[str, object]]:
    comparisons: list[dict[str, object]] = []
    for label, window, site, stations in SHARED_SITES:
        site_path, site_raw = capture(
            f"hydroportail_Q_site_{site}_{label}", f"{HYDROPORTAIL}/sitehydro/ajax/{site}/series", series_params(window)
        )
        site_points = points(site_raw)
        entry: dict[str, object] = {
            "label": label,
            "window": f"{window[0]} - {window[1]}",
            "code_site": site,
            "site_series": {**recorded(site_path), "points": len(site_points)},
            "stations": [],
        }
        for station in stations:
            path, raw = capture(
                f"hydroportail_Q_station_{station}_{label}",
                f"{HYDROPORTAIL}/stationhydro/ajax/{station}/series",
                series_params(window),
            )
            station_points = points(raw)
            shared = set(site_points) & set(station_points)
            entry["stations"].append(  # type: ignore[union-attr]
                {
                    **recorded(path),
                    "code_station": station,
                    "points": len(station_points),
                    "instants_shared_with_site": len(shared),
                    "shared_instants_with_equal_value": sum(site_points[t] == station_points[t] for t in shared),
                }
            )
        for code, kind in ((site, "site"), *((station, "station") for station in stations)):
            capture(
                f"observations_tr_Q_{kind}_{code}_identities",
                f"{HUBEAU}/observations_tr",
                {"code_entite": code, "grandeur_hydro": "Q", "size": "20", "fields": "code_site,code_station,date_obs"},
            )
        comparisons.append(entry)
    return comparisons


def main() -> None:
    for recording_id, url, params, quotes in DOCUMENTS:
        capture(recording_id, url, params, quotes)

    capture(
        "obs_elab_QmnJ_zero_count_valid_hydrometry_station",
        f"{HUBEAU}/obs_elab",
        {"code_entite": ZERO_COUNT_STATION, "grandeur_hydro_elab": "QmnJ", "size": "1", "fields": "code_station"},
    )
    capture(
        "obs_elab_HIXnJ_count_same_station_entity_recognised",
        f"{HUBEAU}/obs_elab",
        {"code_entite": ZERO_COUNT_STATION, "grandeur_hydro_elab": "HIXnJ", "size": "1", "fields": "code_station"},
    )
    capture(
        "referentiel_stations_zero_count_station",
        f"{HUBEAU}/referentiel/stations",
        {"code_station": ZERO_COUNT_STATION},
    )

    comparison = {
        "method": (
            "Site and station Q series requested over the same window; values compared in memory at "
            "identical instants. Only counts are written; no value is stored."
        ),
        "shared_sites": shared_sites(),
    }
    out = HERE / "evidence" / "station_site_comparison.json"
    out.write_text(json.dumps(comparison, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"comparison -> {out.name}")


if __name__ == "__main__":
    main()
