"""Derived readings of one recorded response: identities, counts and endpoints, never a value.

    derive : ResponseBytes -> Readings   (pure)

Used wherever a response carrying observations is receipted instead of kept: the reading records what
the response established (how many rows, which entity answered, which instants it spans) without
copying any measurement.
"""

from __future__ import annotations

import html
import json
import re

DATE_FIELDS = ("date_obs", "date_obs_elab", "date_mesure_temp")


def page_text(raw: bytes) -> str:
    """Visible text of an HTML or XML page: scripts and tags removed, entities decoded, spaces collapsed.

    Quoted passages are checked against this text, so a quote is always a slice of the recorded bytes.
    """
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", raw.decode("utf-8", "replace"), flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def _codes(rows: list[dict], field: str) -> list[str]:
    return sorted({"<null>" if row.get(field) is None else str(row[field]) for row in rows if field in row})


def derive(raw: bytes) -> dict[str, object]:
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"parse": "not_json"}
    if not isinstance(document, dict):
        return {"parse": "json_non_object"}
    if isinstance(document.get("series"), dict):
        series = document["series"]
        data = series.get("data") or []
        statistics = document.get("statistics")
        return {
            "parse": "hydroportail_series",
            "series_code": series.get("code"),
            "series_metric": series.get("metric"),
            "series_title": series.get("title"),
            "range": document.get("range"),
            "timezone": document.get("timezone"),
            "points": len(data),
            "point_fields": sorted(data[0]) if data else [],
            "first_t": data[0].get("t") if data else None,
            "last_t": data[-1].get("t") if data else None,
            "statistics_state": "absent" if statistics is None else ("empty" if not statistics else "populated"),
        }
    if "count" in document and isinstance(document.get("data"), list):
        rows = [row for row in document["data"] if isinstance(row, dict)]
        reading: dict[str, object] = {
            "parse": "hubeau_page",
            "count": document.get("count"),
            "rows": len(rows),
            "row_fields": sorted({key for row in rows for key in row}),
            "returned_code_station": _codes(rows, "code_station"),
            "returned_code_site": _codes(rows, "code_site"),
        }
        for field in DATE_FIELDS:
            instants = sorted(str(row[field]) for row in rows if row.get(field))
            if instants:
                reading[f"{field}_min"] = instants[0]
                reading[f"{field}_max"] = instants[-1]
        return reading
    if "field_errors" in document or ("code" in document and "message" in document):
        return {"parse": "hubeau_error", "code": document.get("code"), "message": document.get("message")}
    return {"parse": "json_other", "keys": sorted(document)}
