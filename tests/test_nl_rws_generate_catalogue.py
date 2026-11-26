"""Source-independent tests for the Netherlands Rijkswaterstaat (nl_rws) catalogue builder."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionRecord,
    ArchiveMemberReference,
    CatalogueBuildInputs,
    CodeReference,
    FactBinding,
    NativeTableIdentity,
    RecordingReference,
    RetainedInputUse,
    SourceStatement,
)
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.catalogues.native import RetrievedAt, write_native_table
from rivretrieve._internal.catalogues.source_series import materialize_series
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.nl_rws import generate_catalogue
from rivretrieve._internal.providers.nl_rws.catalogue_series import PRODUCT_DEFINITIONS
from rivretrieve._internal.providers.nl_rws.origins import (
    STATION_CATALOGUE_ORIGINS,
    build_acquisition_provenance,
)

RETRIEVED_AT = RetrievedAt(datetime(2026, 11, 25, 13, 45, 25, tzinfo=UTC))
CHECKED_ON = date(2026, 11, 25)


def _meta(
    mid: int,
    *,
    comp: str = "OW",
    g: str,
    e: str,
    h: str = "NVT",
    pt: str = "meting",
    wbw: str = "NVT",
    wbp: str = "other:F216",
    grp: str = "",
) -> dict[str, object]:
    return {
        "AquoMetadata_MessageID": mid,
        "Compartiment": {"Code": comp, "Omschrijving": comp},
        "Grootheid": {"Code": g, "Omschrijving": g},
        "Eenheid": {"Code": e, "Omschrijving": e},
        "Hoedanigheid": {"Code": h, "Omschrijving": h},
        "ProcesType": pt,
        "WaardeBewerkingsMethode": {"Code": wbw, "Omschrijving": wbw},
        "WaardeBepalingsMethode": {"Code": wbp, "Omschrijving": wbp},
        "Groepering": {"Code": grp, "Omschrijving": grp},
    }


def _synthetic_catalogus() -> dict[str, object]:
    return {
        "Succesvol": True,
        "LocatieLijst": [
            {
                "Locatie_MessageID": 1001,
                "Code": "lobith.bovenrijn.tolkamer",
                "Coordinatenstelsel": "ETRS89",
                "Lat": 51.849,
                "Lon": 6.112,
                "Naam": "Lobith",
                "Omschrijving": "Bovenrijn Tolkamer",
            },
            {
                "Locatie_MessageID": 1002,
                "Code": "eijsden.grens",
                "Coordinatenstelsel": "ETRS89",
                "Lat": 50.779,
                "Lon": 5.694,
                "Naam": "Eijsden grens",
                "Omschrijving": "Eijsden grens",
            },
            {
                "Locatie_MessageID": 1003,
                "Code": "kralendijk.plazabeachterminal",
                "Coordinatenstelsel": "ETRS89",
                "Lat": 12.149638,
                "Lon": -68.277813,
                "Naam": "Kralendijk Plazabeach Terminal",
                "Omschrijving": "Bonaire",
            },
            {
                "Locatie_MessageID": 1004,
                "Code": "excluded.only.forecast",
                "Coordinatenstelsel": "ETRS89",
                "Lat": 52.0,
                "Lon": 5.0,
                "Naam": "Excluded Station",
                "Omschrijving": "Forecast and tidal extreme only",
            },
        ],
        "AquoMetadataLijst": [
            # Parallel WaardeBepalingsMethode (F216 + F230) for the same physical product Q m3/s NVT
            _meta(1, g="Q", e="m3/s", h="NVT", pt="meting", wbw="NVT", wbp="other:F216"),
            _meta(2, g="Q", e="m3/s", h="NVT", pt="meting", wbw="NVT", wbp="other:F230"),
            _meta(3, g="Q", e="m3/s", h="NVT", pt="meting", wbw="GEM24H", wbp="other:F216"),
            _meta(4, g="Q", e="m3/d", h="NVT", pt="meting", wbw="NVT", wbp="other:F006"),
            _meta(5, g="WATHTE", e="cm", h="NAP", pt="meting", wbw="NVT"),
            _meta(6, g="WATHTE", e="cm", h="NAP", pt="meting", wbw="GEM24H"),
            _meta(7, g="WATHTE", e="cm", h="PLAATSLR", pt="meting", wbw="NVT"),
            _meta(8, g="WATHTE", e="cm", h="MSL", pt="meting", wbw="NVT"),
            _meta(9, g="WATHTE", e="cm", h="TAW", pt="meting", wbw="NVT"),
            _meta(10, g="T", e="oC", h="NVT", pt="meting", wbw="NVT"),
            _meta(11, g="T", e="oC", h="NVT", pt="meting", wbw="GEM24H"),
            # Out-of-scope entries that must be excluded
            _meta(20, g="Q", e="m3/s", h="NVT", pt="verwachting", wbw="NVT"),
            _meta(21, g="WATHTE", e="cm", h="NAP", pt="astronomisch", wbw="NVT"),
            _meta(22, g="WATHTE", e="cm", h="NAP", pt="meting", wbw="NVT", grp="GETETM2"),
            _meta(23, g="WATHTE", e="cm", h="NAP", pt="meting", wbw="NVT", grp="EXTMWTHTE2"),
            _meta(24, g="Q", e="m3/d", h="NVT", pt="meting", wbw="SOM"),
            _meta(25, g="WATHTE", e="cm", h="NAP", pt="meting", wbw="GEMH"),
            _meta(26, g="T", e="oC", h="NVT", pt="meting", wbw="GEM6H"),
            _meta(27, g="T", e="oC", h="NVT", pt="meting", wbw="GEM"),
            _meta(28, g="WATHTE", e="cm", h="NAP", pt="meting", wbw="other:EXTMND", grp="EXTMWTHTE2"),
            _meta(29, comp="LT", g="T", e="oC", h="NVT", pt="meting", wbw="NVT"),
            _meta(30, comp="OW", g="SALNTT", e="DIMSLS", h="NVT", pt="meting", wbw="NVT"),
        ],
        "AquoMetadataLocatieLijst": [
            # Lobith has both F216 and F230 for Q m3/s NVT -> must deduplicate to 1 association
            {"AquoMetaData_MessageID": 1, "Locatie_MessageID": 1001},
            {"AquoMetaData_MessageID": 2, "Locatie_MessageID": 1001},
            {"AquoMetaData_MessageID": 3, "Locatie_MessageID": 1001},
            {"AquoMetaData_MessageID": 4, "Locatie_MessageID": 1001},
            {"AquoMetaData_MessageID": 5, "Locatie_MessageID": 1001},
            {"AquoMetaData_MessageID": 6, "Locatie_MessageID": 1001},
            {"AquoMetaData_MessageID": 10, "Locatie_MessageID": 1001},
            {"AquoMetaData_MessageID": 11, "Locatie_MessageID": 1001},
            # Eijsden has TAW and PLAATSLR
            {"AquoMetaData_MessageID": 7, "Locatie_MessageID": 1002},
            {"AquoMetaData_MessageID": 9, "Locatie_MessageID": 1002},
            # Bonaire has MSL and T
            {"AquoMetaData_MessageID": 8, "Locatie_MessageID": 1003},
            {"AquoMetaData_MessageID": 10, "Locatie_MessageID": 1003},
            # Excluded station only has out-of-scope metadata
            {"AquoMetaData_MessageID": 20, "Locatie_MessageID": 1004},
            {"AquoMetaData_MessageID": 21, "Locatie_MessageID": 1004},
            {"AquoMetaData_MessageID": 22, "Locatie_MessageID": 1004},
            {"AquoMetaData_MessageID": 23, "Locatie_MessageID": 1004},
            {"AquoMetaData_MessageID": 24, "Locatie_MessageID": 1004},
            {"AquoMetaData_MessageID": 25, "Locatie_MessageID": 1004},
            {"AquoMetaData_MessageID": 26, "Locatie_MessageID": 1004},
            {"AquoMetaData_MessageID": 27, "Locatie_MessageID": 1004},
            {"AquoMetaData_MessageID": 28, "Locatie_MessageID": 1004},
            {"AquoMetaData_MessageID": 29, "Locatie_MessageID": 1004},
            {"AquoMetaData_MessageID": 30, "Locatie_MessageID": 1004},
        ],
    }


def _synthetic_provenance(native_bytes: bytes):
    catalogus_rec = RecordingReference(
        recording_id="nl_rws_catalogus_extended",
        repository_path="01b_catalogus_extended.json",
        source_url="https://ddapi20-waterwebservices.rijkswaterstaat.nl/METADATASERVICES/OphalenCatalogus",
        retrieved_at=RETRIEVED_AT.value,
        media_type="application/json",
        sha256="a" * 64,
    )
    terms_rec = RecordingReference(
        recording_id="nl_rws_terms_rec",
        repository_path="acquisition-receipts.json",
        source_url="https://www.rijkswaterstaat.nl/copyright",
        retrieved_at=RETRIEVED_AT.value,
        media_type="application/json",
        sha256="f" * 64,
    )
    acquisitions = (
        AcquisitionRecord(
            acquisition_id="nl_rws_catalogus",
            method="http_request",
            instant_type="retrieval",
            retrieved_at_start=RETRIEVED_AT.value,
            recording_ids=(catalogus_rec.recording_id,),
            description="Extended DDAPI 2.0 OphalenCatalogus snapshot",
            requested_from=(catalogus_rec.source_url,),
        ),
        AcquisitionRecord(
            acquisition_id="nl_rws_terms",
            method="http_request",
            instant_type="retrieval",
            retrieved_at_start=RETRIEVED_AT.value,
            recording_ids=(terms_rec.recording_id,),
            description="Rijkswaterstaat open data terms (Public Domain Mark 1.0 / CC0 1.0)",
            requested_from=(terms_rec.source_url,),
        ),
    )
    bindings = (
        FactBinding(
            fact_group="nl_rws_catalogus_source",
            source_id="nl_rws",
            acquisition_id="nl_rws_catalogus",
            facts=(
                "source.station.ophalen_catalogus_locations",
                "source.station.etrs89_coordinates",
                "source.product.aquo_metadata_catalogue",
                "source.station_product.aquo_metadata_location_links",
            ),
        ),
        FactBinding(
            fact_group="nl_rws_terms_source",
            source_id="nl_rws",
            acquisition_id="nl_rws_terms",
            facts=("source.provider.license", "source.provider.citation"),
        ),
    )
    statements = (
        SourceStatement(
            kind="license",
            exact_text="CC0-1.0",
            recording_id=terms_rec.recording_id,
            fact="source.provider.license",
        ),
        SourceStatement(
            kind="citation",
            exact_text="Bron: Rijkswaterstaat – Waterwebservices",
            recording_id=terms_rec.recording_id,
            fact="source.provider.citation",
        ),
    )
    return build_acquisition_provenance(
        NativeTableIdentity(
            location_kind="retained",
            repository_path="maintenance/catalogue/nl_rws/official/native.parquet",
            revision="b" * 40,
            sha256=hashlib.sha256(native_bytes).hexdigest(),
            byte_size=len(native_bytes),
        ),
        (catalogus_rec, terms_rec),
        acquisitions=acquisitions,
        source_bindings=bindings,
        statements=statements,
    )


def test_station_native_table_filters_scope_deduplicates_methods_and_preserves_native_fields() -> None:
    native, associations = generate_catalogue.station_native_table(_synthetic_catalogus(), retrieved_at=RETRIEVED_AT)
    # 3 in-scope stations (including Bonaire), 1 excluded station dropped
    assert native.data["Code"].to_list() == [
        "eijsden.grens",
        "kralendijk.plazabeachterminal",
        "lobith.bovenrijn.tolkamer",
    ]
    # Omschrijving and Locatie_MessageID preserved in NativeTable
    lobith = native.data.filter(pl.col("Code") == "lobith.bovenrijn.tolkamer").to_dicts()[0]
    assert lobith["Locatie_MessageID"] == 1001
    assert lobith["Naam"] == "Lobith"
    assert lobith["Omschrijving"] == "Bovenrijn Tolkamer"
    assert lobith["Coordinatenstelsel"] == "ETRS89"

    # Parallel F216 + F230 collapsed into one (Code, product_id) association
    lobith_products = sorted(associations.filter(pl.col("Code") == "lobith.bovenrijn.tolkamer")["product_id"].to_list())
    assert lobith_products == [
        "discharge_m3d_nvt",
        "discharge_m3s_gem24h",
        "discharge_m3s_nvt",
        "stage_nap_gem24h",
        "stage_nap_nvt",
        "water_temperature_gem24h",
        "water_temperature_nvt",
    ]
    assert len(associations.filter(pl.col("Code") == "lobith.bovenrijn.tolkamer")) == 7


def test_build_products_has_exact_ten_admitted_products_and_canonical_units() -> None:
    products = generate_catalogue.build_products()
    assert len(products) == 10
    assert len(PRODUCT_DEFINITIONS) == 10
    by_id = {row["product_id"]: row for row in products.iter_rows(named=True)}

    assert by_id["discharge_m3s_nvt"]["unit"] == "m3/s"
    assert by_id["discharge_m3s_nvt"]["frequency"] == "unknown"
    assert by_id["discharge_m3s_nvt"]["statistic"] == "unknown"

    assert by_id["discharge_m3s_gem24h"]["unit"] == "m3/s"
    assert by_id["discharge_m3s_gem24h"]["frequency"] == "P1D"
    assert by_id["discharge_m3s_gem24h"]["statistic"] == "mean"
    assert by_id["discharge_m3s_gem24h"]["period_anchor"] == "unknown"

    assert by_id["discharge_m3d_nvt"]["unit"] == "m3/s"
    assert by_id["stage_nap_nvt"]["unit"] == "m"
    assert by_id["stage_nap_gem24h"]["frequency"] == "P1D"
    assert by_id["stage_nap_gem24h"]["statistic"] == "mean"
    assert {"stage_nap_nvt", "stage_plaatslr_nvt", "stage_msl_nvt", "stage_taw_nvt"} <= set(by_id)

    assert by_id["water_temperature_nvt"]["observed_property"] == "water_temperature"
    assert by_id["water_temperature_nvt"]["unit"] == "degC"
    assert by_id["water_temperature_gem24h"]["frequency"] == "P1D"
    assert by_id["water_temperature_gem24h"]["statistic"] == "mean"


def test_write_and_load_packaged_catalogue_round_trip(tmp_path: Path) -> None:
    native, associations = generate_catalogue.station_native_table(_synthetic_catalogus(), retrieved_at=RETRIEVED_AT)
    native_path = tmp_path / "native.parquet"
    write_native_table(native, native_path)
    native_bytes = native_path.read_bytes()
    provenance = _synthetic_provenance(native_bytes)

    catalogue = generate_catalogue.build_catalogue(
        native,
        STATION_CATALOGUE_ORIGINS,
        associations=associations,
        checked_on=CHECKED_ON,
        provenance=provenance,
    )
    assert catalogue.stations["crs"].to_list() == ["EPSG:4258", "EPSG:4258", "EPSG:4258"]
    assert catalogue.station_products["published_record_start_date"].null_count() == len(catalogue.station_products)
    assert catalogue.station_products["published_record_end_date"].null_count() == len(catalogue.station_products)

    prefix = "src/rivretrieve/_internal/providers/nl_rws/"
    code_id = {"repository": "https://github.com/RivRetrieve/RivRetrieve", "revision": "c" * 40}
    archive_id = {
        "archive_repository": "https://github.com/RivRetrieve/verification-evidence",
        "archive_revision": "d" * 40,
        "collection_id": "nl_rws-access-2026-11-25-v1",
        "manifest_sha256": "e" * 64,
    }
    build_inputs = CatalogueBuildInputs(
        build=CodeReference(**code_id, repository_path=prefix + "generate_catalogue.py", symbol="write_catalogue"),
        declarations=(
            CodeReference(**code_id, repository_path=prefix + "generate_catalogue.py", symbol="build_catalogue"),
            CodeReference(**code_id, repository_path=prefix + "origins.py", symbol="build_acquisition_provenance"),
            CodeReference(**code_id, repository_path=prefix + "origins.py", symbol="STATION_METADATA_FIELDS"),
            CodeReference(**code_id, repository_path=prefix + "origins.py", symbol="STATION_METADATA_NOTICE"),
            CodeReference(**code_id, repository_path=prefix + "catalogue_series.py", symbol="describe_catalogue"),
        ),
        inputs=(
            RetainedInputUse(
                reference=ArchiveMemberReference(
                    **archive_id,
                    artifact_id="nl_rws_native_parquet",
                    role="derived_input",
                    sha256=provenance.native_table.sha256,
                    byte_size=len(native_bytes),
                ),
                usage="native_table",
                facts=(
                    "source.station.ophalen_catalogus_locations",
                    "source.station.etrs89_coordinates",
                    "source.station_product.aquo_metadata_location_links",
                ),
            ),
            RetainedInputUse(
                reference=ArchiveMemberReference(
                    **archive_id,
                    artifact_id="catalogus_extended",
                    role="response_recording",
                    sha256="a" * 64,
                    byte_size=1234,
                ),
                usage="recording",
                facts=(
                    "source.station.ophalen_catalogus_locations",
                    "source.station.etrs89_coordinates",
                    "source.product.aquo_metadata_catalogue",
                    "source.station_product.aquo_metadata_location_links",
                ),
            ),
            RetainedInputUse(
                reference=ArchiveMemberReference(
                    **archive_id,
                    artifact_id="acquisition_receipts",
                    role="acquisition_receipt",
                    sha256="f" * 64,
                    byte_size=567,
                ),
                usage="recording",
                facts=("source.provider.license", "source.provider.citation"),
            ),
        ),
    )

    out_dir = tmp_path / "catalogue"
    generate_catalogue.write_catalogue(catalogue, out_dir, build_inputs=build_inputs, native_table=native)

    artifact = load_packaged_catalogue_artifact(out_dir, on_issue="raise")
    assert artifact.provider_info["provider_id"] == "nl_rws"
    assert len(artifact.stations) == 3
    assert len(artifact.products) == 10
    metadata_df = pl.read_parquet(out_dir / "station_metadata.parquet")
    present_roles = metadata_df.filter(pl.col("source_value").is_not_null())["attribute_role"].unique().to_list()
    assert present_roles == ["station_name"]
    assert '"Lobith"' in metadata_df.filter(pl.col("attribute_role") == "station_name")["source_value"].to_list()
    series, _ = materialize_series(artifact)
    assert len({s.product_id for s in series}) == 10


def test_station_native_table_rejects_duplicate_code_and_unknown_crs() -> None:
    bad_dup = _synthetic_catalogus()
    bad_dup["LocatieLijst"] = [
        *bad_dup["LocatieLijst"],
        {
            "Locatie_MessageID": 9999,
            "Code": "lobith.bovenrijn.tolkamer",
            "Coordinatenstelsel": "ETRS89",
            "Lat": 51.85,
            "Lon": 6.11,
            "Naam": "Lobith Duplicate",
            "Omschrijving": "Duplicate",
        },
    ]
    with pytest.raises(FatalContractError, match="duplicate"):
        generate_catalogue.station_native_table(bad_dup, retrieved_at=RETRIEVED_AT)

    bad_crs = _synthetic_catalogus()
    bad_crs["LocatieLijst"][0]["Coordinatenstelsel"] = "RD"
    with pytest.raises(FatalContractError, match="ETRS89"):
        generate_catalogue.station_native_table(bad_crs, retrieved_at=RETRIEVED_AT)


def test_packaged_nl_rws_catalogue_loads_cleanly() -> None:
    catalogue_dir = Path("src/rivretrieve/_internal/providers/nl_rws/catalogue")
    artifact = load_packaged_catalogue_artifact(catalogue_dir, on_issue="raise")
    assert artifact.provider_info["provider_id"] == "nl_rws"
    assert artifact.provider_info["license"] == "CC0-1.0"
    assert len(artifact.stations) == 1706
    assert len(artifact.products) == 10
    assert artifact.stations["crs"].unique().to_list() == ["EPSG:4258"]
    assert "lobith.bovenrijn.tolkamer" in artifact.stations["station_id"].to_list()
    assert "kralendijk.plazabeachterminal" in artifact.stations["station_id"].to_list()
