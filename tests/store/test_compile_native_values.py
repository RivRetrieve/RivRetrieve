"""Native values remain unchanged in a compiled observation store."""

from pathlib import Path

from tests.store.test_compile_value_states import _compile


def test_native_value_is_unchanged_on_disk(tmp_path: Path) -> None:
    result = _compile(tmp_path)
    published = result.selected_rows.filter(result.selected_rows["value_state"] == "published_value")
    assert published["value"].item() == 12.4
    assert published["native_value"].item() == 12.4
