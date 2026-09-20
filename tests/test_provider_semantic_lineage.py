"""Publisher dictionaries, not station responses, establish product semantics."""

import json
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path

import pytest

from rivretrieve._internal.providers.cz_chmi.origins import build_acquisition_provenance as chmi_provenance
from rivretrieve._internal.providers.lt_lhmt.origins import build_acquisition_provenance as lhmt_provenance

ROOT = Path(__file__).parents[1]


class _DocumentText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())


def _recording_for_fact(provenance, fact, acquisition_id):
    (binding,) = (binding for binding in provenance.fact_bindings if fact in binding.facts)
    assert binding.acquisition_id == acquisition_id
    (canonical,) = (item for item in provenance.fact_bindings if "canonical.product_period" in item.facts)
    assert canonical.transformation is not None
    assert any(item.fact == fact for item in canonical.transformation.external_inputs)
    (source,) = (source for source in provenance.source_records if source.source_id == binding.source_id)
    (acquisition,) = (item for item in source.acquisitions if item.acquisition_id == acquisition_id)
    (recording,) = (
        item.recording for item in source.evidence if item.recording.recording_id in acquisition.recording_ids
    )
    content = (ROOT / recording.repository_path).read_bytes()
    assert sha256(content).hexdigest() == recording.sha256
    assert acquisition.requested_from == (recording.source_url,)
    assert acquisition.retrieved_at_start == recording.retrieved_at
    return recording, content


@pytest.mark.parametrize(
    "fact",
    ["source.product.native_identity", "source.product.daily_mean_semantics", "source.product.hourly_mean_semantics"],
)
def test_chmi_product_facts_resolve_to_publisher_dictionary(fact):
    provenance = chmi_provenance()
    recording, content = _recording_for_fact(provenance, fact, "product_semantics_capture_2026_09_02")
    assert recording.source_url == "https://opendata.chmi.cz/hydrology/historical/metadata/meta2.json"
    assert recording.repository_path == "tests/test_data/cz_meta2.json"
    table = json.loads(content)["data"]["data"]
    assert table["header"] == "TSCON_ID,TSCON_DS,UNIT_ID,UNIT_DS"
    rows = {row[0]: row for row in table["values"]}
    assert {code: rows[code] for code in ("HD", "QD", "TD", "HH", "QH")} == {
        "HD": ["HD", "Průměrné denní vodní stavy", "CM", "cm"],
        "QD": ["QD", "Průměrné denní průtoky", "M3_S", "m3/s"],
        "TD": ["TD", "Průměrné denní teploty vody", "0C", "°C"],
        "HH": ["HH", "Průměrné hodinové vodní stavy", "CM", "cm"],
        "QH": ["QH", "Průměrné hodinové průtoky", "M3_S", "m3/s"],
    }


@pytest.mark.parametrize(
    "fact",
    [
        "source.product.native_fields",
        "source.station.crs_documentation",
        "source.product.historical_daily_mean_semantics",
        "source.product.historical_time_zone",
    ],
)
def test_lhmt_product_and_crs_facts_resolve_to_api_documentation(fact):
    provenance = lhmt_provenance()
    recording, content = _recording_for_fact(provenance, fact, "terms_capture_2026_08_21")
    assert recording.source_url == "https://api.meteo.lt/"
    assert recording.repository_path == "tests/test_data/lt_lhmt_terms_licence.html"
    parser = _DocumentText()
    parser.feed(content.decode())
    text = " ".join(parser.parts)
    historical = text.rsplit("Stoties istoriniai hidrologiniai duomenys", 1)[1]
    assert "/hydro-stations/{station-code}/observations/historical/{date}" in historical
    assert "waterLevel - vandens lygis, cm. Vidurkis per parą." in historical
    assert "waterDischarge - vandens debitas, m 3 /s. Vidurkis per parą." in historical
    assert "observationDateUtc - atliktų stebėjimų data (UTC laiko juosta)." in historical
    assert "coordinates - stoties koordinatės (WGS 84 dešimtainiais laipsniais)." in historical


@pytest.mark.parametrize(
    "build,capture",
    [(chmi_provenance, "catalogue_capture_2026_08_02"), (lhmt_provenance, "catalogue_capture_2026_08_01")],
)
def test_station_values_retain_data_capture_lineage(build, capture):
    provenance = build()
    for fact in ("source.station.native_identity", "source.station.native_location"):
        (binding,) = (binding for binding in provenance.fact_bindings if fact in binding.facts)
        assert binding.acquisition_id == capture
    (binding,) = (binding for binding in provenance.fact_bindings if "source.observation.native_value" in binding.facts)
    assert binding.acquisition_id == "observation_request"
