# Time and its zone are two columns

An observation's timestamp is returned as a naive `time` column holding the source's own
wall-clock value, paired with a `time_zone` column stating that row's zone, or `unknown`
where the source does not establish one. The canonical table is therefore
`time | time_zone | station_id | product_id | value`.

The reason is a representation limit that ADR 0001 did not account for. A dataframe
timestamp column carries a single zone for all of its rows, and one result may span
stations in different zones: the United States and Canada are the immediate cases, where
the zone is a per-station fact rather than a provider-wide one. Asking for two gauges in
different zones is an ordinary request, not an edge case, so a single zone-bearing column
cannot express the answer at all.

Two alternatives were rejected. Making the column zone-aware and failing when a request
spans zones is more type-safe and would break the most common multi-station query in the
library. Keeping the zone out of the frame entirely, as per-station catalogue metadata,
would hand the user a naive column and require a join to interpret it, which is the
silent-wrongness ADR 0001 exists to prevent.

The accepted cost is that `time` alone is naive, so a user who ignores `time_zone` can
compare timestamps across zones without noticing. The pairing is what makes that mistake
visible rather than invisible: under both rejected alternatives the same user would have
had no signal at all. The two columns travel together and neither is meaningful alone.

## Consequence: best-effort UTC is derived, not stored

Conversion to UTC becomes an operation over `time` and `time_zone` rather than a storage
decision, defined exactly where the zone is known and declining where it is `unknown`.
That is the same promise ADR 0001 made, now expressible per row instead of per result.
The storage layout in ADR 0002 holds the same two columns, so a cached or archived row
carries its zone as faithfully as a freshly retrieved one.
