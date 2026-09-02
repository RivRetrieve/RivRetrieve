# Vision: a provider declares itself

Program: https://github.com/RivRetrieve/RivRetrieve/issues/6
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/146

## Goal / Why

Adding a source to RivRetrieve currently means writing a provider directory and then editing
five things scattered across the codebase that have nothing to do with that source:

1. a thirteen-clause boolean guard in `_internal/discovery.py`;
2. a near-identical registration block beside it, in the same 151-line function;
3. an undocumented `if provider_id == "ca_eccc" / "pl_imgw"` chain in `_internal/bulk.py`
   that falls through to `raise AssertionError("registered bulk provider has no
   composition-root wiring")`;
4. `ORIGIN_GATE_ENROLLED_PROVIDERS` in `_internal/catalogue_origins.py`;
5. a hand-maintained per-filename census (`RUNTIME_FILE_COUNTS`) in
   `tests/test_provider_architecture_contracts.py`, patched by two literal provider tuples
   and carrying a comment explaining that an anonymous `+= 1` once silently under-reported
   because git deduplicated identical text across branches.

Two of these fail silently. Omitting the guard clause costs a re-registration scan on every
call and nothing says so. Omitting the bulk branch produces a provider that registers cleanly
and then crashes on its first download with an internal assertion.

On top of that, nine of the thirteen `module.py` files are **byte-identical** once the
provider id is substituted — 61 lines each of `info` / `products` / `stations` /
`station_products`, all delegating to the same `CatalogueReader`. Ten of the thirteen
providers register with `provider_module=None`, and ADR 0019 deleted `ProviderHandle` and
`provider` from the public surface, so **no runtime path reaches those functions at all**.
The only line of `module.py` anyone reads is `_CATALOGUE_PATH`. Eight test files still call
them, 46 times, through a door no user can open.

After this vision a provider is one directory. It declares where its catalogue lives and
which of three kinds it is; the engine dispatches on that declared kind rather than on the
provider's id, so no code anywhere asks which provider it is holding. Adding a fourteenth
source touches that directory and one manifest line.

This is a prerequisite to #17, whose eleven remaining ports would each edit the registration
switch this vision removes and each copy the 61 dead lines forward.

## Scope — In

1. **A provider declaration.** `providers/<id>/declaration.py` states the packaged catalogue
   path and the provider's kind. Named `declaration.py` rather than `provider.py` because
   every `catalogue/` directory already contains a `provider.json`.
2. **A closed set of three provider kinds**, engine-owned, in a new
   `_internal/providers/registration.py`: `CatalogueOnly` (ten today), `LiveStages`
   (fetch + parse + window declarations; one today), `BulkStore` (config + download +
   compile; two today). A source fitting none of the three is a deliberate engine change,
   not a fourth architecture invented locally.
3. **An explicit built-in manifest** — one tuple of thirteen provider ids, the single central
   file, one line per provider. Chosen over package/filesystem discovery; see Constraints.
4. **A bootstrap that walks the manifest**, replacing the 151-line
   `_ensure_default_providers_registered` and its thirteen-clause guard. Deterministic,
   idempotent, and preserving the deliberate property recorded on #17: `_provider_lookup` is
   bare `_registry.get`, safe only because every path to `fetch` comes through `find` /
   `pick` / `from_frame`, each of which registers defaults first.
5. **A unified bulk contract.** `bulk.py`'s id-string switch and its `AssertionError` are
   deleted; the engine calls `download` and `compile` off the declaration. The two
   field-for-field identical compile-request types (`HydatCompileRequest`,
   `ImgwCompileRequest` — same six fields under two names) collapse into one. One download
   signature both providers satisfy: Canada probes for the newest dated release, Poland
   derives its year from `today` and ignores the probe.
6. **Deletion of all thirteen `module.py` files**, and repointing the 46 test call sites in
   eight test files at either the shipped surface (`rr.find(provider=...)`) or the
   `CatalogueReader` the engine itself uses. Same assertions, same catalogues, real path.
7. **A derived file census.** `RUNTIME_FILE_COUNTS` and its two literal provider tuples stop
   being hand-maintained and are derived from the manifest and the declared kinds.
8. **Loud refusal on a broken install.** A provider the manifest promises but which cannot be
   loaded refuses the whole library, naming the provider and what was missing, rather than
   serving the remaining twelve.

## Scope — Out (explicit non-goals)

- **Porting any provider.** Turning a `CatalogueOnly` provider into `LiveStages` is #17.
  This vision changes how a provider is declared, never what its stages do.
- **`ORIGIN_GATE_ENROLLED_PROVIDERS`.** It records who has been *audited*, not who *ships*.
  Folding it into the declaration would let a new provider certify itself by declaring
  itself. `br_ana` and `no_nve` remain deliberately unenrolled and building.
- **A fourth provider kind.** Credentialed sources (#90), FTP sources and scraped sources are
  not accommodated speculatively. When one arrives, it is an engine change made once for
  everyone.
- **Anything the engine does with a provider once it has one.** Stage contracts (#7), window
  arithmetic (#10), result shape (#11) and store layout (#12) are settled and untouched.
- **Package/filesystem discovery of providers.** Considered and rejected; see Constraints.
- **Implicit import-time registration.** Registration stays explicit and lazy.
- **Changing the public surface.** The ten names ADR 0019 shipped are unchanged. `module.py`
  is internal and unreachable from any of them.

## Constraints

- **Manifest over discovery, decided.** #17 requires this comparison be made and justified.
  Scanning the providers directory makes the filesystem an implicit registry: a half-finished
  provider directory ships itself, ordering becomes filesystem-dependent, and "what does this
  wheel contain?" stops being answerable by reading one screen. `providers/` has no
  `__init__.py` and is a namespace package, which makes scanning cheaper to write and no
  safer. The manifest costs one line per provider and buys a reviewable diff.
- **The id is declared once.** The manifest entry *is* the id. `declaration.py` does not
  repeat it; `ProviderRegistry.register` already verifies the registered id against the
  packaged catalogue's own `provider_info["provider_id"]` and raises on mismatch.
- **No `if provider_id == ...` anywhere.** Dispatch is on the declared kind. This is the
  measurable form of the vision and it applies to `bulk.py` as much as to `discovery.py`.
- **Registration stays lazy and idempotent**, and stays explicit enough to audit.
- **The engine keeps reading catalogues from the artifact**, not through provider functions.
  `_ProviderHandle.info/products/stations/station_products` already use
  `CatalogueReader(self._artifact, ...)` directly; deleting `module.py` removes nothing they
  call.
- **`_ProviderHandle.__getattr__` forwarding must keep working** for the attributes that are
  genuinely provider-specific and not on the handle (`config`, `window_declarations`,
  `fetch`, `parse`, `cache_status`).
- **First-party content fails fast.** All thirteen providers are content RivRetrieve builds,
  commits and ships. The plugin-system convention of degrading on a broken component applies
  to third-party plugins; a missing bundled data file is a corrupt installation. Serving
  twelve of thirteen without a signal that survives into a dataframe is the silent-exclusion
  shape this project banned under *shows rather than decides* and under the origin gate.
- **NumPy-style docstrings**, and the recording rule, per `AGENTS.md`.
- No network access is required by any criterion except the packaging check, which requires a
  build and a clean install rather than a network.

## Acceptance criteria (vision-level "done")

```json
{
  "criteria": [
    {
      "name": "A new provider touches one directory",
      "input": "Add a fourteenth provider as a new directory containing a declaration and a catalogue, plus one line in the built-in manifest, changing no other file",
      "observation": "It appears in providers(), find() returns its stations, and git diff --stat names only the new directory and the manifest"
    },
    {
      "name": "A missing catalogue refuses",
      "input": "Install the package, delete one provider's catalogue directory, then call find(product=\"discharge\")",
      "observation": "The call raises naming that provider and the missing catalogue, instead of returning the other twelve providers' stations"
    },
    {
      "name": "A bulk provider needs no central wiring",
      "input": "Register a bulk provider that declares its own download and compile and is named in no branch of bulk.py, then call download() for it",
      "observation": "It downloads and compiles to a validated store; no AssertionError about composition-root wiring is reachable because no such branch exists in bulk.py"
    },
    {
      "name": "A duplicate id fails loudly",
      "input": "A built-in manifest naming the same provider id twice",
      "observation": "Registration raises naming the duplicated id, rather than registering it once or twice silently"
    },
    {
      "name": "A declaration lying about its identity fails loudly",
      "input": "A provider directory named xx_test whose packaged catalogue's provider_id says usgs_nwis",
      "observation": "Registration raises naming both the directory id and the catalogue's id"
    },
    {
      "name": "Registration is idempotent",
      "input": "Call providers(), then find(), then products() in succession in a fresh process",
      "observation": "Each provider is registered exactly once and no re-registration scan runs after the first call"
    },
    {
      "name": "A malformed declaration fails loudly",
      "input": "A declaration whose observations field is the bare string \"live\" rather than one of the three kinds",
      "observation": "Registration raises naming the provider and the unrecognised kind, rather than treating it as catalogue-only"
    },
    {
      "name": "All thirteen catalogues survive packaging",
      "input": "Build the wheel, install it into a clean environment with no repository present, import rivretrieve and call providers()",
      "observation": "Thirteen provider ids are returned and every provider's catalogue is readable from the installed wheel"
    },
    {
      "name": "No provider id is switched on",
      "input": "Scan the runtime source tree outside the providers directory for a comparison against a literal provider id",
      "observation": "No such comparison exists in discovery.py, bulk.py or any other engine module"
    },
    {
      "name": "The duplicated catalogue surface is gone",
      "input": "Search the source tree for module.py under the providers directory and run the full test suite",
      "observation": "No provider defines module.py, and the suite passes with its catalogue assertions made through the shipped surface or the shared catalogue reader"
    }
  ]
}
```

## Decomposition hints

- The declaration vocabulary and the manifest come first: nothing else can be expressed
  until `CatalogueOnly` / `LiveStages` / `BulkStore` exist and thirteen declarations are
  written. The three failure criteria (duplicate id, lying identity, malformed declaration)
  are runnable as soon as the loader exists and need no provider ported.
- The bulk unification is independent of the `module.py` deletion and can proceed in
  parallel; it only needs the declaration vocabulary. Collapsing the two identical
  compile-request types is the first move, since it is mechanical and the divergence is
  cosmetic.
- The `module.py` deletion is the largest mechanical slice — thirteen files removed, 46 call
  sites across eight test files repointed — and depends on the declarations existing, since
  `_CATALOGUE_PATH` is the one thing `module.py` still supplies.
- Fixture-shaped criteria before install-shaped ones: everything except the packaging check
  runs against the working tree.
- The derived file census should land with the declaration vocabulary, since the thing it
  derives from is the manifest.

## Open questions / risks

- The packaging criterion ("All thirteen catalogues survive packaging") is only checkable
  outside the run that delivers it: it needs a real `uv build`, a clean environment and an
  install, not a test in the working tree. Ticket #9 owns the release path; if that check
  proves to belong there, it moves, but this vision states the requirement either way.
  `pyproject.toml` declares no explicit package-data rules and each catalogue is five binary
  files in a subdirectory, so the risk is live rather than theoretical.
- The 46 test call sites are the largest source of accidental loss. They assert real
  catalogue content per provider; repointing must preserve every assertion rather than
  thinning the suite to whatever the shipped surface makes convenient. A repoint that drops
  assertions is a silent regression this vision would be blamed for.
- `tests/test_provider_architecture_contracts.py` encodes a merge hazard in a comment: an
  anonymous `+= 1` was git-deduplicated across branches and silently under-reported. Whatever
  replaces the census must not reintroduce a hand-maintained count that two branches can
  merge into one.
- Two of #11's guarantees ship designed but unexercised (the raw envelope for an archive
  member, and secret-cannot-reach-raw). Neither is touched here, but the `BulkStore` and
  credentialed-source shapes border them; a fourth provider kind for #90 is explicitly not
  pre-built.
