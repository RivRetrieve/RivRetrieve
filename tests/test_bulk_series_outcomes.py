"""Public local bulk queries expose outcomes even without observation rows."""

from datetime import datetime
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.registry import ProviderRegistry
from rivretrieve._internal.source_series import OutcomeStatus
from tests.test_ca_eccc_boundary_probe import _compiled_derived_store
from tests.test_pl_imgw_boundary_probe import _compiled_store


@pytest.mark.parametrize(
    "provider",
    [
        pytest.param("ca_eccc", marks=pytest.mark.derived("tests/test_data/ca_eccc_02GA010_2020_01_derived_input.zip")),
        pytest.param("pl_imgw", marks=pytest.mark.recorded("tests/test_data/pl_imgw_codz_2022_01.recording.json")),
    ],
)
@pytest.mark.parametrize("scenario", ["success", "empty", "explicit", "mixed"])
def test_public_compiled_queries_report_success_empty_and_unsettled_explicit_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    scenario: str,
    retained_evidence_root: Path,
) -> None:
    if provider == "ca_eccc":
        from rivretrieve._internal.providers.ca_eccc.config import config
        from rivretrieve._internal.providers.ca_eccc.declaration import declaration

        store = _compiled_derived_store(tmp_path, retained_evidence_root / "tests/test_data")
        station, inside, outside = "02GA010", "2020-01-01", "2020-02-01"
    else:
        from rivretrieve._internal.providers.pl_imgw.config import config
        from rivretrieve._internal.providers.pl_imgw.declaration import declaration

        store = _compiled_store(retained_evidence_root, tmp_path)
        station, inside, outside = "154210010", "2021-11-01", "2021-12-01"
    registry = ProviderRegistry()
    registry.register(
        provider,
        load_packaged_catalogue_artifact(declaration.catalogue, on_issue="raise"),
        bulk_config=config,
        observation_store=store,
    )
    monkeypatch.setattr(discovery, "_registry", registry)
    monkeypatch.setattr(discovery, "_provider_lookup", registry.get)
    monkeypatch.setattr(discovery, "_ensure_default_providers_registered", lambda: None)

    class NoNetwork:
        def send(self, request):
            pytest.fail("Explicit local bulk retrieval must not contact observation services")

    monkeypatch.setattr(discovery, "HttpClient", NoNetwork)
    selection = rr.find(provider=provider, station=station, quantity="stage")
    successful = rr.fetch(selection, start=inside, end=inside, on_issue="ignore")
    assert successful.data.height == 1
    if scenario == "success":
        assert len(successful.outcomes) == 1, "compilation metadata cannot substitute for this query outcome"
        outcome = successful.outcomes[0]
        assert outcome.status is OutcomeStatus.SUCCESS
        assert outcome.series_id == successful.data["series_id"].item()
        assert outcome.facts_ids == (successful.data["facts_id"].item(),)
        assert outcome.window.start == datetime.fromisoformat(inside)
        assert outcome.window.end == datetime.fromisoformat(inside).replace(
            hour=23, minute=59, second=59, microsecond=999999
        )
        assert outcome.retrieved_at is None, "a local store query is not a fresh publisher response"
        return
    if scenario == "empty":
        empty = rr.fetch(selection, start=outside, end=outside, on_issue="ignore")
        assert empty.data.is_empty()
        assert len(empty.outcomes) == 1
        assert empty.outcomes[0].status is OutcomeStatus.EMPTY
        assert empty.outcomes[0].series_id == successful.data["series_id"].item()
        assert empty.outcomes[0].window.start == datetime.fromisoformat(outside)
        return
    if scenario == "mixed":
        restriction = rr.pick(
            selection, series_id=(successful.data["series_id"].item(), "unresolved-source-identity"), on_issue="ignore"
        )
        mixed = rr.fetch(restriction, start=inside, end=inside, on_issue="ignore")
        assert mixed.data.height == 1
        assert any(
            item.requested_selector is not None and item.requested_selector.value == "unresolved-source-identity"
            for item in mixed.outcomes
        )
        assert all(not item.calls and item.retrieved_at is None for item in mixed.outcomes)
        return
    restriction = rr.pick(selection, variant="unpublished-test-restriction", on_issue="ignore")
    unresolved = rr.fetch(restriction, start=inside, end=inside, on_issue="ignore")
    assert unresolved.data.is_empty()
    assert unresolved.outcomes, "an unmatched explicit restriction must not silently disappear"
    assert all(
        item.status in (OutcomeStatus.NO_MATCH, OutcomeStatus.UNRESOLVED) and item.reason
        for item in unresolved.outcomes
    )
    assert all(item.status not in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY) for item in unresolved.outcomes)
