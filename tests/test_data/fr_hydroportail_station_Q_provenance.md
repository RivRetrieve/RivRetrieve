# Station-own HydroPortail discharge test expectations

The source recordings, acquisition records and complete historical attestations
are retained in the private [source archive](../../docs/maintenance/evidence.md).
Retrieve the exact selected inputs outside source checkouts, preserving their
repository-relative paths. Set `RIVRETRIEVE_TEST_EVIDENCE_ROOT` to that external
root before running the retained-input tests.

## Independent boundary expectations

The station-own discharge boundary probe uses
`tests/test_data/fr_hydroportail_station_Q_padded.recording.json` for the public
June 1–2, 2026 window. Its accepted source-only expectations were established
without reading the provider implementation or its outputs:

- Reading count: 282.
- First wall-clock time: `2026-06-01T00:00:00`.
- Last wall-clock time: `2026-06-02T18:00:00`.
- Time-zone carrier: `+00:00`.

The count and wall clocks describe clipping to
`[2026-06-01T00:00:00Z, 2026-06-03T00:00:00Z)`. The separate accepted time-carrier
attestation represents the source UTC label as the fixed offset `+00:00`.
That representation leaves the count and wall clocks unchanged; it does not
normalize timestamps or establish a new source time zone.

These expectations do not independently establish the discharge unit conversion.
The unit-definition checks remain separate. See
[the boundary tests](../test_fr_hydroportail_station.py) and
[the unit-definition tests](../test_fr_hydroportail_unit_definition.py).

## Separate empty-result controls

The June 3–6, 2026 clipping test uses the separate retained
`tests/test_data/fr_hydroportail_station_Q_empty_clip.recording.json`.
It must not substitute for the positive boundary recording.

Parser checks use the genuine empty envelope
`tests/test_data/fr_hydroportail_J783301020_empty.body` with its retained receipt.
Adversarial cases mutate metadata explicitly to test validation before row
iteration. Those mutated payloads are protocol controls, not recordings or
independent boundary evidence. Source statistics are not treated as observations,
and missing evidence about executed request headers is not filled in.
