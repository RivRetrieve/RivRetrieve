"""A citation cannot turn an unbound literal litre into a discharge unit."""

from dataclasses import replace

import polars as pl
import pytest

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.source_series import PhysicalFacts, admission, known
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.store.accumulation import StoreUpdate, accumulate
from tests.test_source_series_store import _definition, _success


@pytest.mark.parametrize(
    "citation",
    [
        "arbitrary nonempty evidence",
        "https://hydro.eaufrance.fr/build/5621.4ab47ec9.js",
    ],
)
def test_unbound_literal_litre_cannot_gain_rate_admission_from_citation(citation):
    facts = PhysicalFacts(
        facts_id="literal-volume",
        quantity=known("discharge", "source parameter claim"),
        source_unit=known("l", citation),
    )
    # Deliberately emulate malformed internal metadata without a provider-code binding.
    claimed_rate = facts.model_copy(update={"normalized_unit": "l/s"})
    assert admission(claimed_rate).status == "unsupported"


@pytest.mark.parametrize(
    "citation",
    [
        "arbitrary nonempty evidence",
        "https://hydro.eaufrance.fr/build/5621.4ab47ec9.js",
    ],
)
def test_actual_accumulation_refuses_unbound_litre_to_rate_claim_even_with_fr_citation(tmp_path, citation):
    base = _definition("unbound-litre")
    facts = PhysicalFacts(
        facts_id="facts", quantity=known("discharge", "source parameter claim"), source_unit=known("l", citation)
    ).model_copy(update={"normalized_unit": "l/s"})
    definition = base.model_copy(update={"facts": (facts,)})
    outcome, replacement = _success(definition.series_id, "unqualified-source-answer", [12.0])
    replacement = replace(replacement, rows=replacement.rows.with_columns(pl.lit("l").alias("source_unit")))
    store = StoreRoot(tmp_path / "store")
    with pytest.raises(FatalContractError, match="admitted|normaliz|unit|context"):
        accumulate(store, ProviderId("fixture_live"), StoreUpdate((definition,), (), (outcome,), (replacement,)))
    assert not store.exists()


def _bound_definition():
    from rivretrieve._internal.source_series import SourceIdentity, SourceSeries, SourceUnitCodeDefinition

    definition = SourceUnitCodeDefinition(
        provider_id="fr_hubeau",
        namespace="fr_hubeau/hydroportail/Q",
        code="l",
        unit="l/s",
        evidence=("https://hydro.eaufrance.fr/build/5621.4ab47ec9.js#common.unit.q.l",),
    )
    facts = PhysicalFacts(
        facts_id="bound-facts",
        quantity=known("discharge", "qualified publisher Q dictionary"),
        source_unit=known("l", "qualified publisher Q code"),
        normalized_unit="l/s",
        source_unit_definition=definition,
    )
    return SourceSeries(
        series_id="bound-series",
        provider_id="fr_hubeau",
        station_id="a",
        product_id="level",
        identity=SourceIdentity(
            namespace="fr_hubeau/hydroportail/Q", origin="mapping", evidence=("controlled native cells",)
        ),
        facts=(facts,),
    )


@pytest.mark.parametrize("defect", ["provider", "namespace"])
def test_empty_native_stage_rejects_copied_source_unit_context_mismatch(defect):
    from rivretrieve._internal.engine import RowsSchema
    from rivretrieve._internal.source_series import validate_series_rows

    definition = _bound_definition()
    if defect == "provider":
        malformed = definition.model_copy(update={"provider_id": "unqualified_provider"})
    else:
        malformed = definition.model_copy(
            update={"identity": definition.identity.model_copy(update={"namespace": "other-field"})}
        )
    with pytest.raises(FatalContractError, match="context|namespace|physical|admitted"):
        validate_series_rows(pl.DataFrame(schema=RowsSchema.polars_schema), (malformed,))


def test_bound_code_preserves_native_values_and_context_through_store_conversion_and_bundle(tmp_path):
    import rivretrieve as rr
    from rivretrieve._internal.conversion import convert
    from rivretrieve._internal.engine import Unit
    from rivretrieve._internal.selection import _Selection
    from rivretrieve._internal.source_series import SeriesScope
    from rivretrieve._internal.store import StoreQuery, StoreReader
    from tests.test_internal_conversion import _config, _product, _window

    definition = _bound_definition()
    outcome, replacement = _success(definition.series_id, "bound-answer", [12.0])
    outcome = outcome.model_copy(update={"facts_ids": ("bound-facts",)})
    rows = replacement.rows.with_columns(pl.lit("l").alias("source_unit"), pl.lit("bound-facts").alias("facts_id"))
    replacement = replace(replacement, rows=rows)
    store = StoreRoot(tmp_path / "store")
    accumulate(store, ProviderId("fr_hubeau"), StoreUpdate((definition,), (), (outcome,), (replacement,)))
    read = StoreReader().query(
        StoreQuery(store, ProviderId("fr_hubeau"), ("a",), ("level",), outcome.window.start, outcome.window.end)
    )
    assert read.rows["source_unit"].item() == "l"
    assert read.rows["value"].item() == 12.0
    assert read.manifest.series[0].facts[0].source_unit_definition == definition.facts[0].source_unit_definition
    converted = convert(
        read.rows,
        _config({"level": _product(Unit.L_S)}),
        _window(outcome.window.start, outcome.window.end),
        series=read.manifest.series,
    )
    assert converted.value["value"].item() == pytest.approx(0.012)
    assert converted.value["unit"].item() == "m3/s"
    assert converted.value["source_unit"].item() == "l"
    selection = _Selection(
        scope=SeriesScope(provider_ids=("fr_hubeau",), station_ids=("a",)), known_series=(definition,)
    )
    restored = rr.from_bundle(rr.to_bundle(selection))
    assert restored.known_series == selection.known_series


def test_binding_code_and_imported_context_are_checked_at_model_boundaries():
    import json
    from io import BytesIO
    from zipfile import ZipFile

    import rivretrieve as rr
    from rivretrieve._internal.selection import _Selection
    from rivretrieve._internal.source_series import SeriesScope

    definition = _bound_definition()
    facts = definition.facts[0]
    raw = facts.model_dump(mode="json")
    raw["source_unit_definition"]["code"] = "other-code"
    with pytest.raises(ValueError, match="code"):
        PhysicalFacts.model_validate(raw)
    selection = _Selection(scope=SeriesScope(provider_ids=("fr_hubeau",)), known_series=(definition,))
    altered = BytesIO()
    with ZipFile(BytesIO(rr.to_bundle(selection))) as source, ZipFile(altered, "w") as target:
        for name in source.namelist():
            body = source.read(name)
            if name == "manifest.json":
                document = json.loads(body)
                document["series"][0]["identity"]["namespace"] = "outside-qualified-Q-context"
                body = json.dumps(document).encode()
            target.writestr(name, body)
    with pytest.raises(ValueError, match="namespace"):
        rr.from_bundle(altered.getvalue())


def test_unknown_source_unit_empty_stage_remains_a_valid_source_limitation():
    from rivretrieve._internal.engine import RowsSchema
    from rivretrieve._internal.source_series import EvidenceFact, validate_series_rows

    definition = _definition("source-unknown")
    unknown = definition.facts[0].model_copy(update={"source_unit": EvidenceFact(), "normalized_unit": None})
    definition = definition.model_copy(update={"facts": (unknown,)})
    validate_series_rows(pl.DataFrame(schema=RowsSchema.polars_schema), (definition,))
    assert admission(unknown).status == "unsupported"


def test_absent_binding_omits_only_its_new_optional_field_from_fact_serialization():
    facts = _definition("unchanged-unbound-facts").facts[0]
    payload = facts.model_dump(mode="json")
    assert "source_unit_definition" not in payload
    assert "label_time" in payload and payload["label_time"] is None
    assert payload["day_definition"]["value"] is None
    assert payload["vertical_datum"]["value"] is None


def test_present_binding_remains_in_fact_serialization():
    facts = _bound_definition().facts[0]
    payload = facts.model_dump(mode="json")
    assert payload["source_unit_definition"] == facts.source_unit_definition.model_dump(mode="json")
    assert payload["source_unit"]["value"] == "l"
