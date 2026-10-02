"""HydroPortail Q unit-code evidence and exact real public retrieval."""

import hashlib
import json
from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.observations import ReceiptAuthorship
from rivretrieve._internal.recordings import ReplayTransport, read_recording

DATA = Path("tests/test_data")
LABEL_ASSET = "fr_hydroportail_unit_definition_5621.4ab47ec9"
UI_ASSET = "fr_hydroportail_unit_definition_4210.e6896d9b"
LABEL_HASH = "ab41e52a4af9b0cec642de98c68cd445f4a9b269f705da45dc43bd5664494823"
UI_HASH = "72571d0bd095d5cf616a1378e799aa5e8f6818330fcca2f5691891463a92cda6"


@pytest.mark.recorded(
    "tests/test_data/fr_hydroportail_unit_definition_4210.e6896d9b.identity.json",
    "tests/test_data/fr_hydroportail_unit_definition_4210.e6896d9b.js",
    "tests/test_data/fr_hydroportail_unit_definition_5621.4ab47ec9.identity.json",
    "tests/test_data/fr_hydroportail_unit_definition_5621.4ab47ec9.js",
)
def test_publisher_q_unit_code_definition_is_exact_and_context_qualified(retained_evidence_root):
    label = (retained_evidence_root / DATA / f"{LABEL_ASSET}.js").read_bytes()
    ui = (retained_evidence_root / DATA / f"{UI_ASSET}.js").read_bytes()
    assert hashlib.sha256(label).hexdigest() == LABEL_HASH
    assert hashlib.sha256(ui).hexdigest() == UI_HASH
    assert b'a.add("common.unit.q.l","l/s","common","fr")' in label
    assert b'case"Q":case"D":s=[{code:"m3",label:"unit.q.m3"},{code:"l",label:"unit.q.l"}]' in ui
    for name, content in ((LABEL_ASSET, label), (UI_ASSET, ui)):
        manifest = json.loads((retained_evidence_root / DATA / f"{name}.identity.json").read_text())
        assert manifest["byte_size"] == len(content)
        assert manifest["sha256"] == hashlib.sha256(content).hexdigest()
        assert manifest["source_url"].startswith("https://hydro.eaufrance.fr/build/")
        assert manifest["http_status"] == 200
        assert manifest["interpretation_authorship"] == "RivRetrieve analysis, not a publisher sentence"


@pytest.mark.recorded("tests/test_data/fr_hydroportail_station_Q_padded.recording.json")
@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_public_hydroportail_q_preserves_raw_code_and_uses_cited_rate_definition(
    retained_evidence_root, monkeypatch, tmp_path
):
    recording = read_recording(retained_evidence_root / DATA / "fr_hydroportail_station_Q_padded.recording.json")
    assert recording.sha256 == "aa99bc0a91dd45c928ce64d6fd68dff875abcb1e47cf348b11354980413e3f8f"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selection = rr.find(
        provider="fr_hydroportail", station="1232000101", quantity="discharge", statistic="instantaneous"
    )
    result = rr.fetch(
        rr.pick(selection, variant="raw"),
        start="2026-06-01",
        end="2026-06-02",
        cache="bypass",
        receipts=True,
        on_issue="raise",
    )
    rows = result.data.sort("time")
    assert rows.height == 282
    assert rows["source_unit"].unique().to_list() == ["l"]
    assert rows["unit"].unique().to_list() == ["m3/s"]
    assert rows["quantity"].unique().to_list() == ["discharge"]
    assert rows.item(0, "value") == 1.28
    assert rows.item(-1, "value") == 1.23
    assert result.receipts.entries[0].authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD
    assert result.receipts.entries[0].content == recording.content
    assert result.provenance.calls_made[0]["request_parameters"] == dict(recording.request.parameters)
    for series in result.source_series:
        assert series.identity.namespace == "fr_hydroportail/Q"
        for facts in series.facts:
            definition = facts.source_unit_definition
            assert definition is not None
            assert definition.provider_id == series.provider_id == "fr_hydroportail"
            assert definition.namespace == series.identity.namespace
            assert definition.code == facts.source_unit.value == "l"
            assert definition.unit == facts.normalized_unit == "l/s"
            assert LABEL_HASH in " ".join(definition.evidence)
            assert UI_HASH in " ".join(definition.evidence)
            assert set(definition.evidence).issubset(facts.source_unit.evidence)
