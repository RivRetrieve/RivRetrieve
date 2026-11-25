"""`declaration.py`'s shape (#1020): a valid `LiveStages` declaration, not yet built-in.

`de_pegelonline` is deliberately not yet added to `provider_manifest.py`'s
`BUILTIN_PROVIDER_IDS` or `catalogues/artifact.py`'s
`ACQUISITION_PROVENANCE_ENROLLED_PROVIDERS` (see `generate_catalogue.py`'s
module docstring and the PR description): its packaged catalogue needs a
genuine `verification-evidence` archive registration first, which `register_manifest`
would otherwise load for every other built-in provider before any of them
register (its own ordering safety rule). This module only proves the
declaration itself is well-formed and passes the shared manifest validation
`load_manifest` applies to every declared provider.
"""

from __future__ import annotations

from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.de_pegelonline.declaration import declaration
from rivretrieve._internal.providers.registration import LiveStages, load_manifest


def test_declaration_is_a_live_stages_provider_with_no_required_credentials():
    assert isinstance(declaration.observations, LiveStages)
    assert declaration.required_credentials == ()
    assert declaration.optional_credentials == ()
    assert declaration.catalogue.name == "catalogue"


def test_declaration_passes_shared_manifest_validation():
    (declared,) = load_manifest(("de_pegelonline",), declaration_loader=lambda _provider_id: declaration)

    assert declared.provider_id == "de_pegelonline"


def test_declaration_stages_cover_every_product():
    stages = declaration.observations.stages

    assert stages.observation_source == "live"
    assert set(stages.config.products) == {ProductId(p) for p in ("W", "Q", "WT", "TRM", "TRM_WT")}
    assert set(stages.window_declarations.products) == set(stages.config.products)
