"""Native publisher cells retain source-series identity through certified compilation."""

import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.recordings import read_recording
from rivretrieve._internal.store import StoreQuery, StoreReader, StoreRoot


@pytest.mark.parametrize("provider", ["ca_eccc", "pl_imgw"])
def test_certified_native_bulk_retains_concrete_identity_and_physical_units(tmp_path: Path, provider: str) -> None:
    data = Path(__file__).parent / "test_data"
    store = StoreRoot(tmp_path / "store")
    if provider == "ca_eccc":
        from rivretrieve._internal.providers.ca_eccc.bulk import HydatCompileRequest, compile_hydat

        artifact = tmp_path / "derived-input.zip"
        shutil.copyfile(data / "ca_eccc_02GA010_2020_01_derived_input.zip", artifact)
        compiled = compile_hydat(
            HydatCompileRequest(
                artifact,
                store,
                "https://raw.githubusercontent.com/RivRetrieve/RivRetrieve/main/tests/test_data/ca_eccc_02GA010_2020_01_derived_input.zip",
                date(2020, 1, 31),
                datetime(2026, 9, 2, tzinfo=UTC),
                "0.1.49",
            )
        )
        station, start, end, native_unit = "02GA010", datetime(2020, 1, 1), datetime(2020, 1, 3), "m"
    else:
        from rivretrieve._internal.providers.pl_imgw.bulk import ImgwCompileRequest, compile_imgw

        recording = read_recording(data / "pl_imgw_codz_2022_01.recording.json")
        artifact = tmp_path / "codz_2022_01.zip"
        artifact.write_bytes(recording.content)
        compiled = compile_imgw(
            ImgwCompileRequest(
                artifact,
                store,
                "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/2022/codz_2022_01.zip",
                date(2021, 11, 30),
                datetime(2026, 9, 2, tzinfo=UTC),
                "0.1.49",
            )
        )
        station, start, end, native_unit = "154210010", datetime(2021, 11, 1), datetime(2021, 11, 3), "cm"
    assert compiled.manifest.format_version == 5
    assert compiled.manifest.series
    assert not artifact.exists()
    selected = StoreReader().query(
        StoreQuery(
            store,
            ProviderId(provider),
            (station,),
            ("stage_daily_mean" if provider == "ca_eccc" else "stage_daily",),
            start,
            end,
        )
    )
    assert selected.rows.height == 3
    assert selected.rows["series_id"].n_unique() == 1
    assert selected.rows["source_unit"].unique().to_list() == [native_unit]
    identity = selected.rows["series_id"][0]
    definition = next(item for item in compiled.manifest.series if item.series_id == identity)
    assert definition.variant is None
    assert definition.facts[0].source_unit.value == native_unit
    assert selected.physical_rows["series_id"].to_list() == selected.rows["series_id"].to_list()
    if provider == "pl_imgw":
        assert selected.rows["value"].to_list() == [103.0, 102.0, 103.0]
        assert selected.physical_rows["IMGW_DAILY.level_cm"].to_list() == ["103", "102", "103"]
    else:
        assert selected.physical_rows["DLY_LEVELS.NO_DAYS"].unique().to_list() == [31]
