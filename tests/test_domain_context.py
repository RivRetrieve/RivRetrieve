"""domain context contract : DomainContextText → glossary-contract assertions."""

from pathlib import Path

CONTEXT_PATH = Path(__file__).parents[1] / "CONTEXT.md"

RECEIPT_ENTRY = """**Receipt**:
What a [[provider]]'s parse [[stage]] was handed, kept alongside the returned result so a
user can audit a value against what the source actually said, and only when the caller
asks for it — unasked, the slot exists and is empty and no response bytes are reachable
from the result. It is bytes and stays bytes: thirteen sources answer in JSON, CSV, HTML
and spreadsheets, and modelling that would be parsing. Each entry carries a uniform
envelope naming where the bytes came from, with the fields that do not apply left
[[unknown]] and request headers excluded entirely so a credential has no route in. It is
deliberately what parse read rather than what came off the wire: a zip explains no value,
and a bulk provider never touches the network on a request. Every receipt declares its
authorship, because the two are not the same kind of thing and only the reader can tell
which matters: a **publisher payload** is untouched bytes the source itself served, and a
**store excerpt** is bytes RivRetrieve produced by encoding rows read out of its own
[[store]]. A store excerpt is exactly as complete as [[compile]] made the store and never
reconstructs a value the store does not hold.
_Avoid_: raw (the former name; it presented RivRetrieve's own encoding as the source's own
words), untouched payload (one unzipping step removes it from what the server sent),
response, blob"""

NATIVE_TABLE_RECEIPT_AVOID = """_Avoid_: metadata (the opaque per-row JSON string it replaces), raw table (collides with
[[receipt]], the exact bytes handed to a [[provider]]'s parse [[stage]] and retained only when
requested), source table"""

NATIVE_TIME_ENTRY = """**Native time**:
A timestamp exactly as the provider published it. The complete returned observation
frame is `time | time_zone | station_id | product_id | value`, in that order. Its `time`
column holds the source's naive wall-clock value, paired on every row with the
source-published `time_zone`, or `unknown` only where the source establishes no zone.
All five columns travel together as the observation frame; `time` and `time_zone` are
not meaningful alone. The pairing exists because one dataframe timestamp column carries
a single zone for all its rows, while one result may span stations in different zones.
_Avoid_: raw time (collides with [[receipt]], the exact bytes handed to a [[provider]]'s parse
[[stage]] and retained only when requested), local time (ambiguous between the gauge's
own zone and a provider-wide national zone)"""

PROVIDER_ENTRY = """**Provider**:
An adapter over the [[engine]] for one national source. It contributes only what is
true about that source. An HTTP provider contributes `fetch.py`, `parse.py`, and
`config.py`; a bulk provider contributes `config.py` and `bulk.py`.
_Avoid_: source, backend, plugin"""

STAGE_ENTRY = """**Stage**:
One of fetch, parse, convert, and assemble. An HTTP retrieval passes through all four.
A bulk retrieval queries the [[store]] and then passes through convert and assemble; it
passes through neither provider fetch nor provider parse, and no provider code executes
on its retrieval path. A provider file is named for a stage only when the provider writes
code for that stage, which is why convert and assemble have no provider file.
_Avoid_: step, phase"""

STORE_ENTRY = """**Store**:
Retrieved observations at rest in RivRetrieve's own layout, together with the
[[manifest]] describing them. It is the single form ADR 0002 fixes for anything held on
disk, so a [[cache]] and a [[user-cache]] are both stores. Revision `1` of the compiled-
store manifest contract applies only to a store produced by compiling a
[[publisher-artifact]]. Whether a user-cache store carries a reduced manifest under
revision `1` or uses a distinct format revision remains undecided, so revision `1` does
not yet promise that one reader serves both. A store holds the source's native values and
native wall-clock timestamps; unit conversion and clipping happen on read through the
same convert [[stage]] every provider uses, so standardising the container is not the
same act as changing the numbers. The layout is authored by RivRetrieve rather than
owned by a publisher, which is why it carries a format version and why reading one is a
compatibility obligation rather than an implementation detail.
_Avoid_: cache (one kind of store, not the category), database, local format"""

UNKNOWN_ENTRY = """**Unknown**:
A representable state meaning the source does not tell us. Distinct from zero, from
empty, and from a default. Never resolved by assumption, and never filled by computing
a value the source did not publish. A license or citation RivRetrieve has not yet
established is absent, not [[unknown]]: that is RivRetrieve's pre-research state, not
source silence.
_Avoid_: missing, N/A, not available, default"""

LICENSE_ENTRY = """**License**:
A source's own terms, surfaced as a link and, where the source publishes one, its
verbatim text. RivRetrieve never classifies, summarises or interprets what a license
permits. A license RivRetrieve has not yet established is absent, not [[unknown]];
[[unknown]] would mean the source does not tell us.
_Avoid_: license status, redistribution status, open/attribution/restricted"""

CITATION_ENTRY = """**Citation**:
The credit a source requests for its data, surfaced verbatim rather than rewritten or
inferred. A citation RivRetrieve has not yet established is absent, not [[unknown]];
[[unknown]] would mean the source does not tell us."""


def _context() -> str:
    return CONTEXT_PATH.read_text(encoding="utf-8")


def test_receipt_authorship_reserves_untouched_for_publisher_payload() -> None:
    described = _context().replace(
        "untouched payload (one unzipping step removes it from what the server sent)",
        "",
    )
    assert "**publisher payload** is untouched bytes the source itself served" in described
    assert described.lower().count("untouched") == 1


def test_receipt_is_exact_parse_input_and_opt_in() -> None:
    assert RECEIPT_ENTRY in _context()


def test_native_table_avoidance_uses_the_exact_receipt_meaning() -> None:
    assert NATIVE_TABLE_RECEIPT_AVOID in _context()


def test_native_time_is_the_ordered_five_column_observation_frame() -> None:
    assert NATIVE_TIME_ENTRY in _context()


def test_provider_shape_depends_on_provider_kind() -> None:
    assert PROVIDER_ENTRY in _context()


def test_bulk_retrieval_skips_provider_fetch_and_parse() -> None:
    assert STAGE_ENTRY in _context()


def test_store_revision_one_does_not_promise_a_user_cache_reader() -> None:
    assert STORE_ENTRY in _context()


def test_unknown_distinguishes_pre_research_absence_from_source_silence() -> None:
    assert UNKNOWN_ENTRY in _context()


def test_license_distinguishes_pre_research_absence_from_unknown() -> None:
    assert LICENSE_ENTRY in _context()


def test_citation_exists_and_distinguishes_pre_research_absence_from_unknown() -> None:
    assert CITATION_ENTRY in _context()
