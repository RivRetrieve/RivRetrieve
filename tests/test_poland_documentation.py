"""Offline checks for the Poland documentation; not live acquisition evidence.

The retrieval snippets are replayed against a store compiled from the committed
publisher archive for hydrological year 2024, not from a fresh national download.
"""

import contextlib
import io
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.pl_imgw.bulk import ImgwCompileRequest, compile_imgw
from rivretrieve._internal.store import StoreRoot

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/providers/pl_imgw.md"
ARCHIVE = ROOT / "tests/test_data/pl_imgw_annual/codz_2024.zip"
URL = "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/2024/codz_2024.zip"
BLOCK = re.compile(r"```(python|text)\n(.*?)```", re.DOTALL)


def _snippets():
    blocks = BLOCK.findall(PAGE.read_text())
    return [
        (body, blocks[index + 1][1] if index + 1 < len(blocks) and blocks[index + 1][0] == "text" else None)
        for index, (kind, body) in enumerate(blocks)
        if kind == "python"
    ]


def test_poland_documentation_snippets_are_valid_current_python():
    snippets = _snippets()
    assert len(snippets) == 2
    for body, _ in snippets:
        compile(body, str(PAGE), "exec")
    text = PAGE.read_text()
    assert 'product="' not in text
    assert "_daily_mean" not in text
    assert 'rr.download("pl_imgw")' in snippets[0][0]


def test_poland_documentation_selection_matches_packaged_catalogue():
    assert len(rr.find(provider="pl_imgw").locations) == 1301
    selection = rr.find(provider="pl_imgw", station="152140020", quantity="discharge")
    assert rr.series(selection).select("product_id", "quantity", "frequency", "statistic", "unit").rows() == [
        ("discharge_daily", "discharge", "daily", None, "m3/s")
    ]
    assert rr.series(rr.find(provider="pl_imgw", station="152140020", statistic="mean")).height == 0
    assert "providers/pl_imgw.md" in (ROOT / "docs/README.md").read_text()


def test_poland_retrieval_snippets_replay_committed_archive(tmp_path, monkeypatch):
    artifact = tmp_path / ARCHIVE.name
    shutil.copyfile(ARCHIVE, artifact)
    (tmp_path / "pl_imgw").mkdir()
    compile_imgw(
        ImgwCompileRequest(
            artifact,
            StoreRoot(tmp_path / "pl_imgw" / "store"),
            URL,
            date(2024, 10, 31),
            datetime(2026, 9, 24, tzinfo=UTC),
            rr.__version__,
        )
    )
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))

    from rivretrieve._internal import discovery

    class NoNetwork:
        def send(self, request):
            raise AssertionError("Compiled retrieval must not contact IMGW-PIB")

    monkeypatch.setattr(discovery, "HttpClient", NoNetwork)
    scope = {"rr": rr}
    replayed = 0
    for body, expected in _snippets():
        if "rr.download(" in body or "cache_status" in body:
            continue
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            exec(compile(body, str(PAGE), "exec"), scope)
        assert captured.getvalue() == expected
        replayed += 1
    assert replayed == 1
    assert scope["result"].provenance.publisher_artifact_urls == (URL,)
    assert scope["result"].data["time_zone"].unique().to_list() == ["unknown"]
    with pytest.raises(FatalContractError, match="time_zone is 'unknown'"):
        rr.to_utc(scope["result"])
