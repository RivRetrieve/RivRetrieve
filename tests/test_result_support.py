"""Inventory dependencies remain evidence rather than active retrieval diagnoses."""

import polars as pl
import polars.testing as pt
import pytest

import rivretrieve as rr
from rivretrieve._internal.assembly import assemble
from rivretrieve._internal.issues import ObservationDataSchemaError
from rivretrieve._internal.observations import (
    ObservationDataSchema,
    ObservationProvenance,
    ObservationResult,
    Receipts,
)
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    PhysicalFacts,
    SeriesScope,
    SourceIdentity,
    SourceSeries,
    known,
)
from rivretrieve._internal.store.authority import compact_evidence
from tests.test_cache_authority import _cover, _issue, _outcome


@pytest.fixture
def recovered_evidence():
    failed = _outcome("failed-acquisition", status=OutcomeStatus.FAILED)
    recovered = _outcome("recovered", status=OutcomeStatus.EMPTY)
    scope = SeriesScope(provider_ids=("fixture_live",), station_ids=("a",), product_ids=("q",))
    original = InventorySnapshot(
        snapshot_id="original-inventory",
        scope=scope,
        members=("s",),
        member_facts=(("s", ("f",)),),
        completeness=InventoryCompleteness.INCOMPLETE,
        reason="Original acquisition was incomplete",
        access="authored inventory",
        origin="response",
        window=failed.window,
        evidence=("retrieval-outcome:failed-acquisition",),
    )
    complete = original.model_copy(
        update={
            "snapshot_id": "complete-inventory",
            "completeness": InventoryCompleteness.COMPLETE,
            "reason": None,
            "evidence": ("source-inventory:original-inventory", "retrieval-outcome:recovered"),
        }
    )
    current = compact_evidence(
        (_cover(recovered),),
        (failed, recovered),
        (original, complete),
        (_issue(failed),),
        ({"call_id": "failed-acquisition"}, {"call_id": "recovered"}),
    )
    # Independently stated recovery contract: the old failure supports only
    # the unchanged inventory, and does not remain an active diagnosis.
    assert current.outcomes == (recovered,)
    assert current.supporting_outcomes == (failed,)
    assert current.inventories == (original, complete)
    assert current.issues == ()
    return current, scope


@pytest.fixture
def supported_result(recovered_evidence):
    current, scope = recovered_evidence
    facts = PhysicalFacts(
        facts_id="f",
        quantity=known("discharge", "authored"),
        source_unit=known("m3/s", "authored"),
        normalized_unit="m3/s",
    )
    definition = SourceSeries(
        series_id="s",
        provider_id="fixture_live",
        station_id="a",
        product_id="q",
        identity=SourceIdentity(namespace="authored", origin="response", evidence=("authored",)),
        facts=(facts,),
    )
    return ObservationResult(
        data=pl.DataFrame(schema=ObservationDataSchema.polars_schema),
        provenance=ObservationProvenance(
            source="live", provider_id=ProviderId("fixture_live"), calls_made=current.source_calls
        ),
        receipts=Receipts(ProviderId("fixture_live")),
        source_series=(definition,),
        scope=scope,
        inventories=current.inventories,
        outcomes=current.outcomes,
        supporting_outcomes=current.supporting_outcomes,
    )


def test_supporting_failure_survives_bundle_and_pick_without_becoming_diagnostic(supported_result):
    result = supported_result
    assert result.supporting_outcomes[0].outcome_id == "failed-acquisition"
    restored = rr.from_bundle(rr.to_bundle(result))
    picked = rr.pick(restored, series_id="s", on_issue="raise")
    for value in (restored, picked, rr.from_bundle(rr.to_bundle(picked))):
        pt.assert_frame_equal(value.data, result.data)
        assert value.inventories == result.inventories
        assert value.supporting_outcomes == result.supporting_outcomes
        assert value.outcomes == result.outcomes
        assert value.issues == ()
        assert value.provenance.calls_made == result.provenance.calls_made
        assert value.supporting_outcomes[0].retrieved_at == result.supporting_outcomes[0].retrieved_at
        assert value.inventories[0].evidence == ("retrieval-outcome:failed-acquisition",)


def test_assembly_keeps_support_separate_and_defaults_to_empty(supported_result):
    result = supported_result
    assembled = assemble(
        result.data, result.provenance, (), result.receipts, supporting_outcomes=result.supporting_outcomes
    )
    assert assembled.supporting_outcomes == result.supporting_outcomes
    assert assembled.outcomes == ()
    assert assemble(result.data, result.provenance, (), result.receipts).supporting_outcomes == ()


@pytest.mark.parametrize("defect", ["unknown_series", "unknown_fact", "coordinate", "active", "duplicate"])
def test_result_rejects_invalid_support_context(supported_result, defect):
    result = supported_result
    support = result.supporting_outcomes[0]
    changes = {
        "unknown_series": {"series_id": "absent"},
        "unknown_fact": {"facts_ids": ("absent",)},
        "coordinate": {"station_id": "other"},
    }
    supports = (
        (support.model_copy(update=changes[defect]),)
        if defect in changes
        else (result.outcomes[0],)
        if defect == "active"
        else (support, support)
    )
    with pytest.raises(ObservationDataSchemaError):
        ObservationResult(**{**result.model_dump(mode="python"), "supporting_outcomes": supports})
