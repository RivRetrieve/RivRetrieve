"""Synthetic checks for the complete retained-response rebuild composition."""

import hashlib
import json
import lzma
from dataclasses import replace
from unittest.mock import Mock

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.catalogues import publication
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.fr_hubeau import generate_catalogue as generator
from rivretrieve._internal.providers.fr_hubeau import origins
from rivretrieve._internal.providers.fr_hubeau import rebuild_catalogue as module
from rivretrieve._internal.providers.fr_hubeau.station_metadata import read_station_metadata_sources
from tests.test_catalogue_build_provenance import _build
from tests.test_fr_hubeau_station_metadata import adopted, response, site
from tests.test_fr_hubeau_station_metadata import source_inputs as _source_inputs

source_inputs = _source_inputs


@pytest.fixture
def rebuild_inputs(source_inputs):
    root, arguments = source_inputs
    sources = read_station_metadata_sources(root, **arguments)
    inventory = root / "maintenance/catalogue/fr_hubeau/inventory"
    inventory.mkdir(parents=True)
    row = dict.fromkeys(generator.HYDROMETRY_REQUIRED_FIELDS)
    row.update(
        code_station="H001",
        code_site="001",
        latitude_station=48.0,
        longitude_station=2.0,
        code_projection=26,
        libelle_station="Gauge",
    )
    for endpoint, rows, url in (
        ("hydrometry", [row], generator.HYDRO_STATIONS_URL),
        ("temperature", [], generator.TEMP_STATIONS_URL),
    ):
        body = json.dumps({"count": len(rows), "next": None, "data": rows}).encode()
        stem = inventory / f"{endpoint}-stations-2026-09-21"
        stem.with_suffix(".json.xz").write_bytes(lzma.compress(body))
        stem.with_suffix(".receipt.json").write_text(
            json.dumps(
                {
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "bytes": len(body),
                    "status": 200,
                    "content_type": "application/json",
                    "retrieved_at": "2026-01-01T00:00:00+00:00",
                    "url": url,
                    "params": {},
                }
            )
        )
    ledger = inventory / "governing_evidence.json.xz"
    ledger.write_bytes(
        lzma.compress(
            json.dumps(
                {
                    "native_table": {
                        "filename": "src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet",
                        "sha256": generator.NATIVE_TABLE_SHA256,
                        "byte_count": generator.NATIVE_TABLE_BYTE_SIZE,
                    },
                    "pairs": [],
                    "research_head": "b" * 40,
                    "schema_version": 1,
                    "scope": "Synthetic",
                    "summary": {"available": 0, "by_status": {}, "pairs": 0, "stations": 0, "unknown": 0},
                }
            ).encode()
        )
    )
    build = _build().model_copy(update={"inputs": adopted(arguments)})
    return root, ledger, sources, build


@pytest.mark.parametrize("defect", [None, "changed", "unadopted"])
def test_rebuild_hands_metadata_to_real_build_and_publication(rebuild_inputs, tmp_path_factory, monkeypatch, defect):
    root, ledger, sources, build = rebuild_inputs
    destination = tmp_path_factory.mktemp("rebuild-output")
    output = destination / "output"
    capture = destination / "capture.json"
    # Shared provenance certification is covered separately with genuine inputs.
    monkeypatch.setattr(module, "verify_provenance_recordings", Mock())
    final_metadata = Mock(return_value={})
    monkeypatch.setattr(publication, "build_catalogue_metadata", final_metadata)
    if defect == "changed":
        sources = replace(sources, site_bodies={"batch-001": response([site(altitude_site=123.0)])})
    elif defect == "unadopted":
        build = build.model_copy(update={"inputs": build.inputs[:-1]})

    def run():
        module.rebuild(root, ledger, output, capture, "a" * 40, build_inputs=build, metadata_sources=sources)

    if defect is not None:
        with pytest.raises(FatalContractError, match="validated identity|adopted archive members"):
            run()
        final_metadata.assert_not_called()
        assert not (output / "provider.json").exists()
        return

    run()
    final_metadata.assert_called_once()
    call = final_metadata.call_args
    assert call.kwargs["build_inputs"] is build
    metadata = call.kwargs["station_metadata"]
    elevation = metadata.filter(pl.col("source_field") == "altitude_site")
    expected = pl.DataFrame({"station_id": ["H001"], "source_value": ["0.0"], "source_datum": ["0"]})
    assert_frame_equal(elevation.select(expected.columns), expected)
    assert (
        call.args[0].native_table
        == generator.NativeInventoryCapture.model_validate_json(capture.read_bytes()).native_table
    )
    assert (output / "native.parquet").is_file()
    assert pl.read_parquet(output / "stations.parquet")["station_id"].to_list() == ["H001"]
    assert (output / "provider.json").is_file()


def cli_arguments(tmp_path):
    return [
        "--evidence-root",
        str(tmp_path / "inputs"),
        "--availability-ledger",
        str(tmp_path / "ledger.json.xz"),
        "--build-inputs",
        str(tmp_path / "build.json"),
        "--out",
        str(tmp_path / "output"),
        "--capture-output",
        str(tmp_path / "capture.json"),
        "--revision",
        "a" * 40,
    ]


def test_cli_requires_selected_receipt_before_reads(tmp_path, capsys):
    with pytest.raises(SystemExit, match="2"):
        module.main(cli_arguments(tmp_path))
    assert "--input-receipt" in capsys.readouterr().err
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("reader_fails", [False, True])
def test_cli_composes_pinned_metadata_before_rebuild(source_inputs, tmp_path, monkeypatch, reader_fails):
    root, arguments = source_inputs
    sources = read_station_metadata_sources(root, **arguments)
    build = _build()
    (tmp_path / "build.json").write_text(build.model_dump_json())
    receipt_path = tmp_path / "selected.json"
    receipt_path.write_text(arguments["input_receipt"].model_dump_json())
    reader = Mock(return_value=sources)
    if reader_fails:
        reader.side_effect = FatalContractError("Selected metadata is missing")
    rebuild = Mock()
    monkeypatch.setattr(module, "read_station_metadata_sources", reader)
    monkeypatch.setattr(module, "rebuild", rebuild)
    argv = cli_arguments(tmp_path) + ["--input-receipt", str(receipt_path)]
    if reader_fails:
        with pytest.raises(FatalContractError, match="Selected metadata is missing"):
            module.main(argv)
        rebuild.assert_not_called()
    else:
        assert module.main(argv) == 0
        rebuild.assert_called_once_with(
            tmp_path / "inputs",
            tmp_path / "ledger.json.xz",
            tmp_path / "output",
            tmp_path / "capture.json",
            "a" * 40,
            build_inputs=build,
            metadata_sources=sources,
        )
    reader.assert_called_once_with(
        tmp_path / "inputs",
        input_receipt=arguments["input_receipt"],
        site_root=origins.SITE_METADATA_ROOT,
        manifest_sha256=origins.SITE_METADATA_MANIFEST_SHA256,
        lineage_sha256=origins.SITE_METADATA_LINEAGE_SHA256,
    )


def test_selected_metadata_body_must_exist(source_inputs):
    root, arguments = source_inputs
    (root / "sites/batch-001/body").unlink()
    with pytest.raises(FatalContractError):
        read_station_metadata_sources(root, **arguments)
