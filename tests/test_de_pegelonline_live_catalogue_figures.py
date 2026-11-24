"""Headline figures pinned to a fresh 2026-11-24 live PEGELONLINE fetch.

These tests read the committed native table (and the raw fixture it was derived
from) through `retained_evidence_root`, following the project's existing
derived-input/recorded-response test levels
(`docs/maintenance/testing.md`). They are excluded from `uv run pytest
--logic-only` like every other provider's equivalent catalogue tests
(`test_lt_lhmt_generate_catalogue.py`, etc.), since they consume retained
material rather than proving conversion logic in isolation.

Figures were re-derived from a fresh live fetch made while building this
catalogue (2026-11-24T17:20:15Z), not trusted from the step-2 vision's pinned
table, per that vision's own instruction. One genuine discrepancy was found and
is deliberately NOT papered over here: the vision expects 120 stations with a
`TRM` timeseries and 2 with `TRM_WT`; the live fetch found zero of either. See
`generate_catalogue.py`'s module docstring and the PR description.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.catalogues.native import read_native_table
from rivretrieve._internal.providers.de_pegelonline import generate_catalogue
from rivretrieve._internal.providers.de_pegelonline.origins import STATION_CATALOGUE_ORIGINS

FIXTURE_PATH = Path("tests/test_data/de_pegelonline_stations.json")
NATIVE_PATH = Path("src/rivretrieve/_internal/providers/de_pegelonline/catalogue/native.parquet")
ATTESTED_RETRIEVED_AT = datetime(2026, 11, 24, 17, 20, 15, tzinfo=UTC)
ATTESTED_FIXTURE_SHA256 = "75aaf0d4ecd63c2672c7ab77e152ebb417711361188cb4c30048e593dfef6aae"
CHECKED_ON = date(2026, 11, 24)


@pytest.mark.recorded(str(FIXTURE_PATH))
def test_live_fixture_matches_attested_digest(retained_evidence_root) -> None:
    content = (retained_evidence_root / FIXTURE_PATH).read_bytes()
    assert hashlib.sha256(content).hexdigest() == ATTESTED_FIXTURE_SHA256
    payload = json.loads(content)
    assert isinstance(payload, list)
    assert len(payload) == 787


def _catalogue(retained_evidence_root):
    native = read_native_table(retained_evidence_root / NATIVE_PATH)
    return generate_catalogue.build_catalogue(native, STATION_CATALOGUE_ORIGINS)


@pytest.mark.derived(str(NATIVE_PATH))
def test_committed_native_table_has_787_stations_and_attested_unit_regimes(retained_evidence_root) -> None:
    native = read_native_table(retained_evidence_root / NATIVE_PATH)

    assert native.data.height == 787
    assert native.data["uuid"].n_unique() == 787

    regimes = dict(native.data["w_unit"].value_counts().iter_rows())
    assert regimes["cm"] == 669
    assert regimes["m+NN"] == 67
    assert regimes["m+PNP"] == 2


@pytest.mark.derived(str(NATIVE_PATH))
def test_committed_native_table_resolves_neustadt_collision_to_two_uuids(retained_evidence_root) -> None:
    native = read_native_table(retained_evidence_root / NATIVE_PATH)

    neustadt = native.data.filter(pl.col("shortname") == "NEUSTADT")
    assert neustadt.height == 2
    assert neustadt["uuid"].n_unique() == 2


@pytest.mark.derived(str(NATIVE_PATH))
def test_station_catalogue_has_787_stations_with_57_null_coordinates(retained_evidence_root) -> None:
    catalogue = _catalogue(retained_evidence_root)

    assert catalogue.stations.height == 787
    assert catalogue.stations.filter(pl.col("crs") == "unknown").height == 57
    assert catalogue.stations.filter(pl.col("latitude").is_null() & pl.col("longitude").is_null()).height == 57
    assert catalogue.stations.filter(pl.col("crs") == "EPSG:4326").height == 730


@pytest.mark.derived(str(NATIVE_PATH))
def test_product_catalogue_has_exactly_the_three_witnessed_product_ids(retained_evidence_root) -> None:
    catalogue = _catalogue(retained_evidence_root)

    assert catalogue.products["product_id"].sort().to_list() == ["Q", "W", "WT"]
    assert set(catalogue.products["statistic"]) == {"unknown"}


@pytest.mark.derived(str(NATIVE_PATH))
def test_station_product_availability_matches_attested_per_timeseries_counts(retained_evidence_root) -> None:
    catalogue = _catalogue(retained_evidence_root)

    available = catalogue.station_products.filter(pl.col("availability") == "available")
    counts = dict(available.group_by("product_id").len().iter_rows())
    assert counts == {"W": 738, "WT": 142, "Q": 96}
    assert set(catalogue.station_products["published_record_start_date"]) == {None}
    assert set(catalogue.station_products["published_record_end_date"]) == {None}


@pytest.mark.derived(str(NATIVE_PATH))
def test_provider_info_license_matches_the_settled_value(retained_evidence_root) -> None:
    catalogue = _catalogue(retained_evidence_root)

    assert catalogue.provider_info["license"] == "DL-DE->Zero-2.0"
    assert catalogue.provider_info["citation"] is None
    assert catalogue.provider_info["catalogue_version"] == CHECKED_ON.isoformat()
