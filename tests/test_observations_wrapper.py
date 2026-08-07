from __future__ import annotations

from typing import Any

import pytest

import rivretrieve as rr
from rivretrieve import RawMode
from rivretrieve._internal import discovery


def test_observations_wrapper_delegates_to_provider_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    result = object()
    calls: list[tuple[str, dict[str, object]]] = []

    class SpyHandle:
        def observations(self, **kwargs: object) -> object:
            calls.append(("observations", kwargs))
            return result

    def provider_lookup(provider_id: str) -> SpyHandle:
        calls.append(("provider", {"provider_id": provider_id}))
        return SpyHandle()

    monkeypatch.setattr(discovery, "_provider_lookup", provider_lookup)

    returned = rr.observations(
        provider="spy",
        stations=["2206"],
        products=["discharge_instantaneous"],
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
        raw=RawMode.INCLUDE,
    )

    assert returned is result
    assert calls == [
        ("provider", {"provider_id": "spy"}),
        (
            "observations",
            {
                "stations": ["2206"],
                "products": ["discharge_instantaneous"],
                "start": "2025-01-01",
                "end": "2025-01-01",
                "on_issue": "ignore",
                "raw": RawMode.INCLUDE,
            },
        ),
    ]


def test_observations_wrapper_forwards_default_on_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    observed_kwargs: dict[str, object] = {}

    class SpyHandle:
        def observations(self, **kwargs: object) -> object:
            observed_kwargs.update(kwargs)
            return object()

    monkeypatch.setattr(discovery, "_provider_lookup", lambda _provider_id: SpyHandle())

    rr.observations(
        provider="spy",
        stations="2206",
        products="discharge_instantaneous",
        start="2025-01-01",
        end="2025-01-01",
    )

    assert observed_kwargs["on_issue"] == "warn"
    assert observed_kwargs["raw"] is RawMode.OMIT


@pytest.mark.parametrize("missing_kwarg", ["provider", "stations", "products", "start", "end"])
def test_observations_wrapper_requires_core_keywords(
    monkeypatch: pytest.MonkeyPatch,
    missing_kwarg: str,
) -> None:
    def fail_provider_lookup(_provider_id: str) -> object:
        raise AssertionError("provider lookup should not run")

    kwargs: dict[str, Any] = {
        "provider": "spy",
        "stations": "2206",
        "products": "discharge_instantaneous",
        "start": "2025-01-01",
        "end": "2025-01-01",
    }
    kwargs.pop(missing_kwarg)
    monkeypatch.setattr(discovery, "_provider_lookup", fail_provider_lookup)

    with pytest.raises(TypeError):
        rr.observations(**kwargs)
