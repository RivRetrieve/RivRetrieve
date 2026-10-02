"""Normalized evidence preserves all ordered source assertions and rejects corrupt relations."""

import json
from hashlib import sha256
from pathlib import Path

import polars as pl
import polars.testing as plt
import pytest
from pydantic import ValidationError

from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance
from rivretrieve._internal.catalogues.evidence import (
    EVIDENCE_SCHEMAS,
    CatalogueEvidence,
    EvidenceHeader,
    normalize_provenance,
    validate_catalogue_locators,
)
from rivretrieve._internal.catalogues.evidence_encoding import (
    encode_catalogue_evidence,
    parse_catalogue_evidence,
    reconstruct_provenance,
)
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS

ROOT = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers"


def _legacy(provider, path=None):
    path = ROOT / provider / "catalogue" if path is None else path
    content = (path / "provenance.json").read_bytes()
    import json

    if json.loads(content)["schema_version"] == 3:
        header = EvidenceHeader.model_validate_json(content)
        evidence = parse_catalogue_evidence(header, {name: (path / name).read_bytes() for name in header.files})
        return reconstruct_provenance(evidence)
    return AcquisitionProvenance.model_validate_json(content)


def _normalized(provider):
    path = ROOT / provider / "catalogue"
    return normalize_provenance(
        _legacy(provider),
        stations=pl.read_parquet(path / "stations.parquet"),
        station_products=pl.read_parquet(path / "station_products.parquet"),
    )


@pytest.mark.parametrize("provider", BUILTIN_PROVIDER_IDS)
def test_complete_ordered_provenance_roundtrip(provider):
    old = _legacy(provider)
    path = ROOT / provider / "catalogue"
    evidence = normalize_provenance(
        old,
        stations=pl.read_parquet(path / "stations.parquet"),
        station_products=pl.read_parquet(path / "station_products.parquet"),
    )
    assert reconstruct_provenance(evidence).model_dump(mode="json") == old.model_dump(mode="json")
    files = encode_catalogue_evidence(evidence)
    assert files == encode_catalogue_evidence(evidence)
    header = EvidenceHeader.model_validate_json(files.pop("provenance.json"))
    parsed = parse_catalogue_evidence(header, files)
    assert parsed.header == evidence.header
    for name in EVIDENCE_SCHEMAS:
        plt.assert_frame_equal(getattr(parsed, name), getattr(evidence, name))
    assert reconstruct_provenance(parsed).model_dump(mode="json") == old.model_dump(mode="json")


def test_column_json_roundtrip_and_python_values():
    evidence = _normalized("pl_imgw")
    parsed = CatalogueEvidence.model_validate_json(evidence.model_dump_json())
    assert parsed.header == evidence.header
    assert isinstance(evidence.model_dump()["facts"], pl.DataFrame)
    for name in EVIDENCE_SCHEMAS:
        plt.assert_frame_equal(getattr(parsed, name), getattr(evidence, name))
    assert "source.station" not in repr(evidence)


def _change(evidence, name, frame):
    return {**evidence.model_dump(), name: frame}


@pytest.mark.parametrize(
    "relation,column,value",
    [
        ("facts", "fact_id", 999999),
        ("acquisitions", "source_ordinal", 999999),
        ("acquisitions", "acquisition_ordinal", 999999),
        ("acquisitions", "description_id", 999999),
        ("bindings", "acquisition_key", 999999),
        ("binding_facts", "fact_id", 999999),
        ("external_inputs", "source_ordinal", 999999),
        ("external_inputs", "position", 999999),
    ],
)
def test_relation_keys_fail_closed(relation, column, value):
    evidence = _normalized("pl_imgw")
    frame = getattr(evidence, relation).with_columns(
        pl.when(pl.int_range(pl.len()) == 0)
        .then(pl.lit(value, dtype=pl.UInt32))
        .otherwise(pl.col(column))
        .alias(column)
    )
    with pytest.raises(ValidationError):
        CatalogueEvidence.model_validate(_change(evidence, relation, frame))


@pytest.mark.parametrize(
    "column,value",
    [
        ("requested_from", ["https://bad host"]),
        ("requested_from", []),
        ("recording_ids", [None]),
        ("method", "guess"),
        ("instant_type", "runtime"),
        ("retrieved_at_start", None),
        ("material_sha256", "invalid"),
    ],
)
def test_acquisition_semantics_fail_closed(column, value):
    evidence = _normalized("usgs_nwis")
    frame = evidence.acquisitions.with_columns(
        pl.when(pl.int_range(pl.len()) == 0)
        .then(pl.lit(value, dtype=EVIDENCE_SCHEMAS["acquisitions"][column]))
        .otherwise(pl.col(column))
        .alias(column)
    )
    with pytest.raises(ValidationError):
        CatalogueEvidence.model_validate(_change(evidence, "acquisitions", frame))


def test_exact_file_authority_and_bytes():
    evidence = _normalized("usgs_nwis")
    files = encode_catalogue_evidence(evidence)
    header = EvidenceHeader.model_validate_json(files.pop("provenance.json"))
    with pytest.raises(ValueError, match="five"):
        parse_catalogue_evidence(header, {**files, "native.parquet": b"private"})
    filename = next(iter(files))
    with pytest.raises(ValueError, match="digest"):
        parse_catalogue_evidence(header, {**files, filename: files[filename] + b"changed"})
    payload = header.model_dump()
    payload["files"][filename]["path"] = "../" + filename
    with pytest.raises(ValidationError, match="basename"):
        EvidenceHeader.model_validate(payload)


@pytest.mark.parametrize("provider", ["fr_hubeau", "ba_fhmzbih", "th_thaiwater"])
def test_every_actual_pair_has_exact_availability_locator(provider):
    evidence = _normalized(provider)
    path = ROOT / provider / "catalogue"
    pairs = pl.read_parquet(path / "station_products.parquet")
    stations = pl.read_parquet(path / "stations.parquet")
    locators = evidence.facts.filter(pl.col("locator_role") == "availability")
    plt.assert_frame_equal(
        locators.select("station_id", "product_id").sort("station_id", "product_id"),
        pairs.select("station_id", "product_id").sort("station_id", "product_id"),
    )
    with pytest.raises(ValueError, match="absent canonical"):
        validate_catalogue_locators(evidence, stations=stations, station_products=pairs.slice(1))
    fact = locators["fact_id"][0]
    frame = evidence.facts.with_columns(
        [
            pl.when(pl.col("fact_id") == fact).then(None).otherwise(pl.col(c)).alias(c)
            for c in ("carrier", "station_id", "product_id", "locator_role")
        ]
    )
    incomplete = CatalogueEvidence.model_validate(_change(evidence, "facts", frame))
    with pytest.raises(ValueError, match="exactly cover"):
        validate_catalogue_locators(incomplete, stations=stations, station_products=pairs)


def test_runtime_ancestor_and_source_ownership_rejected():
    evidence = _normalized("pl_imgw")
    # A transformed canonical binding cannot consume its own output.
    b = evidence.bindings.filter(pl.col("transformation_id").is_not_null())["binding_id"][0]
    fact = evidence.binding_facts.filter(pl.col("binding_id") == b)["fact_id"][0]
    inputs = evidence.external_inputs.with_columns(
        pl.when((pl.col("binding_id") == b) & (pl.col("position") == 0))
        .then(pl.lit(fact, dtype=pl.UInt32))
        .otherwise(pl.col("fact_id"))
        .alias("fact_id"),
        pl.when((pl.col("binding_id") == b) & (pl.col("position") == 0))
        .then(None)
        .otherwise(pl.col("source_ordinal"))
        .alias("source_ordinal"),
    )
    with pytest.raises(ValidationError, match="cycle"):
        CatalogueEvidence.model_validate(_change(evidence, "external_inputs", inputs))
    inputs = evidence.external_inputs.with_columns(
        pl.when((pl.col("binding_id") == b) & (pl.col("position") == 0))
        .then(None)
        .otherwise(pl.col("source_ordinal"))
        .alias("source_ordinal")
    )
    with pytest.raises(ValidationError, match="misattributed"):
        CatalogueEvidence.model_validate(_change(evidence, "external_inputs", inputs))
    # Runtime cannot become the ancestor of packaged station facts.
    acquisition = evidence.acquisitions.with_columns(
        [
            pl.when(pl.col("acquisition_key") == 0)
            .then(pl.lit(value, dtype=EVIDENCE_SCHEMAS["acquisitions"][column]))
            .otherwise(pl.col(column))
            .alias(column)
            for column, value in (
                ("method", "runtime_http_request"),
                ("instant_type", "runtime"),
                ("retrieved_at_start", None),
                ("retrieved_at_end", None),
            )
        ]
    )
    with pytest.raises(ValidationError, match="runtime acquisitions"):
        CatalogueEvidence.model_validate(_change(evidence, "acquisitions", acquisition))


@pytest.mark.parametrize(
    "column,value", [("requested_from", ["https://example.org/other"]), ("retrieved_at_start", "2000-01-01T00:00:00Z")]
)
def test_statement_requires_exact_request_and_instant(column, value):
    evidence = _normalized("usgs_nwis")
    statement = evidence.header.source_records[0].statements[0]
    key = evidence.acquisitions.filter(pl.col("recording_ids").list.contains(statement.recording_id))[
        "acquisition_key"
    ][0]
    frame = evidence.acquisitions.with_columns(
        pl.when(pl.col("acquisition_key") == key)
        .then(pl.lit(value, dtype=EVIDENCE_SCHEMAS["acquisitions"][column]))
        .otherwise(pl.col(column))
        .alias(column)
    )
    with pytest.raises(ValidationError, match="exact recording URL and instant"):
        CatalogueEvidence.model_validate(_change(evidence, "acquisitions", frame))


@pytest.mark.parametrize("mutation", ["extra", "unequal", "boolean", "negative", "overflow", "string", "partial"])
def test_json_column_boundary_rejects_invalid_shapes(mutation):
    import json

    payload = _normalized("usgs_nwis").model_dump(mode="json")
    if mutation == "extra":
        payload["facts"]["extra"] = []
    elif mutation == "unequal":
        payload["facts"]["name"].pop()
    elif mutation == "partial":
        payload["facts"]["station_id"][0] = "unlocated"
    else:
        payload["facts"]["fact_id"][0] = {"boolean": True, "negative": -1, "overflow": 2**32, "string": "0"}[mutation]
    with pytest.raises(ValidationError):
        CatalogueEvidence.model_validate_json(json.dumps(payload))


def test_v3_parse_never_constructs_old_national_models(monkeypatch):
    from rivretrieve._internal import acquisition_provenance as legacy

    evidence = _normalized("th_thaiwater")
    files = encode_catalogue_evidence(evidence)
    header = EvidenceHeader.model_validate_json(files.pop("provenance.json"))

    def reject(*args, **kwargs):
        raise AssertionError("v2 national model constructed")

    for model in (
        legacy.AcquisitionProvenance,
        legacy.AcquisitionRecord,
        legacy.FactBinding,
        legacy.ExternalFactReference,
        legacy.Transformation,
        legacy.SourceRecord,
    ):
        monkeypatch.setattr(model, "__init__", reject)
    parsed = parse_catalogue_evidence(header, files)
    plt.assert_frame_equal(parsed.facts, evidence.facts)


# Brazil has new adopted-product acquisitions after this migration oracle.
# Its current evidence still passes the all-provider lossless roundtrip above;
# source-material and per-pair assertions live in test_br_ana_catalogue_telemetry.
def _assert_usgs_modern_extension_and_restore_legacy(retained_evidence_root: Path, provenance):
    """Check the complete modern delta before applying the immutable legacy oracle."""
    import gzip

    directory = retained_evidence_root / "research/usgs-modern-coverage"
    legacy = _legacy("usgs_nwis", directory / "legacy-catalogue")
    previous = legacy.model_dump(mode="json")
    source = previous["source_records"][0]
    recordings = []
    receipts = sorted(directory.glob("metadata-*.receipt.json"))
    assert len(receipts) == 14
    for index, path in enumerate(receipts):
        receipt = json.loads(path.read_text())
        compressed = (directory / receipt["file"]).read_bytes()
        original = gzip.decompress(compressed)
        assert sha256(original).hexdigest() == receipt["sha256"]
        assert len(original) == receipt["bytes"]
        assert receipt["status"] == 200
        assert receipt["retrieved_at"].endswith("+00:00")
        recordings.append(
            {
                "recording_id": f"modern_metadata_{index}",
                "repository_path": f"research/usgs-modern-coverage/{receipt['file']}",
                "source_url": receipt["url"],
                "retrieved_at": receipt["retrieved_at"][:-6] + "Z",
                "media_type": "application/gzip",
                "sha256": sha256(compressed).hexdigest(),
            }
        )
    metadata_id = "modern_time_series_metadata_2026_09_22"
    runtime_id = "modern_observation_request"
    acquisitions = [
        {
            "acquisition_id": metadata_id,
            "method": "http_campaign",
            "instant_type": "retrieval_interval",
            "description": "Complete unsorted v1 metadata pagination for parameters 00060 and 00065, including discontinued records; exact decompressed response hashes and request receipts retained alongside gzip recordings. Station scope remains the independently acquired native station table. UTC metadata ranges do not establish physical daily support.",
            "requested_from": [item["source_url"] for item in recordings],
            "retrieved_at_start": min(item["retrieved_at"] for item in recordings),
            "retrieved_at_end": max(item["retrieved_at"] for item in recordings),
            "recording_ids": [item["recording_id"] for item in recordings],
            "material": None,
        },
        {
            "acquisition_id": runtime_id,
            "method": "runtime_http_request",
            "instant_type": "runtime",
            "description": "Exact modern Water Data v1 daily or continuous request and response retained at runtime; independent of historical WaterServices calls",
            "requested_from": [
                "https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily/items",
                "https://api.waterdata.usgs.gov/ogcapi/v1/collections/continuous/items",
            ],
            "retrieved_at_start": None,
            "retrieved_at_end": None,
            "recording_ids": [],
            "material": None,
        },
    ]
    extended_source = {
        **source,
        "acquisitions": source["acquisitions"] + acquisitions,
        "evidence": source["evidence"]
        + [
            {
                "evidence_id": item["recording_id"],
                "description": "Exact modern metadata response compressed losslessly",
                "recording": item,
            }
            for item in recordings
        ],
    }
    metadata_facts = [
        "source.product.modern_parameter_statistic_computation_codes",
        "source.station_product.modern_series_availability",
        "source.series.modern_identity_description_and_utc_ranges",
    ]
    observation_facts = ["source.observation.modern_values_qualifiers_and_timestamps"]
    canonical = previous["fact_bindings"][-1]
    assert canonical["fact_group"] == "canonical_catalogue_carrier"
    source_count = len(previous["fact_universe"]) - len(canonical["facts"])
    assert previous["fact_universe"][source_count:] == canonical["facts"]
    extended_canonical = {
        **canonical,
        "transformation": {
            "name": "USGS native station facts and modern series metadata to canonical catalogue carriers",
            "external_inputs": [
                {"source_id": "usgs_nwis", "fact": fact}
                for fact in [
                    "source.provider.usgs_agency_identity",
                    "source.station.nwis_identity_location_datum",
                    *metadata_facts,
                ]
            ],
        },
    }
    expected = {
        **previous,
        "source_records": [extended_source],
        "fact_universe": previous["fact_universe"][:source_count]
        + metadata_facts
        + observation_facts
        + canonical["facts"],
        "fact_bindings": previous["fact_bindings"][:-1]
        + [
            {
                "fact_group": "modern_series_metadata",
                "facts": metadata_facts,
                "source_id": "usgs_nwis",
                "acquisition_id": metadata_id,
            },
            {
                "fact_group": "modern_observation_values",
                "facts": observation_facts,
                "source_id": "usgs_nwis",
                "acquisition_id": runtime_id,
            },
            extended_canonical,
        ],
    }
    # Every legacy value and its order must survive in the current publication;
    # only the explicitly checked modern delta and projection may differ.
    assert provenance.model_dump(mode="json") == expected
    return legacy


def _assert_usgs_definition_extension_and_restore_original(retained_evidence_root: Path, provenance):
    """Prove the exact new publisher evidence, then compare every original assertion."""
    model = provenance.model_dump(mode="json")
    fact = "source.usgs.instantaneous_value_definition"
    recording_id = "usgs_nwis_instantaneous_values_definition"
    acquisition_id = "instantaneous_values_definition_capture_2026_09_19"
    source_url = "https://waterservices.usgs.gov/docs/instantaneous-values/instantaneous-values-details/"
    retrieved_at = "2026-09-19T20:58:46.743636Z"
    digest = "1cec37f8cec8173f635d4afaba2d08814347d9cff672b25c29d427b004d0b3a2"
    repository_path = "tests/test_data/usgs_nwis_instantaneous_values_definition.html"
    source_bytes = (retained_evidence_root / repository_path).read_bytes()
    assert sha256(source_bytes).hexdigest() == digest
    assert b"most recent instantaneous value" in source_bytes
    expected_acquisition = {
        "acquisition_id": acquisition_id,
        "method": "http_request",
        "instant_type": "retrieval",
        "description": "Publisher Instantaneous Values Service Details documentation calls the returned measurement an instantaneous value; it does not establish a concrete series sampling frequency.",
        "requested_from": [source_url],
        "retrieved_at_start": retrieved_at,
        "retrieved_at_end": None,
        "recording_ids": [recording_id],
        "material": None,
    }
    expected_evidence = {
        "evidence_id": "usgs_instantaneous_value_definition",
        "description": 'Publisher service documentation: "most recent instantaneous value"; the service request URL is /nwis/iv/.',
        "recording": {
            "recording_id": recording_id,
            "repository_path": repository_path,
            "source_url": source_url,
            "retrieved_at": retrieved_at,
            "media_type": "text/html; charset=UTF-8",
            "sha256": digest,
        },
    }
    expected_binding = {
        "fact_group": "instantaneous_value_definition",
        "facts": [fact],
        "source_id": "usgs_nwis",
        "acquisition_id": acquisition_id,
    }
    assert model["fact_universe"].count(fact) == 1
    assert model["fact_universe"][0] == fact
    source = next(item for item in model["source_records"] if item["source_id"] == "usgs_nwis")
    assert [item for item in source["acquisitions"] if item["acquisition_id"] == acquisition_id] == [
        expected_acquisition
    ]
    assert source["acquisitions"][-1] == expected_acquisition
    assert [item for item in source["evidence"] if item["evidence_id"] == expected_evidence["evidence_id"]] == [
        expected_evidence
    ]
    assert source["evidence"][0] == expected_evidence
    assert [item for item in model["fact_bindings"] if item["fact_group"] == expected_binding["fact_group"]] == [
        expected_binding
    ]
    assert model["fact_bindings"][0] == expected_binding
    # Remove only the exact, separately verified additions. All other contents
    # and their complete original order remain subject to the pinned v2 oracle.
    model["fact_universe"].pop(0)
    source["acquisitions"].pop()
    source["evidence"].pop(0)
    model["fact_bindings"].pop(0)
    return AcquisitionProvenance.model_validate(model)


def _assert_semantic_lineage_repair_and_restore_original(provenance):
    """Verify intentional repairs before comparing every unchanged ordered assertion.

    This restoration is only an oracle projection, not usable provider lineage.
    Publisher content and current fact bindings are tested in
    test_provider_semantic_lineage.py.
    """
    model = provenance.model_dump(mode="json")
    provider = model["provider_id"]
    (source,) = model["source_records"]
    bindings = {item["fact_group"]: item for item in model["fact_bindings"]}
    catalogue = bindings["catalogue_external"]
    if provider == "cz_chmi":
        added = ["source.product.daily_mean_semantics"]
        assert model["fact_universe"][9:10] == added
        assert catalogue["facts"] == [
            "source.provider.service",
            "source.station.native_identity",
            "source.station.native_location",
            "source.station.crs_not_published",
            "source.station_product.availability_not_published",
        ]
        catalogue["facts"].insert(1, "source.product.native_identity")
        semantics = bindings["product_semantics"]
        assert semantics == {
            "fact_group": "product_semantics",
            "facts": [
                "source.product.native_identity",
                "source.product.hourly_mean_semantics",
                "source.product.hourly_interval_anchor_not_established",
                *added,
            ],
            "source_id": provider,
            "acquisition_id": "product_semantics_capture_2026_09_02",
        }
        semantics["fact_group"] = "hourly_product_semantics"
        semantics["facts"] = semantics["facts"][1:-1]
        acquisition = source["acquisitions"][2]
        assert acquisition["acquisition_id"] == "product_semantics_capture_2026_09_02"
        assert acquisition["description"] == (
            "CHMI TSCON_ID/TSCON_DS and UNIT_ID/UNIT_DS dictionary: "
            "HD/QD/TD daily means and HH/QH hourly means, quantities and coded units"
        )
        acquisition["description"] = "CHMI product dictionary establishing HH and QH as hourly means"
        input_positions = {"canonical_catalogue": 8, "canonical_catalogue_carrier": 7}
    else:
        assert provider == "lt_lhmt"
        added = ["source.product.historical_daily_mean_semantics", "source.product.historical_time_zone"]
        assert model["fact_universe"][6:8] == added
        assert catalogue["facts"] == [
            "source.provider.service",
            "source.station.native_identity",
            "source.station.native_location",
            "source.station_product.availability_not_published",
        ]
        catalogue["facts"].insert(1, "source.product.native_fields")
        catalogue["facts"].insert(4, "source.station.crs_documentation")
        semantics = bindings["api_documented_semantics"]
        assert semantics == {
            "fact_group": "api_documented_semantics",
            "facts": ["source.product.native_fields", "source.station.crs_documentation", *added],
            "source_id": provider,
            "acquisition_id": "terms_capture_2026_08_21",
        }
        assert model["fact_bindings"][2] == semantics
        model["fact_bindings"].pop(2)
        acquisition = source["acquisitions"][1]
        assert acquisition["acquisition_id"] == "terms_capture_2026_08_21"
        assert acquisition["description"] == "Meteo LT API documentation and data-use conditions HTML recording"
        acquisition["description"] = "Meteo LT API data-use conditions HTML recording"
        (evidence,) = source["evidence"]
        assert evidence["description"] == (
            "Meteo LT API documentation and data-use conditions: historical observations "
            "waterLevel (cm) and waterDischarge (m3/s), Vidurkis per parą; "
            "observationDateUtc (UTC laiko juosta); coordinates (WGS 84)"
        )
        evidence["description"] = "Meteo LT API data-use conditions"
        input_positions = {"canonical_catalogue": 6, "canonical_catalogue_carrier": 2}
    # Both transformations must include precisely the new publisher facts at
    # their declared positions. All other input ordering remains oracle-checked.
    for group, position in input_positions.items():
        binding = bindings[group]
        inputs = binding["transformation"]["external_inputs"]
        assert inputs[position : position + len(added)] == [{"source_id": provider, "fact": fact} for fact in added]
        del inputs[position : position + len(added)]
    for fact in added:
        assert model["fact_universe"].count(fact) == 1
        model["fact_universe"].remove(fact)
    return AcquisitionProvenance.model_validate(model)


def _assert_field_source_lineage_repair_and_restore_original(retained_evidence_root: Path, provenance):
    """Check exact source-field repairs, then retain the original full ordered oracle.

    See source-field-conformance.md and test_source_field_boundaries.py for
    independent source headers, L1 identity, title and observation-carrier proof.
    This projection is test-only; it does not restore obsolete runtime lineage.
    """
    model = provenance.model_dump(mode="json")
    provider = model["provider_id"]
    if provider == "ch_foen":
        assert model["fact_universe"][11] == "observation.source_series_shape"
        model["fact_universe"][11] = "observation.canonical_five_column_shape"
        binding = next(item for item in model["fact_bindings"] if item["fact_group"] == "canonical_observation_shape")
        assert binding["facts"] == ["observation.source_series_shape"]
        assert binding["transformation"]["name"] == "BAFU observations to identified RivRetrieve observations"
        binding["facts"] = ["observation.canonical_five_column_shape"]
        binding["transformation"]["name"] = "BAFU observations to RivRetrieve five-column result shape"
    elif provider == "fr_hubeau":
        acquisition = next(
            item
            for source in model["source_records"]
            for item in source["acquisitions"]
            if item["acquisition_id"] == "station_observation_publication"
        )
        assert acquisition["description"] == (
            "HydroPortail station-own Q/H publication from PHyC; response titles establish instantaneous quantities; "
            "not a shared-site series or original-producer assertion"
        )
        acquisition["description"] = (
            "HydroPortail station-own instantaneous Q/H publication from PHyC; "
            "not a shared-site series or original-producer assertion"
        )
    else:
        assert provider == "ba_fhmzbih"
        (source,) = model["source_records"]
        assert source["source_id"] == "ba_avp_sava"
        fact = "source.series.layer20_discharge_identity"
        assert model["fact_universe"].count(fact) == 1
        assert model["fact_universe"][484] == fact
        model["fact_universe"].pop(484)
        assert model["fact_bindings"].pop(0) == {
            "fact_group": "layer20_discharge_series",
            "facts": [fact],
            "source_id": "ba_avp_sava",
            "acquisition_id": "layer20_series_capture",
        }
        binding = next(item for item in model["fact_bindings"] if item["fact_group"] == "canonical_products")
        assert binding == {
            "fact_group": "canonical_products",
            "facts": ["source.product.native_identifiers", "source.product.native_physics"],
            "source_id": "ba_avp_sava",
            "acquisition_id": "product_workbook_headers",
        }
        binding["acquisition_id"] = "catalogue_capture_2026_08_02"
        recordings = [
            (
                "ba_fhmzbih_4024_Q_1Y",
                "stations/4/4024/Q/Q_1Y.xlsx",
                "2026-09-02T14:45:27.662275Z",
                "e40e760cf99d4e23b62b8d5d95edc86af01ddca9aa6c55226d59c859e8801d05",
            ),
            (
                "ba_fhmzbih_4024_H_1Y",
                "stations/4/4024/H/H_1Y.xlsx",
                "2026-09-02T14:45:27.984829Z",
                "45b5663132a58f5bdcf3ee29c5cdd8c5f83389dabb80d3716b5e318b77ca79a0",
            ),
            (
                "ba_fhmzbih_4110_Tvode_1Y",
                "stations/4/4110/WT/Tvode_1Y.xlsx",
                "2026-09-02T14:46:35.312471Z",
                "e0532ec0a269acb735db6957a478652ac0fb7ece9194b688852478d6d186dbb3",
            ),
            (
                "ba_fhmzbih_layer20_series",
                "layers/20/index.json",
                "2026-09-02T14:45:07.284216Z",
                "afb0dbd8530f1b589028731a42611e933d6991ec35414bdaba071c7a3180dabf",
            ),
        ]
        expected_evidence = []
        for index, (recording_id, route, instant, digest) in enumerate(recordings):
            filename = recording_id if index < 3 else "ba_fhmzbih_metadata_index"
            repository_path = f"tests/test_data/{filename}.recording.json"
            assert sha256((retained_evidence_root / repository_path).read_bytes()).hexdigest() == digest
            expected_evidence.append(
                {
                    "evidence_id": recording_id if index < 3 else "layer20_discharge_series",
                    "description": "Published workbook parameter, unit and series-name headers"
                    if index < 3
                    else "Published L1_ts_id, L1_ts_name, parameter and unit",
                    "recording": {
                        "recording_id": recording_id,
                        "repository_path": repository_path,
                        "source_url": f"https://vodostaji.voda.ba/data/internet/{route}",
                        "retrieved_at": instant,
                        "media_type": "application/vnd.rivretrieve.recording+json",
                        "sha256": digest,
                    },
                }
            )
        assert source["evidence"][:4] == expected_evidence
        assert source["acquisitions"][:2] == [
            {
                "acquisition_id": "product_workbook_headers",
                "method": "http_request",
                "instant_type": "retrieval_interval",
                "description": "Exact Q, H and water-temperature workbook parameter, unit and source-series headers",
                "requested_from": [item["recording"]["source_url"] for item in expected_evidence[:3]],
                "retrieved_at_start": recordings[0][2],
                "retrieved_at_end": recordings[2][2],
                "recording_ids": [item[0] for item in recordings[:3]],
                "material": None,
            },
            {
                "acquisition_id": "layer20_series_capture",
                "method": "http_request",
                "instant_type": "retrieval",
                "description": "Exact layer-20 L1 discharge series identities; no workbook-ID equivalence established",
                "requested_from": [expected_evidence[3]["recording"]["source_url"]],
                "retrieved_at_start": recordings[3][2],
                "retrieved_at_end": None,
                "recording_ids": [recordings[3][0]],
                "material": None,
            },
        ]
        del source["evidence"][:4]
        del source["acquisitions"][:2]
    return AcquisitionProvenance.model_validate(model)


def _assert_swiss_credential_redaction_and_restore_original(retained_evidence_root: Path, provenance):
    """Verify the redacted fixture before applying the immutable historical oracle.

    Only this comparison projection restores the old description and digest.
    The fixture and packaged evidence retain their credential-safe form.
    """
    model = provenance.model_dump(mode="json")
    source = next(item for item in model["source_records"] if item["source_id"] == "ch_existenz")
    repository_path = "tests/test_data/ch_foen_terms_existenz.html"
    digest = "b353852a474516acf404c1d8b775cc77c5cf3c97bd3055380fc4534bcba9111c"
    source_bytes = (retained_evidence_root / repository_path).read_bytes()
    assert sha256(source_bytes).hexdigest() == digest
    assert source_bytes.count(b"REDACTED-PUBLISHED-READ-ONLY-TOKEN") == 1
    assert source["evidence"] == [
        {
            "evidence_id": "existenz_api_terms",
            "description": (
                "Intermediary API conditions and BAFU credit statement; "
                "retained fixture has published archive credential redacted"
            ),
            "recording": {
                "recording_id": "ch_foen_terms_existenz",
                "repository_path": repository_path,
                "source_url": "https://api.existenz.ch/",
                "retrieved_at": "2026-08-20T13:12:58Z",
                "media_type": "text/html; charset=UTF-8",
                "sha256": digest,
            },
        }
    ]
    acquisition = source["acquisitions"][2]
    assert acquisition["recording_ids"] == ["ch_foen_terms_existenz"]
    assert acquisition["description"] == (
        "Existenz API conditions and BAFU credit response; published archive credential redacted in retained fixture"
    )
    acquisition["description"] = "Existenz API conditions and BAFU credit response"
    evidence = source["evidence"][0]
    evidence["description"] = "Intermediary API conditions and BAFU credit statement"
    evidence["recording"]["sha256"] = "488b25d24651aafb520d7cf69c1d36ac9f4384fa096b9cab77b44c6b669f82df"
    return AcquisitionProvenance.model_validate(model)


def _assert_bulk_source_history_preserved(retained_evidence_root: Path, provider, provenance):
    """Compare retained source inputs, not superseded output/authority assertions."""
    path = retained_evidence_root / "tests/test_data/catalogue_provenance_original_v2" / f"{provider}.json"
    original = AcquisitionProvenance.model_validate_json(path.read_bytes())
    before = original.model_dump(mode="json")
    after = provenance.model_dump(mode="json")
    if provider == "ca_eccc":
        # The observation carrier changed; publisher evidence did not.
        assert before["fact_universe"][7] == "observation.canonical_five_column_shape"
        assert after["fact_universe"][7] == "observation.identity_bearing_shape"
        after["fact_universe"][7] = before["fact_universe"][7]
        old_binding = next(x for x in before["fact_bindings"] if x["fact_group"] == "canonical_observation_shape")
        new_binding = next(x for x in after["fact_bindings"] if x["fact_group"] == "canonical_observation_shape")
        assert new_binding["facts"] == ["observation.identity_bearing_shape"]
        assert (
            new_binding["transformation"]["name"]
            == "HYDAT observations to identity-bearing RivRetrieve observation rows"
        )
        new_binding["facts"] = old_binding["facts"]
        new_binding["transformation"]["name"] = old_binding["transformation"]["name"]
    elif provider == "pl_imgw":
        source = next(x for x in after["source_records"] if x["source_id"] == "sr.pl.imgw")
        assert source["acquisitions"][0]["acquisition_id"] == "imgw_archive_definitions_2026_09_20"
        assert source["acquisitions"][0]["recording_ids"] == ["pl_imgw_codz_format", "pl_imgw_yearbook_2025"]
        source["acquisitions"].pop(0)
        assert [x["evidence_id"] for x in source["evidence"][:2]] == [
            "pl_imgw_codz_definition",
            "pl_imgw_yearbook_methods",
        ]
        del source["evidence"][:2]
        physics = next(x for x in after["fact_bindings"] if x["fact_group"] == "imgw_archive_physics")
        assert physics == {
            "fact_group": "imgw_archive_physics",
            "facts": ["source.imgw.observation_archive_product_semantics"],
            "source_id": "sr.pl.imgw",
            "acquisition_id": "imgw_archive_definitions_2026_09_20",
        }
        after["fact_bindings"].remove(physics)
        roster = next(x for x in after["fact_bindings"] if x["fact_group"] == "imgw_catalogue_inputs")
        assert "source.imgw.observation_archive_product_semantics" not in roster["facts"]
        roster["facts"].insert(1, "source.imgw.observation_archive_product_semantics")
    else:
        # CatalogueOnly has no runtime observation acquisition. Its field facts
        # now cite recovered publisher legends rather than a station catalogue.
        (old_source,) = before["source_records"]
        (new_source,) = after["source_records"]
        assert [x["acquisition_id"] for x in old_source["acquisitions"]] == [
            "verified_hydrology_archive_campaign_2026_08_02",
            "observation_request",
        ]
        assert [x["acquisition_id"] for x in new_source["acquisitions"]] == [
            "verified_hydrology_archive_campaign_2026_08_02",
            "daily_field_definitions_repository_recovery",
            "point_field_definitions_repository_recovery",
        ]
        old_note = next(x for x in old_source["evidence"] if x["evidence_id"] == "za_dws_observation_terms_absence")
        new_note = next(x for x in new_source["evidence"] if x["evidence_id"] == "za_dws_observation_terms_absence")
        assert new_note["description"] == (
            "Archived A2H023 Monthly response publishes Variable 100.00 Surface Water Level and monthly volumes "
            "in million cubic metres; no equivalence with D_AVG_FR, COR_FLOW or COR_LEVEL is established. "
            "No applicable terms or citation statement."
        )
        new_note["description"] = old_note["description"]
        old_source["acquisitions"].pop()
        del new_source["acquisitions"][1:]
        removed = {
            "source.product.dws_datatype_and_file_semantics",
            "source.observation.dws_fixed_format_values_quality_and_time",
        }
        added = {"source.product.daily_field_definition", "source.product.point_field_definitions"}
        assert set(before["fact_universe"]) - set(after["fact_universe"]) == removed
        assert set(after["fact_universe"]) - set(before["fact_universe"]) == added
        before["fact_universe"] = [x for x in before["fact_universe"] if x not in removed]
        after["fact_universe"] = [x for x in after["fact_universe"] if x not in added]
        for group, fact, acquisition in (
            (
                "daily_product_identity",
                "source.product.daily_field_definition",
                "daily_field_definitions_repository_recovery",
            ),
            (
                "point_product_identity",
                "source.product.point_field_definitions",
                "point_field_definitions_repository_recovery",
            ),
        ):
            assert next(x for x in after["fact_bindings"] if x["fact_group"] == group) == {
                "fact_group": group,
                "facts": [fact],
                "source_id": "za_dws",
                "acquisition_id": acquisition,
            }
        before["fact_bindings"] = [
            x for x in before["fact_bindings"] if x["fact_group"] not in {"product_identity", "observation_values"}
        ]
        after["fact_bindings"] = [
            x
            for x in after["fact_bindings"]
            if x["fact_group"] not in {"daily_product_identity", "point_product_identity"}
        ]
        for model, omitted in ((before, removed), (after, added)):
            carrier = next(x for x in model["fact_bindings"] if x["fact_group"] == "canonical_catalogue_carrier")
            carrier["transformation"]["external_inputs"] = [
                x for x in carrier["transformation"]["external_inputs"] if x["fact"] not in omitted
            ]
    assert after == before
    # The immutable historical fixture, not today's corrected assertions, remains
    # subject to the original full ordered digest below.
    return original


@pytest.mark.parametrize(
    "provider", tuple(provider for provider in BUILTIN_PROVIDER_IDS if provider not in {"br_ana", "fr_hydroportail"})
)
def test_all_ordered_source_assertions_match_pinned_original_revision(retained_evidence_root: Path, provider):
    oracle = json.loads((Path(__file__).parent / "test_data/catalogue_provenance_ordered_v2.json").read_text())
    assert oracle["revision"] == "6f0edf6a455735cb1f8c858a1a9f35d4245cf209"
    # This expected digest comes from original v2 Git bytes, not a v3 self-roundtrip.
    # The French oracle names the historical combined publication. Its exact
    # authenticated evidence remains readable for research, never as a current catalogue.
    restored = _legacy(
        provider,
        retained_evidence_root / "tests/test_data/french_combined_catalogue" if provider == "fr_hubeau" else None,
    )
    if provider in {"ba_fhmzbih", "ch_foen", "fr_hubeau"}:
        restored = _assert_field_source_lineage_repair_and_restore_original(retained_evidence_root, restored)
    if provider == "ch_foen":
        restored = _assert_swiss_credential_redaction_and_restore_original(retained_evidence_root, restored)
    if provider in {"ca_eccc", "pl_imgw", "za_dws"}:
        restored = _assert_bulk_source_history_preserved(retained_evidence_root, provider, restored)
    if provider == "usgs_nwis":
        restored = _assert_usgs_modern_extension_and_restore_legacy(retained_evidence_root, restored)
        restored = _assert_usgs_definition_extension_and_restore_original(retained_evidence_root, restored)
        assert oracle["providers"][provider]["ordered_model_sha256"] == (
            "28e9cc34f71f4fd3712c69cc205c30b8c70d55270cfc04f90e991a55121450a0"
        )
    if provider in {"cz_chmi", "lt_lhmt"}:
        restored = _assert_semantic_lineage_repair_and_restore_original(restored)
    if provider == "no_nve":
        model = restored.model_dump(mode="json")
        binding = next(item for item in model["fact_bindings"] if item["fact_group"] == "canonical_products")
        assert binding["transformation"]["name"] == (
            "NVE parameter-resolution-unit access vocabulary; raw cadence and version-dependent method, "
            "temporal support and anchor remain unknown at product grain"
        )
        # Verify this corrected projection wording, then compare all unchanged
        # source assertions and ordering against the historical evidence oracle.
        binding["transformation"]["name"] = "NVE parameter-resolution-unit vocabulary to canonical products"
        restored = AcquisitionProvenance.model_validate(model)
    ordered = json.dumps(restored.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    assert sha256(ordered.encode()).hexdigest() == oracle["providers"][provider]["ordered_model_sha256"]
