# USGS discovery implementation validation

This is authored engineering evidence, not a publisher response or a historical
coverage guarantee. The national coverage audit remains unchanged in
`research/usgs-modern-coverage`. The owner approved modern-only treatment of its
five metadata gaps and six unknown-statistic cases in issue 331, comment 5778571205.

## Catalogue representation

The initial concrete source-description encoding contained 59,159 series and was
96,519,770 bytes. A decode-only process used 1,275,461,632 bytes peak RSS and 1.509 s.
Disk encoding 2 stores identified physical facts once, with strict references:
28,681,480 bytes, 8 shared immutable fact objects, 0.620 s decode and 371,671,040
bytes peak RSS in a separate measured process. All 59,159 decoded objects were
equal before/after the representation-only change. Encoding 1 remains readable
and remains the default writer for other providers.

A later contract correction changed the new modern `facts_id` hashes to the
repository's established exact-facts-and-evidence content hash. The complete
definition digest excluding **only** `facts_id` stayed
`4a928815966463413f2a22c1f16fbbfaaf0690c394e9cfbe9447d9b57acc2e96`.
Series IDs, physical fields, descriptions and evidence were unchanged. The
current complete definition digest is pinned in `test_usgs_modern_catalogue.py`.
The representation equality result must not be misread as equality of the IDs
across this separate correction. Legacy USGS artifacts are explicitly refused.

## Cold public discovery measurements

Measured sequentially in separate processes on the same development machine,
without a competing full suite. Each command imports the installed project and
calls `rr.find` then `rr.series`. These measurements include existing eager
registration of all providers, which accounts for substantial baseline cost.
They are local observations, not performance guarantees.

| Revision/selection | Seconds | Peak RSS bytes | Series rows |
| --- | ---: | ---: | ---: |
| sequential-baseline-station | 2.158 | 629,964,800 | 6 |
| sequential-baseline-full | 5.261 | 1,186,037,760 | 57,961 |
| final-modern-station | 2.823 | 815,251,456 | 6 |
| final-modern-full | 6.410 | 1,268,563,968 | 59,159 |

Baseline is main `d77b6dba710d7ae550b476d08322f51c8a409df1`.
The baseline catalogue has generic route definitions and independent claims;
current discovery exposes concrete publisher series. No unrelated lazy-loading
refactor was introduced.

Commands (baseline uses `uv run --directory <baseline-checkout>`):

```sh
/usr/bin/time -l uv run python -c 'from time import perf_counter; import rivretrieve as rr; t=perf_counter(); s=rr.find(provider="usgs_nwis",station="07374000"); f=rr.series(s); print(perf_counter()-t,f.height)'
/usr/bin/time -l uv run python -c 'from time import perf_counter; import rivretrieve as rr; t=perf_counter(); s=rr.find(provider="usgs_nwis"); f=rr.series(s); print(perf_counter()-t,f.height)'
```

## Regression evidence

The replacement map in `tests/test_data/usgs_modern/REGRESSION-COVERAGE.md`
links retired protocol-specific checks to active modern tests. Legacy bodies,
unknown acquisition facts, method descriptions and source offsets remain
independently tested without a duplicate retired provider implementation.

Publication rebuilds are offline, hash checked and byte deterministic, including
all source descriptions, provenance tables, descriptor and monitoring-location
map. Tests cover corrupt normalized references and immutable shared facts;
source-boundary negative controls are explicitly authored rather than recordings.
The fixture replay adapter keeps actual acquisition headers in manifests and
does not manufacture engine execution headers.

The first full-suite attempt was deliberately interrupted at 6% before changing
the high-memory catalogue encoding. It is not counted as complete validation.
The second full-suite run was diagnostic and was stopped after identifying active
legacy-replay failures while review repairs were in progress. It is also not
counted as final validation. Final stable-head full-suite and independent review
results are reported in the implementation PR.


## Station identities and selectable series

The catalogue retains all 26,258 station identities. Modern concrete series are
available at 26,201 stations. The frozen legacy six-product availability table
covered 26,200 stations: the approved 09385701 daily-discharge metadata gap loses
one, while 02312719 and 11047350 gain supported products within the existing
station scope. The exact five lost station/product pairs remain the approved
five; 465 station/product pairs are gained.

Of the 57 retained stations without modern concrete series, 56 had no supported
baseline products. The remaining station is 09385701. All six null-statistic
continuous cases remain present. `STATION-SELECTION-ACCOUNTING.json` is an
authored enumeration joined to retained audit records, with input hashes. It is
not a publisher response. The coverage-map regression checks the complete gap
set and both station counts; no placeholder routes are added to inflate discovery.
