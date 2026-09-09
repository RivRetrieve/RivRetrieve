"""Compose the station x product evidence inventory for fr_hubeau.

Sources, in the order they settle a pair:

  daily and temperature  - the publisher's own `count` from obs_elab / temperature/chronique with no
                           date filter, so the figure is that station's whole record rather than a
                           sampled window
  instantaneous          - `observations_tr` count over its rolling 30-day window, then, for pairs
                           reading zero at an in-service station, a HydroPortail probe over two
                           windows outside that horizon

Status vocabulary (non-interchangeable, per issue #222):
  available                - the publisher reports at least one observation for the pair
  empty_no_data_published  - the publisher reports a total of zero over the station's whole record
  empty_in_tested_window   - zero within a tested window, where no whole-record total is available
  uninvestigated           - not resolved by this survey; never a claim about the source
  access_failed            - the request did not complete; never a claim about the source

There is deliberately no "unsupported" status: no recorded evidence states that a station cannot
supply a measurement.
"""

from __future__ import annotations

import base64
import json
import pathlib

import pandas as pd

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = pathlib.Path(__file__).resolve().parents[3].parent
NATIVE = ROOT / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet"
INVENTORY = HERE / "inventory"


def _producers() -> dict[str, str]:
    """Map station code to its producing body, from the two Sandre WFS captures."""
    producers: dict[str, str] = {}
    for name, code_field, producer_field in (
        ("sandre_wfs_stationhydro_all", "CdStationHydro", "NomIntervenant"),
        ("sandre_wfs_stationmesure_producers", "CdStationMesureEauxSurface", "ProducteurDuJeu"),
    ):
        document = json.loads((HERE / "recordings" / f"{name}.recording.json").read_text())
        payload = json.loads(base64.b64decode(document["response"]["content_base64"]))
        for feature in payload.get("features") or []:
            properties = feature.get("properties") or {}
            code = str(properties.get(code_field) or "")
            value = properties.get(producer_field)
            if code and value and str(value).strip():
                producers[code] = str(value).strip()
    return producers


def _text(value: object) -> str:
    """Cell text with pandas' NaN treated as empty. `str(nan)` is "nan", which is truthy."""
    if value is None or (isinstance(value, float) and value != value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _number(value: object) -> float | None:
    """Cell value as a float, with NaN and blanks treated as absent."""
    if value is None or (isinstance(value, float) and value != value):
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _settled(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep one row per pair, preferring a row that carries a count."""
    frame = frame.copy()
    frame["n"] = pd.to_numeric(frame["count"], errors="coerce")
    frame["has_count"] = frame.n.notna()
    frame = frame.sort_values("has_count").drop_duplicates(["code_station", "product_id"], keep="last")
    return frame


def main() -> None:
    native = pd.read_parquet(NATIVE)
    hydro = native[native.source_endpoint == "hydrometrie/referentiel/stations"]
    temperature = native[native.source_endpoint == "temperature/station"]
    meta: dict[str, dict[str, str]] = {
        _text(row.code_station): {
            "code_site": _text(row.code_site),
            "libelle_station": _text(row.libelle_station),
            "libelle_cours_eau": _text(row.libelle_cours_eau),
            "libelle_departement": _text(row.libelle_departement),
            "en_service": _text(row.en_service),
            "endpoint": _text(row.source_endpoint),
        }
        for row in native.itertuples()
    }
    producers = _producers()

    daily = _settled(pd.read_csv(INVENTORY / "hubeau_counts.csv", dtype=str))
    instant = _settled(pd.read_csv(INVENTORY / "instantaneous_counts.csv", dtype=str))
    history_path = INVENTORY / "instantaneous_history.csv"
    history: dict[tuple[str, str], tuple[float, str]] = {}
    if history_path.exists():
        for row in pd.read_csv(history_path, dtype=str).itertuples():
            first = _number(row.points_window_1)
            second = _number(row.points_window_2)
            if _text(row.request_error):
                continue
            points = (first or 0.0) + (second or 0.0)
            history[(_text(row.code_station), _text(row.product_id))] = (points, _text(row.windows))

    records: list[dict[str, object]] = []

    for row in daily.itertuples():
        station = _text(row.code_station)
        info = meta.get(station, {})
        observations = _number(row.n)
        if _text(row.request_error) or observations is None:
            status, basis = "access_failed", f"request did not complete: {row.request_error}"
        elif observations > 0:
            status = "available"
            basis = f"publisher reports {int(observations)} observations over the station's whole record"
        else:
            status = "empty_no_data_published"
            basis = "publisher reports a total of zero over the station's whole record (no date filter applied)"
        records.append(
            {
                "code_station": station,
                "code_site": info.get("code_site", ""),
                "station_name": info.get("libelle_station", ""),
                "river": info.get("libelle_cours_eau", ""),
                "departement": info.get("libelle_departement", ""),
                "en_service": info.get("en_service", ""),
                "producer": producers.get(station, ""),
                "product_id": _text(row.product_id),
                "native_field": _text(row.native_field),
                "route": _text(row.route),
                "status": status,
                "evidence_basis": basis,
                "observations": "" if observations is None else int(observations),
                "window": "whole record (no date filter)",
                "probed_at": _text(row.probed_at),
            }
        )

    for row in instant.itertuples():
        station = _text(row.code_station)
        info = meta.get(station, {})
        probed = history.get((station, _text(row.product_id)))
        observed: int | None = None
        observations = _number(row.n)
        if _text(row.request_error) or observations is None:
            status, basis, window = (
                "access_failed",
                f"request did not complete: {_text(row.request_error)}",
                _text(row.window),
            )
        elif observations > 0:
            status = "available"
            basis = f"observations_tr reports {int(observations)} observations in its rolling 30-day window"
            window = _text(row.window)
        elif probed is not None:
            probed_points, probed_windows = probed
            window = f"30-day real-time window, then HydroPortail {probed_windows}"
            if probed_points > 0:
                status = "available"
                observed = int(probed_points)
                basis = f"zero on the 30-day route, but HydroPortail returned {observed} points outside that horizon"
            else:
                status = "empty_in_tested_window"
                basis = (
                    "zero on the 30-day route and no points from HydroPortail in either probed window; "
                    "the source states nothing about support"
                )
        elif info.get("en_service") == "False":
            status = "empty_in_tested_window"
            basis = (
                "zero in the 30-day real-time window at a station the referential marks out of service; "
                "not probed against HydroPortail and not a claim about the source"
            )
            window = _text(row.window)
        else:
            status = "uninvestigated"
            basis = (
                "zero in the 30-day real-time window at an in-service station, outside the bounded "
                "HydroPortail sample; unresolved, and deliberately not recorded as absence"
            )
            window = _text(row.window)
        records.append(
            {
                "code_station": station,
                "code_site": info.get("code_site", ""),
                "station_name": info.get("libelle_station", ""),
                "river": info.get("libelle_cours_eau", ""),
                "departement": info.get("libelle_departement", ""),
                "en_service": info.get("en_service", ""),
                "producer": producers.get(station, ""),
                "product_id": _text(row.product_id),
                "native_field": _text(row.native_field),
                "route": _text(row.route),
                "status": status,
                "evidence_basis": basis,
                "observations": observed
                if observed is not None
                else ("" if observations is None else int(observations)),
                "window": window,
                "probed_at": _text(row.probed_at),
            }
        )

    frame = pd.DataFrame(records).sort_values(["code_station", "product_id"])
    path = INVENTORY / "station_product_evidence.csv"
    frame.to_csv(path, index=False)

    expected = len(hydro) * 5 + len(temperature)
    assert len(frame) == expected, f"expected {expected} rows, got {len(frame)}"
    assert set(frame.code_station) == set(native.code_station.astype(str)), "every baseline station must appear"
    print(f"wrote {len(frame)} rows / {frame.code_station.nunique()} stations -> {path.name}\n")
    print(pd.crosstab(frame.product_id, frame.status).to_string())


if __name__ == "__main__":
    main()
