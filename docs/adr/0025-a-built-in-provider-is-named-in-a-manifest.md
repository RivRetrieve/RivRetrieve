# ADR-0025: A built-in provider is named in a manifest, not discovered

## Status

Accepted

## Context

Adding a source meant writing a provider directory and then editing five things that had
nothing to do with that source: a thirteen-clause boolean guard in `discovery.py`, a
near-identical registration block beside it, an `if provider_id == "ca_eccc" / "pl_imgw"`
chain in `bulk.py` falling through to `raise AssertionError("registered bulk provider has
no composition-root wiring")`, `ORIGIN_GATE_ENROLLED_PROVIDERS`, and a hand-maintained
per-filename census in the architecture tests. Two of those failed silently: omitting the
guard clause cost a re-registration scan on every call and nothing said so, and omitting
the bulk branch produced a provider that registered cleanly and then crashed on its first
download with an internal assertion.

Ticket #17 required that the choice between an explicit manifest and package or filesystem
discovery be made and justified rather than assumed, because its eleven remaining ports
would each edit whatever registration mechanism survives.

Discovery is the cheaper thing to write. `providers/` has no `__init__.py` and is a
namespace package, so scanning it is a few lines. That cheapness is what makes the
comparison worth recording: the reason to reject it is not effort.

ADR 0022 already established that the provider surface differs by kind — only a bulk
provider answers `download`, `cache_status` and `clear_cache` — and named this ticket as
the one that inherits that distinction.

## Decision

`BUILTIN_PROVIDER_IDS` is an explicit tuple of thirteen provider ids in one file, one line
per provider. Registration walks it. The manifest entry *is* the id; a declaration does not
repeat it, because `ProviderRegistry.register` already verifies the registered id against
the packaged catalogue's own `provider_info["provider_id"]`.

Each provider directory carries `declaration.py` stating where its packaged catalogue lives
and which of three engine-owned kinds it is: `CatalogueOnly`, `LiveStages` or `BulkStore`.
The engine dispatches on the declared kind. No comparison against a literal provider id
survives anywhere outside a provider's own directory — this applies to `bulk.py` as much as
to `discovery.py`, and is the measurable form of the decision rather than a style rule.

Package and filesystem discovery are rejected. Scanning makes the filesystem an implicit
registry: a half-finished provider directory ships itself, ordering becomes
filesystem-dependent, and "what does this wheel contain?" stops being answerable by reading
one screen. The manifest costs one line per provider and buys a reviewable diff.

Registration stays lazy, explicit and idempotent. Implicit import-time registration is
rejected for the same reason as scanning: it moves a shipping decision somewhere no one
reviews.

## Consequences

Adding a fourteenth source touches that source's own directory and one manifest line. This
is the property #17 depends on, and it is what makes the eleven remaining ports edits to
provider directories rather than edits to the engine.

A source fitting none of the three kinds is a deliberate engine change made once for
everyone, not a fourth architecture invented locally. Credentialed sources (#90), FTP
sources and scraped sources are deliberately not accommodated in advance; the closed set is
the point, and a fourth kind should cost a conversation.

A provider the manifest promises but which cannot be loaded refuses the whole library,
naming the provider and what was missing, rather than serving the remaining twelve. All
thirteen providers are content RivRetrieve builds, commits and ships; the plugin-system
convention of degrading on a broken component applies to third-party plugins, and a missing
bundled data file is a corrupt installation. Serving twelve of thirteen without a signal
that survives into a dataframe is the silent-exclusion shape this project bans under *shows
rather than decides* and under the origin gate.

Duplicate ids, a declaration whose catalogue contradicts its directory, and an unrecognised
kind all refuse loudly at registration rather than degrading to a default.

`ORIGIN_GATE_ENROLLED_PROVIDERS` stays outside the declaration. It records who has been
audited, not who ships; folding it in would let a new provider certify itself by declaring
itself. `no_nve` later entered the gate after its catalogue was certified; `br_ana`
remains deliberately unenrolled and building.

The thirteen `module.py` files are deleted. Nine were byte-identical once the provider id
was substituted, ten providers registered with `provider_module=None`, and ADR 0019 had
already removed `ProviderHandle` and `provider` from the public surface, so no runtime path
reached them; the engine reads catalogues through `CatalogueReader` and always did. Their
46 test call sites now assert the same catalogue content through the shipped surface or
that same reader.
