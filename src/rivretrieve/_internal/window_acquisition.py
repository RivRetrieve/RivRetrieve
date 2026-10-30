"""Coordinate response-driven subdivision without assigning source meanings."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from enum import StrEnum

from rivretrieve._internal.engine import RenderedWindow, SourceAcquisition
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.window_planning import subdivide_window


class WindowResponseMeaning(StrEnum):
    COMPLETE = "complete"
    OVERFLOW = "overflow"


@dataclass(frozen=True, slots=True)
class WindowAcquisition:
    acquisition: SourceAcquisition
    meaning: WindowResponseMeaning = WindowResponseMeaning.COMPLETE
    overflow_outcome_ids: tuple[str, ...] = ()


def acquire_window(
    window: RenderedWindow,
    *,
    precision: timedelta,
    acquire: Callable[[RenderedWindow], WindowAcquisition],
) -> SourceAcquisition:
    """Keep independent child results and all parent calls after confirmed overflow.

    The provider identifies overflow and its terminal outcome identities. The
    engine owns subdivision and rendering. COMPLETE means no subdivision was
    requested, not a promise of continuous observations or complete inventory.
    """
    pending: list[tuple[RenderedWindow, tuple[str, ...]]] = [(window, ())]
    results: list[SourceAcquisition] = []
    while pending:
        current, ancestors = pending.pop()
        result = acquire(current)
        acquisition = result.acquisition
        acquisition = replace(
            acquisition,
            value=tuple(
                replace(item, prerequisite_acquisition_ids=(*ancestors, *item.prerequisite_acquisition_ids))
                for item in acquisition.value
            ),
            calls=tuple(
                replace(item, prerequisite_acquisition_ids=(*ancestors, *item.prerequisite_acquisition_ids))
                for item in acquisition.calls
            ),
            failed_requests=tuple(
                replace(item, prerequisite_acquisition_ids=(*ancestors, *item.prerequisite_acquisition_ids))
                for item in acquisition.failed_requests
            ),
        )
        if result.meaning is WindowResponseMeaning.OVERFLOW:
            if acquisition.value or not result.overflow_outcome_ids:
                raise FatalContractError("Overflow requires terminal outcomes and cannot contain successful payloads")
            children = subdivide_window(current, precision=precision)
            if children:
                acquisition = replace(
                    acquisition,
                    outcomes=tuple(
                        item for item in acquisition.outcomes if item.outcome_id not in result.overflow_outcome_ids
                    ),
                )
                parent_ids = tuple(item.acquisition_id for item in acquisition.calls if item.acquisition_id is not None)
                pending.extend((child, (*ancestors, *parent_ids)) for child in reversed(children))
        results.append(acquisition)
    return SourceAcquisition(
        value=tuple(item for result in results for item in result.value),
        issues=tuple(item for result in results for item in result.issues),
        series=tuple(item for result in results for item in result.series),
        inventories=tuple(item for result in results for item in result.inventories),
        outcomes=tuple(item for result in results for item in result.outcomes),
        calls=tuple(item for result in results for item in result.calls),
        failed_requests=tuple(item for result in results for item in result.failed_requests),
    )
