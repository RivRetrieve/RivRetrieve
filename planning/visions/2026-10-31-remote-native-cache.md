# Remote native cache

RivRetrieve can retain its native observation cache in a user-owned S3-compatible
bucket instead of a persistent local directory. Normal retrieval reads reusable
cached data from the bucket and writes newly acquired data back automatically.
Users can build an RR archive directly in their bucket without manually uploading
or restoring local snapshots. The motivating use case is acquisition on a Hetzner
VM with retained data in Hetzner object storage.

Implementing this vision completes [issue #620](https://github.com/RivRetrieve/RivRetrieve/issues/620).
Publishing this document does not complete the issue.

## Scope and behavior

- Support a bucket/prefix and a configurable S3-compatible endpoint, including
  non-AWS storage. Resolve configuration and credentials at public composition
  boundaries. Keep credentials out of stored records and diagnostics.
- The remote store is the retained cache. Temporary local files are acceptable;
  a persistent local cache and a full-cache download are not required for reuse.
- Preserve the existing native representation, provenance, integrity checks,
  coverage-based reuse and refresh behavior. Local caching remains available.
- Keep the work in shared storage and configuration. Provider fetch and parse
  logic should not need a provider-wide refactor or knowledge of S3.
- Do not expand the local cache's feature set or concurrency guarantees. Multiple
  VMs, distributed writer coordination and new multi-writer capabilities are out
  of scope. Object-storage publication must nevertheless handle interrupted
  operations safely and must not expose incomplete data as a valid cache.
- Add one very short section to the existing user documentation, following
  [docs/AGENTS.md](../../docs/AGENTS.md). Give only the setup needed to use the
  feature and a compact practical example, including installation if applicable.
  Avoid a long backend explanation or a separate documentation project.

## Implementation direction

Use an established object-storage library rather than building authentication,
transfer, multipart-upload or transport-retry machinery in RR. RR remains
responsible for its cache semantics and integrity. Choose the approach that keeps
RR-owned code small; do not build a general backend framework or several competing
client integrations.

`obstore` is a candidate, not a required dependency. PyArrow is already a project
dependency and also provides S3 filesystem access. The implementing agent chooses
the library, configuration API and dependency packaging. An optional installation
extra is reasonable if adding `obstore`; it is not a settled requirement. If an
extra is needed but missing, explain how to install it instead of silently using
a local cache.

The current `_resolve_store_root` in `src/rivretrieve/_internal/discovery.py`
resolves `RIVRETRIEVE_CACHE_DIR` as a local `Path`. Shared store code under
`src/rivretrieve/_internal/store/` uses local filesystem operations, including
hardlinks and publication machinery. Merely accepting an S3 URL or mounting a
bucket does not establish equivalent behavior. Adapt this shared boundary to
object storage without assuming local locking and rename semantics apply there.
Follow the [architecture](../../docs/architecture.md) and
[observation-store contract](../../docs/design/observation-store-layout.md).

Remote storage does not add source fields that the existing cache does not retain.
Source quality-field preservation is separate work.

## Evidence of completion

Show that normal retrieval populates a configured S3-compatible cache, and a later
retrieval can reuse that cache without a persistent local copy or another source
acquisition for covered data. Show that newly acquired coverage is retained
remotely and existing cache semantics and local behavior remain intact.

Cover interruption and integrity failures at the shared storage boundary so an
incomplete or corrupt publication cannot masquerade as reusable data. Match checks
to the chosen implementation and the repository testing and evidence guidance;
this work does not require a new provider-by-provider certification campaign.
Document the supported configuration in the short user section described above.
