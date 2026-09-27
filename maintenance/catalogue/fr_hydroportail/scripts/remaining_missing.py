"""Acquire missing identity pages into a new explicit evidence directory."""

import argparse
import json
from pathlib import Path

from acquire_inventory import acquire

from rivretrieve._internal.transport import HttpClient, TransportFailure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gaps", type=Path, required=True, help="Regenerated unmatched-stations.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    client = HttpClient()
    codes = [entry["station_id"] for entry in json.loads(args.gaps.read_bytes())]
    for code in codes:
        if not isinstance(code, str) or not code.isalnum():
            raise ValueError("Invalid full source station code")
        name = "missing-" + code
        if (args.out / (name + ".receipt.json")).exists():
            continue
        try:
            acquire(client, args.out, name, "https://hydro.eaufrance.fr/stationhydro/" + code + "/fiche")
        except (TransportFailure, ValueError) as exc:
            (args.out / (name + ".failure.json")).write_text(json.dumps({"error": repr(exc)}))


if __name__ == "__main__":
    main()
