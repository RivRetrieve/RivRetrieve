"""Unit spelling normalization cannot change publisher scale, offset, or dimension."""

import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.conversion import convert
from rivretrieve._internal.engine import Unit
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.source_series import EvidenceFact, PhysicalFacts, admission, known
from rivretrieve._internal.store import ObservationStoreRefusedError, StoreRoot
from rivretrieve._internal.store.accumulation import StoreUpdate, accumulate
from tests.test_internal_conversion import _config, _product, _window
from tests.test_source_series_store import _definition, _query, _success
from tests.usgs_modern_recordings import ModernReplay


@pytest.mark.parametrize(
    ("source_unit", "normalized_unit"),
    [
        ("cm", "m"),
        ("mm", "cm"),
        ("ft3/s", "m3/s"),
        ("m", "m3/s"),
        ("K", "degC"),
        ("°C", "K"),
    ],
)
def test_external_fact_model_rejects_scale_offset_and_dimension_normalization_changes(source_unit, normalized_unit):
    with pytest.raises(ValueError, match="normaliz"):
        PhysicalFacts(
            facts_id="corrupt",
            quantity=known("stage", "source definition"),
            source_unit=known(source_unit, "publisher unit spelling"),
            normalized_unit=normalized_unit,
        )


def test_corrupt_store_manifest_cannot_turn_twelve_centimetres_into_twelve_metres(tmp_path: Path):
    store = StoreRoot(tmp_path / "store")
    definition = _definition("native-centimetres")
    outcome, replacement = _success(definition.series_id, "source-answer", [12.0])
    accumulate(store, ProviderId("fixture_live"), StoreUpdate((definition,), (), (outcome,), (replacement,)))
    path = store / "manifest.json"
    raw = json.loads(path.read_text())
    raw["series"][0]["facts"][0]["normalized_unit"] = "m"
    path.write_text(json.dumps(raw))
    from tests.store.test_integrity import _resign

    # Reach the unit-consistency rule, rather than an earlier byte-identity refusal.
    _resign(store)
    with pytest.raises(ObservationStoreRefusedError, match="normaliz"):
        read = _query(store)
        result = convert(
            read.rows,
            _config({"level": _product(Unit.CM)}),
            _window(outcome.window.start, outcome.window.end),
            series=read.manifest.series,
        )
        print("corrupt store converted 12 cm to", result.value["value"].item(), result.value["unit"].item())


def test_accumulation_rejects_copied_internal_normalization_contradiction(tmp_path: Path):
    definition = _definition("native-centimetres")
    bad = definition.facts[0].model_copy(update={"normalized_unit": "m"})
    definition = definition.model_copy(update={"facts": (bad,)})
    outcome, replacement = _success(definition.series_id, "source-answer", [12.0])
    store = StoreRoot(tmp_path / "store")
    with pytest.raises(FatalContractError, match="admitted|normaliz"):
        accumulate(store, ProviderId("fixture_live"), StoreUpdate((definition,), (), (outcome,), (replacement,)))
    assert not store.exists()


@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_public_recorded_bundle_import_refuses_scale_changed_facts(monkeypatch, tmp_path, retained_evidence_root: Path):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(
        discovery, "HttpClient", lambda: ModernReplay("daily-07374000-docs-2023", evidence_root=retained_evidence_root)
    )
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    result = rr.fetch(selection, start="2023-01-01", end="2023-01-01", receipts=True, cache="reuse")
    output = BytesIO()
    with ZipFile(BytesIO(rr.to_bundle(result))) as source, ZipFile(output, "w") as target:
        for name in source.namelist():
            body = source.read(name)
            if name == "manifest.json":
                manifest = json.loads(body)
                for definition in manifest["series"]:
                    for fact in definition["facts"]:
                        if fact["source_unit"]["value"] == "ft^3/s":
                            fact["normalized_unit"] = "m3/s"
                body = json.dumps(manifest).encode()
            target.writestr(name, body)
    with pytest.raises(ValueError, match="normaliz"):
        rr.from_bundle(output.getvalue())


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
@pytest.mark.parametrize("answer_rows", ["nonempty", "empty", "unsupported_empty"])
@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_public_recorded_conversion_rejects_internal_scale_change_under_every_policy(
    monkeypatch, tmp_path, policy, answer_rows, retained_evidence_root: Path
):
    from rivretrieve._internal.providers.usgs_nwis.declaration import declaration
    from tests.usgs_modern_recordings import ModernReplay

    stages = declaration.observations.stages
    original = stages.parse
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(
        discovery, "HttpClient", lambda: ModernReplay("daily-07374000-docs-2023", evidence_root=retained_evidence_root)
    )

    def corrupt_parse(payload, config):
        parsed = original(payload, config)
        definitions = tuple(
            item.model_copy(
                update={"facts": tuple(fact.model_copy(update={"normalized_unit": "m3/s"}) for fact in item.facts)}
            )
            for item in parsed.series
        )
        if answer_rows in ("empty", "unsupported_empty"):
            from rivretrieve._internal.source_series import OutcomeStatus

            return replace(
                parsed,
                series=definitions,
                rows=parsed.rows.clear(),
                outcomes=tuple(
                    item.model_copy(
                        update={
                            "status": OutcomeStatus.EMPTY if answer_rows == "empty" else OutcomeStatus.UNSUPPORTED,
                            "reason": None
                            if answer_rows == "empty"
                            else "authored unsupported classification of invalid internal facts",
                        }
                    )
                    for item in parsed.outcomes
                ),
            )
        return replace(parsed, series=definitions)

    monkeypatch.setattr(stages, "parse", staticmethod(corrupt_parse))
    # Compose only the recorded provider; unrelated catalogue regeneration must
    # not intercept this real public parse-to-result contract regression.
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.registry import ProviderRegistry

    registry = ProviderRegistry()
    registry.register(
        "usgs_nwis",
        load_packaged_catalogue_artifact(declaration.catalogue, on_issue="raise"),
        engine_provider_module=stages,
    )
    monkeypatch.setattr(discovery, "_registry", registry)
    monkeypatch.setattr(discovery, "_provider_lookup", registry.get)
    monkeypatch.setattr(discovery, "_ensure_default_providers_registered", lambda: None)
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    with pytest.raises(FatalContractError, match="admitted|normaliz") as raised:
        result = rr.fetch(selection, start="2023-01-01", end="2023-01-01", cache="bypass", on_issue=policy)
        print("corrupt actual parser returned", result.data.height, "rows", result.data["value"].to_list())
    print("malformed", answer_rows, "parse outcome rejected:", raised.value)


@pytest.mark.parametrize(
    ("source_unit", "normalized", "quantity", "factor"),
    [
        ("cm", "cm", "stage", 0.01),
        ("mm", "mm", "stage", 0.001),
        ("m³/s", "m3/s", "discharge", 1.0),
        ("ft³/s", "ft3/s", "discharge", 0.028316846592),
        ("°C", "degC", "temperature", 1.0),
        ("publisher-Q-code", "l/s", "discharge", 0.001),
    ],
)
def test_established_spelling_aliases_and_documented_codes_roundtrip_native_store_and_convert_once(
    tmp_path, source_unit, normalized, quantity, factor
):
    base = _definition("known-unit")
    fact = PhysicalFacts(
        facts_id="facts",
        quantity=known(quantity, "source definition"),
        source_unit=known(source_unit, "publisher unit-code definition: explicit normalized meaning"),
        normalized_unit=normalized,
    )
    definition = base.model_copy(update={"facts": (fact,)})
    outcome, replacement = _success(definition.series_id, "source-answer", [12.0])
    rows = replacement.rows.with_columns(pl.lit(source_unit).alias("source_unit"))
    replacement = replace(replacement, rows=rows)
    store = StoreRoot(tmp_path / "store")
    accumulate(store, ProviderId("fixture_live"), StoreUpdate((definition,), (), (outcome,), (replacement,)))
    read = _query(store)
    assert read.rows["value"].item() == 12.0
    assert read.manifest.series[0].facts[0].source_unit.value == source_unit
    result = convert(
        read.rows,
        _config({"level": _product(Unit(normalized))}),
        _window(outcome.window.start, outcome.window.end),
        series=read.manifest.series,
    )
    assert result.value["value"].item() == pytest.approx(12.0 * factor)
    assert result.value["source_unit"].item() == source_unit


def test_unknown_source_unit_and_absent_source_unit_remain_distinct_unsupported_facts():
    unknown = PhysicalFacts(
        facts_id="unknown",
        quantity=known("stage", "source definition"),
        source_unit=known("unrecognised-publisher-unit", "exact publisher label"),
    )
    absent = PhysicalFacts(facts_id="absent", quantity=known("stage", "source definition"), source_unit=EvidenceFact())
    assert admission(unknown).status == admission(absent).status == "unsupported"
    assert unknown.source_unit.value == "unrecognised-publisher-unit"
    assert absent.source_unit.value is None
    assert admission(unknown).reason != admission(absent).reason


def test_unknown_evidence_state_cannot_use_a_copied_normalized_meaning():
    facts = PhysicalFacts(facts_id="unknown-meaning", quantity=known("discharge", "publisher quantity"))
    copied = facts.model_copy(update={"normalized_unit": "l/s"})
    decision = admission(copied)
    assert decision.status == "unsupported"
    assert decision.factor is None
    assert copied.source_unit.value is None


def test_known_published_code_without_established_normalized_meaning_is_unsupported():
    facts = PhysicalFacts(
        facts_id="known-code-unknown-meaning",
        quantity=known("discharge", "publisher quantity"),
        source_unit=known("publisher-Q-code", "exact published token; meaning not established"),
    )
    decision = admission(facts)
    assert decision.status == "unsupported"
    assert decision.factor is None
    assert facts.source_unit.value == "publisher-Q-code"


def test_known_source_code_normalization_requires_nonempty_source_evidence_even_after_internal_copy():
    fact = PhysicalFacts(
        facts_id="documented-code",
        quantity=known("discharge", "publisher quantity"),
        source_unit=known("publisher-Q-code", "publisher dictionary establishes litres per second"),
        normalized_unit="l/s",
    )
    stripped = fact.model_copy(update={"source_unit": fact.source_unit.model_copy(update={"evidence": ()})})
    assert admission(stripped).status == "unsupported"
    assert "evidence" in admission(stripped).reason
