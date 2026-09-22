"""Acquire an explicit all-types, test-inclusive public HydroPortail search."""

import argparse
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path

from rivretrieve._internal.transport import HttpClient, HttpMethod, TransportRequest


class SiteTypeOptions(HTMLParser):
    def __init__(self):
        super().__init__()
        self.options = {}
        self.site_types = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "select":
            self.site_types = attributes.get("name") == "hydro_entities_search[siteTypes][]"
        elif tag == "option" and self.site_types:
            value = attributes.get("value")
            if not value:
                raise ValueError("Published site type option has no value")
            self.options[f"hydro_entities_search[siteTypes][{len(self.options)}]"] = value

    def handle_endtag(self, tag):
        if tag == "select":
            self.site_types = False


def acquire(client, output, name, url, params=None):
    response = client.send(TransportRequest(HttpMethod.GET, url, params=params))
    (output / f"{name}.body").write_bytes(response.content)
    (output / f"{name}.receipt.json").write_text(
        json.dumps(
            {
                "url": url,
                "params": params,
                "status": response.status_code,
                "retrieved_at": response.retrieved_at.isoformat(),
                "content_type": response.content_type,
                "bytes": len(response.content),
                "sha256": hashlib.sha256(response.content).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
    if response.status_code != 200:
        raise ValueError(f"Source acquisition {name} failed: HTTP {response.status_code}")
    return response.content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    client = HttpClient()
    form = acquire(client, args.out, "search-form", "https://hydro.eaufrance.fr/rechercher/entites-hydrometriques")
    options = SiteTypeOptions()
    options.feed(form.decode())
    if not options.options:
        raise ValueError("No published site type controls found")
    params = {
        **options.options,
        "hydro_entities_search[active]": "1",
        "hydro_entities_search[closed]": "1",
        "hydro_entities_search[test]": "1",
    }
    acquire(
        client, args.out, "national-tests", "https://hydro.eaufrance.fr/rechercher/ajax/entites-hydrometriques", params
    )


if __name__ == "__main__":
    main()
