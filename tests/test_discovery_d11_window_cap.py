"""D11's window-cap table must re-derive from the dates it prints, and store no measurement value.

D11 is prose, and prose drifts from the evidence it describes without anything noticing. The review
on #230 found exactly that: the entry had said the source "clamps `start_date` to `end_date` minus
365 days", that 366 days was clamped, and that "one calendar year" therefore fails in leap years.
The recorded probe shows the 366-inclusive-date request was honoured. Nothing in the suite read
`docs/discoveries.md`, so every one of those statements passed.

These checks read the committed entry and re-derive its arithmetic from the dates printed in it, so
a day count that silently switches between elapsed days and inclusive calendar dates, or a row that
reasserts the corrected-away clamp, fails the build.

The day-count convention under test is **inclusive calendar dates**: both endpoints counted, so
elapsed days = dates - 1.
"""

from __future__ import annotations

import pathlib
import re
from datetime import date

DISCOVERIES = pathlib.Path(__file__).resolve().parents[1] / "docs" / "discoveries.md"

# "| 2025-06-06 .. 2026-09-06 | 458 | 2025-09-06 .. 2026-09-06 | 366 |"
_ROW = re.compile(
    r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\.\.\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([\d,]+)\s*\|\s*"
    r"(as requested|\d{4}-\d{2}-\d{2}\s*\.\.\s*\d{4}-\d{2}-\d{2})\s*\|\s*([\d,]+)\s*\|",
    re.MULTILINE,
)
_RANGE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*\.\.\s*(\d{4}-\d{2}-\d{2})")
# A measurement value pasted out of a response body, e.g. '"discharge": 104.30157'.
_MEASUREMENT = re.compile(r"\"(?:value|discharge|value_out)\"\s*:\s*-?\d")
_DISCLAIMERS = ("no rule", "not established", "supports no", "no conclusion", "no tested window", "does not")


def _section() -> str:
    text = DISCOVERIES.read_text(encoding="utf-8")
    start = text.index("## D11 —")
    nxt = text.find("\n## ", start + 1)
    return text[start:] if nxt == -1 else text[start:nxt]


def _dates(literal: str) -> int:
    return int(literal.replace(",", ""))


def _inclusive(first: str, last: str) -> int:
    return (date.fromisoformat(last) - date.fromisoformat(first)).days + 1


def test_d11_table_day_counts_are_inclusive_dates() -> None:
    """Each printed count must equal the inclusive dates of the range printed beside it."""
    rows = _ROW.findall(_section())
    assert len(rows) >= 7, f"D11's window-cap table is missing or unparseable (found {len(rows)} rows)"
    wrong: list[str] = []
    for req_first, req_last, req_dates, returned, ret_dates in rows:
        if _inclusive(req_first, req_last) != _dates(req_dates):
            wrong.append(
                f"requested {req_first}..{req_last} is {_inclusive(req_first, req_last)} "
                f"inclusive dates, table says {req_dates}"
            )
        if returned.strip() == "as requested":
            if _dates(ret_dates) != _dates(req_dates):
                wrong.append(f"{req_first}..{req_last} is 'as requested' but returns {ret_dates} of {req_dates}")
        else:
            returned_range = _RANGE.search(returned)
            assert returned_range is not None, f"unreadable returned span {returned!r}"
            got_first, got_last = returned_range.groups()
            if _inclusive(got_first, got_last) != _dates(ret_dates):
                wrong.append(
                    f"returned {got_first}..{got_last} is {_inclusive(got_first, got_last)} "
                    f"inclusive dates, table says {ret_dates}"
                )
            if _dates(ret_dates) >= _dates(req_dates):
                wrong.append(f"{req_first}..{req_last} is shown shortened but did not shrink")
            if got_last != req_last:
                wrong.append(f"{req_first}..{req_last} returned a different end date {got_last}")
    assert not wrong, "D11's window-cap table contradicts the dates it prints: " + "; ".join(wrong)


def test_d11_records_the_366_date_request_as_honoured() -> None:
    """The correction the review asked for: that request was honoured, not clamped."""
    rows = _ROW.findall(_section())
    match = [r for r in rows if (r[0], r[1]) == ("2025-09-06", "2026-09-06")]
    assert match, "D11 no longer records the 2025-09-06 .. 2026-09-06 request"
    _, _, req_dates, returned, ret_dates = match[0]
    assert _dates(req_dates) == 366, f"that request is 366 inclusive dates, D11 says {req_dates}"
    assert returned.strip() == "as requested", (
        f"the 366-inclusive-date request was honoured; D11 records it as returning {returned!r}"
    )
    assert _dates(ret_dates) == 366


def test_d11_largest_honoured_request_is_not_presented_as_the_maximum() -> None:
    honoured = [_dates(r[2]) for r in _ROW.findall(_section()) if r[3].strip() == "as requested"]
    assert honoured, "D11 records no honoured request"
    assert max(honoured) == 366
    section = _section().lower()
    assert "not a measured general maximum" in section or "demonstrated working" in section, (
        "D11 must distinguish the largest demonstrated working size from the source's maximum"
    )


def test_d11_asserts_no_unqualified_leap_year_rule() -> None:
    """The withdrawn conclusion must not come back without evidence that distinguishes the rules."""
    offending = [
        sentence.strip()
        for sentence in re.split(r"(?<=\.)\s+", _section())
        if "leap" in sentence.lower() and not any(d in sentence.lower() for d in _DISCLAIMERS)
    ]
    assert not offending, "D11 asserts a leap-year rule the probe does not establish: " + " | ".join(offending)


def test_d11_stores_no_measurement_value() -> None:
    """This project does not redistribute source observations, in documentation either."""
    found = _MEASUREMENT.findall(DISCOVERIES.read_text(encoding="utf-8"))
    assert not found, f"docs/discoveries.md stores publisher measurement values: {found}"
