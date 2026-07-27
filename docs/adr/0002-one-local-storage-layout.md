# One storage layout for anything we store locally

Whenever RivRetrieve stores retrieved data on disk, it uses a single standardised
layout, and the engine queries that layout rather than the shape any particular source
happened to ship. This covers the bulk-provider cache today and a user-built archive if
we add one, since both are the same act: retrieved data at rest.

The reason is read paths, not disk space. Letting each source keep its own format means
a separate read, query and status implementation per provider, re-implemented every
time a new bulk provider arrives, and Austria is already coming. With one layout, a
provider contributes only a download step and a step that compiles its source into that
layout, and querying is written once against a data interface.

The objection considered was faithfulness: re-encoding a source's file could be read as
altering the data. It does not, because the store holds the source's native values
unchanged and all conversion happens on read, through the same convert stage every
other provider uses. Standardising the container is not the same act as changing the
numbers.

The layout itself, and the interface the engine queries it through, are not specified
here.
