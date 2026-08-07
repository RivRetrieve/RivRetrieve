"""domain context contract : DomainContextText → glossary-contract assertions."""

from pathlib import Path

CONTEXT_PATH = Path(__file__).parents[1] / "CONTEXT.md"

RAW_ENTRY = """**Raw**:
What a [[provider]]'s parse [[stage]] was handed, kept alongside the returned result so a
user can audit a value against what the source actually said, and only when the caller
asks for it — unasked, the slot exists and is empty and no response bytes are reachable
from the result. It is bytes and stays bytes: thirteen sources answer in JSON, CSV, HTML
and spreadsheets, and modelling that would be parsing. Each entry carries a uniform
envelope naming where the bytes came from — for eleven providers an HTTP call, for
`ca_eccc` a query against the local [[cache]], for `pl_imgw` a member of a downloaded
zip — with the fields that do not apply left [[unknown]], and request headers excluded
entirely so a credential has no route in. It is deliberately what parse read rather than
what came off the wire: a zip explains no value, and `ca_eccc` never touches the network,
so the wire would hand back an empty box for the one provider where a stale cache is the
likeliest cause of a wrong number.
_Avoid_: untouched payload (one unzipping step removes it from what the server sent),
response, blob"""

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
    described = "\n".join(line for line in _context().splitlines() if not line.startswith("_Avoid_:"))
    assert "untouched" not in described.lower()


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
