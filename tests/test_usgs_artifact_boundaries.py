"""Authored compatibility controls; these are not publisher recordings."""

import json
from io import BytesIO
from zipfile import ZipFile

import pytest

from rivretrieve._internal import export_bundle
from rivretrieve._internal.catalogues.artifact import CorruptCatalogArtifactError, _validate_format
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.publication_identity import publication_identity_fields
from rivretrieve._internal.selection import _Selection
from rivretrieve._internal.source_series import SeriesScope
from rivretrieve._internal.store.accumulation import StoreUpdate, accumulate
from rivretrieve._internal.store.validation import ObservationStoreRefusedError, StoreRoot, validate_store


@pytest.mark.parametrize(
    "providers,expected",
    [
        ((), {}),
        (("no_nve", "fr_hydroportail"), {}),
        (("fr_hubeau",), {"publication_service": "hubeau"}),
        (("usgs_nwis",), {"usgs_publication_service": "usgs-waterdata-v1"}),
        (
            ("usgs_nwis", "fr_hubeau", "usgs_nwis"),
            {"publication_service": "hubeau", "usgs_publication_service": "usgs-waterdata-v1"},
        ),
    ],
)
def test_independent_identity_fields(providers, expected):
    assert publication_identity_fields(iter(providers)) == expected


@pytest.mark.parametrize("providers", [("usgs_nwis",), ("fr_hubeau",), ("usgs_nwis", "fr_hubeau")])
def test_empty_selection_bundle_round_trip(providers):
    selection = _Selection(scope=SeriesScope(provider_ids=providers))
    content = export_bundle.encode_bundle(selection)
    with ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    for field, value in publication_identity_fields(providers).items():
        assert manifest[field] == value
    assert export_bundle.decode_bundle(content) == selection


@pytest.mark.parametrize(
    "location", ["scope", "series", "receipt_provider", "provenance", "locations", "inventories", "catalogue_evidence"]
)
def test_usgs_identity_retained_from_each_bundle_context(location):
    contexts = {
        "scope": {"provider_ids": ["usgs_nwis"]},
        "series": [{"provider_id": "usgs_nwis"}],
        "receipt_provider": "usgs_nwis",
        "provenance": {"provider_id": "usgs_nwis"},
        "locations": [{"provider_id": "usgs_nwis"}],
        "inventories": [{"scope": {"provider_ids": ["usgs_nwis"]}}],
        "catalogue_evidence": [{"header": {"provider_id": "usgs_nwis"}}],
    }
    assert export_bundle._publication_identity({location: contexts[location]}) == {
        "usgs_publication_service": "usgs-waterdata-v1"
    }


@pytest.mark.parametrize("identity", [None, "nwis", "usgs-waterdata-v0"])
@pytest.mark.parametrize("kind", ["selection", "result"])
def test_legacy_bundle_refused_before_values(identity, kind, tmp_path, monkeypatch):
    manifest = {
        "format": "rivretrieve-source-series",
        "version": 2,
        "kind": kind,
        "scope": {"provider_ids": ["usgs_nwis"]},
    }
    if identity is not None:
        manifest["usgs_publication_service"] = identity
    path = tmp_path / "legacy.bundle"
    with ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
    content = path.read_bytes()
    monkeypatch.setattr(export_bundle.pl, "read_parquet", lambda *a, **k: pytest.fail("read legacy values"))
    with pytest.raises(ValueError, match="publication_service"):
        export_bundle.decode_bundle(content)
    assert path.read_bytes() == content


@pytest.mark.parametrize("identity", [None, "nwis", "usgs-waterdata-v0"])
def test_legacy_catalogue_refusal_is_non_destructive(identity, tmp_path):
    document = {"catalogue_format_version": 2}
    if identity is not None:
        document["usgs_publication_service"] = identity
    path = tmp_path / "format.json"
    path.write_text(json.dumps(document))
    before = path.read_bytes()
    with pytest.raises(CorruptCatalogArtifactError, match="publication service identity"):
        _validate_format(tmp_path, "usgs_nwis")
    assert path.read_bytes() == before


def test_modern_catalogue_format(tmp_path):
    (tmp_path / "format.json").write_text(
        json.dumps({"catalogue_format_version": 2, "usgs_publication_service": "usgs-waterdata-v1"})
    )
    _validate_format(tmp_path, "usgs_nwis")


@pytest.mark.parametrize("identity", [None, "nwis", "usgs-waterdata-v0"])
@pytest.mark.parametrize("operation", ["validate", "accumulate"])
def test_legacy_store_refusal_is_non_destructive(identity, operation, tmp_path):
    store = StoreRoot(tmp_path / "store")
    from tests.store.test_integrity import _resign

    accumulate(store, ProviderId("usgs_nwis"), StoreUpdate((), (), (), ()))
    path = store / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest.pop("usgs_publication_service")
    if identity is not None:
        manifest["usgs_publication_service"] = identity
    path.write_text(json.dumps(manifest))
    # Update byte controls so each operation reaches publication-service refusal.
    _resign(store)
    before = {p.name: p.read_bytes() for p in store.iterdir()}
    siblings = set(tmp_path.iterdir())
    with pytest.raises(ObservationStoreRefusedError, match="usgs_publication_service"):
        if operation == "validate":
            validate_store(store, ProviderId("usgs_nwis"))
        else:
            accumulate(store, ProviderId("usgs_nwis"), StoreUpdate((), (), (), ()))
    assert {p.name: p.read_bytes() for p in store.iterdir()} == before
    assert set(tmp_path.iterdir()) == siblings


@pytest.mark.parametrize("provider", ["usgs_nwis", "fr_hubeau", "no_nve"])
def test_new_empty_store_declares_only_its_service(provider, tmp_path):
    store = StoreRoot(tmp_path / "store")
    accumulate(store, ProviderId(provider), StoreUpdate((), (), (), ()))
    raw = json.loads((store / "manifest.json").read_text())
    fields = {k: v for k, v in raw.items() if k.endswith("publication_service")}
    assert fields == publication_identity_fields((provider,))
    assert validate_store(store, ProviderId(provider)).manifest.provider_id == provider


@pytest.mark.parametrize("mutation", ["missing_hash", "wrong_hash", "wrong_shape", "wrong_station"])
def test_monitoring_location_composition_refuses_corrupt_identity_map(tmp_path, mutation):
    import hashlib

    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.providers.usgs_nwis.declaration import _load_monitoring_locations

    content = b'{"07374000":"USGS-07374000"}'
    if mutation == "wrong_shape":
        content = b"[]"
    elif mutation == "wrong_station":
        content = b'{"07374000":"USGS-00000000"}'
    digest = hashlib.sha256(content).hexdigest() if mutation != "wrong_hash" else "0" * 64
    distribution = [] if mutation == "missing_hash" else [{"contentUrl": "monitoring_locations.json", "sha256": digest}]
    (tmp_path / "monitoring_locations.json").write_bytes(content)
    (tmp_path / "croissant.json").write_text(json.dumps({"distribution": distribution}))
    with pytest.raises(FatalContractError, match="monitoring-location"):
        _load_monitoring_locations(tmp_path)
    assert (tmp_path / "monitoring_locations.json").read_bytes() == content
