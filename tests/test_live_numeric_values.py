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
    if provider in ("lt_lhmt", "th_thaiwater", "cz_chmi"):
        sibling = {
            "lt_lhmt": "discharge_daily_mean",
            "th_thaiwater": "discharge_reported",
            "cz_chmi": "discharge_daily_mean",
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
        if s.product_id == product and (provider != "no_nve" or s.identity.published_id == "2")
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
        pytest.param(provider, mutation, marks=pytest.mark.recorded(*requirements))
        for provider, requirements in (
            (
                "fr_hubeau",
                ("tests/test_data/fr_hubeau_1011000101_QmnJ_padded.recording.json",),
            ),
            (
                "no_nve",
                (
                    "tests/test_data/no_nve_109.42.0_1001_1440_version-2_2024-01-01_2024-01-03.recording.json",
                    "tests/test_data/no_nve_109.42.0_1001_1440_version-1_2024-01-01_2024-01-03.recording.json",
                ),
            ),
            (
                "lt_lhmt",
                ("tests/test_data/lt_lhmt_anyksciu-vms_2023-06.recording.json",),
            ),
            (
                "th_thaiwater",
                ("tests/test_data/th_thaiwater_1373273_2026-08-01_2026-08-02.recording.json",),
            ),
            (
                "cz_chmi",
                ("tests/test_data/cz_chmi_0-203-1-000400_DQ_2023.recording.json",),
            ),
            (
                "ba_fhmzbih",
                ("tests/test_data/ba_fhmzbih_4024_H_1Y.recording.json",),
            ),
            (
                "jp_mlit",
                ("tests/test_data/jp_mlit_stage_hourly_2023_dat.recording.json",),
            ),
        )
        for mutation in (*BAD, "zero", "finite", "null")
        # DAT missing slots use source flags, tested separately, not a JSON null token.
        if (provider, mutation) != ("jp_mlit", "null")
    ],
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


@pytest.mark.parametrize("wire_format", ["owf_csv", "pegel_bgis_json", "pegel_longterm_json"])
@pytest.mark.parametrize("mutation", [*BAD, "boolean", "zero", "finite", "null"])
@pytest.mark.recorded("maintenance/observations/at_ehyd/retrieval")
def test_at_ehyd_numeric_guards_reject_unrepresentable_cells_across_wire_formats(
    retained_evidence_root: Path, wire_format: str, mutation: str
) -> None:
    from rivretrieve._internal.providers.at_ehyd.config import AtEhydPegelEndpointCoordinates
    from rivretrieve._internal.providers.at_ehyd.config import config as at_config
    from rivretrieve._internal.providers.at_ehyd.parse import parse as at_parse
    from rivretrieve._internal.source_series import OutcomeStatus
    from tests.test_at_ehyd_retrieval_recorded import _capture, _origin_from_receipt

    cfg = at_config()
    win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2000, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2030, 1, 1)),
    )

    if wire_format == "owf_csv":
        body, rcpt = _capture(retained_evidence_root, "access", "owf-209486-file5-q-tagesmittel")
        prod = ProductId("owf_abfl_tagesmittel")
        source = Payload(cfg.products[prod].coordinates, (("209486", prod),), win, body, _origin_from_receipt(rcpt), ())
        baseline = at_parse(source, cfg)
        header, sep, values = body.partition(b"Werte:")
        lines = values.decode("cp1252").splitlines(keepends=True)
        first_idx = next(i for i, line in enumerate(lines) if ";" in line and "Lücke" not in line)
        ts_part = lines[first_idx].split(";", 1)[0]
        token_map = {
            **TOKENS,
            "boolean": "true",
            "finite": "1,25",
            "null": "Lücke",
        }
        lines[first_idx] = f"{ts_part}; {token_map[mutation]}\r\n"
        mutated_bytes = header + sep + "".join(lines).encode("cp1252")
    else:
        capture_name, subsystem, prod, sibling_prod = (
            (
                "pegel-bgis-209486",
                "pegel_bgis",
                ProductId("pegel_bgis_abfluss"),
                ProductId("pegel_bgis_wasserstand"),
            )
            if wire_format == "pegel_bgis_json"
            else (
                "pegel-longterm-209486",
                "pegel_longterm",
                ProductId("pegel_longterm_abfluss"),
                ProductId("pegel_longterm_wasserstand"),
            )
        )
        body, rcpt = _capture(retained_evidence_root, "access", capture_name)
        source = Payload(
            SourceCoordinates(AtEhydPegelEndpointCoordinates(subsystem)),
            (("209486", prod), ("209486", sibling_prod)),
            win,
            body,
            _origin_from_receipt(rcpt),
            (),
        )
        baseline = at_parse(source, cfg)
        doc = json.loads(body)
        field = "data" if wire_format == "pegel_bgis_json" else "current_value"
        marker = "__AT_EHYD_NUMERIC_CELL__"
        doc[field][0] = marker
        raw_token = "true" if mutation == "boolean" else TOKENS[mutation]
        mutated_bytes = json.dumps(doc).encode().replace(json.dumps(marker).encode(), raw_token.encode())

    changed = at_parse(replace(source, content=mutated_bytes), cfg)
    if mutation in (*BAD, "boolean"):
        prod_outcomes = [item for item in changed.outcomes if item.product_id == str(prod)]
        assert [item.status for item in prod_outcomes] == [OutcomeStatus.FAILED], (wire_format, mutation)
        assert prod_outcomes[0].reason
        assert changed.rows.is_empty()
        if wire_format != "owf_csv":
            sibling_outcomes = [item for item in changed.outcomes if item.product_id != str(prod)]
            assert [item.status for item in sibling_outcomes] == [OutcomeStatus.NO_MATCH]
    elif wire_format == "owf_csv" and mutation == "null":
        # In owf CSVs, Lücke is an omitted gap-transition marker rather than a numeric row.
        assert any(item.status is OutcomeStatus.SUCCESS for item in changed.outcomes)
        assert changed.rows.height == baseline.rows.height - 1
        assert_frame_equal(changed.rows, baseline.rows.slice(1))
    else:
        assert any(item.status is OutcomeStatus.SUCCESS for item in changed.outcomes)
        assert changed.rows.height == baseline.rows.height
        assert changed.rows["value"][0] == {"zero": 0.0, "finite": 1.25, "null": None}[mutation]
        assert_frame_equal(changed.rows.slice(1), baseline.rows.slice(1))


@pytest.mark.parametrize("mutation", [*BAD, "boolean", "zero", "finite", "null"])
@pytest.mark.recorded("maintenance/observations/co_ideam/retrieval")
def test_co_ideam_numeric_guards_reject_unrepresentable_cells(retained_evidence_root: Path, mutation: str) -> None:
    from rivretrieve._internal.providers.co_ideam.config import config as co_config
    from rivretrieve._internal.providers.co_ideam.parse import parse as co_parse
    from rivretrieve._internal.source_series import OutcomeStatus
    from tests.test_co_ideam_retrieval_recorded import _capture

    cfg = co_config()
    win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(1970, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2030, 1, 1)),
    )
    body, rcpt = _capture(retained_evidence_root, "access", "s3-0011017010-q-media-d")
    prod = ProductId("q_media_d")
    origin = SourceCallOrigin(
        str(rcpt["url"]),
        {},
        int(str(rcpt["http_status"])),
        datetime.fromisoformat(str(rcpt["retrieved_at"]).replace("Z", "+00:00")),
        str(rcpt.get("media_type") or "text/csv"),
        UnknownOriginFact(),
        UnknownOriginFact(),
    )
    source = Payload(cfg.products[prod].coordinates, (("0011017010", prod),), win, body, origin, ())
    baseline = co_parse(source, cfg)

    lines = body.decode("utf-8").splitlines(keepends=True)
    ts_part, _, approval_part = lines[1].rstrip("\r\n").split(",")
    token_map = {
        **TOKENS,
        "boolean": "true",
        "null": "",
    }
    lines[1] = f"{ts_part},{token_map[mutation]},{approval_part}\n"
    mutated_bytes = "".join(lines).encode("utf-8")

    changed = co_parse(replace(source, content=mutated_bytes), cfg)
    if mutation in (*BAD, "boolean", "null"):
        assert [item.status for item in changed.outcomes] == [OutcomeStatus.FAILED], mutation
        assert changed.outcomes[0].reason
        assert changed.rows.is_empty()
    else:
        assert any(item.status is OutcomeStatus.SUCCESS for item in changed.outcomes)
        assert changed.rows.height == baseline.rows.height
        assert changed.rows["value"][0] == {"zero": 0.0, "finite": 1.25}[mutation]
        assert_frame_equal(changed.rows.slice(1), baseline.rows.slice(1))


@pytest.mark.parametrize("route_kind", ["archive", "recent"])
@pytest.mark.parametrize("mutation", [*BAD, "boolean", "zero", "finite", "null"])
@pytest.mark.recorded("maintenance/observations/ch_foen/official-retrieval")
def test_ch_foen_official_numeric_guards_reject_unrepresentable_cells(
    retained_evidence_root: Path, route_kind: str, mutation: str
) -> None:
    from rivretrieve._internal.engine import SourceQuery
    from rivretrieve._internal.providers.ch_foen.official_config import OfficialRoute
    from rivretrieve._internal.providers.ch_foen.official_config import config as ch_config
    from rivretrieve._internal.providers.ch_foen.official_parse import parse as ch_parse
    from rivretrieve._internal.providers.ch_foen.official_series import product_id, source_series
    from rivretrieve._internal.source_series import OutcomeStatus

    root = retained_evidence_root / "maintenance/observations/ch_foen/official-retrieval"
    capture_name, station, route, parameter = (
        ("daily-min", "2602", "data_1day_min", "Q")
        if route_kind == "archive"
        else ("recent-single-parameter", "2018", "data_live", "Q")
    )
    body = (root / f"{capture_name}.body").read_bytes()
    receipt = json.loads((root / f"{capture_name}.receipt.json").read_text())
    acquired = receipt["acquired_at"] if "request_json" in receipt else receipt["acquired"]
    query = receipt["request_json"]["query"] if "request_json" in receipt else receipt["query"]
    cfg = ch_config()
    prod = ProductId(product_id(route, parameter))
    win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2000, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2030, 1, 1)),
    )
    origin = SourceCallOrigin(
        str(receipt["url"]),
        {},
        int(receipt["status"]),
        datetime.fromisoformat(str(acquired)),
        "application/json",
        UnknownOriginFact(),
        SourceQuery(str(query), ()),
    )
    known = (
        ()
        if route_kind == "archive"
        else (
            source_series(
                station,
                route,
                parameter,
                None,
                units=("m3/s",),
                evidence="catalogue:ch_foen:source.product.native_physics",
                temporal_evidence="catalogue:ch_foen:source.product.temporal_meaning",
                origin="catalogue",
            ),
        )
    )
    source = Payload(
        SourceCoordinates(OfficialRoute(route, parameter)),
        ((station, prod),),
        win,
        body,
        origin,
        (),
        known_series=known,
    )
    baseline = ch_parse(source, cfg)
    assert baseline.rows.height > 0

    doc = json.loads(body)
    marker = "__CH_FOEN_NUMERIC_CELL__"
    doc["data"]["water"]["observations"][route][0]["value"] = marker
    raw_token = "true" if mutation == "boolean" else TOKENS[mutation]
    mutated_bytes = json.dumps(doc).encode().replace(json.dumps(marker).encode(), raw_token.encode())

    changed = ch_parse(replace(source, content=mutated_bytes), cfg)
    if mutation in (*BAD, "boolean"):
        assert [item.status for item in changed.outcomes] == [OutcomeStatus.FAILED], (route_kind, mutation)
        assert changed.outcomes[0].reason
        assert changed.rows.is_empty()
    else:
        assert [item.status for item in changed.outcomes] == [item.status for item in baseline.outcomes]
        assert all(item.status is OutcomeStatus.SUCCESS for item in changed.outcomes)
        assert changed.rows.height == baseline.rows.height
        assert changed.rows["value"][0] == {"zero": 0.0, "finite": 1.25, "null": None}[mutation]
        assert_frame_equal(changed.rows.slice(1), baseline.rows.slice(1))
