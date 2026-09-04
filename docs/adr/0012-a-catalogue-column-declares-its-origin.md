# A catalogue column declares its origin

Every catalogue column declares, per provider, where its values come from: a column of
that provider's native table, a constant stated in the provider's documentation, the
statement that this source publishes nothing for it, or native-only. A column with no
declaration fails the build, as does an origin naming a native column that was never
fetched, a null where the native column held a value, a documented constant that differs
from the emitted value, and a documented or not-published claim carrying no evidence.

The documented-constant form exists because a source may state a value in its
documentation rather than repeat it for every station. `Field` would falsely claim that
a native column carries that value, while `NotPublished` would falsely claim that the
source is silent; the constant and its evidence therefore travel together in the origin.

The decision exists because a null in the shipped catalogue means two incompatible things
and nothing can tell them apart. `usgs_nwis` ships `begin_date` as a key on all 26,231
station metadata blobs and every one is `None`, so `published_record_start_date` is null for the whole
provider. USGS publishes period of record; the site service returns it under
`seriesCatalogOutput=true` and our generator calls the default output. The catalogue
therefore states, indistinguishably from fact, that USGS has no start dates. `br_ana` is
worse: its 52,145 `station_products` rows carry `availability = unknown` with the reason
*"ANA catalogue does not expose per-variable station availability"*, while every one of
its station blobs in the same file carries populated `has_discharge`, `has_stage` and
`has_water_temperature` flags. The reason is contradicted by a column we ship ourselves.
`no_nve` carries an `active` key on all 4,889 stations, all null. `jp_mlit` keeps a
station whose scrape failed with `None` fields and prints a warning, freezing a network
failure into the artefact as though it were a fact about MLIT.

The rejected alternative is the guaranteed and best-effort tier proposed in
`docs/design/provider-redesign-review.md` §6.1. It is already implemented:
`validate_catalogue` raises on any null in a `nullable=False` column and the six
guaranteed columns are already non-nullable and fully populated. It would have caught none
of the four defects above, because each is a best-effort column that is legally empty
under it. Fabrication cannot be detected by inspecting a value, only by requiring the
value to name its origin.

Evidence is required on a not-published claim because a mechanical check reproduces the
bug it exists to catch. Absence from a payload proves only how we asked, and the USGS
payload genuinely contains no period of record, so a payload-only check would certify the
false claim cleanly. A person reads the source's documentation once and links it.

## Consequence: the build stays red until every enrolled provider is declared

On 2026-08-03 the operator deferred `br_ana` and `no_nve` to separate work. That statement
records the boundary at the time of this decision. `no_nve` subsequently gained a complete
attested native table and origin declarations and entered `ORIGIN_GATE_ENROLLED_PROVIDERS`.
The complete-provider rule now quantifies over all twelve enrolled members. `br_ana` remains
intentionally unenrolled rather than compliant. There is no half-landed state within
`ORIGIN_GATE_ENROLLED_PROVIDERS`: every provider in the enrolled set is completely declared,
while the explicitly deferred `br_ana` remains outside that set. Brazil's availability must
ultimately be fixed because no honest evidence link can be written for it, and USGS's request
was corrected for the same reason. The original defect history included 64% of the 284,399
`unknown` rows in `station_products` across Brazil and Norway.
