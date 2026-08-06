# The engine owns every window arithmetic; a provider only renders

A window is an engine-owned object that a provider can read and never compute on. The
engine widens the requested window by a fixed two days at each end, splits the result
into sub-windows at a granularity the provider *declares*, and clips at the end of
convert. A provider turns a window into its source's vocabulary — an ISO instant, a date,
a year, a year-month, or nothing where the source accepts no date parameter — and does
nothing else. The window offers no arithmetic to reach for: it cannot be added to,
shifted, or split outside the engine.

The pad is uniform rather than computed per source because the widest disagreement
between any two calendars on Earth is 26 hours, so a fixed two days cannot fail to
contain the request whatever calendar the source's date parameters turn out to be in.
The rejected alternative — each provider declaring its own calendar relationship and
padding exactly — buys tighter fetches and thirteen chances to state an offset wrong.
That is precisely the mistake already made: the charting audit found ten of eleven
providers expressing the fetch window in one calendar and the clip window in another.

Splitting is engine-owned for the same reason found by survey rather than by argument.
Six of the nine portable legacy providers chop one window into many — two `_split_windows`,
one `_decompose_windows`, `_iter_years`, `_iter_year_months`, and `_query_years` already
in `src/` — for two distinct reasons, a capped response size or one file per calendar
unit. The granularity is a fact about the source; the splitting is arithmetic. Separating
them means those six implementations are never ported.

The granularity set is open, and widening it has exactly one place and no alternative. A
provider names its granularity, and the engine refuses a name it does not know with an
error identifying the module to add it in. When porting in #17 discovers arithmetic this
survey did not anticipate, the provider cannot absorb it locally; the only path forward
is the intended one.

The consequence to accept is that every request fetches four days more than it needs,
permanently, on every provider. For the bulk sources that read whole years or whole files
it rounds away to nothing; for a queried source it is four days against a typical
multi-week request. That is the price of making an entire class of edge defect unwritable
by nine ports that have not been written yet.
