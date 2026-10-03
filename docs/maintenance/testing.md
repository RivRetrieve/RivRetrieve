# Choosing useful tests

Every test protects a named promise, uses an expectation that can detect the
claimed defect, and runs at the simplest level that can expose it. Providers
share this model. Source differences justify focused exceptions.

## Choose the level

| Level | Useful proof | Expected answer |
| --- | --- | --- |
| Small synthetic example | A conversion, parser rule, invariant or failure boundary | An explicit value or independently constructed invalid input |
| Shared library contract | Engine, catalogue, transport, store or public API behavior | Handwritten rows, identities, states and errors |
| Retained response replay | A provider handles the selected publisher response | Independently read source fields and values |
| Native-input rebuild | The assembled catalogue path reproduces the approved product | Reviewed packaged tables and source declarations |
| Independent source check | A particular interpretation agrees with retained source material | Original bodies, publisher receipts and reviewed source controls |
| Installed distribution | The built package works offline and excludes private material | Public behavior and explicit permitted package contents |
| Live observation | A publisher service behaved that way at that time | The request and response recorded for that observation |

A successful rebuild from a derived table does not prove that its originals exist.
Replay does not establish current service availability. A round trip can prove
preservation or encoding consistency; it cannot establish the correctness of the
source interpretation used on both sides.

## Make the expectation independent

Use a small calculation when it fully describes the promise. This synthetic
coordinate example checks arithmetic and the converter's declared sign convention:

```python
import pytest

from rivretrieve._internal.providers.za_dws.generate_catalogue import (
    convert_unsigned_dms_coordinates,
)

coordinates = convert_unsigned_dms_coordinates(
    "25:30:00", "28:15:00", station_id="example"
)

assert coordinates == pytest.approx((-25.5, 28.25))
```

It does not verify the contents of an original DWS PDF. That claim needs the
original material and its source-specific check.

For recorded observations, compare timestamps and values together. Sorting the
values alone can miss values attached to the wrong time. Include the source-series
identity when several series share a timestamp. Use library frame assertions for
whole tables. Keep units, unknowns, null values, absent rows and failed requests
distinct in expected results.

A historical snapshot can remain an independent regression control when its
reviewed source facts and order are still intentional promises. State that role.
Do not calculate a replacement expectation with the transformation being tested.
Test historical readability separately from the current package interface.

## Share contracts without hiding source differences

The shared all-provider catalogue rebuild in
`tests/test_catalogue_origin_certification.py` exercises each real publication
entry point with selected inputs. It checks offline operation, unchanged inputs,
output completeness, source identity and approved catalogue contents. Add a new
provider there rather than copying a second successful national rebuild.

A shared small test covers each origin-validation rule. One negative build per
provider or distinct partition proves that the generator calls that validation.
A full national build for every missing column repeats the same local rule.

Retain focused provider checks for real differences such as native units, timestamp
labels, pagination, source quality vocabulary, identity fields and coordinate
interpretation. Keep a positive replay for each distinct published route. Generic
malformed-input cases usually belong beside the parser or shared validator, with
one assembled check where failure propagation adds a separate promise.

A negative test must reach the rule it names. Start from a valid input. For a
relation-validation test, update unrelated byte identities when necessary to get
past the byte-integrity check. For a corruption test, leave those identities
unchanged. Eleven ledger edits rejected by the same digest check prove one digest
boundary, not eleven field validators.

## Keep setup isolated

Use temporary cache and store roots. A public `fetch` test must not read a
contributor's compiled store. Keep registry and monkeypatch state local to each
test. Share expensive unchanged package inputs only through the existing detached,
fingerprint-aware fixtures. Changed or corrupt files must still reach validation.

Reuse the existing installed wheel and sdist-wheel fixtures. Their verification
processes have separate working directories and homes. Keep planted-file exclusion
checks: inspecting a clean package alone cannot prove that private files would be
excluded from a build.

Do not add a second validator, downloader, fixture registry or test coordinator.
A helper should remove repetition without making a parallel implementation of the
behavior it claims to test.

## Keep ownership and acceptance clear

RivRetrieve owns library behavior and catalogue transformations. It keeps small
synthetic fixtures, approved runtime products and safe support references. The
private archive owns acquisition, retention and controlled verification mechanics,
including nested-package byte checks. Outer archive integrity does not replace
checks of inner members or publisher receipts.

Run source-independent checks with:

```sh
uv run pytest --logic-only
```

Tests that consume retained material declare exact consumer scopes and their
purpose. Use the existing private coordinator to select verified inputs and run
required complete positive checks before the related negative regressions.
See [Verification evidence](evidence.md) for commands, review requirements and
private-output rules. Missing mandatory inputs block acceptance; they are never
silently skipped or replaced by synthetic data.

When changing tests, explain the defect protected by each new case and where a
removed case's useful guarantee goes. Exact prose, private helper names and file
layout need checks only when they are intentional contracts. Measure expensive
changes against the same selected suite, Python version and isolation conditions.
Report interrupted runs and unavailable evidence separately from passing results.
