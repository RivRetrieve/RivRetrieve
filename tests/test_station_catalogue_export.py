from __future__ import annotations

import polars as pl

from docs.scripts.generate_station_catalogue import encode_catalogue
from rivretrieve._internal.source_series import (
    EvidenceFact,
    PhysicalFacts,
    SourceIdentity,
    SourceSeries,
    known,
)


def test_compact_catalogue_preserves_identity_unknowns_and_fact_segments():
    stations = pl.DataFrame(
        {
            "provider_id": ["a", "b", "a"],
            "station_id": ["001", "001", "002"],
            "station_name": ["River é", None, "No series"],
            "latitude": [1.123456789, None, 3.0],
            "longitude": [2.0, None, 4.0],
            "crs": ["unknown", None, "EPSG:4326"],
        }
    )
    providers = [
        {"provider_id": p, "name": p, "retrieval": p == "a", "bulk": False, "credentials": []} for p in ("a", "b")
    ]
    first = PhysicalFacts(
        facts_id="one",
        quantity=known("discharge", "synthetic"),
        source_unit=known("m3/s", "synthetic"),
        normalized_unit="m3/s",
        frequency=EvidenceFact(state="source_silent"),
    )
    second = PhysicalFacts(facts_id="two", quantity=known("stage", "synthetic"))
    series = [
        SourceSeries(
            series_id="exact-id",
            provider_id="a",
            station_id="001",
            product_id="route",
            identity=SourceIdentity(
                namespace="test", published_id="published", origin="catalogue", evidence=("synthetic",)
            ),
            variant="original",
            facts=(first, second),
        ),
        SourceSeries(
            series_id="another-id",
            provider_id="b",
            station_id="001",
            product_id="route",
            identity=SourceIdentity(namespace="test", origin="catalogue", evidence=("synthetic",)),
            facts=(first.model_copy(update={"facts_id": "different-id"}),),
        ),
    ]
    result = encode_catalogue(providers, stations, series)
    assert result["stations"] == [
        [0, "001", "River é", 1.123456789, 2.0, "unknown"],
        [1, "001", None, None, None, None],
        [0, "002", "No series", 3.0, 4.0, "EPSG:4326"],
    ]
    assert result["series"] == [[0, "exact-id", "original", "published", [0, 1]], [1, "another-id", None, None, [0]]]
    assert len(result["facts"]) == 2
    assert result["facts"][0]["frequency"] == {"value": None, "state": "source_silent"}
    assert result["facts"][0]["time_zone"] == {"value": None, "state": "not_established"}
    assert result["facts"][0]["quantity"] == {"value": "discharge", "state": "known"}
    assert result["facts"][0]["admission"] == "supported"
    assert result["facts"][1]["admission"] == "unsupported"
    assert "evidence" not in str(result)


def test_export_uses_declared_capabilities_and_never_credential_values(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from docs.scripts import generate_station_catalogue as exporter
    from rivretrieve._internal.providers.registration import BulkStore, CatalogueOnly, LiveStages

    kinds = [CatalogueOnly(), BulkStore(None, None, None), LiveStages(None)]
    declared = [
        SimpleNamespace(
            provider_id=str(i),
            declaration=SimpleNamespace(
                catalogue=tmp_path / str(i),
                observations=kind,
                required_credentials=("TEST_SECRET",) if i == 2 else (),
            ),
        )
        for i, kind in enumerate(kinds)
    ]
    monkeypatch.setenv("TEST_SECRET", "must-never-be-exported")
    monkeypatch.setattr(exporter, "load_manifest", lambda _: declared)

    def load(path, **kwargs):
        provider = path.name
        return SimpleNamespace(
            provider_info={"provider_id": provider, "name": "Synthetic"},
            stations=pl.DataFrame(
                {
                    "provider_id": [provider],
                    "station_id": ["001"],
                    "station_name": [None],
                    "latitude": [None],
                    "longitude": [None],
                    "crs": ["unknown"],
                }
            ),
        )

    monkeypatch.setattr(exporter, "load_packaged_catalogue_artifact", load)
    monkeypatch.setattr(exporter.pl, "read_parquet", lambda _: pl.DataFrame())
    monkeypatch.setattr(exporter, "source_metadata_frame", lambda keys, source: source)
    monkeypatch.setattr(exporter, "station_metadata_frame", lambda keys, source, locations: locations)
    monkeypatch.setattr(exporter, "catalogue_series", lambda _: ((), ()))
    path = tmp_path / "public" / "catalogue.json"
    exporter.build_catalogue(path)
    text = path.read_text()
    result = json.loads(text)
    assert result["providers"] == [
        {"provider_id": "0", "name": "Synthetic", "retrieval": False, "bulk": False, "credentials": []},
        {"provider_id": "1", "name": "Synthetic", "retrieval": True, "bulk": True, "credentials": []},
        {"provider_id": "2", "name": "Synthetic", "retrieval": True, "bulk": False, "credentials": ["TEST_SECRET"]},
    ]
    assert "must-never-be-exported" not in text
    assert len(result["stations"]) == 3
    assert result["series"] == []
