# A provider is three files over a shared engine

Each provider contributes `fetch.py`, `parse.py` and `config.py`, and nothing else.
Fetch and parse are genuine per-source code, because how bytes are obtained and how a
format is decoded differ irreducibly between sources. Config is a typed declaration
rather than code, because once parse has produced rows the only remaining differences
between providers are facts, not behaviour. Convert and assemble have no provider file
at all, since the engine performs them for everyone.

That gives a naming rule worth stating: a provider file is named for a stage only when
the provider writes code for that stage. The file is therefore `config.py`, not
`convert.py`, which removes a real collision where two filenames named stages the
provider implements and a third named a stage the engine owns.

Three alternatives were considered and rejected. A single file per provider was argued
for on contributor ownership; the counter that carried was that contributors do not own
files in a shared package, and that a `Contributed by:` docstring field rendering in the
published docs serves the same purpose without shaping the codebase around it. A class
per provider subclassing a base was the previous design; an object only earns its keep
when it holds state that is expensive to compute and reused across tasks, and nothing
here does. Pure configuration with no code at all was rejected because the irreducible
parsing cases cannot be expressed as configuration, and adding escape hatches would
turn the configuration into a second-rate programming language.
