"""End-to-end `write_catalogue()` mechanics for de_pegelonline, against real native data.

Builds the full packaged catalogue (products/stations/station_products,
`source_series.json`, `provenance.json`, `format.json`, `croissant.json`, ...)
from the real committed station fixture and the real `describe_station_products`
builder, proving the write/load round-trip and the shared engine's discovery
path (`materialize_series`) both work. The archive member identifiers below are
placeholders (matching `tests/test_ch_foen_official_origins.py`'s own synthetic
`CatalogueBuildInputs` test pattern): this test proves the *mechanics*, not a
reviewed archive registration, which a real publication to
`catalogue/provenance.json` additionally requires (and is not committed by
this change -- see the PR description).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rivretrieve._internal.acquisition_provenance import (
    ArchiveMemberReference,
    CatalogueBuildInputs,
    CodeReference,
    NativeTableIdentity,
    RecordingReference,
    RetainedInputUse,
)
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.catalogues.native import RetrievedAt, write_native_table
from rivretrieve._internal.catalogues.source_series import materialize_series
from rivretrieve._internal.providers.de_pegelonline import generate_catalogue
from rivretrieve._internal.providers.de_pegelonline.origins import (
    STATION_CATALOGUE_ORIGINS,
    build_acquisition_provenance,
)

FIXTURE_PATH = Path("tests/test_data/de_pegelonline_stations.json")
TERMS_PATH = Path("tests/test_data/de_pegelonline_terms.html")
RETRIEVED_AT = RetrievedAt(datetime(2026, 11, 24, 20, 8, 8, tzinfo=UTC))


@pytest.fixture(scope="module")
def _published(tmp_path_factory: pytest.TempPathFactory):
    tmp_path = tmp_path_factory.mktemp("de_pegelonline_catalogue")
    native = generate_catalogue.refresh_native_table_from_fixture(FIXTURE_PATH, retrieved_at=RETRIEVED_AT)
    native_path = tmp_path / "native.parquet"
    write_native_table(native, native_path)
    native_bytes = native_path.read_bytes()

    terms_bytes = TERMS_PATH.read_bytes()
    terms_recording = RecordingReference(
        recording_id="de_pegelonline-terms",
        repository_path=str(TERMS_PATH),
        source_url="https://pegelonline.wsv.de/gast/nutzungsbedingungen",
        retrieved_at=datetime(2026, 11, 24, 17, 27, 46, tzinfo=UTC),
        media_type="text/html; charset=utf-8",
        sha256=hashlib.sha256(terms_bytes).hexdigest(),
    )
    provenance = build_acquisition_provenance(
        stations_retrieved_at=RETRIEVED_AT.value,
        native_identity=NativeTableIdentity(
            repository_path="src/rivretrieve/_internal/providers/de_pegelonline/catalogue/native.parquet",
            revision="0" * 40,
            sha256=hashlib.sha256(native_bytes).hexdigest(),
            byte_size=len(native_bytes),
        ),
        terms_recording=terms_recording,
        license_exact_text=(
            "Informationen, Produkte oder Dienste, die Sie von dieser Website erhalten, dürfen übernommen "
            "werden. Dies geschieht auf der Grundlage der Lizenz DL-DE->Zero-2.0"
        ),
    )
    catalogue = generate_catalogue.build_catalogue(native, STATION_CATALOGUE_ORIGINS, acquisition_provenance=provenance)

    prefix = "src/rivretrieve/_internal/providers/de_pegelonline/"
    code_identity = {"repository": "https://github.com/RivRetrieve/RivRetrieve", "revision": "d" * 40}
    archive_identity = {
        "archive_repository": "https://github.com/RivRetrieve/verification-evidence",
        "archive_revision": "e" * 40,
        "collection_id": "synthetic",
        "manifest_sha256": "f" * 64,
    }
    build_inputs = CatalogueBuildInputs(
        build=CodeReference(
            **code_identity, repository_path=prefix + "generate_catalogue.py", symbol="write_catalogue"
        ),
        declarations=(
            CodeReference(**code_identity, repository_path=prefix + "generate_catalogue.py", symbol="build_catalogue"),
            CodeReference(
                **code_identity, repository_path=prefix + "origins.py", symbol="build_acquisition_provenance"
            ),
            CodeReference(**code_identity, repository_path=prefix + "origins.py", symbol="STATION_METADATA_FIELDS"),
        ),
        inputs=(
            RetainedInputUse(
                reference=ArchiveMemberReference(
                    **archive_identity,
                    artifact_id="native",
                    role="derived_input",
                    sha256=provenance.native_table.sha256,
                    byte_size=len(native_bytes),
                ),
                usage="native_table",
                facts=(
                    "source.station.native_identity",
                    "source.station.native_geometry",
                    "source.station.documented_crs",
                    "source.product.native_timeseries_shortnames",
                    "source.product.temporal_meaning",
                    "source.station_product.native_timeseries_listing",
                    "source.station.pegelonline_vertical_datum_regime",
                ),
            ),
            RetainedInputUse(
                reference=ArchiveMemberReference(
                    **archive_identity,
                    artifact_id="terms",
                    role="publisher_original",
                    sha256=terms_recording.sha256,
                    byte_size=len(terms_bytes),
                ),
                usage="recording",
                facts=("source.de_pegelonline.license_statement",),
            ),
        ),
    )
    output = tmp_path / "catalogue"
    generate_catalogue.write_catalogue(catalogue, output, build_inputs=build_inputs, native_table=native)
    return output


def test_published_catalogue_loads_through_the_shared_artifact_loader(_published):
    artifact = load_packaged_catalogue_artifact(_published, on_issue="raise")

    assert artifact.provider_info["provider_id"] == "de_pegelonline"
    assert artifact.stations.height == 787
    assert artifact.source_descriptions is not None
    assert {description.product_id for description in artifact.source_descriptions.descriptions} == {
        "W",
        "Q",
        "WT",
        "TRM",
        "TRM_WT",
    }


def test_published_catalogue_materializes_a_known_station_product(_published):
    artifact = load_packaged_catalogue_artifact(_published, on_issue="raise")

    series, _inventories = materialize_series(artifact)
    hofkirchen = [item for item in series if item.station_id == "616dd98e-816d-4e17-b8cd-57b163dbc8a2"]
    assert any(item.product_id == "Q" for item in hofkirchen)
