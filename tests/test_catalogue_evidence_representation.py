"""National evidence representation budgets on real discovery and build paths."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

import rivretrieve as rr

ROOT = Path(__file__).parents[1]
CATALOGUE = ROOT / "src/rivretrieve/_internal/providers/fr_hubeau/catalogue"


def test_public_discovery_does_not_materialize_national_v2_provenance() -> None:
    national_models: list[int] = []

    def observe(frame, event, arg):
        if event == "call" and frame.f_code.co_name == "_references_are_closed":
            value = frame.f_locals["self"]
            if type(value).__name__ == "AcquisitionProvenance" and len(value.fact_bindings) > 10_000:
                national_models.append(len(value.fact_bindings))

    previous = sys.getprofile()
    sys.setprofile(observe)
    try:
        selection = rr.find(provider="usgs_nwis", station="01010000")
    finally:
        sys.setprofile(previous)
    assert len(selection.series) == 3
    assert national_models == [], f"ordinary discovery materialized national v2 graphs: {national_models}"


def test_france_public_evidence_and_descriptor_fit_normalized_budget() -> None:
    files = [CATALOGUE / "provenance.json", CATALOGUE / "croissant.json", *CATALOGUE.glob("provenance_*.parquet")]
    sizes = {path.name: path.stat().st_size for path in files}
    assert sum(sizes.values()) <= 8_000_000, sizes
    assert sizes["croissant.json"] <= 262_144, sizes


def test_real_france_generator_does_not_render_national_acquisition_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from rivretrieve._internal.providers.fr_hubeau.generate_catalogue import main

    def denied(*args, **kwargs):
        raise AssertionError("offline catalogue build attempted network access")

    monkeypatch.setattr(socket.socket, "connect", denied)
    acquisition_nodes = 0

    def observe(frame, event, arg):
        nonlocal acquisition_nodes
        if (
            event == "call"
            and frame.f_code.co_name == "_acquired_material"
            and frame.f_code.co_filename.endswith("catalogues/descriptor.py")
        ):
            acquisition_nodes += 1

    previous = sys.getprofile()
    sys.setprofile(observe)
    try:
        result = main([
            "--native", str(CATALOGUE / "native.parquet"),
            "--availability-ledger", str(ROOT / "research/station-coverage/fr_hubeau/inventory/governing_evidence.json.xz"),
            "--out", str(tmp_path / "catalogue"),
        ])
    finally:
        sys.setprofile(previous)
    assert result == 0
    assert acquisition_nodes == 0, f"root descriptor rendered {acquisition_nodes} individual acquisition nodes"
