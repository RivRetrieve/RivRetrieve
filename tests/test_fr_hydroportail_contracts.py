"""Fatal HydroPortail internal stage contract errors stay fatal."""

from dataclasses import replace

import pytest

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.fr_hydroportail.config import config
from rivretrieve._internal.providers.fr_hydroportail.parse import parse
from tests.test_fr_hydroportail_station import _empty_payload


@pytest.mark.recorded(
    "tests/test_data/fr_hydroportail_J783301020_empty.body",
    "tests/test_data/fr_hydroportail_J783301020_empty.receipt.json",
)
def test_unknown_payload_product_is_fatal_contract_error(retained_evidence_root):
    payload = replace(_empty_payload(retained_evidence_root), station_products=(("J783301020", ProductId("unknown")),))
    with pytest.raises(FatalContractError):
        parse(payload, config())
