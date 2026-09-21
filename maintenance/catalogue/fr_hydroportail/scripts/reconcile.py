import json
import lzma
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[4]
out = Path(__file__).resolve().parents[1] / "evidence"


def load(n):
    if n in {"hubeau-stations-valid", "hubeau-temperature"}:
        filename = (
            "hydrometry-stations-2026-09-21.json.xz"
            if n == "hubeau-stations-valid"
            else "temperature-stations-2026-09-21.json.xz"
        )
        return json.loads(lzma.decompress((root / "maintenance/catalogue/fr_hubeau/inventory" / filename).read_bytes()))
    return json.loads((out / (n + ".body")).read_bytes())


def stations(n):
    sites = load(n)
    rows = [dict(s, site_code=site["bookmarkCode"]) for site in sites for s in site["stations"]]
    assert len(rows) == len({s["bookmarkCode"] for s in rows})
    assert all(s["entityType"] == "station" for s in rows)
    return {s["bookmarkCode"]: s for s in rows}


hb = {s["code_station"]: s for s in load("hubeau-stations-valid")["data"]}
old = {
    s["code_station"]: s
    for s in json.loads((root / "tests/test_data/fr_hubeau_referentiel_stations_full.json").read_text())["data"]
}
base = stations("national-alltypes")
native = stations("national-tests")
missing = sorted(hb.keys() - native.keys())
metadata = []
for code, s in native.items():
    h = hb[code]
    lon, lat = h["longitude_station"], h["latitude_station"]
    if h["code_projection"] == 31:
        assert h["coordonnee_x_station"] == lat and h["coordonnee_y_station"] == lon
        lon, lat = lat, lon
    metadata.append(
        {
            "station_id": code,
            "label_equal": s["label"] == h["libelle_station"],
            "site_equal": s["site_code"] == h["code_site"],
            "native_x": s["coordinates"]["x"],
            "native_y": s["coordinates"]["y"],
            "hubeau_longitude_after_projection31_correction": lon,
            "hubeau_latitude_after_projection31_correction": lat,
            "maximum_coordinate_difference": max(abs(s["coordinates"]["x"] - lon), abs(s["coordinates"]["y"] - lat)),
        }
    )
(out / "metadata-comparison.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
gaps = []
for code in missing:
    p = out / ("missing-" + code + ".receipt.json")
    gaps.append(
        {
            "station_id": code,
            "old_supported": code in old,
            "hub_native": hb[code],
            "native_identity_response": json.loads(p.read_text()) if p.exists() else None,
        }
    )
(out / "unmatched-stations.json").write_text(json.dumps(gaps, ensure_ascii=False, indent=2))
summary = {
    "hubeau": len(hb),
    "hubeau_old": len(old),
    "hubeau_added": sorted(hb.keys() - old.keys()),
    "hubeau_removed": sorted(old.keys() - hb.keys()),
    "hydroportail_sites": len(load("national-tests")),
    "hydroportail_stations": len(native),
    "hydroportail_status": dict(Counter(s["entityStatus"] for s in native.values())),
    "test_filter_additions": sorted(native.keys() - base.keys()),
    "missing_current": len(missing),
    "missing_old": len(set(missing) & old.keys()),
    "missing_identity_status": dict(
        Counter(
            g["native_identity_response"]["status"] if g["native_identity_response"] else "unchecked_or_failed"
            for g in gaps
        )
    ),
    "label_differences": sum(not m["label_equal"] for m in metadata),
    "site_differences": sum(not m["site_equal"] for m in metadata),
    "maximum_coordinate_difference": max(m["maximum_coordinate_difference"] for m in metadata),
    "coordinate_differences_over_1e_6": [m for m in metadata if m["maximum_coordinate_difference"] > 1e-6],
    "hubeau_temperature": load("hubeau-temperature")["count"],
}
(out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
print(
    json.dumps(
        {
            k: v
            for k, v in summary.items()
            if k not in ["coordinate_differences_over_1e_6", "test_filter_additions", "hubeau_added"]
        },
        indent=2,
    )
)
