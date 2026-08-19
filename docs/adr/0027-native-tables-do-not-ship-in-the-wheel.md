# Native tables do not ship in the wheel

No provider's native table is installed by `pip install rivretrieve`. What ships in its
place is the table's identity — where it lives, at which revision, and its digest —
carried by the packaged catalogue, so a user can obtain the exact table their installed
version was generated from and prove it is that one.

This overturns ADR 0013's consequence, which recorded that native tables ship in the
wheel because ADR 0015 reduced the canonical catalogue to identity and geometry and the
rest of each agency's data would otherwise leave the package entirely. That reasoning was
sound and the decision was never implemented: `pyproject.toml` has excluded
`*/catalogue/native.parquet` from the wheel throughout, so the accepted ADR and the
shipped artifact have disagreed without anyone noticing.

The decision is settled the other way for three reasons that stack. A uniform rule
applied to all thirteen sources regardless of their terms means the wheel's contents
disclose no reading of any licence, which is what keeps ADR 0004 intact once a
redistribution question is being asked at all. No runtime path reads a native table —
only the per-provider generators and their tests do — so nothing shipped needs it. And
the eleven tables are 15.8 MB, of which `usgs_nwis` alone is 14.1 MB at 26,258 rows by 55
columns, carried by every install for a file nothing opens.

The identity-not-bytes shape is the one ADR 0021 already chose, where a bulk source's
downloaded artifact is deleted after compiling and its URL, vintage and checksum survive
so a value can still be traced to a specific release. A digest of an agency's data is not
that agency's data, so nothing about this depends on rights we have not established.

## Consequence: auditing a coordinate becomes a reach

An installed package can no longer settle, offline, whether a coordinate was carried
across faithfully. The user follows the recorded identity, obtains the one immutable
file, and verifies the digest — and learns it if the file they got is not the file their
version was built from, which a bare repository link would not have told them. Agency
endpoints are unversioned and overwritten in place, so the committed native table is the
only immutable reference in the chain and the only thing worth pointing at.
