"""ThaiWater declared source failure remains an issue, not a parser-contract defect."""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import polars as pl
from polars.testing import assert_frame_equal

from rivretrieve._internal.engine import (
    Payload,
    RowsSchema,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.providers.th_thaiwater.declaration import declaration
from rivretrieve._internal.providers.th_thaiwater.fetch import ThThaiWaterGraphRoute
from rivretrieve._internal.providers.th_thaiwater.issue_codes import ThThaiWaterObservationIssueCodes


def _recorded_database_failure() -> Payload:
    # This is the complete historical source answer plus its actual acquisition receipt.
    # It has no executed-header evidence, so is not relabelled as a current runtime-v2 interaction.
    root = Path(__file__).resolve().parents[1] / "maintenance/catalogue/th_thaiwater"
    request_id = "1109499_2026-06-08_2026-09-06_a1"
    with (root / "evidence/graph_receipts.csv").open(newline="") as handle:
        receipt = next(row for row in csv.DictReader(handle) if row["request_id"] == request_id)
    body = (root / "recordings" / f"{request_id}.body").read_bytes()
    assert len(body) == int(receipt["response_bytes"])
    assert hashlib.sha256(body).hexdigest() == receipt["response_sha256"]
    url = urlparse(receipt["request_url"])
    return Payload(
        source_coordinates=SourceCoordinates(ThThaiWaterGraphRoute()),
        station_products=(("1109499", ProductId("stage_reported")),),
        fetch_window=_make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2026, 6, 8)),
            WindowEndpoint.from_datetime(datetime(2026, 9, 6, 23, 59, 59, 999999)),
        ),
        content=body,
        prerequisite_calls=(),
        origin=SourceCallOrigin(
            url=f"{url.scheme}://{url.netloc}{url.path}",
            request_parameters={key: values[0] for key, values in parse_qs(url.query).items()},
            status_code=int(receipt["http_status"]),
            retrieved_at=datetime.fromisoformat(receipt["retrieved_at"]),
            content_type=receipt["content_type"],
            source_path=UnknownOriginFact(),
            query=UnknownOriginFact(),
        ),
    )


def test_recorded_http200_database_failure_returns_source_issue() -> None:
    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages
    result = stages.parse(_recorded_database_failure(), stages.config)
    assert_frame_equal(result.rows, pl.DataFrame(schema=RowsSchema.polars_schema))
    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.status == "failed"
    assert outcome.series_id == result.series[0].series_id
    assert outcome.station_id == "1109499"
    assert outcome.product_id == "stage_reported"
    assert "500:  Internal Database Error ...pq: out of shared memory" in outcome.reason
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.severity == "error"
    assert issue.code == ThThaiWaterObservationIssueCodes.SOURCE_REQUEST_FAILED
    assert issue.details is not None
    assert issue.details["station_id"] == "1109499"
    assert issue.details["source_message"] == "500:  Internal Database Error ...pq: out of shared memory"


def test_malformed_failure_message_and_broken_json_remain_identified_unsupported_outcomes() -> None:
    import json
    from dataclasses import replace

    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages
    payload = _recorded_database_failure()
    document = json.loads(payload.content)
    del document["data"]
    for content, reason in (
        (json.dumps(document).encode(), "source failure must carry"),
        (payload.content[:-1], "not valid JSON"),
    ):
        result = stages.parse(replace(payload, content=content), stages.config)
        assert result.rows.is_empty()
        assert result.outcomes[0].status == "unsupported"
        assert result.outcomes[0].series_id == result.series[0].series_id
        assert result.outcomes[0].station_id == "1109499"
        assert reason in result.outcomes[0].reason
        assert result.issues[0].code == "unsupported_source_structure"


def test_unknown_result_state_is_unsupported_not_an_asserted_source_failure() -> None:
    import json
    from dataclasses import replace

    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages
    payload = _recorded_database_failure()
    document = json.loads(payload.content)
    document["result"] = "BROKEN-CONTRACT"
    result = stages.parse(replace(payload, content=json.dumps(document).encode()), stages.config)
    assert result.rows.is_empty()
    assert result.outcomes[0].status == "unsupported"
    assert result.outcomes[0].series_id == result.series[0].series_id
    assert "result must be 'OK'" in result.outcomes[0].reason
    assert result.issues[0].code == "unsupported_source_structure"
    assert all(issue.code != ThThaiWaterObservationIssueCodes.SOURCE_REQUEST_FAILED for issue in result.issues)
