"""provider declaration : PackagedCatalogue × CatalogueOnly → DeclaredProvider."""

from pathlib import Path

from rivretrieve._internal.providers.registration import CatalogueOnly, ProviderDeclaration

declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=CatalogueOnly(),
)
