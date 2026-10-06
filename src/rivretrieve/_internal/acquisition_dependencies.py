"""Directed support between source acquisitions, separate from call aliases."""

from collections.abc import Mapping
from typing import cast

from rivretrieve._internal.issues import FatalContractError


def validate_prerequisite_ids(value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, tuple)
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(set(value)) != len(value)
    ):
        raise FatalContractError("Prerequisite acquisition identities must be a tuple of unique nonempty strings")
    return cast(tuple[str, ...], value)


def validate_acquisition_dependencies(dependencies: Mapping[str, tuple[str, ...]]) -> None:
    """Reject unknown acquisitions and cycles before evidence can be retained."""
    remaining = {}
    dependents: dict[str, set[str]] = {}
    for identity, references in dependencies.items():
        if not isinstance(identity, str) or not identity.strip():
            raise FatalContractError("Prerequisite acquisition identity must be a nonempty string")
        validate_prerequisite_ids(references)
        if any(reference not in dependencies for reference in references):
            raise FatalContractError("Prerequisite references an unknown acquisition")
        if identity in references:
            raise FatalContractError("Prerequisite acquisition cannot reference itself")
        remaining[identity] = len(references)
        for reference in references:
            dependents.setdefault(reference, set()).add(identity)
    pending = [identity for identity, count in remaining.items() if not count]
    visited = 0
    while pending:
        visited += 1
        for dependent in dependents.get(pending.pop(), ()):
            remaining[dependent] -= 1
            if not remaining[dependent]:
                pending.append(dependent)
    if visited != len(dependencies):
        raise FatalContractError("Prerequisite acquisitions contain a cycle")


def source_call_dependencies(calls: tuple[dict[str, object], ...]) -> dict[str, tuple[str, ...]]:
    """Validate directed support using acquisition identities, not retry aliases."""
    dependencies: dict[str, tuple[str, ...]] = {}
    for call in calls:
        identity = call.get("acquisition_id", call.get("call_id"))
        references = validate_prerequisite_ids(call.get("prerequisite_acquisition_ids", ()))
        if not isinstance(identity, str) or not identity.strip():
            raise FatalContractError("Source calls require an acquisition or call identity")
        # Credential calls belong to an acquisition but do not declare its support.
        if "prerequisite_acquisition_ids" in call:
            previous = dependencies.get(identity)
            if previous is not None and previous != references:
                raise FatalContractError("Prerequisite declarations conflict for one acquisition")
            dependencies[identity] = references
    for call in calls:
        identity = call.get("acquisition_id", call.get("call_id"))
        assert isinstance(identity, str)
        dependencies.setdefault(identity, ())
    validate_acquisition_dependencies(dependencies)
    return dependencies


def source_call_support(calls: tuple[dict[str, object], ...], references: set[str]) -> set[str]:
    """Find explicit call support without activating prerequisite outcomes or issues."""
    dependencies = source_call_dependencies(calls)
    aliases: dict[str, set[str]] = {}
    for call in calls:
        identity, acquisition = call.get("call_id"), call.get("acquisition_id")
        if isinstance(identity, str) and isinstance(acquisition, str):
            aliases.setdefault(identity, set()).add(acquisition)
            aliases.setdefault(acquisition, set()).add(identity)
    needed = set(references)
    pending = list(needed)
    while pending:
        identity = pending.pop()
        for reference in (*aliases.get(identity, ()), *dependencies.get(identity, ())):
            if reference not in needed:
                needed.add(reference)
                pending.append(reference)
    return needed
