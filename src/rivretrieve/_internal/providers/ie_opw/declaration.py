"""Provider declaration for Ireland Office of Public Works (`ie_opw`)."""

from __future__ import annotations

from pathlib import Path

from rivretrieve._internal.providers.registration import CatalogueOnly, ProviderDeclaration

declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=CatalogueOnly(),
    required_credentials=(),
)
