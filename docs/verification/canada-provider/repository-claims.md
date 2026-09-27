# Repository claim checks

Tested production revision: `6da9b64` (same production tree as main `5469884`).

| Page claim | Evidence |
|---|---|
| Daily discharge and stage, units, unknown zone/day | `src/rivretrieve/_internal/providers/ca_eccc/config.py`, `series.py` |
| Vertical reference unestablished | `diagnose_empty.log` prints public selection PhysicalFacts: `vertical_reference=None`, `vertical_datum=None` |
| Published null cells remain rows | `bulk.py::_unpivot_month` iterates every valid day of each published monthly row; appends `value=None`, `value_state="published_null"` for source NULL |
| Absent monthly records yield no rows | `bulk.py::decode_hydat_batches` iterates publisher monthly records only; no monthly gap filling; `diagnose_empty.log` confirms original example's 2000 absence |
| Symbols retained but no public quality column | `_declared_schema`/`_unpivot_month` preserve native symbol columns; `retrieval.log` prints the ten public columns |
| Receipts preserve selected native source cells | `retrieve_available.py` executes public `fetch(..., receipts=True)`; full local `retrieve_available.log` contains StoreExcerptReceipt with native `DLY_FLOWS.FLOW_SYMBOL1` etc. and store-excerpt authorship |
| No implicit acquisition; refresh refused | `isolated_conditions.py/.log`; `tests/test_missing_bulk_outcomes.py` |
| Bypass/reuse both local | `retrieve_available.py` compares actual public frames with Polars assertion; log records no issues; provenance is local |
| Archive URL/date resolution | `bulk.py::download_hydat` probes dated releases back at most 365 days; no alternate route added |
| Resource admission | `_internal/bulk.py::_download` checks configured free bytes before transfer; peak resources not measured |

These code checks do not substitute for publisher evidence about institutional
responsibilities, licence conditions or meanings of symbols. The preserved
compiler certification verifies publisher cell preservation for the fresh
archive; no production code was edited.
