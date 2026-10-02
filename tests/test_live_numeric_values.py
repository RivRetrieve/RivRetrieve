"""Live publisher numeric cells must fit finite native Float64 observations."""

import json
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import datetime
from functools import lru_cache
from importlib import import_module
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import openpyxl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.recordings import read_recording

BAD = ("huge_integer", "large_exponent", "nan", "infinity", "negative_infinity")
TOKENS = {
    "huge_integer": "9" * 401,
    "large_exponent": "1e400",
    "nan": "NaN",
    "infinity": "Infinity",
    "negative_infinity": "-Infinity",
    "zero": "0",
    "finite": "1.25",
    "null": "null",
}


@lru_cache
def _source(retained_evidence_root: Path, provider):
    config = import_module(f"rivretrieve._internal.providers.{provider}.config").config()
    parse = import_module(f"rivretrieve._internal.providers.{provider}.parse").parse
    cases = {
        "fr_hubeau": ("fr_hubeau_1011000101_QmnJ_padded.recording.json", "1011000101", "discharge_daily_mean"),
        "no_nve": (
            "no_nve_109.42.0_1001_1440_version-2_2024-01-01_2024-01-03.recording.json",
            "109.42.0",
            "discharge_daily_mean",
        ),
        "ch_foen": ("ch_foen_2251_rest_2026-09-19.recording.json", "2251", "discharge_reported"),
        "lt_lhmt": ("lt_lhmt_anyksciu-vms_2023-06.recording.json", "anyksciu-vms", "stage_daily_mean"),
        "th_thaiwater": ("th_thaiwater_1373273_2026-08-01_2026-08-02.recording.json", "1373273", "stage_reported"),
        "cz_chmi": ("cz_chmi_0-203-1-000400_DQ_2023.recording.json", "0-203-1-000400", "stage_daily_mean"),
        "ba_fhmzbih": ("ba_fhmzbih_4024_H_1Y.recording.json", "4024", "stage_reported"),
        "jp_mlit": ("jp_mlit_stage_hourly_2023_dat.recording.json", "301011281104010", "stage_hourly"),
    }
    filename, station, product = cases[provider]
    recording = read_recording(retained_evidence_root / "tests/test_data" / filename)
    source = Payload(
        config.products[ProductId(product)].coordinates,
        ((station, ProductId(product)),),
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2000, 1, 1)), WindowEndpoint.from_datetime(datetime(2030, 1, 1))
        ),
        recording.content,
        SourceCallOrigin(
            recording.request.url,
            recording.request.parameters or {},
            recording.status_code,
            recording.retrieved_at,
            recording.content_type,
            UnknownOriginFact(),
            UnknownOriginFact(),
        ),
        recording.prerequisite_calls,
    )
    if provider in ("lt_lhmt", "th_thaiwater", "cz_chmi", "ch_foen"):
        sibling = {
            "lt_lhmt": "discharge_daily_mean",
            "th_thaiwater": "discharge_reported",
            "cz_chmi": "discharge_daily_mean",
            "ch_foen": "stage_reported",
        }[provider]
        source = replace(source, station_products=(*source.station_products, (station, ProductId(sibling))))
    if provider == "cz_chmi":
        from rivretrieve._internal.providers.cz_chmi.fetch import CzChmiRequestCoordinates

        source = replace(source, source_coordinates=SourceCoordinates(CzChmiRequestCoordinates("DQ", ("HD", "QD"))))
    if provider == "jp_mlit":
        from rivretrieve._internal.providers.jp_mlit.fetch import JpMlitPayloadCoordinates

        source = replace(source, source_coordinates=SourceCoordinates(JpMlitPayloadCoordinates(2, "dat")))
    if provider == "no_nve":
        document = json.loads(source.content)
        sibling = read_recording(
            retained_evidence_root
            / "tests/test_data"
            / "no_nve_109.42.0_1001_1440_version-1_2024-01-01_2024-01-03.recording.json"
        )
        document["data"].extend(json.loads(sibling.content)["data"])
        source = replace(source, content=json.dumps(document).encode())
    baseline = parse(source, config)
    target = next(
        s
        for s in baseline.series
        if s.product_id == product
        and (provider != "no_nve" or s.identity.published_id == "2")
        and (provider != "ch_foen" or s.identity.published_id == "flow_ls")
    )
    return config, parse, source, baseline, target.series_id


def _mutated(provider, source, mutation):
    if provider == "ba_fhmzbih":
        if mutation == "huge_integer":
            # Preserve the real workbook structure and publish an integer numeric cell,
            # rather than forcing the XLSX writer to coerce a Python integer to float.
            output = BytesIO()
            with ZipFile(BytesIO(source.content)) as original, ZipFile(output, "w") as changed:
                for item in original.infolist():
                    content = original.read(item.filename)
                    if item.filename == "xl/worksheets/sheet1.xml":
                        root = ET.fromstring(content)
                        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                        cell = root.find(".//s:c[@r='B9']", ns)
                        assert cell is not None
                        cell.set("t", "n")
                        value = cell.find("s:v", ns)
                        assert value is not None
                        value.text = TOKENS[mutation]
                        content = ET.tostring(root)
                    changed.writestr(item, content)
            return output.getvalue()
        workbook = openpyxl.load_workbook(BytesIO(source.content))
        sheet = workbook.worksheets[0]
        sheet["B9"] = None if mutation == "null" else (True if mutation == "boolean" else TOKENS[mutation])
        output = BytesIO()
        workbook.save(output)
        workbook.close()
        return output.getvalue()
    if provider == "jp_mlit":
        replacement = TOKENS[mutation].encode()
        assert b"321.52, " in source.content
        return source.content.replace(b"321.52, ", replacement + b", ", 1)
    document = json.loads(source.content)
    marker = "__NUMERIC_TEST_CELL__"
    if provider == "fr_hubeau":
        document["data"][0]["resultat_obs_elab"] = marker
    elif provider == "no_nve":
        document["data"][0]["observations"][0]["value"] = marker
    elif provider == "ch_foen":
        document["payload"]["2251|flow_ls"][0] = marker
    elif provider == "lt_lhmt":
        document["observations"][0]["waterLevel"] = marker
    elif provider == "th_thaiwater":
        document["data"]["graph_data"][0]["value"] = marker
    elif provider == "cz_chmi":
        document["tsList"][0]["tsData"]["data"]["values"][0][1] = marker
    return json.dumps(document).encode().replace(json.dumps(marker).encode(), TOKENS[mutation].encode())


@pytest.mark.parametrize(
    ("provider", "mutation"),
    [
        (provider, mutation)
        for provider in (
            "fr_hubeau",
            "no_nve",
            "ch_foen",
            "lt_lhmt",
            "th_thaiwater",
            "cz_chmi",
            "ba_fhmzbih",
            "jp_mlit",
        )
        for mutation in (*BAD, "zero", "finite", "null")
        # DAT missing slots use source flags, tested separately, not a JSON null token.
        if (provider, mutation) != ("jp_mlit", "null")
    ],
)
@pytest.mark.recorded(
    "tests/test_data/ba_fhmzbih_4024_H_1Y.recording.json",
    "tests/test_data/ch_foen_2251_rest_2026-09-19.recording.json",
    "tests/test_data/cz_chmi_0-203-1-000400_DQ_2023.recording.json",
    "tests/test_data/fr_hubeau_1011000101_QmnJ_padded.recording.json",
    "tests/test_data/jp_mlit_stage_hourly_2023_dat.recording.json",
    "tests/test_data/lt_lhmt_anyksciu-vms_2023-06.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-1_2024-01-01_2024-01-03.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-2_2024-01-01_2024-01-03.recording.json",
    "tests/test_data/th_thaiwater_1373273_2026-08-01_2026-08-02.recording.json",
)
def test_actual_live_parser_isolates_unrepresentable_numeric_cells(retained_evidence_root: Path, provider, mutation):
    config, parse, source, baseline, target = _source(retained_evidence_root, provider)
    changed = parse(replace(source, content=_mutated(provider, source, mutation)), config)
    outcome = next(item for item in changed.outcomes if item.series_id == target)
    if mutation in BAD:
        assert outcome.status == "unsupported", (provider, mutation, outcome)
        assert outcome.reason
        assert changed.rows.filter(changed.rows["series_id"] == target).is_empty()
    else:
        assert outcome.status == "success"
        assert changed.rows.height == baseline.rows.height
        changed_value = changed.rows.filter(changed.rows["series_id"] == target)["value"][0]
        assert changed_value == {"zero": 0.0, "finite": 1.25, "null": None}[mutation]
    assert_frame_equal(
        changed.rows.filter(changed.rows["series_id"] != target),
        baseline.rows.filter(baseline.rows["series_id"] != target),
    )


@pytest.mark.recorded("tests/test_data/ba_fhmzbih_4024_H_1Y.recording.json")
def test_workbook_boolean_is_not_a_numeric_observation(retained_evidence_root: Path):
    config, parse, source, _, target = _source(retained_evidence_root, "ba_fhmzbih")
    changed = parse(replace(source, content=_mutated("ba_fhmzbih", source, "boolean")), config)
    assert next(item for item in changed.outcomes if item.series_id == target).status == "unsupported"


@pytest.mark.parametrize("mutation", [*BAD, "zero", "finite", "null"])
@pytest.mark.recorded("tests/recordings/br_ana/HidroSerieCotas_15400000_2020-01-01_2020-01-31.recording.json")
def test_ana_decimal_string_guard_preserves_consistency_sibling(retained_evidence_root: Path, mutation):
    from rivretrieve._internal.providers.br_ana.config import config
    from rivretrieve._internal.providers.br_ana.parse import parse
    from tests.test_representative_source_series import payload

    source = payload(
        retained_evidence_root,
        "tests/recordings/br_ana/HidroSerieCotas_15400000_2020-01-01_2020-01-31.recording.json",
        "15400000",
        "stage_daily_mean_bruto",
        config(),
        "2020-01-01",
        "2020-01-31",
    )
    baseline = parse(source, config())
    document = json.loads(source.content)
    for row in document["items"]:
        if row["Mediadiaria"] == "1" and row["nivelconsistencia"] == "1":
            row["Cota_01"] = None if mutation == "null" else TOKENS[mutation]
    changed = parse(replace(source, content=json.dumps(document).encode()), config())
    target = next(series.series_id for series in changed.series if series.variant == "bruto")
    assert next(outcome for outcome in changed.outcomes if outcome.series_id == target).status == (
        "unsupported" if mutation in BAD else "success"
    )
    assert_frame_equal(
        changed.rows.filter(changed.rows["series_id"] != target),
        baseline.rows.filter(baseline.rows["series_id"] != target),
    )


@pytest.mark.recorded("tests/test_data/jp_mlit_stage_hourly_2023_dat.recording.json")
def test_japan_published_missing_flag_remains_absent_not_invalid_numeric(retained_evidence_root: Path):
    config, parse, source, baseline, _ = _source(retained_evidence_root, "jp_mlit")
    content = source.content.replace(b"321.52, ", b"321.52,$", 1)
    result = parse(replace(source, content=content), config)
    assert result.rows.height == baseline.rows.height - 1
    assert result.outcomes[0].status == "success"
    assert any(issue.code == "source_missing" for issue in result.issues)
