"""Project established physical facts into canonical product catalogue rows."""

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.source_series import PhysicalFacts, admission


def product_row(provider_id: str, product_id: str, native_id: str | None, facts: PhysicalFacts) -> dict[str, object]:
    """Keep access coordinates separate from scientific facts and target units."""
    decision = admission(facts)
    if decision.status != "supported":
        raise FatalContractError(f"Cannot advertise unsupported product {provider_id}/{product_id}: {decision.reason}")
    quantity = facts.quantity.value
    return {
        "provider_id": provider_id,
        "product_id": product_id,
        "observed_property": "water_temperature" if quantity == "temperature" else quantity,
        "frequency": facts.frequency.value or "unknown",
        "statistic": facts.statistic.value or "unknown",
        "period_type": facts.temporal_support.value or "unknown",
        "period_anchor": facts.timestamp_anchor.value or "unknown",
        "unit": decision.target_unit,
        "native_id": native_id,
    }
