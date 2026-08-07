from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.artifact import (
    CorruptCatalogArtifactError,
    PackagedCatalogArtifact,
    load_packaged_catalogue_artifact,
    packaged_catalogue_artifact_from_components,
)
from rivretrieve._internal.catalogues.schemas import AvailabilityDtype, CatalogueDtype


def provider_info_dict(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "provider_id": "synthetic",
        "name": "Synthetic Provider",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": "2026.01",
        "license": None,
        "citation": None,
    }
    data.update(overrides)
    return data


def products_df(**overrides: object) -> pl.DataFrame:
    data: dict[str, object] = {
        "provider_id": ["synthetic"],
        "product_id": ["level"],
        "observed_property": ["water_level"],
        "frequency": ["daily"],
        "statistic": ["mean"],
        "period_type": ["calendar_day"],
        "period_anchor": ["UTC"],
        "unit": ["m"],
        "native_id": ["WATER_LEVEL"],
        "derived": [False],
        "derivation_method": [None],
    }
    data.update(overrides)
    return pl.DataFrame(
        data,
        schema={
            "provider_id": pl.Utf8,
            "product_id": pl.Utf8,
            "observed_property": pl.Utf8,
            "frequency": pl.Utf8,
            "statistic": pl.Utf8,
            "period_type": pl.Utf8,
            "period_anchor": pl.Utf8,
            "unit": pl.Utf8,
            "native_id": pl.Utf8,
            "derived": pl.Boolean,
            "derivation_method": pl.Utf8,
        },
    )


def stations_df(**overrides: object) -> pl.DataFrame:
    data: dict[str, object] = {
        "provider_id": ["synthetic"],
        "station_id": ["station-1"],
        "latitude": [46.2],
        "longitude": [7.1],
        "crs": ["unknown"],
    }
    data.update(overrides)
    return pl.DataFrame(
        data,
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "latitude": pl.Float64,
            "longitude": pl.Float64,
            "crs": pl.Utf8,
        },
    )


def station_products_df(
    *,
    availability_dtype: CatalogueDtype = AvailabilityDtype,
    **overrides: object,
) -> pl.DataFrame:
    data: dict[str, object] = {
        "provider_id": ["synthetic"],
        "station_id": ["station-1"],
        "product_id": ["level"],
        "availability": ["available"],
        "availability_reason": [None],
        "start_date": [date(2020, 1, 1)],
        "end_date": [None],
        "last_catalogue_check": [date(2026, 1, 1)],
    }
    data.update(overrides)
    return pl.DataFrame(
        data,
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "availability": availability_dtype,
            "availability_reason": pl.Utf8,
            "start_date": pl.Date,
            "end_date": pl.Date,
            "last_catalogue_check": pl.Date,
        },
    )


def write_artifact(
    path: Path,
    *,
    provider_info: dict[str, object] | None = None,
    products: pl.DataFrame | None = None,
    stations: pl.DataFrame | None = None,
    station_products: pl.DataFrame | None = None,
) -> Path:
    path.mkdir()
    (path / "provider.json").write_text(
        json.dumps(provider_info or provider_info_dict(), sort_keys=True),
        encoding="utf-8",
    )
    (products if products is not None else products_df()).write_parquet(path / "products.parquet")
    (stations if stations is not None else stations_df()).write_parquet(path / "stations.parquet")
    (station_products if station_products is not None else station_products_df()).write_parquet(
        path / "station_products.parquet"
    )
    return path


def test_packaged_artifact_from_components_happy_path() -> None:
    artifact = packaged_catalogue_artifact_from_components(
        provider_info_dict(),
        products_df(),
        stations_df(),
        station_products_df(),
        on_issue="raise",
    )

    assert isinstance(artifact, PackagedCatalogArtifact)
    assert artifact.provider_info["provider_id"] == "synthetic"
    pl_testing.assert_frame_equal(artifact.products, products_df(), check_exact=True)
    pl_testing.assert_frame_equal(artifact.stations, stations_df(), check_exact=True)
    pl_testing.assert_frame_equal(artifact.station_products, station_products_df(), check_exact=True)


def test_packaged_artifact_from_path_happy_path(tmp_path: Path) -> None:
    artifact_path = write_artifact(
        tmp_path / "catalogue",
        station_products=station_products_df(availability_dtype=pl.Utf8),
    )

    artifact = load_packaged_catalogue_artifact(artifact_path, on_issue="raise")

    assert artifact.provider_info["provider_id"] == "synthetic"
    assert artifact.station_products.schema["availability"] == AvailabilityDtype


def test_packaged_artifact_missing_directory_raises_corrupt(tmp_path: Path) -> None:
    with pytest.raises(CorruptCatalogArtifactError):
        load_packaged_catalogue_artifact(tmp_path / "missing")


def test_packaged_artifact_path_not_directory_raises_corrupt(tmp_path: Path) -> None:
    artifact_file = tmp_path / "catalogue"
    artifact_file.write_text("not a directory", encoding="utf-8")

    with pytest.raises(CorruptCatalogArtifactError):
        load_packaged_catalogue_artifact(artifact_file)


def test_packaged_artifact_missing_file_raises_corrupt(tmp_path: Path) -> None:
    artifact_path = write_artifact(tmp_path / "catalogue")
    (artifact_path / "products.parquet").unlink()

    with pytest.raises(CorruptCatalogArtifactError):
        load_packaged_catalogue_artifact(artifact_path)


def test_packaged_artifact_unparseable_json_raises_corrupt(tmp_path: Path) -> None:
    artifact_path = write_artifact(tmp_path / "catalogue")
    (artifact_path / "provider.json").write_text("{", encoding="utf-8")

    with pytest.raises(CorruptCatalogArtifactError):
        load_packaged_catalogue_artifact(artifact_path)


def test_packaged_artifact_provider_json_not_object_raises_corrupt(tmp_path: Path) -> None:
    artifact_path = write_artifact(tmp_path / "catalogue")
    (artifact_path / "provider.json").write_text("[]", encoding="utf-8")

    with pytest.raises(CorruptCatalogArtifactError):
        load_packaged_catalogue_artifact(artifact_path)


def test_packaged_artifact_unreadable_parquet_raises_corrupt(tmp_path: Path) -> None:
    artifact_path = write_artifact(tmp_path / "catalogue")
    (artifact_path / "stations.parquet").write_bytes(b"not parquet")

    with pytest.raises(CorruptCatalogArtifactError):
        load_packaged_catalogue_artifact(artifact_path)


def test_packaged_artifact_schema_missing_column_raises_corrupt() -> None:
    with pytest.raises(CorruptCatalogArtifactError):
        packaged_catalogue_artifact_from_components(
            provider_info_dict(),
            products_df(),
            stations_df().drop("station_id"),
            station_products_df(),
        )


def test_packaged_artifact_schema_wrong_dtype_raises_corrupt() -> None:
    with pytest.raises(CorruptCatalogArtifactError):
        packaged_catalogue_artifact_from_components(
            provider_info_dict(),
            products_df(),
            stations_df().with_columns(pl.col("latitude").cast(pl.Utf8)),
            station_products_df(),
        )


def test_packaged_artifact_non_nullable_null_raises_corrupt() -> None:
    with pytest.raises(CorruptCatalogArtifactError):
        packaged_catalogue_artifact_from_components(
            provider_info_dict(),
            products_df(),
            stations_df(crs=[None]),
            station_products_df(),
        )


def test_packaged_artifact_invalid_availability_raises_corrupt() -> None:
    with pytest.raises(CorruptCatalogArtifactError):
        packaged_catalogue_artifact_from_components(
            provider_info_dict(),
            products_df(),
            stations_df(),
            station_products_df(availability=["retired"], availability_dtype=pl.Utf8),
        )


def test_packaged_artifact_duplicate_station_key_raises_corrupt() -> None:
    with pytest.raises(CorruptCatalogArtifactError):
        packaged_catalogue_artifact_from_components(
            provider_info_dict(),
            products_df(),
            stations_df(
                provider_id=["synthetic", "synthetic"],
                station_id=["station-1", "station-1"],
                latitude=[46.2, 46.2],
                longitude=[7.1, 7.1],
                crs=["unknown", "unknown"],
            ),
            station_products_df(),
        )


def test_packaged_artifact_duplicate_product_key_raises_corrupt() -> None:
    with pytest.raises(CorruptCatalogArtifactError):
        packaged_catalogue_artifact_from_components(
            provider_info_dict(),
            products_df(
                provider_id=["synthetic", "synthetic"],
                product_id=["level", "level"],
                observed_property=["water_level", "water_level"],
                frequency=["daily", "daily"],
                statistic=["mean", "mean"],
                period_type=["calendar_day", "calendar_day"],
                period_anchor=["UTC", "UTC"],
                unit=["m", "m"],
                native_id=["WATER_LEVEL", "WATER_LEVEL"],
                derived=[False, False],
                derivation_method=[None, None],
            ),
            stations_df(),
            station_products_df(),
        )


def test_packaged_artifact_duplicate_station_product_key_raises_corrupt() -> None:
    with pytest.raises(CorruptCatalogArtifactError):
        packaged_catalogue_artifact_from_components(
            provider_info_dict(),
            products_df(),
            stations_df(),
            station_products_df(
                provider_id=["synthetic", "synthetic"],
                station_id=["station-1", "station-1"],
                product_id=["level", "level"],
                availability=["available", "available"],
                availability_reason=[None, None],
                start_date=[date(2020, 1, 1), date(2020, 1, 1)],
                end_date=[None, None],
                last_catalogue_check=[date(2026, 1, 1), date(2026, 1, 1)],
            ),
        )


def test_packaged_artifact_duplicate_provider_info_key_raises_corrupt() -> None:
    with pytest.raises(CorruptCatalogArtifactError):
        packaged_catalogue_artifact_from_components(
            {
                "provider_id": ["synthetic", "synthetic"],
                "name": ["Synthetic Provider", "Synthetic Provider Duplicate"],
                "live_stations": [False, False],
                "live_products": [False, False],
                "live_station_products": [False, False],
                "bulk_observations": ["none", "none"],
                "catalogue_version": ["2026.01", "2026.01"],
                "license": [None, None],
                "citation": [None, None],
            },
            products_df(),
            stations_df(),
            station_products_df(),
        )


def test_packaged_artifact_provider_id_mismatch_raises_corrupt() -> None:
    with pytest.raises(CorruptCatalogArtifactError):
        packaged_catalogue_artifact_from_components(
            provider_info_dict(),
            products_df(provider_id=["other"]),
            stations_df(),
            station_products_df(),
        )


def test_packaged_artifact_dangling_station_product_station_fk_raises_corrupt() -> None:
    with pytest.raises(CorruptCatalogArtifactError):
        packaged_catalogue_artifact_from_components(
            provider_info_dict(),
            products_df(),
            stations_df(),
            station_products_df(station_id=["missing-station"]),
        )


def test_packaged_artifact_dangling_station_product_product_fk_raises_corrupt() -> None:
    with pytest.raises(CorruptCatalogArtifactError):
        packaged_catalogue_artifact_from_components(
            provider_info_dict(),
            products_df(),
            stations_df(),
            station_products_df(product_id=["missing-product"]),
        )


def test_corrupt_artifact_still_raises_under_ignore(tmp_path: Path) -> None:
    artifact_path = write_artifact(tmp_path / "catalogue")
    (artifact_path / "stations.parquet").unlink()

    with pytest.raises(CorruptCatalogArtifactError):
        load_packaged_catalogue_artifact(artifact_path, on_issue="ignore")
