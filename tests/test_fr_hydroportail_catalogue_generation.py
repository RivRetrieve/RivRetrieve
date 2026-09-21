import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rivretrieve._internal.catalogues.native import RetrievedAt
from rivretrieve._internal.providers.fr_hydroportail.generate_catalogue import decode_inventory, read_inventory

EVIDENCE = Path(__file__).resolve().parents[1] / "maintenance/catalogue/fr_hydroportail/evidence"


def station_body():
    return [
        {
            "bookmarkCode": "SITE",
            "entityType": "site",
            "coordinates": {"x": 99, "y": 55},
            "stations": [
                {
                    "bookmarkCode": "FULL000001",
                    "entityType": "station",
                    "label": "Native label",
                    "entityStatus": "closed",
                    "isEntityAccessLimited": False,
                    "coordinates": {"x": 1.1234567, "y": None},
                }
            ],
        }
    ]


def decode(body):
    return decode_inventory(json.dumps(body).encode(), RetrievedAt(datetime(2026, 9, 21, tzinfo=UTC)))


def test_native_station_coordinates_never_use_site_coordinates():
    row = decode(station_body()).data.row(0, named=True)
    assert row["bookmarkCode"] == "FULL000001"
    assert row["site_code"] == "SITE"
    assert row["x"] == 1.1234567
    assert row["y"] is None
    assert row["entityStatus"] == "closed"


def test_population_is_not_frozen():
    body = station_body()
    second = json.loads(json.dumps(body[0]))
    second["bookmarkCode"] = "ANOTHER_SITE"
    second["stations"][0]["bookmarkCode"] = "ANOTHER_FULL_CODE"
    assert decode(body + [second]).data.height == 2


def test_duplicate_full_identity_refused():
    body = station_body()
    body[0]["stations"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        decode(body)


@pytest.mark.parametrize("value", [True, float("nan"), 181, "1.2"])
def test_invalid_coordinate_refused(value):
    body = station_body()
    body[0]["stations"][0]["coordinates"]["x"] = value
    with pytest.raises(ValueError, match="coordinate"):
        decode(body)


def test_retained_capture_identity():
    native, receipt = read_inventory(EVIDENCE / "national-tests.body", EVIDENCE / "national-tests.receipt.json")
    assert native.data.height > 0
    assert receipt["params"]["hydro_entities_search[test]"] == "1"


@pytest.mark.parametrize(
    ("field", "value"), [("entityStatus", "guessed"), ("label", None), ("isEntityAccessLimited", "false")]
)
def test_invalid_native_metadata_refused(field, value):
    body = station_body()
    body[0]["stations"][0][field] = value
    with pytest.raises(ValueError, match="metadata"):
        decode(body)


def test_history_projection_keeps_only_native_scopes():
    import lzma

    from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import decode_availability
    from rivretrieve._internal.providers.fr_hydroportail.generate_catalogue import project_availability

    history = decode_availability(
        lzma.decompress((EVIDENCE.parents[1] / "fr_hubeau/inventory/governing_evidence.json.xz").read_bytes())
    )
    native, _ = read_inventory(EVIDENCE / "national-tests.body", EVIDENCE / "national-tests.receipt.json")
    pairs = project_availability(tuple(native.data["bookmarkCode"].to_list()), history)
    expected_witnesses = {
        (p.code_station, p.product_id) for p in history.pairs if p.basis == "historical_positive_witness"
    }
    assert {(p.station_id, p.product_id) for p in pairs if p.status == "available"} == expected_witnesses
    old = {(p.code_station, p.product_id): p for p in history.pairs}
    for pair in pairs:
        prior = old.get((pair.station_id, pair.product_id))
        assert pair.acquisitions == (
            tuple(a for a in prior.acquisitions if a.role == "historical_check") if prior else ()
        )
        assert all(a.role == "historical_check" for a in pair.acquisitions)
        if not pair.acquisitions:
            assert pair.status == "history_unchecked"
            assert pair.witness_points is None


@pytest.mark.parametrize("mutation", ["missing_x", "blank_station", "blank_site"])
def test_missing_required_native_identity_or_coordinate_is_not_null(mutation):
    body = station_body()
    if mutation == "missing_x":
        del body[0]["stations"][0]["coordinates"]["x"]
    elif mutation == "blank_station":
        body[0]["stations"][0]["bookmarkCode"] = "   "
    else:
        body[0]["bookmarkCode"] = "   "
    with pytest.raises(ValueError):
        decode(body)


def test_current_form_options_match_captured_native_query():
    import runpy

    script = EVIDENCE.parent / "scripts/acquire_inventory.py"
    namespace = runpy.run_path(str(script))
    parser = namespace["SiteTypeOptions"]()
    parser.feed((EVIDENCE / "search-form.body").read_text())
    receipt = json.loads((EVIDENCE / "national-tests.receipt.json").read_bytes())
    assert parser.options
    assert parser.options == {
        k: v for k, v in receipt["params"].items() if k.startswith("hydro_entities_search[siteTypes]")
    }


def test_source_capture_receipt_tamper_refused(tmp_path):
    receipt = json.loads((EVIDENCE / "national-tests.receipt.json").read_bytes())
    receipt["bytes"] += 1
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="identity mismatch"):
        read_inventory(EVIDENCE / "national-tests.body", path)
