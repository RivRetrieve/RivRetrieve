from importlib.metadata import version

from rivretrieve import __version__


def test_version() -> None:
    assert __version__ == version("rivretrieve")
