"""Exact request URL attestations : PackagedProvenance → RequestLists."""

from __future__ import annotations

import json
from pathlib import Path


def _acquisition(provider: str, acquisition_id: str) -> dict[str, object]:
    path = Path("src/rivretrieve/_internal/providers") / provider / "catalogue" / "provenance.json"
    document = json.loads(path.read_text())
    return next(
        a for s in document["source_records"] for a in s["acquisitions"] if a["acquisition_id"] == acquisition_id
    )


def test_south_africa_archive_capture_names_all_exact_recorded_requests() -> None:
    expected = [
        "http://web.archive.org/web/20260311133455id_/https://www.dws.gov.za/hydrology/Verified/HyCatalogue.aspx",
        "http://web.archive.org/web/20251122081546id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA1_Limpopo-Olifants_River.pdf",
        "http://web.archive.org/web/20251127140120id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA2_Inkomati-Usuthu_River.pdf",
        "http://web.archive.org/web/20251127181748id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA3_Pongola-Mtamvuna_River.pdf",
        "http://web.archive.org/web/20251126040946id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA4_Vaal-Orange_River.pdf",
        "http://web.archive.org/web/20251127142153id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA5_Mzimvubu-Tsitsikamma_River.pdf",
        "http://web.archive.org/web/20251121090856id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA6_Breede-Olifants_River.pdf",
        "http://web.archive.org/web/20251121161554id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA7_Eswatini_River.pdf",
        "http://web.archive.org/web/20251121113702id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA8_Lesotho_River.pdf",
    ]
    assert _acquisition("za_dws", "verified_hydrology_archive_campaign_2026_08_02")["requested_from"] == expected


def test_france_catalogue_capture_names_all_exact_recorded_requests() -> None:
    expected = [
        *(
            f"https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?size=1000&page={page}&format=json"
            for page in range(1, 8)
        ),
        "https://hubeau.eaufrance.fr/api/v1/temperature/station?size=2000&format=json",
    ]
    hydrometry = _acquisition("fr_hubeau", "hydrometry_catalogue_capture_2026_08_02")
    temperature = _acquisition("fr_hubeau", "temperature_catalogue_capture_2026_08_02")
    assert hydrometry["requested_from"] == expected[:-1]
    assert hydrometry["retrieved_at_start"] == "2026-08-02T17:32:58Z"
    assert temperature["requested_from"] == expected[-1:]
    assert temperature["retrieved_at_start"] == "2026-08-02T17:33:34Z"
    path = Path("src/rivretrieve/_internal/providers/fr_hubeau/catalogue/provenance.json")
    bindings = {
        fact: item["acquisition_id"]
        for item in json.loads(path.read_text())["fact_bindings"]
        for fact in item["facts"]
        if item.get("acquisition_id")
    }
    assert bindings["source.product.hydrometry_api_semantics"] == hydrometry["acquisition_id"]
    assert bindings["source.product.temperature_api_semantics"] == temperature["acquisition_id"]
