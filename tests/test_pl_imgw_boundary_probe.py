"""Official IMGW monthly bytes prove all declared store products."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from rivretrieve._internal.boundary_probes import (
    FIRST_WALL_CLOCK_TIME,
    LAST_WALL_CLOCK_TIME,
    READING_COUNT,
    StoreBoundaryProbe,
    WallClockExpectation,
    run_manifest_boundary_probes,
)
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.pl_imgw.bulk import ImgwCompileRequest, compile_imgw, decode_imgw_batches
from rivretrieve._internal.providers.pl_imgw.declaration import declaration
from rivretrieve._internal.providers.registration import DeclaredProvider
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.store import StoreQuery, StoreRoot, validate_store
from rivretrieve._internal.store.validation import StoreManifest
from rivretrieve._internal.transport import HttpMethod, TransportRequest

_RECORDING = Path("tests/test_data") / "pl_imgw_codz_2022_01.recording.json"
_URL = "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/2022/codz_2022_01.zip"
_PRODUCTS = tuple(ProductId(value) for value in ("discharge_daily", "stage_daily", "water_temperature_daily"))


def _compiled_store(retained_evidence_root: Path, tmp_path: Path) -> StoreRoot:
    recording = read_recording(retained_evidence_root / _RECORDING)
    response = ReplayTransport((recording,)).send(TransportRequest(HttpMethod.GET, _URL))
    artifact = tmp_path / "codz_2022_01.zip"
    artifact.write_bytes(response.content)
    root = StoreRoot(tmp_path / "store")
    compile_imgw(
        ImgwCompileRequest(artifact, root, _URL, date(2021, 11, 30), datetime(2026, 9, 2, tzinfo=UTC), "0.1.49")
    )
    return root


@pytest.mark.recorded("tests/test_data/pl_imgw_codz_2022_01.recording.json")
def test_exact_monthly_recording_replays_through_compiler_and_three_store_probes(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    recording = read_recording(retained_evidence_root / _RECORDING)
    inventory_artifact = tmp_path / "inventory-codz_2022_01.zip"
    inventory_artifact.write_bytes(recording.content)
    stream = decode_imgw_batches(inventory_artifact)
    assert stream.expected_publisher_records == 24_897
    assert stream.expected_emitted_rows == 74_691
    root = _compiled_store(retained_evidence_root, tmp_path)
    probes = tuple(
        StoreBoundaryProbe(
            ProviderId("pl_imgw"),
            product,
            StoreQuery(
                root, ProviderId("pl_imgw"), ("154210010",), (product,), datetime(2021, 11, 1), datetime(2021, 11, 3)
            ),
            {
                READING_COUNT: 3,
                FIRST_WALL_CLOCK_TIME: WallClockExpectation("2021-11-01T00:00:00", "unknown"),
                LAST_WALL_CLOCK_TIME: WallClockExpectation("2021-11-03T00:00:00", "unknown"),
            },
        )
        for product in _PRODUCTS
    )
    results = run_manifest_boundary_probes((DeclaredProvider("pl_imgw", declaration),), probes)
    assert len(results) == 3
    compiled_manifest = validate_store(root, ProviderId("pl_imgw")).manifest
    assert isinstance(compiled_manifest, StoreManifest)
    assert compiled_manifest.source_vintage == date(2021, 11, 30)


@pytest.mark.recorded("tests/test_data/pl_imgw_codz_2022_01.recording.json")
def test_monthly_hydrological_mapping_and_source_values_are_not_inferred(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    root = _compiled_store(retained_evidence_root, tmp_path)
    from rivretrieve._internal.store import read_store

    result = read_store(
        StoreQuery(root, ProviderId("pl_imgw"), ("154210010",), _PRODUCTS, datetime(2021, 11, 1), datetime(2021, 11, 3))
    )
    assert result.rows.select("product_id", "time", "value").sort("product_id", "time").to_dicts() == [
        {"product_id": "discharge_daily", "time": datetime(2021, 11, 1), "value": 11.0},
        {"product_id": "discharge_daily", "time": datetime(2021, 11, 2), "value": 10.9},
        {"product_id": "discharge_daily", "time": datetime(2021, 11, 3), "value": 11.2},
        {"product_id": "stage_daily", "time": datetime(2021, 11, 1), "value": 103.0},
        {"product_id": "stage_daily", "time": datetime(2021, 11, 2), "value": 102.0},
        {"product_id": "stage_daily", "time": datetime(2021, 11, 3), "value": 103.0},
        {"product_id": "water_temperature_daily", "time": datetime(2021, 11, 1), "value": 7.5},
        {"product_id": "water_temperature_daily", "time": datetime(2021, 11, 2), "value": 6.9},
        {"product_id": "water_temperature_daily", "time": datetime(2021, 11, 3), "value": 7.1},
    ]


@pytest.mark.recorded("tests/test_data/pl_imgw_codz_2022_01.recording.json")
def test_warsaw_source_sentinel_remains_null_state_without_losing_stage_or_discharge(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    from rivretrieve._internal.store import read_store

    root = _compiled_store(retained_evidence_root, tmp_path)
    result = read_store(
        StoreQuery(
            root,
            ProviderId("pl_imgw"),
            ("152210170",),
            _PRODUCTS,
            datetime(2021, 11, 1),
            datetime(2021, 11, 3),
        )
    )
    by_product = {
        product: frame.sort("time")
        for (product,), frame in result.physical_rows.partition_by("product", as_dict=True).items()
    }
    assert by_product["stage_daily"]["value"].to_list() == [83.0, 85.0, 82.0]
    assert by_product["discharge_daily"]["value"].to_list() == [351.0, 358.0, 350.0]
    temperature = by_product["water_temperature_daily"]
    assert temperature["value"].to_list() == [None, None, None]
    assert temperature["value_state"].to_list() == ["published_null"] * 3
    assert temperature["IMGW_DAILY.temperature_c"].to_list() == ["99.9"] * 3


@pytest.mark.recorded("tests/test_data/pl_imgw_codz_2022_01.recording.json")
def test_public_bulk_engine_reads_validated_store_and_authors_exact_receipt(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.observations import ReceiptAuthorship, ReceiptMode, StoreExcerptReceipt
    from rivretrieve._internal.providers.pl_imgw.config import config
    from rivretrieve._internal.providers.pl_imgw.declaration import declaration
    from rivretrieve._internal.registry import ProviderRegistry

    root = _compiled_store(retained_evidence_root, tmp_path)
    registry = ProviderRegistry()
    registry.register(
        "pl_imgw",
        load_packaged_catalogue_artifact(declaration.catalogue, on_issue="raise"),
        bulk_config=config,
        observation_store=root,
    )
    result = registry.get("pl_imgw").observations(
        stations="154210010",
        products="discharge_daily",
        start="2021-11-01",
        end="2021-11-03",
        on_issue="raise",
        receipts=ReceiptMode.INCLUDE,
    )

    assert result.data.height == 3
    assert result.data.columns == [
        "time",
        "time_zone",
        "station_id",
        "product_id",
        "series_id",
        "facts_id",
        "quantity",
        "source_unit",
        "unit",
        "value",
    ]
    assert result.provenance.publisher_artifact_checksums == (
        "sha256:4b9a400cd83f06856e4c16c7912573bf1d9d83e74a13a832742b7c62e1fa8119",
    )
    assert result.provenance.publisher_artifact_urls == (_URL,)
    (receipt,) = result.receipts.entries
    assert isinstance(receipt, StoreExcerptReceipt)
    assert receipt.authorship is ReceiptAuthorship.STORE_EXCERPT
    assert receipt.executed_query.stations == ("154210010",)
    assert receipt.executed_query.products == (ProductId("discharge_daily"),)
    from io import BytesIO

    import polars as pl

    excerpt = pl.read_parquet(BytesIO(receipt.content))
    assert excerpt["IMGW_DAILY.flow_m3s"].to_list() == ["11.000", "10.900", "11.200", "11.400", "12.800"]
    assert excerpt["IMGW_DAILY.month_indicator"].to_list() == ["01", "01", "01", "01", "01"]
    assert excerpt["time"].to_list() == [datetime(2021, 11, day) for day in range(1, 6)]
    assert excerpt.unique().height == excerpt.height
    omitted = registry.get("pl_imgw").observations(
        stations="154210010",
        products="discharge_daily",
        start="2021-11-01",
        end="2021-11-03",
        on_issue="raise",
    )
    assert omitted.receipts.entries == ()
