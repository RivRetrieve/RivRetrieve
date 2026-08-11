# A provider's file count is determined by its kind

An HTTP provider contributes `fetch.py`, `parse.py` and `config.py`. A bulk provider
contributes `config.py` and `bulk.py`. Fetch and parse are genuine per-source code for an
HTTP provider, because how bytes are obtained and how a format is decoded differ
irreducibly between sources. Downloading a publisher artifact and compiling it into the
store are genuine per-source code for a bulk provider. Config is a typed declaration
rather than code, because the remaining differences between providers are facts, not
behaviour. Convert and assemble have no provider file at all, since the engine performs
them for everyone.

That gives a naming rule worth stating: a provider file is named for the work the
provider writes code for. An HTTP provider therefore has `fetch.py` and `parse.py`; a
bulk provider has `bulk.py`; and both have `config.py`, not `convert.py`. This removes a
real collision between filenames for work the provider performs and work the engine
owns.

Three alternatives were considered and rejected. A single file per provider was argued
for on contributor ownership; the counter that carried was that contributors do not own
files in a shared package, and that a `Contributed by:` docstring field rendering in the
published docs serves the same purpose without shaping the codebase around it. A class
per provider subclassing a base was the previous design; an object only earns its keep
when it holds state that is expensive to compute and reused across tasks, and nothing
here does. Pure configuration with no code at all was rejected because the irreducible
parsing cases cannot be expressed as configuration, and adding escape hatches would
turn the configuration into a second-rate programming language.
