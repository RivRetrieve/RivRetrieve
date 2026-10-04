"""Synthetic FOEN source structure and exposure contracts, without retained bodies."""

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.catalogues.station_metadata import MetadataField
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ch_foen.station_metadata import (
    parse_station_directory,
    parse_station_page,
    project_station_metadata,
)


def directory_row(station="001", name=" Gauge &amp; name ", water=""):
    return (
        f'<tr class="station-row discharge_{station}" data-key="{station}" data-name="{name}" '
        f'data-hydro-body="{water}"><td><a href="/en/seen-und-fluesse/stations/{station}">Display title</a></td></tr>'
    )


def station_page(
    station="001", fields="<dt>Station altitude</dt><dd> 1,234.0 m a.s.l.</dd><dt>Catchment size</dt><dd>0 km2</dd>"
):
    return (
        f"<h1>General site heading</h1><h1><span>Display title</span><small>{station}</small></h1>"
        f"<div><h2>Station information</h2></div><div><dl>{fields}"
        "<dt>Mean catchment altitude</dt><dd>Excluded</dd></dl></div>"
        "<h3>Data availability</h3><dl><dt>Station altitude</dt><dd>Unrelated</dd></dl>"
    ).encode()


FIELDS = (
    MetadataField("station_name", "data-name", source_scope="station_directory", source_facts=("source.directory",)),
    MetadataField(
        "water_body_name", "data-hydro-body", source_scope="station_directory", source_facts=("source.directory",)
    ),
    MetadataField(
        "drainage_area", "Catchment size", "km2", source_scope="station_page", source_facts=("source.pages",)
    ),
    MetadataField(
        "elevation",
        "Station altitude",
        "m",
        datum="LN02",
        datum_support=("source.reference",),
        source_scope="station_page",
        source_facts=("source.pages",),
    ),
)


def test_directory_decodes_attributes_and_agrees_across_repeated_measurements():
    row = directory_row()
    assert parse_station_directory((row + row.replace("discharge_", "temperature_")).encode()) == {
        "001": {"data-name": " Gauge & name ", "data-hydro-body": ""},
    }
    with pytest.raises(FatalContractError, match="disagree"):
        parse_station_directory((row + directory_row(water="Other water")).encode())


@pytest.mark.parametrize(
    "source",
    [
        directory_row().replace('data-key="001"', 'data-key=""'),
        directory_row().replace('data-name=" Gauge &amp; name "', ""),
        directory_row().replace('data-name=" Gauge &amp; name "', "data-name"),
        directory_row().replace('data-key="001"', 'data-key="001" data-key="002"'),
        directory_row().replace("/stations/001", "/stations/002"),
    ],
)
def test_directory_rejects_missing_or_contradictory_source_identity(source):
    with pytest.raises(FatalContractError):
        parse_station_directory(source.encode())


def test_station_page_keeps_entire_decoded_text_and_excludes_other_sections():
    body = station_page(fields="<dt>Station altitude</dt><dd> 0&nbsp;m a.s.l. </dd><dt>Catchment size</dt><dd></dd>")
    assert parse_station_page(body, "001") == {"Station altitude": " 0\u00a0m a.s.l. ", "Catchment size": ""}
    assert parse_station_page(station_page(fields=""), "001") == {}


@pytest.mark.parametrize(
    "body",
    [
        station_page(station="other"),
        station_page().replace(b"<small>001</small>", b"<small>001</small><small>001</small>"),
        station_page().replace(b"<h2>Station information</h2>", b"<h2>Other information</h2>"),
        station_page(fields="<dt>Station altitude</dt><dd><span>1 m</span></dd>"),
        station_page(fields="<dt>Station altitude</dt><dd>1<br>m</dd>"),
        station_page(fields="<dt>Station altitude</dt><dd>1 m</dd><dt>Station altitude</dt><dd>2 m</dd>"),
        station_page(fields="<dt>Station altitude</dt><span></span><dd>1 m</dd>"),
        b"\xff",
    ],
)
def test_station_page_rejects_invalid_identity_or_ambiguous_scalar_structure(body):
    with pytest.raises(FatalContractError):
        parse_station_page(body, "001")


def test_projection_keeps_unmatched_gauges_and_distinguishes_absent_from_blank_fields():
    stations = pl.DataFrame({"station_id": ["001", "002"], "latitude": [1.0, None], "longitude": [2.0, None]})
    before = stations.clone()
    source = project_station_metadata(
        stations,
        directory_row().encode(),
        {
            "001": station_page(fields="<dt>Station altitude</dt><dd></dd>"),
        },
        FIELDS,
    )
    assert source.filter(pl.col("station_id") == "002")["state"].to_list() == ["no_metadata"] * 4
    exposed = source.filter(pl.col("station_id") == "001")
    assert exposed.filter(pl.col("attribute_role") == "drainage_area")["state"].item() == "no_metadata"
    elevation = exposed.filter(pl.col("attribute_role") == "elevation")
    assert elevation.select("source_value", "source_unit", "source_datum", "state").row(0) == (
        '""',
        "m",
        "LN02",
        "value",
    )
    assert elevation["source_field"].item() == "Station altitude"
    assert elevation["source_scope"].item() == "station_page"
    assert exposed.filter(pl.col("attribute_role") == "water_body_name")["source_value"].item() == '""'
    assert_frame_equal(stations, before)


@pytest.mark.parametrize("pages", [{}, {"001": station_page(), "outside": station_page("outside")}])
def test_projection_does_not_replace_missing_or_extra_adopted_pages_with_absence(pages):
    with pytest.raises(FatalContractError, match="scope"):
        project_station_metadata(pl.DataFrame({"station_id": ["001"]}), directory_row().encode(), pages, FIELDS)


@pytest.fixture
def source_inputs(tmp_path):
    import hashlib
    import json
    from datetime import UTC, datetime

    from rivretrieve._internal.acquisition_provenance import (
        RecordingReference,
        RetainedInputReceipt,
        RetainedInputReference,
    )

    page_url = "https://www.hydrodaten.admin.ch/en/seen-und-fluesse/stations/001"
    directory_url = "https://www.hydrodaten.admin.ch/en/stations-and-data"
    document = {"provider": "ch_foen", "id": "station-001", "station_id": "001", "url": page_url}

    def receipt(body, url, document):
        return json.dumps(
            {
                "document": document,
                "fresh_acquisition": True,
                "stopped": "terminal_response",
                "hops": [
                    {
                        "hop": 0,
                        "requested_url": url,
                        "executed_url": url,
                        "status": 200,
                        "headers": {"Content-Type": "text/html; charset=utf-8"},
                        "body_received_at": "2026-01-01T00:00:00Z",
                        "body_file": "hop-0.body",
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "byte_size": len(body),
                    }
                ],
            }
        ).encode()

    directory = directory_row().encode()
    page = station_page()
    manifest = json.dumps([document]).encode()
    manifest_sha = hashlib.sha256(manifest).hexdigest()
    bodies = {
        "directory/body": directory,
        "directory/receipt.json": receipt(directory, directory_url, {}),
        "pages/001/body": page,
        "pages/001/receipt.json": receipt(page, page_url, document),
        "pages/documents.json": manifest,
        "pages/acquisition-run.json": json.dumps({"manifest_sha256": manifest_sha}).encode(),
    }
    references = []
    for path, body in bodies.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        references.append(
            RetainedInputReference(
                consumer_path=path,
                archive_repository="https://github.com/RivRetrieve/verification-evidence",
                archive_revision="a" * 40,
                collection_id="synthetic-foen",
                manifest_sha256="b" * 64,
                artifact_id=path.replace("/", "-"),
                sha256=hashlib.sha256(body).hexdigest(),
                byte_size=len(body),
                role="publisher_original",
            )
        )
    selected = RetainedInputReceipt(
        schema_version=3,
        archive_code_revision="c" * 40,
        code_revision="d" * 40,
        declaration_revision="d" * 40,
        inputs=tuple(references),
    )
    directory_reference = RecordingReference(
        recording_id="directory",
        repository_path="directory/body",
        source_url=directory_url,
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        media_type="text/html; charset=utf-8",
        sha256=hashlib.sha256(directory).hexdigest(),
    )
    return tmp_path, {
        "directory_reference": directory_reference,
        "input_receipt": selected,
        "page_root": "pages",
        "manifest_sha256": manifest_sha,
    }


def test_reader_keeps_original_receipt_filename_and_binds_independent_members(source_inputs):
    from rivretrieve._internal.acquisition_provenance import ArchiveMemberReference, RetainedInputUse
    from rivretrieve._internal.providers.ch_foen.station_metadata import (
        read_station_metadata_sources,
        verify_adopted_station_metadata,
    )

    root, arguments = source_inputs
    sources = read_station_metadata_sources(root, **arguments)
    assert sources.station_pages["001"] == station_page()
    assert sources.page_recordings[0].repository_path == "pages/001/body"
    assert not (root / "pages/001/hop-0.body").exists()
    adopted = tuple(
        RetainedInputUse(
            reference=ArchiveMemberReference.model_validate(item.model_dump(exclude={"consumer_path"})),
            usage="original",
            facts=(
                ("source.station.foen_directory_identity_and_names",)
                if item.consumer_path.startswith("directory/")
                else ("source.station.foen_reference_altitude_and_catchment",)
            ),
        )
        for item in arguments["input_receipt"].inputs
    )
    verify_adopted_station_metadata(sources, adopted)
    with pytest.raises(FatalContractError, match="adopted archive members"):
        verify_adopted_station_metadata(sources, adopted[:-1])


@pytest.mark.parametrize("change_receipt", [False, True])
def test_source_mutation_cannot_hide_behind_self_consistent_receipt_or_previous_read(source_inputs, change_receipt):
    import hashlib
    import json

    from rivretrieve._internal.providers.ch_foen.station_metadata import read_station_metadata_sources

    root, arguments = source_inputs
    read_station_metadata_sources(root, **arguments)
    body = station_page(fields="<dt>Station altitude</dt><dd>Changed value</dd>")
    (root / "pages/001/body").write_bytes(body)
    if change_receipt:
        receipt = json.loads((root / "pages/001/receipt.json").read_bytes())
        receipt["hops"][0].update(sha256=hashlib.sha256(body).hexdigest(), byte_size=len(body))
        (root / "pages/001/receipt.json").write_text(json.dumps(receipt))
    with pytest.raises(FatalContractError, match="resolved archive identity"):
        read_station_metadata_sources(root, **arguments)


def test_reader_requires_each_consumed_member_in_selected_inputs(source_inputs):
    from rivretrieve._internal.providers.ch_foen.station_metadata import read_station_metadata_sources

    root, arguments = source_inputs
    arguments["input_receipt"] = arguments["input_receipt"].model_copy(
        update={"inputs": arguments["input_receipt"].inputs[:-1]}
    )
    with pytest.raises(FatalContractError, match="absent from the selected archive inputs"):
        read_station_metadata_sources(root, **arguments)


def test_direct_metadata_sources_remain_separate_from_intermediary_provenance(source_inputs):
    from rivretrieve._internal.providers.ch_foen.origins import (
        STATION_PAGE_ROOT,
        build_acquisition_provenance,
        station_metadata_supporting_inputs,
        with_station_metadata_sources,
    )
    from rivretrieve._internal.providers.ch_foen.station_metadata import read_station_metadata_sources

    root, arguments = source_inputs
    sources = read_station_metadata_sources(root, **arguments)
    original = build_acquisition_provenance()
    page_reference = sources.page_recordings[0].model_copy(update={"repository_path": f"{STATION_PAGE_ROOT}/001/body"})
    updated = with_station_metadata_sources(original, (page_reference,))
    assert updated.native_table == original.native_table
    assert updated.source_records[:-1] == original.source_records
    direct = updated.source_records[-1]
    assert direct.source_id == "ch_foen.foen_station_reference"
    assert direct.acquisitions[-1].recording_ids == ("station-001",)
    assert direct.acquisitions[-1].retrieved_at_start == sources.page_recordings[0].retrieved_at
    assert (
        f"{STATION_PAGE_ROOT}/001/receipt.json"
        in station_metadata_supporting_inputs(updated)["source.station.foen_reference_altitude_and_catchment"]
    )


def test_catalogue_composition_adds_direct_metadata_without_changing_native_geometry(source_inputs, monkeypatch):
    from datetime import UTC, datetime

    from rivretrieve._internal.catalogues.native import RetrievedAt, stamp_native_table
    from rivretrieve._internal.providers.ch_foen import origins
    from rivretrieve._internal.providers.ch_foen.generate_catalogue import NATIVE_SOURCE_SCHEMA, build_catalogue
    from rivretrieve._internal.providers.ch_foen.station_metadata import read_station_metadata_sources

    root, arguments = source_inputs
    sources = read_station_metadata_sources(root, **arguments)
    monkeypatch.setattr(origins, "STATION_DIRECTORY_REFERENCE", sources.directory_reference)
    rows = [
        {
            "payload_key": str(index),
            "id": index,
            "name": station,
            "details.id": station,
            "details.name": "Intermediary name",
            "details.water-body-name": "Intermediary water",
            "details.water-body-type": "river",
            "details.chx": 1,
            "details.chy": 2,
            "details.lat": 46.0,
            "details.lon": 8.0,
            "source": "Synthetic source",
            "apiurl": "https://example.org/locations",
            "opendata": "Synthetic terms",
            "license": "Synthetic licence",
        }
        for index, station in enumerate(("001", "002"), start=1)
    ]
    native = stamp_native_table(
        pl.DataFrame(rows, schema=NATIVE_SOURCE_SCHEMA), RetrievedAt(datetime(2026, 1, 1, tzinfo=UTC))
    )
    baseline = build_catalogue(native, origins.STATION_CATALOGUE_ORIGINS)
    actual = build_catalogue(native, origins.STATION_CATALOGUE_ORIGINS, metadata_sources=sources)
    assert_frame_equal(actual.stations, baseline.stations)
    assert_frame_equal(actual.products, baseline.products)
    assert_frame_equal(actual.station_products, baseline.station_products)
    assert actual.acquisition_provenance.native_table == baseline.acquisition_provenance.native_table
    assert actual.station_metadata is not None
    assert (
        actual.station_metadata.filter((pl.col("station_id") == "001") & (pl.col("attribute_role") == "station_name"))[
            "source_value"
        ].item()
        == '" Gauge & name "'
    )
    assert actual.station_metadata.filter(pl.col("station_id") == "002")["state"].to_list() == ["no_metadata"] * 4


@pytest.mark.parametrize("following", ["", "<dt>Catchment size</dt><dd>0 km2</dd>"])
def test_adopted_label_without_its_value_is_not_metadata_absence(following):
    body = (
        f"<h1><small>001</small></h1><h2>Station information</h2><dl><dt>Station altitude</dt>{following}</dl>"
    ).encode()
    with pytest.raises(FatalContractError, match="immediate value"):
        parse_station_page(body, "001")
