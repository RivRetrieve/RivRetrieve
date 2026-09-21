import json

from acquire import get, out

codes = [entry["station_id"] for entry in json.loads((out / "unmatched-stations.json").read_bytes())]
for code in codes:
    name = "missing-" + code
    if not (out / (name + ".body")).exists():
        try:
            get(name, "https://hydro.eaufrance.fr/stationhydro/" + code + "/fiche")
        except Exception as exc:
            (out / (name + ".failure.json")).write_text(json.dumps({"error": repr(exc)}))
