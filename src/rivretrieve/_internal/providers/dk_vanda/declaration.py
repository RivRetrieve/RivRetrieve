"""provider declaration : PackagedCatalogue × CatalogueOnly → DeclaredProvider.

Catalogue-only for now, matching `za_dws`'s precedent for a provider directory
that exists ahead of its `LiveStages` integration. Effort #799/#800 replace
this with `LiveStages` once retrieval behavior and engine integration land;
`dk_vanda` is deliberately not yet in `BUILTIN_PROVIDER_IDS`.
"""

from pathlib import Path

from rivretrieve._internal.providers.registration import CatalogueOnly, ProviderDeclaration

declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=CatalogueOnly(),
    required_credentials=(),
)
