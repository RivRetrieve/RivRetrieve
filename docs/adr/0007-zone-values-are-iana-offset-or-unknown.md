# A zone value is an IANA identifier, a fixed offset, or unknown

The `time_zone` column ADR 0006 introduced needs a value domain, and the thirteen sources
speak three vocabularies rather than one: four stamp an ISO-8601 offset on every row
(`-06:00`, `+01:00`, `Z`), five publish a bare wall clock with no zone at all, and USGS
publishes a zone abbreviation in station metadata. So `time_zone` admits an IANA
identifier, an ISO-8601 fixed offset `±HH:MM`, or the literal `unknown`, and we keep
whichever kind the source stated rather than promoting one to the other.

Abbreviations are excluded, which is the part that needed deciding rather than the part
that was obvious. USGS ships `tz_cd` for all 26,231 stations — `EST` 8172, `CST` 6588,
`MST` 5686, `PST` 4845, `AKST` 519, `HST` 421 — and the trap is that they fail in two
different ways. `AKST`, `CST` and `PST` do not resolve as IANA zones at all. `EST`, `MST`
and `HST` do resolve, as *fixed no-daylight-saving* zones, so reading `EST` for a Maine
gauge in July yields a timestamp wrong by exactly one hour, with a plausible value and no
error. The half that fails loudly is safe; the half that succeeds is the dangerous one.
This costs USGS nothing, because its payload stamps the offset on every row, and that is
the source's own statement about the data rather than about the station.

Three alternatives were rejected. Normalising everything to IANA requires mapping `-05:00`
to a zone, which several zones share, and that is a derivation ADR 0005 forbids.
Normalising everything to offsets discards the zone identity that daily values depend on,
since an offset says nothing about which 24 hours a day covers. Two columns, one for a
zone and one for an offset, doubles the unknown states and asks every consumer to
reconcile them.

## Consequence: USGS `dst_flag` is not needed to read returned data

The Program Map lists capturing `dst_flag` as unspecified, on the grounds that Arizona and
Hawaii cannot otherwise be told from their daylight-saving neighbours. Under this decision
the question does not arise for observations: the payload stamps `-07:00` for Arizona and
`-06:00` for Montana on every July row, so the rows are already distinguishable without
the flag. It may still matter for catalogue work, which is where it should be reconsidered
rather than here.
