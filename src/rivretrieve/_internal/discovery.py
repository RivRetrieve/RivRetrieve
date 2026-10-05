"""public retrieval : Selection × WindowInputs × CacheMode × CredentialSources → ObservationResult(s); provider discovery : ProviderDeclarations × CredentialSources → ProviderAccessFrame; station metadata : Selection → StationMetadataFrame."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, time
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, cast

import polars as pl
from dotenv import dotenv_values
from platformdirs import user_cache_dir

from rivretrieve._internal.authentication import CredentialExchangeTransport
from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.issues import FatalContractError, Issue, MissingCredentialError, apply_on_issue
from rivretrieve._internal.observations import ObservationRequest, ObservationResult, ReceiptMode, Receipts
from rivretrieve._internal.primitives import CacheMode
from rivretrieve._internal.registry import UnknownProviderError, _registry
from rivretrieve._internal.selection import _as_frame as _selection_as_frame
from rivretrieve._internal.selection import _EmptyReason, _require_selection, _Selection
from rivretrieve._internal.selection import _find as _selection_find
from rivretrieve._internal.selection import _from_frame as _selection_from_frame
from rivretrieve._internal.selection import _pick as _selection_pick
from rivretrieve._internal.selection import _station_frame as _selection_station_frame
from rivretrieve._internal.selection import _station_keys as _selection_station_keys
from rivretrieve._internal.source_series import SeriesScope, SourceSeries
from rivretrieve._internal.station_map import StationMap
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.transport import (
    AuthenticatedTransport,
    AuthenticationCapability,
    CredentialHeader,
    HttpClient,
    Transport,
    _SystemClock,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rivretrieve._internal.engine import FetchWindow
    from rivretrieve._internal.primitives import OnIssue
    from rivretrieve._internal.providers.registration import PublicArchiveAccess

_DEFAULT_PROVIDER_REGISTRATION_ENABLED = True


def describe(provider: str) -> dict[str, object]:
    """Read one provider's packaged Croissant JSON-LD descriptor offline.

    Parameters
    ----------
    provider : str
        Built-in provider identifier.

    Returns
    -------
    dict[str, object]
        Parsed descriptor with catalogue file identities, extraction rules,
        evidence relations and recorded absences. This is not an observation
        descriptor or a live inventory.

    Raises
    ------
    UnknownProviderError
        If provider is not in the built-in manifest.
    FatalContractError
        If the JSON document is not an object.
    OSError
        If the packaged descriptor cannot be read.
    json.JSONDecodeError
        If its JSON is malformed.
    """
    from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS

    if provider not in BUILTIN_PROVIDER_IDS:
        raise UnknownProviderError(provider)
    descriptor = files("rivretrieve._internal.providers").joinpath(provider, "catalogue", "croissant.json")
    document = json.loads(descriptor.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise FatalContractError(f"Catalogue descriptor for {provider} must be a JSON object")
    return document


def providers() -> pl.DataFrame:
    """List registered providers and local credential readiness.

    Returns
    -------
    polars.DataFrame
        Columns are provider_id (String), credentials (List(String)) and access
        (String). Rows are sorted by provider_id. Access is "open", "ready",
        or "missing <variable names>". It does not test source access.

    Raises
    ------
    FatalContractError
        If a shipped declaration or catalogue cannot be loaded.

    Notes
    -----
    Reads credential names from declarations and values from the process
    environment or the working directory .env file. A present environment
    variable takes precedence, including a blank value. Values are not returned.
    No source request is made.
    """
    _ensure_default_providers_registered()
    resolved = _resolve_credentials(_registry.list_provider_ids(), require_all=False)
    rows = []
    for record in _registry.iter_records():
        names = record.handle.required_credentials
        missing = tuple(name for name in names if name not in resolved[record.provider_id])
        access = "open" if not names else f"missing {', '.join(missing)}" if missing else "ready"
        rows.append((str(record.provider_id), list(names), access))
    return pl.DataFrame(
        rows,
        schema={"provider_id": pl.Utf8, "credentials": pl.List(pl.Utf8), "access": pl.Utf8},
        orient="row",
    )


def find(
    *,
    provider: str | None = None,
    station: str | None = None,
    quantity: str | None = None,
    frequency: str | None = None,
    statistic: str | None = None,
    temporal_support: str | None = None,
    day_definition: str | None = None,
    timestamp_anchor: str | None = None,
    time_zone: str | None = None,
    vertical_reference: str | None = None,
    vertical_datum: str | None = None,
    variant: str | None = None,
    series_id: str | None = None,
    on_issue: OnIssue = "warn",
) -> _Selection:
    """Search the packaged catalogues for source series that match the given filters.

    ``find`` reads the packaged catalogues only. It does not contact observation
    services, read credentials or use the observation cache. The returned
    selection records the filters as request intent together with the catalogue
    evidence known today. ``fetch`` uses that intent, so an unrestricted
    selection also includes matching series that a source response reveals later.

    Parameters
    ----------
    provider : str or None, default None
        Provider identifier, such as ``"usgs_nwis"``. None searches every
        built-in provider. ``providers()`` lists the identifiers.
    station : str or None, default None
        Station identifier as the provider publishes it. Keep identifiers as
        strings so leading zeros survive. Without ``provider``, the station is
        searched in every provider that lists it.
    quantity, frequency, statistic, temporal_support, day_definition, timestamp_anchor, time_zone, vertical_reference, vertical_datum : str or None, default None
        Exact filters on established physical facts. Quantities are
        ``"discharge"``, ``"stage"`` and ``"temperature"``. Packaged catalogues
        currently use frequencies such as ``"daily"`` and ``"hourly"`` and
        statistics such as ``"mean"``, ``"min"``, ``"max"`` and
        ``"instantaneous"``. A fact that is unknown for a series never matches
        a filter on that fact. Values are compared as exact strings and are not
        checked against a vocabulary, so a misspelled value returns an empty
        selection without an issue.
    variant, series_id : str or None, default None
        Explicit source restriction. ``variant`` matches the source's variant
        name or its published identifier. ``series_id`` matches RivRetrieve's
        internal source-series identifier, as shown by ``series``. Other
        versions of the series are never substituted.
    on_issue : {"warn", "raise", "ignore"}, default "warn"
        Handling of warning and error issues found during selection. See
        ``fetch`` for the meaning of each policy.

    Returns
    -------
    selection
        A selection to pass to ``pick``, ``series``, ``fetch``,
        ``fetch_by_provider``, ``metadata``, ``map`` or ``to_bundle``.
        It cannot be changed in place. Inspect its source series with
        ``series(selection)``.

    Raises
    ------
    UnknownProviderError
        If ``provider`` is not a built-in provider.
    UnknownStationError
        If ``station`` is not listed by the selected providers.
    ValueError
        If ``on_issue`` is not one of the accepted values, or ``provider``,
        ``station``, ``variant`` or ``series_id`` is an empty string.
    IssuePolicyError
        If ``on_issue="raise"`` and selection produced a warning issue.

    Notes
    -----
    Two issue codes can be recorded on the selection's ``issues`` for an
    explicit ``variant`` or ``series_id`` that matches no known series.
    ``selection.no_match`` means the packaged evidence establishes that nothing
    matches. ``selection.unresolved_inventory`` means the catalogue cannot tell
    whether the source publishes that series. RivRetrieve still requests an
    unresolved restriction during ``fetch``. Physical filters that match nothing
    produce an empty selection without an issue. ``fetch`` refuses such a
    selection with ``EmptySelectionError``.

    The packaged catalogue is a snapshot. It does not establish that every
    listed series has observations for a particular period.
    """
    _ensure_default_providers_registered()
    _validate_issue_policy(on_issue)
    return _selection_find(
        _registry.iter_records(),
        provider=provider,
        station=station,
        quantity=quantity,
        frequency=frequency,
        statistic=statistic,
        temporal_support=temporal_support,
        day_definition=day_definition,
        timestamp_anchor=timestamp_anchor,
        time_zone=time_zone,
        vertical_reference=vertical_reference,
        vertical_datum=vertical_datum,
        variant=variant,
        series_id=series_id,
        on_issue=on_issue,
    )


def pick(
    selection: _Selection | ObservationResult,
    *,
    provider: str | Sequence[str] | None = None,
    station: str | Sequence[str] | None = None,
    quantity: str | None = None,
    frequency: str | None = None,
    statistic: str | None = None,
    temporal_support: str | None = None,
    day_definition: str | None = None,
    timestamp_anchor: str | None = None,
    time_zone: str | None = None,
    vertical_reference: str | None = None,
    vertical_datum: str | None = None,
    variant: str | Sequence[str] | None = None,
    series_id: str | Sequence[str] | None = None,
    on_issue: OnIssue = "warn",
) -> _Selection | ObservationResult:
    """Filter a selection or a fetched result without contacting a source.

    Filters combine with the filters already held by ``selection``. A filter
    that conflicts with an existing one, such as a different quantity, leaves an
    empty selection or an empty result view.

    Parameters
    ----------
    selection : selection or ObservationResult
        Selection from ``find``, ``pick`` or ``from_bundle``, or a result from
        ``fetch``, ``fetch_by_provider``, ``pick`` or ``from_bundle``.
    provider, station, variant, series_id : str, sequence of str, or None, default None
        One identifier or a list of identifiers. A list keeps series matching
        any of its values. ``variant`` and ``series_id`` have the same meaning
        as in ``find``.
    quantity, frequency, statistic, temporal_support, day_definition, timestamp_anchor, time_zone, vertical_reference, vertical_datum : str or None, default None
        Exact filters on established physical facts, as in ``find``.
    on_issue : {"warn", "raise", "ignore"}, default "warn"
        Handling of warning and error issues relevant to the narrowed selection
        or view. See ``fetch`` for the meaning of each policy.

    Returns
    -------
    selection or ObservationResult
        The same kind of value as ``selection``.

        For a selection, the result is a new selection with the combined filters.
        Findings about explicit ``variant`` or ``series_id`` restrictions are
        recalculated for the narrowed request. Other selection issues are kept.

        For a result, the returned result keeps only observation rows whose
        series and fact segment match the combined filters. ``view_scope`` holds
        the combined filters and ``scope`` still holds the original request.
        Provenance, receipts, source-series definitions, inventories and
        outcomes are unchanged, so they can describe series and rows outside
        the view. ``issues`` keeps every original issue and adds any selection
        findings for the view. ``on_issue`` acts only on the issues relevant to
        the view.

    Raises
    ------
    TypeError
        If ``selection`` is neither a selection nor an observation result.
    UnknownProviderError
        If ``selection`` is a selection and a requested provider is not registered.
    UnknownStationError
        If ``selection`` is a selection and a requested station is not listed
        for its providers. Unknown identifiers applied to a result leave an
        empty view instead.
    ValueError
        If ``on_issue`` is invalid, or an identifier filter is an empty string.
    IssuePolicyError
        If ``on_issue="raise"`` and a relevant warning or error issue exists.
    """
    from rivretrieve._internal.selection import _intersect_scope, _selection_scope

    _validate_issue_policy(on_issue)
    filters = {
        "provider": provider,
        "station": station,
        "quantity": quantity,
        "frequency": frequency,
        "statistic": statistic,
        "temporal_support": temporal_support,
        "day_definition": day_definition,
        "timestamp_anchor": timestamp_anchor,
        "time_zone": time_zone,
        "vertical_reference": vertical_reference,
        "vertical_datum": vertical_datum,
        "variant": variant,
        "series_id": series_id,
    }
    if isinstance(selection, ObservationResult):
        scope = _intersect_scope(selection.view_scope or selection.scope, _selection_scope(**filters))
        pairs = [
            (item.series_id, facts.facts_id)
            for item in selection.source_series
            if scope.matches(item)
            for facts in item.facts
            if scope.matches_facts(facts)
        ]
        predicate = (
            pl.any_horizontal(
                [
                    (pl.col("series_id") == identifier) & (pl.col("facts_id") == facts_id)
                    for identifier, facts_id in pairs
                ]
            )
            if pairs
            else pl.lit(False)
        )
        selected = _Selection(scope=scope, known_series=selection.source_series, inventories=selection.inventories)
        from rivretrieve._internal.selection import _with_selection_diagnostics

        selected = _with_selection_diagnostics(selected, "ignore")
        current_issues = _selection_issues_for_result(selected, selection)
        result = ObservationResult(
            data=selection.data.filter(predicate),
            provenance=selection.provenance,
            receipts=selection.receipts,
            source_series=selection.source_series,
            inventories=selection.inventories,
            outcomes=selection.outcomes,
            scope=selection.scope,
            view_scope=scope,
            issues=(*selection.issues, *current_issues),
        )
        historical_issues = tuple(issue for issue in selection.issues if _issue_applies_to_view(issue, result))
        apply_on_issue((*historical_issues, *current_issues), on_issue)
        return result
    return _selection_pick(_registry.iter_records(), selection, on_issue=on_issue, **filters)


def _issue_applies_to_view(issue: Issue, result: ObservationResult) -> bool:
    """Report only view-relevant findings while retaining original acquisition history."""
    from rivretrieve._internal.selection import _intersect_scope, _selection_scope
    from rivretrieve._internal.source_series import RequestedSelector, RestrictionKind, ScopeState, SeriesScope

    scope = result.view_scope or result.scope
    if scope.state is ScopeState.EMPTY:
        return False
    if scope.provider_ids and str(result.provenance.provider_id) not in scope.provider_ids:
        return False
    if issue.provider_id is not None and scope.provider_ids and issue.provider_id not in scope.provider_ids:
        return False
    details = issue.details or {}
    for field, allowed in (("station_id", scope.station_ids), ("product_id", scope.product_ids)):
        if allowed and isinstance(details.get(field), str) and details[field] not in allowed:
            return False
    raw_selector = details.get("requested_selector")
    if raw_selector is not None:
        selector = RequestedSelector.model_validate(raw_selector)
        if selector.kind == "variant":
            scope = _intersect_scope(scope, _selection_scope(variant=selector.value))
        else:
            scope = _intersect_scope(scope, _selection_scope(series_id=selector.value))
    recorded_scope = details.get("scope")
    if issue.code.startswith("selection.") and isinstance(recorded_scope, dict):
        scope = _intersect_scope(scope, SeriesScope.model_validate(recorded_scope))
    if scope.state is ScopeState.EMPTY:
        return False
    inventory_scope = details.get("inventory_scope")
    if (
        issue.code == "source.inventory_unresolved"
        and inventory_scope is not None
        and all(details.get(field) is None for field in ("series_id", "requested_selector", "outcome_id"))
    ):
        acquired = SeriesScope.model_validate(inventory_scope)
        if acquired.restriction is RestrictionKind.ALL:
            scope = _intersect_scope(scope, acquired)
            if scope.state is ScopeState.EMPTY:
                return False
            if scope.series_ids:
                definitions = {item.series_id: item for item in result.source_series}
                coordinates = acquired.model_copy(update={"predicates": ()})
                local_ids = tuple(
                    identifier
                    for identifier in scope.series_ids
                    if identifier not in definitions or coordinates.matches(definitions[identifier])
                )
                if not local_ids:
                    return False
                scope = scope.model_copy(update={"series_ids": local_ids})
            if _finite_view_members_represented(scope, result):
                return False
    identity_scope = scope.model_copy(update={"predicates": ()})

    def could_match(definition: SourceSeries) -> bool:
        return identity_scope.matches(definition) and any(
            all(
                getattr(facts, predicate.field).state.value != "known"
                or getattr(facts, predicate.field).value == predicate.value
                for predicate in scope.predicates
            )
            for facts in definition.facts
        )

    definitions = {item.series_id: item for item in result.source_series}
    identifier = details.get("series_id")
    if isinstance(identifier, str) and identifier in definitions:
        return could_match(definitions[identifier])
    if scope.series_ids and all(identifier in definitions for identifier in scope.series_ids):
        return any(could_match(definitions[identifier]) for identifier in scope.series_ids)
    # A finding with no narrower source attribution remains relevant to the request.
    return True


def _finite_view_members_represented(scope: SeriesScope, result: ObservationResult) -> bool:
    """Positive per-member retrieval evidence does not assert exhaustive inventory."""
    from rivretrieve._internal.source_series import OutcomeStatus, RestrictionKind, ScopeState

    if scope.state is ScopeState.EMPTY or scope.restriction is not RestrictionKind.EXPLICIT:
        return False
    members = tuple(
        scope.model_copy(update={field: (value,)})
        for field in ("variants", "series_ids")
        for value in getattr(scope, field)
    )
    if not members:
        return False
    definitions = {item.series_id: item for item in result.source_series}

    def represented(member: SeriesScope) -> bool:
        for outcome in result.outcomes:
            if outcome.status not in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY):
                continue
            definition = definitions.get(outcome.series_id) if outcome.series_id is not None else None
            if definition is None or not member.matches(definition):
                continue
            if any(facts.facts_id in outcome.facts_ids and member.matches_facts(facts) for facts in definition.facts):
                return True
        return False

    return all(represented(member) for member in members)


def series(value: _Selection | ObservationResult) -> pl.DataFrame:
    """Describe each source series in a selection or result as a table.

    Parameters
    ----------
    value : selection or ObservationResult
        A selection from ``find``, ``pick`` or ``from_bundle``, or a fetched
        result. For a selection, rows describe the source series known from packaged
        evidence before retrieval. For a result, rows describe the series known
        after retrieval, including series first identified in the source
        response, together with their retrieval outcomes.

    Returns
    -------
    polars.DataFrame
        One row per source series and physical-fact segment that matches the
        selection or view. The schema is fixed and shown under "Series
        inspection frame" in the API reference. Rows sort by ``provider_id``,
        ``station_id``, ``product_id``, ``series_id`` and ``facts_id``.

        Columns form these groups:

        - Identity: ``provider_id``, ``station_id``, ``product_id`` (an internal
          access route), ``series_id`` and ``facts_id`` join rows to
          observations and outcomes. ``identity_namespace``, ``published_id``,
          ``description``, ``identity_origin`` (``catalogue``, ``response`` or
          ``mapping``), ``identity_evidence`` and ``variant`` preserve the
          agency's own identity. A null ``description`` means no
          description was recorded for the series.
        - Request: ``requested_variants`` and ``requested_series_ids`` repeat
          explicit restrictions. ``requested_selector_kind`` and
          ``requested_selector_value`` are filled only on rows for an outcome
          that has no concrete series identity.
        - Matching and admission: ``physical_match`` is ``matched``,
          ``not_matched`` or ``unestablished``. ``admission`` is ``supported``
          when established quantity and unit facts allow numeric rows,
          otherwise ``unsupported`` with ``admission_reason``.
        - Units: ``source_unit`` with ``source_unit_state`` and
          ``source_unit_evidence``, ``normalized_unit``, and ``unit``, the
          harmonised unit of returned values (m3/s, m or degC). ``unit`` is null
          for unsupported series.
        - Physical facts: ``quantity``, ``frequency``, ``statistic``,
          ``temporal_support``, ``day_definition``, ``timestamp_anchor``,
          ``time_zone``, ``vertical_reference`` and ``vertical_datum``. Each has
          a ``<fact>_state`` column (``known``, ``source_silent`` or
          ``not_established``) and a ``<fact>_evidence`` list. The value is
          null unless the state is ``known``.
        - Inventory: ``inventory_ids``, ``inventory_scope`` and
          ``inventory_windows`` (JSON text), ``inventory_vintage`` (ISO
          acquisition time or catalogue check date) and ``inventory_status``
          (``complete``, ``incomplete`` or ``unresolved``). Inventory describes
          what is known about which series exist. It is not observation
          coverage.
        - Outcomes: ``outcomes`` (statuses such as ``success``, ``empty`` or
          ``failed``), ``outcome_windows`` (JSON text) and ``outcome_reasons``.
          These lists are empty for a selection.

        For a result, a series with a ``failed``, ``unsupported`` or
        ``unresolved`` outcome keeps its row even if it lies outside the
        physical filters. An outcome without a concrete series identity adds a
        row with null identity and fact columns and ``physical_match`` set to
        ``unestablished``.

    Raises
    ------
    TypeError
        If ``value`` is neither a selection nor an observation result.

    Notes
    -----
    A row with ``admission`` equal to ``unsupported`` is still listed. Retrieval
    returns no numeric observation rows for such a series.
    """
    from rivretrieve._internal.selection import _series_frame

    if isinstance(value, ObservationResult):
        return _series_frame(
            value.source_series,
            value.view_scope or value.scope,
            value.inventories,
            value.outcomes,
            provider_id=str(value.provenance.provider_id),
        )
    return _selection_as_frame(value)


def as_frame(selection: _Selection) -> pl.DataFrame:
    """Return the source-series table for a selection, the same table as ``series``.

    Selecting rows from the table does not change the selection. Pass chosen
    identifiers back to ``pick`` instead. Use ``to_bundle`` to save a selection
    without losing information.

    Raises
    ------
    TypeError
        If ``selection`` is not a selection. Use ``series`` for a result.
    """
    return _selection_as_frame(selection)


def from_frame(frame: pl.DataFrame) -> _Selection:
    """Refuse to rebuild a selection from a table; use ``from_bundle`` instead.

    Every call raises ``ValueError``. An inspection frame omits request intent,
    inventory state and evidence, so it cannot be turned back into a selection.
    Use ``to_bundle`` and ``from_bundle`` to save and restore a selection.

    Raises
    ------
    ValueError
        Always.
    """
    return _selection_from_frame((), frame)


def to_bundle(value: _Selection | ObservationResult) -> bytes:
    """Save a selection or result as bytes that ``from_bundle`` can restore.

    Parameters
    ----------
    value : selection or ObservationResult
        Selection from ``find``, ``pick`` or ``from_bundle``, or a result to
        export, including a result view from ``pick``.

    Returns
    -------
    bytes
        ZIP archive in bundle format version 2. Write the bytes to a file to
        keep them. A selection bundle holds its request intent, source-series
        definitions, inventories, issues, station locations, catalogue evidence
        and empty-selection reason. A result bundle also holds the observation
        rows as Parquet, the outcomes, the view scope, provenance and any
        retained receipt bytes. Nothing is read from or written to disk.

    Raises
    ------
    TypeError
        If ``value`` is neither a selection nor an observation result.
    """
    from rivretrieve._internal.export_bundle import encode_bundle

    return encode_bundle(value)


def from_bundle(content: bytes) -> _Selection | ObservationResult:
    """Restore a selection or result saved by ``to_bundle``.

    Parameters
    ----------
    content : bytes
        Bytes produced by ``to_bundle``.

    Returns
    -------
    selection or ObservationResult
        The kind of value that was exported. Identities, physical facts,
        inventories, issues and, for results, observations, outcomes,
        provenance and receipts come from the bundle. The current packaged
        catalogue is not consulted, so a restored selection keeps the evidence
        it had when exported.

    Raises
    ------
    TypeError
        If ``content`` is not ``bytes``.
    ValueError
        If the bytes are not a bundle, the bundle version is not 2, or its
        contents fail validation. Bundles from other format versions must be
        exported again or re-fetched.
    ObservationDataSchemaError
        If a result bundle's observation rows contradict its source-series
        definitions or the observation frame schema, its outcomes contradict
        those definitions, or its receipt provider differs from its
        provenance provider.
    """
    from rivretrieve._internal.export_bundle import decode_bundle

    return decode_bundle(content)


def _validate_issue_policy(on_issue: OnIssue) -> None:
    if on_issue not in ("raise", "warn", "ignore"):
        raise ValueError("on_issue must be raise, warn or ignore")


def metadata(selection: _Selection, *, view: str = "summary") -> pl.DataFrame:
    """Read selected gauges' packaged station metadata offline.

    Parameters
    ----------
    selection : selection
        Selection from find, pick or from_bundle. Multiple providers and series
        are accepted without repeating gauges or their attributes.
    view : {"summary", "source"}, default "summary"
        Summary returns one row per gauge with canonical geometry, a scalar
        station name, and aligned lists of water-body, area and elevation fields.
        Source returns separate source attributes with exact values and support.

    Returns
    -------
    polars.DataFrame
        Both views retain provider_id and station_id as strings. Summary
        station_name is the verbatim name when exactly one distinct nonblank
        supported name exists. It is null when none or several exist; the source
        view distinguishes these cases. Equal names from separate fields count
        as one name. Latitude, longitude
        and crs preserve the canonical catalogue's values and unknowns,
        independently of locations retained in the selection.

        Summary list columns are water_body_name_field, water_body_name_value;
        drainage_area_field, drainage_area_value, drainage_area_unit; and
        elevation_field, elevation_value, elevation_unit, elevation_datum.
        All have List(String) dtype. Within each role, positions align and sort
        by exact native field name, with source_scope breaking ties without
        preference. Identical field names from different source scopes remain
        separate entries. Water-body names are
        decoded strings. Area and elevation values remain JSON scalar text:
        json.loads distinguishes numbers from numeric-looking source strings.
        In the supported Japanese, Bosnian and Swiss quantity fields, complete
        numeric strings with explicit units keep their numeric text separately
        from the unit. For example, '"142.00km2"' becomes '"142.00"' with unit
        'km2'. Numeric spelling is preserved and still needs parsing for arithmetic.
        In USGS alt_va, leading spaces, tabs and nonbreaking spaces are removed
        only from complete numeric strings: '" 0.00"' becomes '"0.00"', still a
        JSON string with unchanged numeric spelling, unit and datum.
        Qualified or unrecognised text stays unchanged. The source view always
        retains the exact original scalar.
        Units and datum labels or codes are plain strings. Unknowns remain null.
        No exposed fields gives null list cells; exposed null fields give named
        entries with null values. Blanks, whitespace, equal values in different
        fields, placeholders and zero values are retained.

        Source columns are provider_id, station_id, source_field, source_scope, source_value,
        source_dtype, source_unit, state, attribute_role, support_fact,
        source_datum, source_datum_field, source_datum_dtype and datum_support_fact.
        All are String except state and attribute_role, which are Enums.
        Decode non-null source_value with json.loads to recover the exact scalar.
        State is value, source_null (an exposed field with null), or no_metadata
        (no exposed field for this role). The latter has null source and support
        columns. Roles are station_name, water_body_name, drainage_area and
        elevation. Source scope identifies the source collection or entity when
        native field names overlap; it is null for an unscoped native projection.
        Datum fields carry the published label or code and its
        association support. Native datum fields retain their name and dtype,
        including when null; documented datum declarations have no native field
        or dtype. No inferred unit, preferred field or conversion is applied.
        Empty selections retain the chosen view's schema.

    Raises
    ------
    TypeError
        If selection is not a RivRetrieve selection.
    ValueError
        If view is not summary or source.
    FatalContractError
        If packaged metadata violates its schema, value states or gauge scope.
    OSError
        If packaged metadata cannot be read.

    Notes
    -----
    No observations, credentials, cache or network access are needed. Gauge
    scope is independent of observation admission and map eligibility. Metadata
    does not establish observation availability. Neither absence state means
    zero or that an agency publishes no metadata elsewhere. See
    docs/station-metadata.md for interpretation and examples.
    """
    from rivretrieve._internal.station_metadata import (
        SOURCE_METADATA_SCHEMA,
        STATION_METADATA_SCHEMA,
        source_metadata_frame,
        station_metadata_frame,
    )

    if view not in ("summary", "source"):
        raise ValueError("view must be summary or source")
    stations = _selection_station_keys(selection)
    if stations.is_empty():
        return pl.DataFrame(schema=SOURCE_METADATA_SCHEMA if view == "source" else STATION_METADATA_SCHEMA)
    frames = []
    locations = []
    for provider in stations["provider_id"].unique().sort():
        catalogue = files("rivretrieve._internal.providers").joinpath(provider, "catalogue")
        with catalogue.joinpath("station_metadata.parquet").open("rb") as stream:
            packaged = pl.read_parquet(stream)
        selected = stations.filter(pl.col("provider_id") == provider)
        frames.append(source_metadata_frame(selected, packaged))
        if view == "summary":
            with catalogue.joinpath("stations.parquet").open("rb") as stream:
                canonical = pl.read_parquet(stream)
            locations.append(canonical.join(selected, on=["provider_id", "station_id"], how="semi"))
    source = pl.concat(frames)
    if view == "source":
        return source
    return station_metadata_frame(stations, source, pl.concat(locations))


def map(selection: _Selection) -> object:
    """Render selected stations without narrowing the selection.

    Parameters
    ----------
    selection : selection
        Selection from find, pick or from_bundle. Each station is shown once.

    Returns
    -------
    folium.Map
        Station markers with identity, coordinates and CRS in their popups.
        Unknown CRS markers are orange and drawn as if EPSG:4326. Established
        CRS markers are blue. The rendering does not rewrite catalogue facts.

    Raises
    ------
    TypeError
        If selection is not a RivRetrieve selection.
    MissingOptionalDependencyError
        If folium is not installed. Install the rivretrieve[map] extra.
    """
    return StationMap(_selection_station_frame(selection)).render()


_provider_lookup = _registry.get


class EmptySelectionError(FatalContractError):
    """Raised by ``fetch`` when a selection routes to no station and access route.

    ``reason.code`` is ``no_match`` when the packaged evidence establishes that
    nothing matches, or ``unresolved_inventory`` when it cannot settle the
    request. ``reason`` also names the requested providers, stations and
    access routes. No source request is made.
    """

    def __init__(self, reason: _EmptyReason) -> None:
        self.reason = reason
        super().__init__(
            "fetch() cannot retrieve an empty selection: "
            f"code={reason.code!r}, provider_ids={reason.provider_ids!r}, "
            f"station_ids={reason.station_ids!r}, product_ids={reason.product_ids!r}, "
            f"published_products={reason.published_products!r}"
        )


class MultiProviderSelectionError(FatalContractError):
    """Raised by ``fetch`` when a selection routes to several providers.

    ``provider_ids`` names them. Use ``fetch_by_provider`` or narrow the
    selection with ``pick(selection, provider=...)``. No source request is made.
    """

    def __init__(self, provider_ids: tuple[str, ...]) -> None:
        self.provider_ids = provider_ids
        super().__init__(
            f"fetch() requires one provider; selection contains providers {provider_ids!r}. "
            "Use fetch_by_provider() for multi-provider selections."
        )


def fetch(
    selection: _Selection,
    *,
    start: object = None,
    end: object = None,
    receipts: bool = False,
    cache: CacheMode = "bypass",
    on_issue: OnIssue = "warn",
) -> ObservationResult:
    """Download observations for a selection whose series come from one provider.

    ``fetch`` requests each station and access route in the selection and
    returns every series whose physical facts and identity match the
    selection's filters. An unrestricted selection includes matching series
    that are first identified in the source response. An explicit ``variant``
    or ``series_id`` restriction returns only those series, even when the
    catalogue could not settle whether they exist.

    Parameters
    ----------
    selection : selection
        Selection from ``find``, ``pick`` or ``from_bundle``. It must route to
        exactly one provider. Use ``fetch_by_provider`` for several providers.
    start : str or datetime.datetime
        Required first time label to include, on the source's own wall clock.
        Accepts an ISO date (``"2023-01-01"``, meaning midnight), an ISO
        date-time without a zone (``"2023-01-01T06:00"``) or a naive
        ``datetime``. Python ``date`` objects and values with a time zone are
        refused.
    end : str, datetime.datetime or None, default None
        Last time label to include, in the same forms as ``start``. A date-only
        end includes that whole date. None means the final instant of the
        caller machine's current local date. An end in the future is kept and
        adds an ``info`` issue with code ``request.future_end``.
    receipts : bool, default False
        If True, keep the source bytes behind the returned rows in
        ``result.receipts``. See ``ReceiptEntry``.
    cache : {"bypass", "reuse", "refresh"}, default "bypass"
        Local observation cache behaviour for live providers. ``bypass`` fetches
        without reading or writing the cache. ``reuse`` decides separately for
        each station and access route. It serves cached observations where the
        cache knows the matching series and successful earlier retrievals
        cover the requested interval, and fetches the whole requested interval
        again for each station and access route that is not covered.
        ``refresh`` requests the interval again, and a successful answer
        replaces the cached answer. If a request fails or its answer cannot be
        used, rows cached by earlier successful retrievals are still returned
        with the new issue and its ``failed`` or ``unsupported`` outcome. The
        earlier ``success`` or ``empty`` outcomes for those rows are also
        returned, and ``provenance.served_intervals`` shows their original
        retrieval times. The same applies when ``reuse`` has to fetch again.
        Successful answers from ``reuse`` and ``refresh`` are written to the
        cache. For a bulk provider, ``bypass`` and ``reuse`` both read its
        compiled store, and ``refresh`` is refused.
    on_issue : {"warn", "raise", "ignore"}, default "warn"
        Handling of ``warning`` and ``error`` issues after retrieval. ``warn``
        emits one ``RuntimeWarning`` per issue and returns the result.
        ``raise`` raises ``IssuePolicyError`` carrying those issues. ``ignore``
        returns the result without notification. ``info`` issues never trigger
        the policy. Every issue stays in ``result.issues`` when a result is
        returned.

    Returns
    -------
    ObservationResult
        Observation rows in ``data`` together with ``source_series``,
        ``inventories``, ``outcomes``, ``provenance``, ``receipts`` and
        ``issues``. Values are converted to m3/s for discharge, m for stage
        and degC for water temperature, and ``source_unit`` keeps the published
        unit. Timestamps stay on the source's wall clock with a per-row
        ``time_zone``, which can be ``unknown``. Rows are clipped to the
        requested window by calendar date or by source timestamp, as recorded
        in each fact segment's ``clipping_axis``.

        A source failure for one station or access route becomes an issue and a
        ``failed`` outcome, and independent series still return their rows. Some
        providers request a series in independent parts, such as monthly files.
        A failed part is reported for its own interval: the issue's
        ``details["window"]`` holds the source interval, and the ``failed``
        outcome covers its overlap with the requested window, or the whole
        source interval when the part lies outside that window. Rows from the
        other parts are kept.

        Failed HTTP requests produce ``source.request_failed`` (error) or, for
        HTTP 404, ``source.http_not_found`` (warning). Their ``details`` keep
        the station, product, request URL, attempt count, status code and
        failure reason.

        A part requested only as padding, wholly outside the requested dates,
        produces no outcome unless its source request fails. A failed padding
        request is reported with an issue and a ``failed`` outcome over its
        source interval, except an HTTP 404 that the provider declares to mean
        no stored observations for that interval. That 404 produces no issue
        and no outcome, and its call stays in ``provenance.calls_made``. A
        padding response that cannot be used, such as a malformed one, is
        reported with an issue only.

        When every request fails, the issues and outcomes explain why. ``data``
        is then empty, except with ``cache="reuse"`` or ``cache="refresh"``
        when the cache holds rows from earlier successful retrievals. Those rows
        and their earlier outcomes are returned alongside the failures, as
        described for ``cache``. A null ``value`` means the source gives no
        value for that time, and the row is still returned. An ``empty``
        outcome means no rows were found for its series and interval. A failed
        request is reported through issues and ``failed`` outcomes.

    Raises
    ------
    TypeError
        If ``selection`` is not a selection.
    ValueError
        If ``cache`` or ``on_issue`` is invalid, or ``RIVRETRIEVE_CACHE_DIR``
        is set to a blank value.
    EmptySelectionError
        If the selection routes to no provider, station and access route.
    MultiProviderSelectionError
        If the selection routes to more than one provider.
    InvalidObservationRequestError
        If ``start`` is missing, either endpoint has an unsupported type,
        cannot be parsed or has a time zone, or ``start`` is after ``end``.
    MissingCredentialError
        If a required credential is not set. No source request is made.
    ObservationsUnavailableError
        If the provider only publishes a catalogue, such as ``za_dws``.
    FatalContractError
        If ``cache="refresh"`` is requested for a bulk provider, before any
        transfer, or if a provider stage breaks its output contract. These
        errors are raised whatever ``on_issue`` is.
    ObservationStoreRefusedError
        If an existing local store is malformed or incompatible.
    IssuePolicyError
        If ``on_issue="raise"`` and the result has a warning or error issue.

    Notes
    -----
    Live providers are contacted over the network unless ``reuse`` finds every
    requested station and access route covered in the cache. Requests that are
    safe to repeat are retried for transient failures. The usage guide
    describes the retry limits.

    Credentials are read from the process environment, then from a ``.env``
    file in the working directory. They are required even when the answer
    comes from the cache. The cache location is ``RIVRETRIEVE_CACHE_DIR``,
    read the same way, or the platform's user cache directory.

    A bulk provider without a compiled store returns an empty result with a
    ``bulk.store_missing`` warning and an ``unresolved`` outcome. ``fetch``
    never starts a national download. Call ``download`` to create the store.

    Examples
    --------
    This example contacts the USGS service. The output shown was checked
    against a recorded USGS response.

    >>> import rivretrieve as rr
    >>> gauge = rr.find(
    ...     provider="usgs_nwis", station="07374000",
    ...     quantity="discharge", frequency="daily", statistic="mean",
    ... )
    >>> result = rr.fetch(gauge, start="2023-01-01", end="2023-01-01")  # doctest: +SKIP
    >>> result.data.select("time", "time_zone", "source_unit", "unit", "value").rows()  # doctest: +SKIP
    [(datetime.datetime(2023, 1, 1, 0, 0), 'unknown', 'ft^3/s', 'm3/s', 10562.183778816001)]
    >>> [outcome.status.value for outcome in result.outcomes]  # doctest: +SKIP
    ['success']
    """
    cache = _parse_cache_mode(cache)
    _validate_issue_policy(on_issue)
    _require_selection(selection)
    partitions = _selection_routes(selection)
    if not partitions:
        if selection.empty_reason is None:
            raise FatalContractError("Selection has no executable source scope")
        raise EmptySelectionError(selection.empty_reason)
    provider_ids = tuple(partitions)
    if len(provider_ids) != 1:
        raise MultiProviderSelectionError(provider_ids)
    routes = tuple(item for values in partitions.values() for item in values)
    normalized_start, normalized_end, future_local_date = _normalize_window(routes, start=start, end=end)
    _require_cache_mode_available(provider_ids, cache)
    credentials = _resolve_credentials(provider_ids, require_all=True)
    provider_id = provider_ids[0]
    result = _fetch_provider_series(
        provider_id,
        partitions[provider_id],
        selection=selection,
        start=normalized_start,
        end=normalized_end,
        future_local_date=future_local_date,
        credentials=credentials[provider_id],
        receipts=ReceiptMode.INCLUDE if receipts else ReceiptMode.OMIT,
        cache=cache,
        store=_resolve_store_root(provider_id, _registry.get(provider_id)._store_root),
        on_issue="ignore",
    )
    result = result.model_copy(update={"issues": (*_selection_issues_for_result(selection, result), *result.issues)})
    apply_on_issue(result.issues, on_issue)
    return result


def fetch_by_provider(
    selection: _Selection,
    *,
    start: object = None,
    end: object = None,
    receipts: bool = False,
    cache: CacheMode = "bypass",
    on_issue: OnIssue = "warn",
) -> dict[str, ObservationResult]:
    """Download observations for a multi-provider selection, one result per provider.

    Parameters are the same as for ``fetch``. The selection can route to any
    number of providers.

    Returns
    -------
    dict[str, ObservationResult]
        One result per routed provider, keyed by provider identifier. Each
        result has the same contents as a ``fetch`` result for that provider.
        An empty selection returns an empty dictionary after applying
        ``on_issue`` to the selection's issues.

    Raises
    ------
    MissingCredentialError
        If any selected provider lacks a required credential. Credentials for
        every provider are checked before any provider is contacted.
    FatalContractError
        If ``cache="refresh"`` includes a bulk provider, before any provider is
        contacted, or if a provider breaks a stage contract.
    IssuePolicyError
        If ``on_issue="raise"`` and any result has a warning or error issue.
        The policy is applied once, after every provider has been retrieved.

    Notes
    -----
    Providers are retrieved one after another. Source failures stay inside the
    affected provider's result as issues and outcomes. An exception raised
    while retrieving one provider stops the call, and results already
    retrieved for other providers are not returned. The other exceptions
    listed for ``fetch``, apart from ``EmptySelectionError`` and
    ``MultiProviderSelectionError``, can also be raised.
    """
    cache = _parse_cache_mode(cache)
    _validate_issue_policy(on_issue)
    _require_selection(selection)
    partitions = _selection_routes(selection)
    if not partitions:
        apply_on_issue(selection.issues, on_issue)
        return {}
    routes = tuple(item for values in partitions.values() for item in values)
    normalized_start, normalized_end, future_local_date = _normalize_window(routes, start=start, end=end)
    provider_ids = tuple(partitions)
    _require_cache_mode_available(provider_ids, cache)
    credentials = _resolve_credentials(provider_ids, require_all=True)
    results = {}
    for provider_id, members in partitions.items():
        result = _fetch_provider_series(
            provider_id,
            members,
            selection=selection,
            start=normalized_start,
            end=normalized_end,
            future_local_date=future_local_date,
            credentials=credentials[provider_id],
            receipts=ReceiptMode.INCLUDE if receipts else ReceiptMode.OMIT,
            cache=cache,
            store=_resolve_store_root(provider_id, _registry.get(provider_id)._store_root),
            on_issue="ignore",
        )
        results[provider_id] = result.model_copy(
            update={"issues": (*_selection_issues_for_result(selection, result), *result.issues)}
        )
    definitions = tuple(item for result in results.values() for item in result.source_series)
    results = {
        provider_id: _reconcile_selector_searches(result, definitions) for provider_id, result in results.items()
    }
    apply_on_issue(tuple(issue for result in results.values() for issue in result.issues), on_issue)
    return results


def _reconcile_selector_searches(result: ObservationResult, definitions: tuple[SourceSeries, ...]) -> ObservationResult:
    """A globally identified series is not missing from an unrelated search coordinate."""
    from rivretrieve._internal.source_series import RequestedSelector

    by_identity: dict[str, SourceSeries] = {}
    for definition in definitions:
        existing = by_identity.get(definition.series_id)
        if existing is not None and (existing.provider_id, existing.station_id, existing.product_id) != (
            definition.provider_id,
            definition.station_id,
            definition.product_id,
        ):
            raise FatalContractError("A global source-series identity has conflicting coordinates")
        by_identity[definition.series_id] = definition
    excluded = set()
    for outcome in result.outcomes:
        selector = outcome.requested_selector
        if outcome.series_id is not None or selector is None or selector.kind != "series_id":
            continue
        if outcome.status.value not in ("no_match", "unresolved"):
            continue
        if outcome.calls or outcome.facts_ids or outcome.retrieved_at is not None:
            continue
        definition = by_identity.get(selector.value)
        if definition is not None and (definition.provider_id, definition.station_id, definition.product_id) != (
            str(result.provenance.provider_id),
            outcome.station_id,
            outcome.product_id,
        ):
            excluded.add(outcome.outcome_id)

    def relevant(issue: Issue) -> bool:
        details = issue.details or {}
        linked_outcome = details.get("outcome_id")
        if isinstance(linked_outcome, str) and linked_outcome in excluded:
            return False
        # Offline discovery findings are scoped to the relevant provider result,
        # not copied as failures onto providers that cannot own the resolved ID.
        raw_selector = details.get("requested_selector")
        if issue.code in ("selection.no_match", "selection.unresolved_inventory") and raw_selector is not None:
            selector = RequestedSelector.model_validate(raw_selector)
            definition = by_identity.get(selector.value) if selector.kind == "series_id" else None
            if definition is not None and definition.provider_id != str(result.provenance.provider_id):
                return False
        return True

    return result.model_copy(
        update={
            "outcomes": tuple(item for item in result.outcomes if item.outcome_id not in excluded),
            "issues": tuple(item for item in result.issues if relevant(item)),
        }
    )


def _selection_issues_for_result(selection: _Selection, result: ObservationResult) -> tuple[Issue, ...]:
    """Settle each discovery restriction independently from its acquired evidence."""
    from rivretrieve._internal.source_series import SeriesScope

    def settled(issue: Issue) -> bool:
        details = issue.details or {}
        recorded_scope = details.get("scope")
        scope = SeriesScope.model_validate(recorded_scope) if isinstance(recorded_scope, dict) else selection.scope
        if any(scope.matches(item) for item in result.source_series):
            return True
        identity_scope = scope.model_copy(update={"predicates": ()})
        identities = {item.series_id for item in result.source_series if identity_scope.matches(item)}
        selector = details.get("requested_selector")
        for outcome in result.outcomes:
            if outcome.status.value == "unresolved":
                continue
            if outcome.series_id in identities:
                return True
            if (
                isinstance(selector, dict)
                and outcome.requested_selector is not None
                and outcome.requested_selector.model_dump(mode="json") == selector
            ):
                return True
        return False

    return tuple(
        issue.model_copy(
            update={
                "severity": "info",
                "code": "selection.inventory_resolved",
                "message": "The explicit source restriction was unresolved during offline discovery and was settled by acquisition.",
                "details": {"discovery_issue": issue.model_dump(mode="json")},
            }
        )
        if issue.code == "selection.unresolved_inventory" and settled(issue)
        else issue
        for issue in selection.issues
    )


def _selection_routes(selection: _Selection) -> dict[str, tuple[SourceSeries, ...]]:
    from rivretrieve._internal.source_series import RestrictionKind, ScopeState

    if selection.scope.state is ScopeState.EMPTY:
        return {}
    # Physical and station scope route acquisition. Explicit response-owned IDs may
    # be absent from the catalogue and therefore cannot remove their acquisition route.
    route_scope = selection.scope.model_copy(
        update={"restriction": RestrictionKind.ALL, "variants": (), "series_ids": ()}
    )
    candidates = tuple(item for item in selection.known_series if route_scope.matches(item))
    if selection.scope.restriction is RestrictionKind.EXPLICIT:
        identities_resolved = all(
            any(item.series_id == identifier for item in candidates) for identifier in selection.scope.series_ids
        ) and all(
            any(item.variant == variant or item.identity.published_id == variant for item in candidates)
            for variant in selection.scope.variants
        )
        if identities_resolved:
            candidates = tuple(item for item in candidates if selection.scope.matches(item))
    return _partition_by_provider(candidates)


def _normalize_window(
    series: tuple[SourceSeries, ...],
    *,
    start: object,
    end: object,
) -> tuple[datetime, datetime, date | None]:
    """public window normalization : InputEndpoints × LocalDate → RequestedWindow × FutureFlag."""
    local_date = date.today()
    normalized_end_input = local_date.isoformat() if end is None else end
    representative = series[0]
    request = ObservationRequest.from_inputs(
        provider_id=representative.provider_id,
        stations=(representative.station_id,),
        products=(representative.product_id,),
        start=start,
        end=normalized_end_input,
    )
    local_day_end = datetime.combine(local_date, time.max)
    future_local_date = local_date if datetime.fromisoformat(request.end.isoformat()) > local_day_end else None
    return (
        datetime.fromisoformat(request.start.isoformat()),
        datetime.fromisoformat(request.end.isoformat()),
        future_local_date,
    )


def _parse_cache_mode(value: object) -> CacheMode:
    if not isinstance(value, str) or value not in ("bypass", "reuse", "refresh"):
        raise ValueError("cache must be 'bypass', 'reuse', or 'refresh'")
    return cast(CacheMode, value)


def _require_cache_mode_available(provider_ids: tuple[str, ...], cache: CacheMode) -> None:
    if cache == "refresh":
        for provider_id in provider_ids:
            if _registry.get(provider_id)._store_config is not None:
                raise FatalContractError(
                    f"Provider {provider_id} uses a compiled store; refresh requires "
                    f'rivretrieve.download("{provider_id}"). No transfer was started.'
                )


def _resolve_store_root(provider_id: str, registered: StoreRoot | None) -> StoreRoot:
    """store location : ProviderId × RegisteredStore × Environment × WorkingDotenv → StoreRoot."""
    name = "RIVRETRIEVE_CACHE_DIR"
    dotenv = dotenv_values(Path.cwd() / ".env")
    value = os.environ[name] if name in os.environ else dotenv.get(name)
    if value is not None:
        if not value.strip():
            raise ValueError("RIVRETRIEVE_CACHE_DIR must name a non-empty cache directory")
        root = Path(value).expanduser().resolve()
        store = root / provider_id / "store"
    elif registered is not None:
        store = Path(registered)
    else:
        store = Path(user_cache_dir("rivretrieve")).resolve() / provider_id / "store"
    if store.parent.is_symlink():
        raise FatalContractError(f'Managed provider directory must not be a symlink: "{store.parent}"')
    return StoreRoot(store)


def _resolve_credentials(
    provider_ids: tuple[str, ...] | list[str],
    *,
    require_all: bool,
) -> dict[str, dict[str, str]]:
    """credential resolution : ProviderDeclarations × Environment × WorkingDotenv → ProviderCredentialValues."""
    dotenv = dotenv_values(Path.cwd() / ".env")
    resolved: dict[str, dict[str, str]] = {}
    missing: dict[str, tuple[str, ...]] = {}
    for provider_id in provider_ids:
        handle = _registry.get(provider_id)
        names = (*handle.required_credentials, *handle.optional_credentials)
        provider_values: dict[str, str] = {}
        for name in names:
            environment_value = os.environ.get(name)
            file_value = dotenv.get(name)
            value: str | None = None
            if name in os.environ:
                if environment_value is not None and environment_value.strip():
                    value = environment_value
            elif isinstance(file_value, str) and file_value.strip():
                value = file_value
            if value is not None:
                provider_values[name] = value
        resolved[provider_id] = provider_values
        absent = tuple(name for name in handle.required_credentials if name not in provider_values)
        if absent:
            missing[provider_id] = absent
    if require_all and missing:
        raise MissingCredentialError(missing)
    return resolved


def _credentialed_transport(provider_id: str, values: dict[str, str]) -> Transport:
    """credential transport : ProviderCredentialValues × (HeaderBindings | CredentialExchangeBinding) → Transport."""
    base = HttpClient()
    handle = _registry.get(provider_id)
    exchange = handle.credential_exchange
    if exchange is not None:
        headers = tuple(
            CredentialHeader(binding.header, values[binding.variable], binding.origins)
            for binding in exchange.credential_headers
            if binding.variable in values
        )
        if not headers:
            return base
        return CredentialExchangeTransport(
            base,
            headers,
            exchange.spec,
            _SystemClock(),
        )
    bindings = tuple(binding for binding in handle.credential_headers if binding.variable in values)
    if not bindings:
        return base
    return AuthenticatedTransport(
        base,
        tuple(CredentialHeader(binding.header, values[binding.variable], binding.origins) for binding in bindings),
    )


def _public_archive_transport(
    base: Transport, access: PublicArchiveAccess, fetch_window: FetchWindow, now: datetime
) -> Transport:
    """Resolve declared public archive access using engine-padded UTC source bounds."""
    if isinstance(base, AuthenticationCapability) and base.can_authenticate(access.endpoint):
        return base
    start = datetime.fromisoformat(fetch_window.start.isoformat()).replace(tzinfo=UTC)
    if start >= now - access.recent_horizon:
        return base
    return AuthenticatedTransport(base, (access.credential,))


def _partition_by_provider(series: tuple[SourceSeries, ...]) -> dict[str, tuple[SourceSeries, ...]]:
    partitions: dict[str, list[SourceSeries]] = {}
    for selected_series in series:
        partitions.setdefault(selected_series.provider_id, []).append(selected_series)
    return {provider_id: tuple(rows) for provider_id, rows in partitions.items()}


def _fetch_provider_series(
    provider_id: str,
    series: tuple[SourceSeries, ...],
    *,
    selection: _Selection,
    start: datetime,
    end: datetime,
    future_local_date: date | None,
    credentials: dict[str, str],
    receipts: ReceiptMode,
    cache: CacheMode,
    store: StoreRoot,
    on_issue: OnIssue,
) -> ObservationResult:
    handle = _provider_lookup(provider_id)
    by_station: dict[str, list[str]] = {}
    for selected_series in series:
        product_ids = by_station.setdefault(selected_series.station_id, [])
        if selected_series.product_id not in product_ids:
            product_ids.append(selected_series.product_id)
    transport = _credentialed_transport(provider_id, credentials)
    if handle.public_archive_access is not None:
        from rivretrieve._internal.coverage import RequestedInterval
        from rivretrieve._internal.driver import _padded_interval

        transport = _public_archive_transport(
            transport,
            handle.public_archive_access,
            _padded_interval(RequestedInterval(start, end)),
            _SystemClock().utcnow(),
        )
    results = tuple(
        handle.observations(
            stations=station_id,
            products=tuple(product_ids),
            start=start,
            end=end,
            on_issue="ignore",
            receipts=receipts,
            transport=transport,
            cache=cache,
            store=store,
            scope=selection.scope.model_copy(update={"provider_ids": (provider_id,)}),
            known_series=tuple(item for item in selection.known_series if item.provider_id == provider_id),
            inventories=tuple(
                item
                for item in selection.inventories
                if not item.scope.provider_ids or provider_id in item.scope.provider_ids
            ),
        )
        for station_id, product_ids in by_station.items()
    )
    result = _merge_provider_results(results, series)
    result = _reconcile_selector_searches(result, result.source_series)
    if future_local_date is not None:
        future_issue = Issue(
            severity="info",
            code="request.future_end",
            message=(
                f"Requested window for provider {provider_id} extends past the caller's local date "
                f"{future_local_date.isoformat()}; the requested end was kept unchanged."
            ),
            details={"requested_end": end.isoformat(), "local_date": future_local_date.isoformat()},
            provider_id=handle.provider_id,
        )
        result = result.model_copy(update={"issues": (*result.issues, future_issue)})
    apply_on_issue(result.issues, on_issue)
    return result


def _merge_provider_results(
    results: tuple[ObservationResult, ...],
    series: tuple[SourceSeries, ...],
) -> ObservationResult:
    """provider result merge : NonEmptyTuple[ObservationResult] × SelectedSeries → ObservationResult"""
    if not results:
        raise FatalContractError("Provider result merge requires at least one result")

    first = results[0]
    request = first.provenance.request
    if request is None or "start" not in request or "end" not in request:
        raise FatalContractError("Observation provenance must retain the normalized requested window")
    merged_request = {
        "scope": first.scope.model_dump(mode="json"),
        "series": [
            {
                "station_id": selected_series.station_id,
                "product_id": selected_series.product_id,
                "series_id": selected_series.series_id,
            }
            for selected_series in series
        ],
        "start": request["start"],
        "end": request["end"],
    }
    issues = _merge_provider_issues(results)
    receipt_entries = tuple(entry for result in results for entry in result.receipts.entries)
    calls_made = tuple(call for result in results for call in result.provenance.calls_made)
    endpoints = tuple(dict.fromkeys(endpoint for result in results for endpoint in result.provenance.endpoints))
    retrieved = tuple(
        result.provenance.retrieved_at for result in results if result.provenance.retrieved_at is not None
    )
    queries: list[dict[str, object]] = []
    for result in results:
        query = result.provenance.query
        if query is not None and query not in queries:
            queries.append(query)
    merged_query = None if not queries else queries[0] if len(queries) == 1 else {"calls": tuple(queries)}
    return ObservationResult(
        data=_canonical_observation_order(pl.concat([result.data for result in results])),
        source_series=_merge_series_definitions(results),
        inventories=tuple({item.snapshot_id: item for result in results for item in result.inventories}.values()),
        outcomes=tuple({item.outcome_id: item for result in results for item in result.outcomes}.values()),
        scope=first.scope,
        provenance=first.provenance.model_copy(
            update={
                "request": merged_request,
                "calls_made": calls_made,
                "served_intervals": tuple(
                    interval for result in results for interval in result.provenance.served_intervals
                ),
                "endpoints": endpoints,
                "retrieved_at": max(retrieved) if retrieved else None,
                "query": merged_query,
                "time_windows": tuple(window for result in results for window in result.provenance.time_windows),
                "decomposition": tuple(
                    dict.fromkeys(value for result in results for value in result.provenance.decomposition)
                ),
            }
        ),
        issues=issues,
        receipts=Receipts(provider_id=first.provenance.provider_id, entries=receipt_entries),
    )


def _merge_series_definitions(results: tuple[ObservationResult, ...]) -> tuple[SourceSeries, ...]:
    definitions: dict[str, SourceSeries] = {}
    for result in results:
        for item in result.source_series:
            existing = definitions.get(item.series_id)
            if existing is None:
                definitions[item.series_id] = item
                continue
            if existing.model_dump(exclude={"facts"}) != item.model_dump(exclude={"facts"}):
                raise FatalContractError("Source-series identity changed while merging result partitions")
            facts = {fact.facts_id: fact for fact in existing.facts}
            for fact in item.facts:
                if fact.facts_id in facts and facts[fact.facts_id] != fact:
                    raise FatalContractError("Physical facts changed under the same fact-segment identity")
                facts[fact.facts_id] = fact
            definitions[item.series_id] = item.model_copy(update={"facts": tuple(facts.values())})
    return tuple(definitions.values())


def _canonical_observation_order(data: pl.DataFrame) -> pl.DataFrame:
    """canonical observation order : ObservationData → ObservationData (pure)."""
    return data.sort(
        ["station_id", "product_id", "series_id", "facts_id", "time", "time_zone", "value"], maintain_order=True
    )


def _merge_provider_issues(results: tuple[ObservationResult, ...]) -> tuple[Issue, ...]:
    merged: list[Issue] = []
    provider_provenance_issues: list[Issue] = []
    for result in results:
        for issue in result.issues:
            if issue.code.startswith("provenance."):
                if issue not in provider_provenance_issues:
                    provider_provenance_issues.append(issue)
                    merged.append(issue)
            else:
                merged.append(issue)
    return tuple(merged)


def products(provider: str | None = None) -> list[str]:
    """Inspect source access-coordinate names recorded in packaged catalogues.

    These internal routing names do not establish physical meaning. They are not
    accepted by find or pick; use quantity and established physical facts there.

    Parameters
    ----------
    provider : str or None, default None
        Registered provider identifier. None includes every provider.

    Returns
    -------
    list[str]
        Sorted, unique access-coordinate names. Neither a name nor its wording
        establishes a series statistic, temporal support or current availability.

    Raises
    ------
    UnknownProviderError
        If provider is not registered.
    FatalContractError
        If a shipped declaration or catalogue is invalid.
    """
    _ensure_default_providers_registered()
    provider_ids = _registry.list_provider_ids()
    if provider is not None and provider not in provider_ids:
        raise UnknownProviderError(provider)
    selected_provider_ids = set(provider_ids if provider is None else [provider])
    return sorted(
        {
            product_id
            for record in _registry.iter_records()
            if record.provider_id in selected_provider_ids
            for product_id in CatalogueReader(record.artifact, record.provider_id)
            .read_products()
            .data["product_id"]
            .to_list()
        }
    )


_DEFAULT_REGISTRATION_GENERATION: int | None = None


def _ensure_default_providers_registered() -> None:
    """Register the built-in manifest once for the registry's current lifetime."""
    global _DEFAULT_REGISTRATION_GENERATION

    if not _DEFAULT_PROVIDER_REGISTRATION_ENABLED:
        return
    if _registry.clear_generation == _DEFAULT_REGISTRATION_GENERATION:
        return

    from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS
    from rivretrieve._internal.providers.registration import register_manifest

    register_manifest(_registry, BUILTIN_PROVIDER_IDS)
    _DEFAULT_REGISTRATION_GENERATION = _registry.clear_generation


def download(provider: str):
    """Download a bulk provider's national dataset and compile it into the local cache.

    Parameters
    ----------
    provider : str
        Registered bulk provider identifier, currently ``"ca_eccc"`` or
        ``"pl_imgw"``. Calling this function is consent to transfer the
        publisher artifacts and compile them locally.

    Returns
    -------
    ValidatedStore
        Validated compiled store with its root, manifest and partition paths.
        Successful certification replaces the previous store and deletes the
        downloaded publisher artifacts. Their identities remain in the manifest.

    Raises
    ------
    TypeError
        If provider is not a nonempty string.
    UnknownProviderError
        If provider is not registered.
    BulkOperationsUnavailableError
        If provider is not a bulk provider.
    InsufficientDiskSpaceError
        If free space is below the declared requirement before any transfer.
    FatalContractError
        If a source response or store validation violates a contract.
    StoreCertificationError
        If compilation certification fails before publication.
    StoreTransactionError
        If preparation failed and retained inputs or cleanup residue require
        recovery. ``original`` preserves the initiating exception;
        ``cleanup_errors`` and ``residue_paths`` preserve cleanup facts.
    StorePostCommitCleanupError
        If publication succeeded but cleanup failed. The new generation remains
        authoritative; the exception identifies it and any remaining paths.
    OSError
        If local file operations fail.
    ValueError
        If the provider finds the publisher's listing or artifacts
        inconsistent, or finds that the newly published history would end
        before the source vintage of the existing compiled store. The existing
        store is not replaced. Also raised if ``RIVRETRIEVE_CACHE_DIR`` is set
        to a blank value.

    Notes
    -----
    This call can transfer a national dataset. It is not needed for live
    providers. Before publication, a failed compilation preserves the previous
    store and publisher inputs. Use recover_cache for interrupted work; use
    clear_cache only when deleting all owned state is intended.
    Transport failures can also propagate rather than becoming result issues.

    An existing compiled store that passes validation supplies its source
    vintage, so the provider can refuse a download whose published history
    would regress. An existing store that fails validation does not block the
    call, because ``download`` is how such a store is rebuilt.

    The store is written under ``RIVRETRIEVE_CACHE_DIR`` when that variable is
    set in the environment or the working directory ``.env`` file, otherwise
    under the platform's user cache directory. ``cache_status`` and
    ``clear_cache`` resolve the same location.
    """
    from rivretrieve._internal.bulk import download as bulk_download

    return bulk_download(provider)


def cache_status(provider: str):
    """Inspect one provider's local observation store without source access.

    Parameters
    ----------
    provider : str
        Registered provider identifier, for a live or bulk store.

    Returns
    -------
    StoreStatus
        Resolved path, committed generation and metadata-checked manifest,
        interrupted paths, cleanup residue and local ownership. Observation bytes
        are not audited. ``present`` means committed data exists; ``interrupted``
        means recognized unfinished work exists without committed data. Only
        ``absent`` means neither exists. Coverage describes established successful
        intervals, not continuous observations or a permanent retrieval history.

    Raises
    ------
    TypeError
        If provider is not a nonempty string.
    UnknownProviderError
        If provider is not registered.
    ObservationStoreRefusedError
        If committed metadata is malformed or its publication identity changed.
    StoreLifecycleError
        If the journal is malformed or managed paths are unsafe.
    OSError
        If local file operations fail.
    ValueError
        If ``RIVRETRIEVE_CACHE_DIR`` is set to a blank value.
    """
    from rivretrieve._internal.bulk import cache_status as bulk_cache_status

    return bulk_cache_status(provider)


def clear_cache(provider: str):
    """Delete one provider's compiled observation store or accumulated live store.

    Parameters
    ----------
    provider : str
        Registered provider identifier. This call is explicit destructive consent.

    Returns
    -------
    CacheClearResult
        Provider identifier, store path, whether anything existed, total bytes
        removed and every removed path. Includes recognized pending publisher
        downloads, staging, previous generations and transaction workspaces.
        The permanent coordination file remains.

    Raises
    ------
    TypeError
        If provider is not a nonempty string.
    UnknownProviderError
        If provider is not registered.
    BulkArtifactCleanupRefusedError
        If the pending-download namespace is symlinked or contains an unsafe entry.
    StoreLifecycleError
        If ownership is active or ambiguous, or a managed provider path is unsafe.
    OSError
        If deletion fails. This operation is not transactional.
    ValueError
        If ``RIVRETRIEVE_CACHE_DIR`` is set to a blank value.

    Notes
    -----
    This destructive action also removes preserved pending publisher downloads
    and recognized staging, previous generations and transaction workspaces,
    allowing a retry after interrupted retrieval or failed compilation. It does not download replacement
    data. It removes symlinks themselves rather than following them.
    Unrelated sibling paths are not removed.
    """
    from rivretrieve._internal.bulk import clear_cache as bulk_clear_cache

    return bulk_clear_cache(provider)


def audit_cache(provider: str):
    """Check every file and observation in one committed local store.

    Parameters
    ----------
    provider : str
        Registered live or bulk provider identifier.

    Returns
    -------
    CacheAuditResult
        Provider, path, generation identity, UTC check time and counts of
        partitions, rows and bytes checked. Return means all local integrity
        and consistency checks passed for that generation.

    Raises
    ------
    ObservationStoreRefusedError
        If data is absent, incompatible, malformed or changed since publication.
    StoreLifecycleError
        If active ownership or interrupted publication prevents an unambiguous
        audit. Inspect ``cache_status`` and use ``recover_cache`` first.

    Notes
    -----
    This read-only operation makes no source request and does not repeat
    certification against original publisher artifacts. It can read the whole
    national dataset. ``cache_status`` does not perform this complete check.
    """
    from rivretrieve._internal.bulk import _cache_registration
    from rivretrieve._internal.store.integrity import audit_store
    from rivretrieve._internal.store.reader import require_readable_store

    provider_id, root = _cache_registration(provider)
    require_readable_store(root)
    return audit_store(root, provider_id)


def recover_cache(provider: str):
    """Finish interrupted local work without downloading observations.

    Parameters
    ----------
    provider : str
        Registered live or bulk provider identifier.

    Returns
    -------
    CacheRecoveryResult
        Provider, canonical path, resulting status and actions taken. Recovery
        validates committed data before preserving or restoring it. Uncommitted
        first-install staging is discarded; it is never promoted to a store.

    Raises
    ------
    StoreLifecycleError
        If ownership is active or ambiguous, or surviving paths do not establish
        which generation was committed. No guess-based restoration is performed.
    ObservationStoreRefusedError
        If the committed generation fails its complete local audit.
    OSError
        If local restoration or cleanup fails. Inspect status before retrying.

    Notes
    -----
    Recovery coordinates with writers and clear. It can read every observation
    byte. It preserves source-selection facts and never merges old and new bulk
    snapshots. Use ``clear_cache`` only when removal of all owned data is intended.
    """
    from rivretrieve._internal.bulk import _cache_registration
    from rivretrieve._internal.store.integrity import audit_store
    from rivretrieve._internal.store.lifecycle import recover_store
    from rivretrieve._internal.store.reader import CacheRecoveryResult, StoreReader

    provider_id, root = _cache_registration(provider)
    actions = recover_store(Path(root), lambda path: audit_store(StoreRoot(path), provider_id, allow_pending=True))
    return CacheRecoveryResult(provider_id, Path(root), StoreReader().status(root, provider_id), actions)
