"""Reused installed distributions keep verifier state and import paths isolated."""

import pytest

from tests._distribution import InstalledDistribution


@pytest.mark.parametrize("installed_distribution", ["wheel", "sdist-wheel"], indirect=True)
def test_distribution_verifiers_have_fresh_state(installed_distribution: InstalledDistribution, monkeypatch):
    monkeypatch.setenv("DISTRIBUTION_TEST_SENTINEL", "must-not-be-inherited")
    probe = """
import os
import socket
import sys
from pathlib import Path


def refuse_network(*args, **kwargs):
    raise AssertionError("Installed import must remain offline")


socket.socket.connect = refuse_network
socket.socket.connect_ex = refuse_network
socket.create_connection = refuse_network
socket.getaddrinfo = refuse_network

import rivretrieve

assert Path(rivretrieve.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
assert "site-packages" in Path(rivretrieve.__file__).parts
assert sys.dont_write_bytecode
assert "PYTHONPATH" not in os.environ
assert "DISTRIBUTION_TEST_SENTINEL" not in os.environ
assert Path.home() == Path.cwd()
assert not Path("verifier-state").exists()
Path("verifier-state").write_text("must-not-leak")
"""
    installed_distribution.verify(probe)
    installed_distribution.verify(probe)
