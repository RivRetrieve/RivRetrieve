"""dk_vanda config/window_declarations : () -> ProviderConfig x ProductWindowDeclarations.

Retrieval endpoint choice per product, decided in Effort #799
(research/dk-vanda-source-access.md, step 4):

* discharge (examinationTypeSc 27) -> ``GET /water-flows``, the endpoint step 1
  (#796) already probed for retention and invalid-station behaviour (a full
  109-year, 530,764-row history returned in one uncapped request).
* stage (examinationTypeSc 25) -> ``GET /water-levels``, the endpoint step 3
  (#798)'s DVR90 cross-check retained bytes from; its response carries both
  admitted stage fields (``result``, ``resultElevationCorrected``) on every row.
* temperature (examinationTypeSc 29) -> ``GET /measurements/results/current``.
  VandA publishes no dedicated streamline endpoint for temperature: the plain
  ``/measurements`` route is POST-only (a write operation, confirmed from
  ``swagger.json``), so temperature has to go through one of the four generic
  ``/measurements/results/*`` GET routes instead. ``current`` is this port's
  choice among them: its swagger summary ("Returns measurements with the
  current result") uses the same "current result(s)" wording as
  ``/water-flows``/``/water-levels`` ("Returns current results of water flow/
  level measurements") -- in both cases "current" names the presently-valid
  result per timestamp, not "only the most recent reading." Step 4 confirmed
  this live: a multi-year-old request window against
  ``/measurements/results/current`` returned that historical range in full,
  not a single latest-reading row (see the research record's step 4
  addendum). The other three results/* routes serve a different, narrower
  purpose each (``/first`` is the first-ever registered result,
  ``/valid-from`` is an as-of-a-past-publication-time query, and ``/all`` is
  the full version-history endpoint already used for the multi-version-
  results checks in steps 1/3/4) and are not used for ordinary retrieval here.

discharge and temperature keep exactly one admitted field each
(``series.py``'s ``SeriesMapping``); stage's two admitted fields are carried
directly by ``catalogue_series.py`` and merged in ``parse.py``, not through
this module's ``ProductConfig``/``SourceCoordinates``, since
``SourceCoordinates`` only selects one HTTP route per product and both stage
fields share that one route and rendered window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rivretrieve._internal.engine import (
    Instant,
    ProductConfig,
    ProductWindowDeclarations,
    ProviderConfig,
    SourceCoordinates,
    StopConvention,
    Unit,
    WindowDeclaration,
    WindowGranularity,
    WindowRenderingVocabulary,
    ZoneValue,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.provider_series import SeriesMapping
from rivretrieve._internal.providers.dk_vanda.series import EXAMINATION_PRODUCTS, series_mappings

DkVandaEndpoint = Literal["water-flows", "water-levels", "measurements-results-current"]

_ENDPOINT_BY_SC: dict[int, DkVandaEndpoint] = {
    27: "water-flows",
    25: "water-levels",
    29: "measurements-results-current",
}
# /water-flows and /water-levels are each already scoped to their one examination
# type by the route itself; /measurements/results/current is a generic
# multi-examination route and requires the filter explicitly (swagger.json).
REQUIRES_EXAMINATION_TYPE_SC: frozenset[DkVandaEndpoint] = frozenset({"measurements-results-current"})

# Path segments, since "measurements-results-current" is not a literal URL path.
ENDPOINT_PATH: dict[DkVandaEndpoint, str] = {
    "water-flows": "water-flows",
    "water-levels": "water-levels",
    "measurements-results-current": "measurements/results/current",
}


@dataclass(frozen=True, slots=True)
class DkVandaSourceCoordinates:
    """One product's VandA request route: an examination type and its endpoint."""

    examination_type_sc: int
    endpoint: DkVandaEndpoint

    def __post_init__(self) -> None:
        if self.examination_type_sc not in EXAMINATION_PRODUCTS:
            raise ValueError(f"Unsupported dk_vanda examinationTypeSc: {self.examination_type_sc}")
        if self.endpoint != _ENDPOINT_BY_SC[self.examination_type_sc]:
            raise ValueError("dk_vanda endpoint does not match its examination type")


_UNIT_BY_PRODUCT: dict[str, Unit] = {"discharge": Unit.L_S, "stage": Unit.CM, "temperature": Unit.DEG_C}

_CONFIG = ProviderConfig(
    # measurementDateTime is always "Z"-suffixed UTC in every response checked
    # across steps 1, 3 and 4 (research/dk-vanda-source-access.md).
    zone=ZoneValue("+00:00"),
    products={
        ProductId(product): ProductConfig(
            coordinates=SourceCoordinates(DkVandaSourceCoordinates(sc, _ENDPOINT_BY_SC[sc])),
            unit=_UNIT_BY_PRODUCT[product],
            # Readings are timestamped instants (5-minute discharge/stage, 60-minute
            # temperature intervals per /config/examination-types'
            # measurementIntervalMin), not a published daily or hourly aggregate.
            semantics=Instant(),
        )
        for sc, product in EXAMINATION_PRODUCTS.items()
    },
)

# No pagination and no documented page/offset/limit parameter exists anywhere in
# VandA's swagger definition (step 1/#796); a single ISO-instant request window
# covers an arbitrarily long range without truncation (reconfirmed in step 4 for
# /water-levels and /measurements/results/current, not only /water-flows). Both
# from/to bounds are inclusive (step 1 finding 6, reconfirmed in step 4).
_WINDOW = WindowDeclaration(
    granularity=WindowGranularity("iso-instant"),
    rendering=WindowRenderingVocabulary.ISO_INSTANT,
    stop_convention=StopConvention.INCLUSIVE,
)
_WINDOW_DECLARATIONS = ProductWindowDeclarations(dict.fromkeys(_CONFIG.products, _WINDOW))

# discharge and temperature have exactly one admitted field each; stage's two
# fields are built directly from catalogue_series.py by parse.py instead (see
# the module docstring), so "stage" is deliberately absent here.
_SERIES_MAPPINGS: dict[str, SeriesMapping] = {
    product: series_mappings(sc)["result"] for sc, product in EXAMINATION_PRODUCTS.items() if product != "stage"
}


def config() -> ProviderConfig:
    return _CONFIG


def window_declarations() -> ProductWindowDeclarations:
    return _WINDOW_DECLARATIONS


def series_mapping(product: str) -> SeriesMapping:
    """The single-field `SeriesMapping` for discharge/temperature (not stage)."""
    if product not in _SERIES_MAPPINGS:
        raise ValueError(f"dk_vanda product {product!r} has no single-field SeriesMapping (stage has two fields)")
    return _SERIES_MAPPINGS[product]
