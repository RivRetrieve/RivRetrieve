from __future__ import annotations

import zipfile
from pathlib import Path

from rivretrieve._internal.providers.pl_imgw.bulk import decode_imgw


def test_imgw_missing_value_sentinels_compile_as_published_null(tmp_path: Path) -> None:
    """IMGW's documented missing-value codes are not physical measurements."""
    artifact = tmp_path / "codz_2023.zip"
    csv_bytes = ("151140030;Przewożniki;Skroda;2023;03;01;9999;99999.999;99.9;1\r\n").encode("cp1250")
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("codz_2023.csv", csv_bytes)

    materialization = decode_imgw(artifact)
    rows = {row["product"]: row for row in materialization.rows.to_dicts()}

    assert set(rows) == {
        "stage_daily_mean",
        "discharge_daily_mean",
        "water_temperature_daily_mean",
    }
    for row in rows.values():
        assert row["value"] is None
        assert row["value_state"] == "published_null"

    # The native source cells remain available verbatim for traceability.
    assert rows["stage_daily_mean"]["IMGW_DAILY.level_cm"] == "9999"
    assert rows["discharge_daily_mean"]["IMGW_DAILY.flow_m3s"] == "99999.999"
    assert rows["water_temperature_daily_mean"]["IMGW_DAILY.temperature_c"] == "99.9"
