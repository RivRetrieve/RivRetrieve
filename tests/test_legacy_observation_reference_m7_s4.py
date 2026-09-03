from pathlib import Path

REFERENCE_ROOT = Path(__file__).parents[1] / "reference" / "legacy_observations"
SOURCE_REF = "51ce7d87da140568ee4145cd41fef0ac9f39fc45"
EXPECTED = {
    "za_dws": {
        "source": {"module.py", "issue_codes.py", "observation_client.py", "parser.py", "retrieval.py", "transform.py"},
        "tests": {"test_za_dws_module.py", "test_za_dws_observations.py"},
        "fixtures": {"za_dws_metadata.json", "za_dws_X3H001_daily_2020-01.txt", "za_dws_X3H001_point_2020-01.txt"},
    }
}


def test_reference_tree_preserves_complete_m7_s4_inventory():
    for provider, expected in EXPECTED.items():
        root = REFERENCE_ROOT / provider
        assert (root / "README.md").is_file()
        assert {p.name for p in (root / "source").iterdir()} == expected["source"]
        assert {p.name for p in (root / "tests").iterdir() if p.name != "test_data"} == expected["tests"]
        assert {p.name for p in (root / "tests" / "test_data").iterdir()} == expected["fixtures"]


def test_reference_readmes_map_every_original_path():
    for provider, expected in EXPECTED.items():
        readme = (REFERENCE_ROOT / provider / "README.md").read_text()
        assert SOURCE_REF in readme
        for name in expected["source"]:
            assert f"source/{name}" in readme
