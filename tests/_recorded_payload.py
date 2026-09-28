"""Native parser inputs from exact saved observation envelopes."""

from datetime import datetime

from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId


def recorded_payload(recording, station, product, config, start, end):
    product = ProductId(product)
    return Payload(
        config.products[product].coordinates,
        ((station, product),),
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime.fromisoformat(start)),
            WindowEndpoint.from_datetime(datetime.fromisoformat(end)),
        ),
        recording.content,
        SourceCallOrigin(
            recording.request.url,
            recording.request.parameters or {},
            recording.status_code,
            recording.retrieved_at,
            recording.content_type,
            UnknownOriginFact(),
            UnknownOriginFact(),
        ),
        recording.prerequisite_calls,
    )
