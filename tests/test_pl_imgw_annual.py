"""The official annual archive passes the same compiler as monthly source files."""

import hashlib
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

from rivretrieve._internal.providers.pl_imgw.bulk import ImgwCompileRequest, compile_imgw
from rivretrieve._internal.store import StoreRoot

DATA = Path(__file__).parent / "test_data" / "pl_imgw_annual"
URL = "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/2024/codz_2024.zip"


def test_exact_annual_archive_compiles_without_losing_native_cells(tmp_path: Path, monkeypatch) -> None:
    source = DATA / "codz_2024.zip"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        "c40ebcda7a6b7ee30c936531fd0f391ba34d5bdf1545b535c3347c39319651fa"
    )
    artifact = tmp_path / source.name
    shutil.copyfile(source, artifact)
    compiled = compile_imgw(
        ImgwCompileRequest(
            artifact,
            StoreRoot(tmp_path / "store"),
            URL,
            date(2024, 10, 31),
            datetime(2026, 9, 20, tzinfo=UTC),
            "0.1.49",
        )
    )
    assert compiled.manifest.series
    assert not artifact.exists()

    from io import BytesIO

    import polars as pl
    import polars.testing as pl_testing

    import rivretrieve as rr
    from rivretrieve._internal import discovery
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.observations import ReceiptAuthorship
    from rivretrieve._internal.providers.pl_imgw.config import config
    from rivretrieve._internal.providers.pl_imgw.declaration import declaration
    from rivretrieve._internal.registry import ProviderRegistry

    registry = ProviderRegistry()
    registry.register(
        "pl_imgw",
        load_packaged_catalogue_artifact(declaration.catalogue, on_issue="raise"),
        bulk_config=config,
        observation_store=StoreRoot(tmp_path / "store"),
    )
    monkeypatch.setattr(discovery, "_registry", registry)
    monkeypatch.setattr(discovery, "_provider_lookup", registry.get)
    monkeypatch.setattr(discovery, "_ensure_default_providers_registered", lambda: None)

    class NoNetwork:
        def send(self, request):
            raise AssertionError("Compiled retrieval must not contact publisher services")

    monkeypatch.setattr(discovery, "HttpClient", NoNetwork)
    selection = rr.find(provider="pl_imgw", station="152140020", quantity="discharge")
    result = rr.fetch(selection, start="2024-01-01", end="2024-01-01", receipts=True)
    pl_testing.assert_frame_equal(
        result.data.select("value", "source_unit", "unit"),
        pl.DataFrame({"value": [999.0], "source_unit": ["m3/s"], "unit": ["m3/s"]}),
    )
    assert result.data["series_id"].n_unique() == 1
    assert result.data["facts_id"].unique().to_list() == [selection.series[0].facts[0].facts_id]
    (receipt,) = result.receipts.entries
    assert receipt.authorship is ReceiptAuthorship.STORE_EXCERPT
    native = pl.read_parquet(BytesIO(receipt.content))
    assert native["facts_id"].unique().to_list() == [selection.series[0].facts[0].facts_id]
    assert native.filter(pl.col("time") == datetime(2024, 1, 1))["IMGW_DAILY.flow_m3s"].item() == "999.000"
    assert result.provenance.publisher_artifact_urls == (URL,)
    for quantity, expected, unit in (("stage", 1.13, "cm"), ("temperature", None, "degC")):
        selected = rr.find(provider="pl_imgw", station="149180020", quantity=quantity)
        fetched = rr.fetch(selected, start="2023-11-01", end="2023-11-01", receipts=True)
        pl_testing.assert_frame_equal(
            fetched.data.select("value"),
            pl.DataFrame({"value": [expected]}, schema={"value": pl.Float64}),
        )
        assert fetched.data["source_unit"].to_list() == [unit]
        raw = pl.read_parquet(BytesIO(fetched.receipts.entries[0].content))
        assert fetched.data["facts_id"].unique().to_list() == [selected.series[0].facts[0].facts_id]
        assert raw["facts_id"].unique().to_list() == [selected.series[0].facts[0].facts_id]
        if quantity == "temperature":
            assert raw["IMGW_DAILY.temperature_c"].to_list() == [""] * raw.height
            assert raw["value_state"].to_list() == ["published_blank"] * raw.height
        else:
            assert raw.filter(pl.col("time") == datetime(2023, 11, 1))["value"].item() == 113.0


def test_annual_definitions_are_exact_publisher_bytes() -> None:
    import json

    for name in ("CODZ_publiczne_format.txt", "UWAGA.txt", "codz_2024.zip", "yearbook-2025.pdf"):
        metadata = json.loads((DATA / (name + ".metadata.json")).read_text())
        assert hashlib.sha256((DATA / name).read_bytes()).hexdigest() == metadata["sha256"]
        assert metadata["status"] == 200
        assert metadata["url"].startswith("https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/")
    definitions = (DATA / "CODZ_publiczne_format.txt").read_bytes().decode("cp1250")
    assert "Przepływ 99999.999 albo NULL" in definitions
    assert "Od roku 2024 braki w danych są oznaczane zawsze jako NULL." in definitions


def test_yearbook_method_scope_is_not_an_archive_wide_mean_definition() -> None:
    from pypdf import PdfReader

    pages = PdfReader(DATA / "yearbook-2025.pdf").pages
    level = " ".join((pages[6].extract_text() or "").split())
    flow = " ".join((pages[7].extract_text() or "").split())
    temperature = " ".join((pages[8].extract_text() or "").split())
    assert "średnie chronologiczne" in level
    assert "godziny 6 UTC" in level
    assert "średnie chronologiczne" in flow
    assert "godziny 6 UTC" in flow
    assert "pomiarów wykonywanych o godzinie 6 UTC" in temperature
