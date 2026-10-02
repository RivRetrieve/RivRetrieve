import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import requests  # noqa: TID251 - independent publisher research, not provider transport
from pypdf import PdfReader

parser = argparse.ArgumentParser(description="Check CHMI source pages and retain fresh responses externally.")
parser.add_argument("--out", type=Path, required=True, help="External directory for new source responses.")
args = parser.parse_args()
out = args.out.expanduser().resolve()
if any((parent / ".git").exists() for parent in (out, *out.parents)):
    parser.error("--out must be outside source checkouts")
out.mkdir(parents=True, exist_ok=True)
urls = {
    "institution": "https://www.chmi.cz/o-chmu",
    "open-data": "https://www.chmi.cz/o-chmu/produkty-a-sluzby/data-a-vyhodnoceni",
    "annual": "https://opendata.chmi.cz/hydrology/historical/data/daily/H_0-203-1-180100_DQ_2020.json",
    "hydrology": "https://opendata.chmi.cz/hydrology/",
    "description": "https://opendata.chmi.cz/hydrology/read_me/Popis_datovych_sad_historical.pdf",
    "meta2": "https://opendata.chmi.cz/hydrology/historical/metadata/meta2.json",
    "meta1": "https://opendata.chmi.cz/hydrology/historical/metadata/meta1.json",
    "terms": "https://www.chmi.cz/vylou%C4%8Den%C3%AD-odpov%C4%9Bdnosti",
}
for name, url in urls.items():
    response = requests.get(url, timeout=45)
    print(
        json.dumps(
            {
                "name": name,
                "url": url,
                "final_url": response.url,
                "status": response.status_code,
                "retrieved_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    response.raise_for_status()
    suffix = ".pdf" if name == "description" else ".txt"
    path = out / (name + suffix)
    path.write_bytes(response.content)
    if suffix == ".pdf":
        (out / (name + ".txt")).write_text("\n".join(page.extract_text() for page in PdfReader(path).pages))
