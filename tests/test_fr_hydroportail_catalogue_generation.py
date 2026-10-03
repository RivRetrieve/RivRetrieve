import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rivretrieve._internal.catalogues.native import RetrievedAt
from rivretrieve._internal.providers.fr_hydroportail.generate_catalogue import decode_inventory, read_inventory

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path("maintenance/catalogue/fr_hydroportail/evidence")


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


@pytest.mark.governing("maintenance/catalogue/fr_hydroportail/evidence")
def test_retained_capture_identity(retained_evidence_root):
    native, receipt = read_inventory(
        retained_evidence_root / EVIDENCE / "national-tests.body",
        retained_evidence_root / EVIDENCE / "national-tests.receipt.json",
    )
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


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
@pytest.mark.governing("maintenance/catalogue/fr_hydroportail/evidence")
def test_history_projection_keeps_only_native_scopes(retained_evidence_root):
    import lzma

    from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import decode_availability
    from rivretrieve._internal.providers.fr_hydroportail.generate_catalogue import project_availability

    history = decode_availability(
        lzma.decompress(
            (
                retained_evidence_root / "maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz"
            ).read_bytes()
        )
    )
    native, _ = read_inventory(
        retained_evidence_root / EVIDENCE / "national-tests.body",
        retained_evidence_root / EVIDENCE / "national-tests.receipt.json",
    )
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


@pytest.mark.governing("maintenance/catalogue/fr_hydroportail/evidence")
def test_source_capture_receipt_tamper_refused(retained_evidence_root, tmp_path):
    receipt = json.loads((retained_evidence_root / EVIDENCE / "national-tests.receipt.json").read_bytes())
    receipt["bytes"] += 1
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="identity mismatch"):
        read_inventory(retained_evidence_root / EVIDENCE / "national-tests.body", path)


@pytest.mark.parametrize("quantity", ["discharge", "stage"])
def test_packaged_catalogue_exposes_independent_source_variants(quantity):
    import rivretrieve as rr
    from rivretrieve._internal.source_series import stable_id

    selection = rr.find(provider="fr_hydroportail", station="Y251002001", quantity=quantity, statistic="instantaneous")
    expected = {"raw", "validated", "pre_validated_and_validated", "most_valid"}
    assert set(rr.series(selection)["variant"]) == expected
    namespace = "fr_hydroportail/Q" if quantity == "discharge" else "fr_hydroportail/H"
    for variant in expected:
        selected = rr.pick(selection, variant=variant)
        assert len(selected.series) == 1
        source = selected.series[0]
        assert source.identity.published_id == variant
        assert source.series_id == stable_id("fr_hydroportail", "Y251002001", namespace, variant)
    assert len({item.series_id for item in selection.series}) == 4


@pytest.mark.derived("maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz")
def test_catalogue_availability_witnesses_remain_raw_scoped(
    retained_evidence_root,
):
    import lzma

    import polars as pl

    from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import decode_availability

    root = ROOT
    packaged = root / "src/rivretrieve/_internal/providers/fr_hydroportail/catalogue"
    pairs = pl.read_parquet(packaged / "station_products.parquet")
    ledger = decode_availability(
        lzma.decompress(
            (
                retained_evidence_root / "maintenance/catalogue/fr_hubeau/inventory/governing_evidence.json.xz"
            ).read_bytes()
        )
    )
    witnessed = {(p.code_station, p.product_id) for p in ledger.pairs if p.basis == "historical_positive_witness"}
    available = pairs.filter(pl.col("availability") == "available")
    assert set(available.select("station_id", "product_id").iter_rows()) == witnessed
    assert all("raw" in reason for reason in pairs["availability_reason"])
    assert set(pairs["availability"]) == {"available", "unknown"}

    import rivretrieve as rr

    for station, product in sorted(witnessed)[:2]:
        selection = rr.find(
            provider="fr_hydroportail",
            station=station,
            quantity="discharge" if product.startswith("discharge") else "stage",
        )
        for variant in ("validated", "pre_validated_and_validated", "most_valid"):
            selected = rr.pick(selection, variant=variant)
            assert len(selected.series) == 1
            # Catalogue membership does not establish bounded observation coverage.
            assert all(inventory.window is None for inventory in selected.inventories)
            assert all(inventory.completeness == "incomplete" for inventory in selected.inventories)
