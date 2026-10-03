# API and capability reference

[Documentation index](README.md)

Functions import from `rivretrieve`. The reference renders their source docstrings automatically.

## Public functions

### as_frame

::: rivretrieve.as_frame

### cache_status

::: rivretrieve.cache_status

### clear_cache

::: rivretrieve.clear_cache

### describe

::: rivretrieve.describe

### download

::: rivretrieve.download

### metadata

::: rivretrieve.metadata

### fetch

::: rivretrieve.fetch

### fetch_by_provider

::: rivretrieve.fetch_by_provider

### find

::: rivretrieve.find

### from_bundle

::: rivretrieve.from_bundle

### from_frame

::: rivretrieve.from_frame

### map

::: rivretrieve.map

### pick

::: rivretrieve.pick

### products

::: rivretrieve.products

### providers

::: rivretrieve.providers

### series

::: rivretrieve.series

### to_bundle

::: rivretrieve.to_bundle

### to_utc

::: rivretrieve.to_utc

## Returned domain types

These types are not re-exported from `rivretrieve`. Their headings identify their implementation locations. Create selections through the public functions rather than constructing `_Selection`.

### _Selection

::: rivretrieve._internal.selection._Selection
    options:
      members: [scope, known_series, inventories, issues, locations, acquisition_provenance, empty_reason, series]

### ObservationResult

::: rivretrieve._internal.observations.ObservationResult
    options:
      members: [data, provenance, issues, receipts, source_series, inventories, outcomes, scope, view_scope]

### ObservationResult.to_polars

::: rivretrieve._internal.observations.ObservationResult.to_polars

### ObservationResult.to_pandas

::: rivretrieve._internal.observations.ObservationResult.to_pandas

### ObservationProvenance

::: rivretrieve._internal.observations.ObservationProvenance
    options:
      members: [source, provider_id, request, calls_made, time_windows, decomposition, endpoints, query, served_intervals, source_vintage, publisher_artifact_checksum, acquisition_provenance, rivretrieve_version, catalogue_version, license, citation, requested_at, retrieved_at, response_version, metadata, publisher_artifact_checksums, publisher_artifact_urls]

### Receipts

::: rivretrieve._internal.observations.Receipts
    options:
      members: [provider_id, entries]

### ReceiptEntry

::: rivretrieve._internal.observations.ReceiptEntry
    options:
      members: [content, origin, authorship]

### StoreExcerptReceipt

::: rivretrieve._internal.observations.StoreExcerptReceipt
    options:
      members: [store_path, executed_query, format_version, source_vintage]

### EvidenceState

::: rivretrieve._internal.source_series.EvidenceState
    options:
      members: [KNOWN, SOURCE_SILENT, NOT_ESTABLISHED]

### EvidenceFact

::: rivretrieve._internal.source_series.EvidenceFact
    options:
      members: [value, state, evidence]

### ClippingAxis

::: rivretrieve._internal.source_series.ClippingAxis
    options:
      members: [CALENDAR_DATE, SOURCE_TIMESTAMP]

### SourceUnitCodeDefinition

::: rivretrieve._internal.source_series.SourceUnitCodeDefinition
    options:
      members: [provider_id, namespace, code, unit, evidence]

### PhysicalFacts

::: rivretrieve._internal.source_series.PhysicalFacts
    options:
      members: [facts_id, quantity, source_unit, normalized_unit, source_unit_definition, frequency, statistic, temporal_support, day_definition, timestamp_anchor, time_zone, vertical_reference, vertical_datum, clipping_axis, label_time]

### Admission

::: rivretrieve._internal.source_series.Admission
    options:
      members: [status, reason, target_unit, factor]

### SourceIdentity

::: rivretrieve._internal.source_series.SourceIdentity
    options:
      members: [namespace, published_id, description, origin, evidence]

### SourceSeries

::: rivretrieve._internal.source_series.SourceSeries
    options:
      members: [series_id, provider_id, station_id, product_id, identity, variant, facts]

### PhysicalPredicate

::: rivretrieve._internal.source_series.PhysicalPredicate
    options:
      members: [field, value]

### RestrictionKind

::: rivretrieve._internal.source_series.RestrictionKind
    options:
      members: [ALL, EXPLICIT]

### ScopeState

::: rivretrieve._internal.source_series.ScopeState
    options:
      members: [ACTIVE, EMPTY]

### SeriesScope

::: rivretrieve._internal.source_series.SeriesScope
    options:
      members: [state, provider_ids, station_ids, product_ids, predicates, restriction, variants, series_ids]

### SeriesWindow

::: rivretrieve._internal.source_series.SeriesWindow
    options:
      members: [start, end, axis]

### InventoryCompleteness

::: rivretrieve._internal.source_series.InventoryCompleteness
    options:
      members: [COMPLETE, INCOMPLETE, UNRESOLVED]

### CatalogueSeriesClaim

::: rivretrieve._internal.source_series.CatalogueSeriesClaim
    options:
      members: [provider_id, station_id, product_id, identity, native_coordinates]

### InventorySnapshot

::: rivretrieve._internal.source_series.InventorySnapshot
    options:
      members: [snapshot_id, scope, members, member_facts, completeness, access, origin, acquired_at, catalogue_check_date, catalogue_claims, window, evidence, reason]

### OutcomeStatus

::: rivretrieve._internal.source_series.OutcomeStatus
    options:
      members: [SUCCESS, EMPTY, FAILED, UNSUPPORTED, UNRESOLVED, NO_MATCH]

### RequestedSelector

::: rivretrieve._internal.source_series.RequestedSelector
    options:
      members: [kind, value]

### RetrievalOutcome

::: rivretrieve._internal.source_series.RetrievalOutcome
    options:
      members: [outcome_id, series_id, station_id, product_id, window, status, facts_ids, reason, retrieved_at, calls, requested_selector, coverage, observation_keys]

### Issue

::: rivretrieve._internal.issues.Issue
    options:
      members: [severity, code, message, details, provider_id]

### CatalogueEvidence

::: rivretrieve._internal.catalogues.evidence.CatalogueEvidence
    options:
      members: [header, facts, acquisitions, bindings, binding_facts, external_inputs]

### RequestedInterval

::: rivretrieve._internal.coverage.RequestedInterval
    options:
      members: [start, end, axis]

### CoverageInterval

::: rivretrieve._internal.coverage.CoverageInterval
    options:
      members: [series_id, interval, retrieved_at, outcome_id, facts_ids]

### SourceCallOrigin

::: rivretrieve._internal.engine.SourceCallOrigin
    options:
      members: [url, request_parameters, status_code, retrieved_at, content_type, source_path, query, attempts]

### StoreStatus

::: rivretrieve._internal.store.reader.StoreStatus
    options:
      members: [store, provider_id, presence, manifest, bytes_on_disk, coverage, partition_row_counts, root, exists, format_version, compiler_version, built_at, source_vintage, publisher_artifact_url, publisher_artifact_checksum, publisher_artifact_urls, publisher_artifact_checksums, source_schema_fingerprint]

### ValidatedStore

::: rivretrieve._internal.store.validation.ValidatedStore
    options:
      members: [root, manifest, partition_files]

### StoreManifest

::: rivretrieve._internal.store.validation.StoreManifest
    options:
      members: [format_version, provider_id, compiler_version, built_at, source_vintage, publisher_artifact, publisher_artifacts, source_schema, source_column_dispositions, partition_row_counts, series, inventories, outcomes, issues, source_calls]

### AccumulatedStoreManifest

::: rivretrieve._internal.store.validation.AccumulatedStoreManifest
    options:
      members: [format_version, provider_id, built_at, coverage, partition_row_counts, series, inventories, outcomes, issues, source_calls]

### CacheClearResult

::: rivretrieve._internal.bulk.CacheClearResult
    options:
      members: [provider_id, path, existed, bytes_freed, removed_paths]

## Exception imports

Function Raises sections state the conditions. FatalContractError subclasses bypass the caller issue policy. Local I/O and bulk transfer failures can also propagate.

### EmptySelectionError

::: rivretrieve._internal.discovery.EmptySelectionError
    options:
      members: []

### MultiProviderSelectionError

::: rivretrieve._internal.discovery.MultiProviderSelectionError
    options:
      members: []

### UnknownProviderError

::: rivretrieve._internal.registry.UnknownProviderError
    options:
      members: []

### UnknownStationError

::: rivretrieve._internal.selection.UnknownStationError
    options:
      members: []

### UnknownProductError

::: rivretrieve._internal.selection.UnknownProductError
    options:
      members: []

### RivRetrieveError

::: rivretrieve._internal.issues.RivRetrieveError
    options:
      members: []

### FatalContractError

::: rivretrieve._internal.issues.FatalContractError
    options:
      members: []

### IssuePolicyError

::: rivretrieve._internal.issues.IssuePolicyError
    options:
      members: []

### InvalidObservationRequestError

::: rivretrieve._internal.issues.InvalidObservationRequestError
    options:
      members: []

### MissingCredentialError

::: rivretrieve._internal.issues.MissingCredentialError
    options:
      members: []

### MissingOptionalDependencyError

::: rivretrieve._internal.issues.MissingOptionalDependencyError
    options:
      members: []

### ObservationsUnavailableError

::: rivretrieve._internal.issues.ObservationsUnavailableError
    options:
      members: []

### ObservationDataSchemaError

::: rivretrieve._internal.issues.ObservationDataSchemaError
    options:
      members: []

### BulkOperationsUnavailableError

::: rivretrieve._internal.bulk.BulkOperationsUnavailableError
    options:
      members: []

### BulkArtifactCleanupRefusedError

::: rivretrieve._internal.bulk.BulkArtifactCleanupRefusedError
    options:
      members: []

### InsufficientDiskSpaceError

::: rivretrieve._internal.bulk.InsufficientDiskSpaceError
    options:
      members: []

### ObservationStoreRefusedError

::: rivretrieve._internal.store.validation.ObservationStoreRefusedError
    options:
      members: []

### StoreCertificationError

::: rivretrieve._internal.store.certification.StoreCertificationError
    options:
      members: []

### StorePostCommitCleanupError

::: rivretrieve._internal.store.certification.StorePostCommitCleanupError
    options:
      members: []

--8<-- "docs/_generated/reference-tables.md"
