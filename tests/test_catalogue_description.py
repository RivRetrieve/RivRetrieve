"""Catalogue description : PackagedDescriptor → OfflinePublicJSONLD."""

import json
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    verified_provider_terms,
    verified_source_terms,
)
from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
from rivretrieve._internal.registry import UnknownProviderError
from tests._provenance import legacy_document
from tests.usgs_modern_recordings import ModernReplay

_ROOT = Path(__file__).parents[1]
_PROVIDERS = _ROOT / "src/rivretrieve/_internal/providers"


@pytest.mark.parametrize("provider", BUILTIN_PROVIDER_IDS)
def test_describe_returns_the_packaged_document(provider: str) -> None:
    expected = json.loads((_PROVIDERS / provider / "catalogue/croissant.json").read_text())
    assert rr.describe(provider) == expected


@pytest.mark.parametrize("provider", ("missing", "../usgs_nwis", "USGS_NWIS"))
def test_describe_rejects_unknown_provider(provider: str) -> None:
    with pytest.raises(UnknownProviderError):
        rr.describe(provider)


def test_recorded_usgs_fetch_carries_exact_verified_source_words(monkeypatch: pytest.MonkeyPatch) -> None:
    replay = ModernReplay("continuous-07374000-2010-discharge")
    monkeypatch.setattr(discovery, "_credentialed_transport", lambda provider_id, values: replay)
    result = rr.fetch(
        rr.find(provider="usgs_nwis", station="07374000", quantity="discharge", temporal_support="instantaneous"),
        start="2010-06-01T05:00:00",
        end="2010-06-02T04:59:59",
        on_issue="ignore",
    )
    evidence = load_packaged_catalogue_artifact(_PROVIDERS / "usgs_nwis/catalogue").acquisition_provenance
    assert evidence is not None
    source = evidence.header.source_records[0]
    expected = {statement.kind: statement.exact_text for statement in source.statements}
    assert result.provenance.license == expected["license"]
    assert result.provenance.citation == expected["citation"]
    assert result.data.height > 0
    assert not any(issue.code.endswith("_not_established") for issue in result.issues)


def test_verified_terms_do_not_combine_issuers_or_rewrite_conflicts() -> None:
    source = AcquisitionProvenance.model_validate(
        legacy_document(_PROVIDERS / "usgs_nwis/catalogue/provenance.json")
    ).source_records[0]
    assert verified_source_terms(()) == {}
    assert verified_source_terms((source, source.model_copy(update={"issuer": "Another issuer"}))) == {}
    assert verified_source_terms((source, source)) == verified_source_terms((source,))
    statement = source.statements[0].model_copy(update={"exact_text": "Different source words"})
    conflicting = source.model_copy(update={"statements": (statement,)})
    with pytest.raises(FatalContractError, match="Conflicting verified"):
        verified_source_terms((source, conflicting))
    private = AcquisitionProvenance.model_validate(legacy_document(_PROVIDERS / "pl_imgw/catalogue/provenance.json"))
    assert verified_source_terms(private.source_records) == {}


def test_provider_terms_do_not_promote_an_explicit_absence_or_unbound_statement() -> None:
    provenance = AcquisitionProvenance.model_validate(legacy_document(_PROVIDERS / "pl_imgw/catalogue/provenance.json"))
    assert verified_provider_terms(provenance.source_records, provenance.fact_bindings, provenance.withheld_facts) == {}
    imgw = next(source for source in provenance.source_records if source.source_id == "sr.pl.imgw")
    assert set(verified_source_terms((imgw,))) == {"license", "citation"}
    assert verified_provider_terms((imgw,), (), ()) == {}
    brazil = AcquisitionProvenance.model_validate(legacy_document(_PROVIDERS / "br_ana/catalogue/provenance.json"))
    assert "license" in verified_source_terms(brazil.source_records)
    assert verified_provider_terms(brazil.source_records, brazil.fact_bindings, brazil.withheld_facts) == {
        "license": verified_source_terms(brazil.source_records)["license"]
    }


def test_south_africa_remains_catalogue_only() -> None:
    from rivretrieve._internal.issues import ObservationsUnavailableError

    candidates = rr.find(provider="za_dws")
    selection = rr.find(provider="za_dws", station=candidates.known_series[0].station_id)
    with pytest.raises(ObservationsUnavailableError, match="no observations registered"):
        rr.fetch(selection, start="2020-01-01", end="2020-01-02", on_issue="ignore")
