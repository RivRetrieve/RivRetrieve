"""domain context contract : DomainContextText → glossary-contract assertions."""

from pathlib import Path

CONTEXT_PATH = Path(__file__).parents[1] / "CONTEXT.md"

RAW_ENTRY = """**Raw**:
The exact bytes handed to a [[provider]]'s parse [[stage]], retained alongside the
returned result only when the caller requests them. When they are not requested, the
result's raw slot is empty."""

NATIVE_TABLE_RAW_AVOID = """_Avoid_: metadata (the opaque per-row JSON string it replaces), raw table (collides with
[[raw]], the exact bytes handed to a [[provider]]'s parse [[stage]] and retained only when
requested), source table"""

NATIVE_TIME_ENTRY = """**Native time**:
A timestamp exactly as the provider published it. The complete returned observation
frame is `time | time_zone | station_id | product_id | value`, in that order. Its `time`
column holds the source's naive wall-clock value, paired on every row with the
source-published `time_zone`, or `unknown` only where the source establishes no zone.
All five columns travel together as the observation frame; `time` and `time_zone` are
not meaningful alone. The pairing exists because one dataframe timestamp column carries
a single zone for all its rows, while one result may span stations in different zones.
_Avoid_: raw time (collides with [[raw]], the exact bytes handed to a [[provider]]'s parse
[[stage]] and retained only when requested), local time (ambiguous between the gauge's
own zone and a provider-wide national zone)"""

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


def test_raw_is_never_described_as_untouched() -> None:
    assert "untouched" not in _context().lower()


def test_raw_is_exact_parse_input_and_opt_in() -> None:
    assert RAW_ENTRY in _context()


def test_native_table_avoidance_uses_the_exact_raw_meaning() -> None:
    assert NATIVE_TABLE_RAW_AVOID in _context()


def test_native_time_is_the_ordered_five_column_observation_frame() -> None:
    assert NATIVE_TIME_ENTRY in _context()


def test_unknown_distinguishes_pre_research_absence_from_source_silence() -> None:
    assert UNKNOWN_ENTRY in _context()


def test_license_distinguishes_pre_research_absence_from_unknown() -> None:
    assert LICENSE_ENTRY in _context()


def test_citation_exists_and_distinguishes_pre_research_absence_from_unknown() -> None:
    assert CITATION_ENTRY in _context()
