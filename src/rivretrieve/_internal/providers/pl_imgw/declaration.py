"""provider declaration : PackagedCatalogue × BulkStore → DeclaredProvider."""

from pathlib import Path

from rivretrieve._internal.providers.pl_imgw import bulk, module
from rivretrieve._internal.providers.registration import BulkStore, ProviderDeclaration

declaration = ProviderDeclaration(
    catalogue=Path(__file__).with_name("catalogue"),
    observations=BulkStore(
        module=module,
        config=module.config,
        download=bulk.download,
        compile=bulk.compile,
    ),
)
