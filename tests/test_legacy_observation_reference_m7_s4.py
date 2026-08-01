from pathlib import Path

REFERENCE_ROOT = Path(__file__).parents[1] / "reference" / "legacy_observations"
SOURCE_REF = "51ce7d87da140568ee4145cd41fef0ac9f39fc45"

EXPECTED = {
    "ba_fhmzbih": {
        "source": {"module.py", "issue_codes.py", "observation_client.py", "parser.py", "retrieval.py", "transform.py"},
        "tests": {"test_ba_fhmzbih_module.py", "test_ba_fhmzbih_observations.py"},
        "fixtures": {
            "ba_fhmzbih_metadata.json",
            "ba_fhmzbih_4510_H_1Y.xlsx",
            "ba_fhmzbih_4510_Q_1Y.xlsx",
            "ba_fhmzbih_4510_Tvode_1Y.xlsx",
        },
    },
    "pl_imgw": {
        "source": {"module.py", "issue_codes.py", "observation_client.py", "parser.py", "retrieval.py", "transform.py"},
        "tests": {"test_pl_imgw_observations.py"},
        "fixtures": {"pl_imgw_metadata.csv", "pl_imgw_151140030_annual_2023.zip", "pl_imgw_cache_fixture.parquet"},
    },
    "za_dws": {
        "source": {"module.py", "issue_codes.py", "observation_client.py", "parser.py", "retrieval.py", "transform.py"},
        "tests": {"test_za_dws_module.py", "test_za_dws_observations.py"},
        "fixtures": {"za_dws_metadata.json", "za_dws_X3H001_daily_2020-01.txt", "za_dws_X3H001_point_2020-01.txt"},
    },
}


def test_reference_tree_preserves_complete_m7_s4_inventory() -> None:
    assert {path.name for path in REFERENCE_ROOT.iterdir() if path.is_dir() and path.name in EXPECTED} == set(EXPECTED)
    for provider, expected in EXPECTED.items():
        root = REFERENCE_ROOT / provider
        assert (root / "README.md").is_file()
        assert {path.name for path in (root / "source").iterdir()} == expected["source"]
        assert {path.name for path in (root / "tests").iterdir() if path.name != "test_data"} == expected["tests"]
        fixtures = root / "tests" / "test_data"
        assert {path.name for path in fixtures.iterdir()} == expected["fixtures"]
        assert all(
            (fixtures / name).is_file() and (fixtures / name).stat().st_size > 0 for name in expected["fixtures"]
        )


def test_reference_readmes_map_every_original_path() -> None:
    for provider, expected in EXPECTED.items():
        readme = (REFERENCE_ROOT / provider / "README.md").read_text()
        assert SOURCE_REF in readme
        for name in expected["source"]:
            assert f"- `src/rivretrieve/_internal/providers/{provider}/{name}` -> `source/{name}`" in readme
        for name in expected["tests"]:
            assert f"- `tests/{name}` -> `tests/{name}`" in readme
        for name in expected["fixtures"]:
            assert f"- `tests/test_data/{name}` -> `tests/test_data/{name}`" in readme


def test_reference_tree_preserves_fetch_and_parse_evidence() -> None:
    ba_root = REFERENCE_ROOT / "ba_fhmzbih" / "source"
    ba_client = (ba_root / "observation_client.py").read_text()
    assert 'METADATA_URL = "https://vodostaji.voda.ba/data/internet/layers/20/index.json"' in ba_client
    assert (
        'WORKBOOK_URL_TEMPLATE = "https://vodostaji.voda.ba/data/internet/stations/{group}/{station_id}/{code}/{file}"'
        in ba_client
    )
    assert "requests.get(request.url, timeout=request.timeout_seconds)" in ba_client
    assert "BaFhmzbihTransportRequest" in ba_client
    assert "BaFhmzbihTransportResponse" in ba_client
    assert "No authentication is required" in ba_client
    assert "def parse_ba_fhmzbih_workbook(" in (ba_root / "parser.py").read_text()
    assert "def retrieve_observations(" in (ba_root / "retrieval.py").read_text()

    pl_root = REFERENCE_ROOT / "pl_imgw" / "source"
    pl_client = (pl_root / "observation_client.py").read_text()
    assert (
        'BASE_URL = "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe"'
        in pl_client
    )
    assert "requests.Session()" in pl_client
    assert "session.get(url, timeout=120)" in pl_client
    for method in (
        "query",
        "ensure_cache",
        "cache_status",
        "refresh_cache",
        "_build_cache",
        "_fetch_year_parts",
        "_fetch_zip",
    ):
        assert f"def {method}(" in pl_client
    pl_parser = (pl_root / "parser.py").read_text()
    assert "def parse_imgw_zip(" in pl_parser
    assert "def parse_imgw_csv_bytes(" in pl_parser
    assert "def retrieve_observations(" in (pl_root / "retrieval.py").read_text()

    za_root = REFERENCE_ROOT / "za_dws" / "source"
    za_client = (za_root / "observation_client.py").read_text()
    assert 'BASE_URL = "https://www.dws.gov.za/Hydrology/Verified/HyData.aspx"' in za_client
    assert 'VARIABLE_CODE = "100.00"' in za_client
    for field in ("Station=", "DataType=", "StartDT=", "EndDT=", "SiteType=RIV"):
        assert field in za_client
    assert 'headers = {"User-Agent": "Mozilla/5.0"}' in za_client
    assert "ZaDwsTransportRequest" in za_client
    assert "ZaDwsTransportResponse" in za_client
    assert "No authentication is required" in za_client
    za_parser = (za_root / "parser.py").read_text()
    assert "def parse_daily_response(" in za_parser
    assert "def parse_point_response(" in za_parser
    assert "def retrieve_observations(" in (za_root / "retrieval.py").read_text()


def test_pl_imgw_reference_client_is_complete_while_runtime_is_narrow() -> None:
    runtime = (
        Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/pl_imgw/observation_client.py"
    ).read_text()
    reference = (REFERENCE_ROOT / "pl_imgw" / "source" / "observation_client.py").read_text()
    assert "def query(" not in runtime
    assert "def query(" in reference
    for method in ("ensure_cache", "cache_status", "refresh_cache", "_build_cache", "_fetch_year_parts", "_fetch_zip"):
        assert f"def {method}(" in runtime
        assert f"def {method}(" in reference
