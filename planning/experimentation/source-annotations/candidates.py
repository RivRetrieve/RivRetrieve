"""Synthetic representation experiments; not a RivRetrieve runtime API.

Fixed, invented source schema. Ordinals label occurrences inside one acquisition;
they do not establish publisher identity across pages or acquisitions.
"""

import json
from dataclasses import dataclass

import polars as pl

TAG = pl.Struct({"kind": pl.String, "string": pl.String, "strings": pl.List(pl.String)})
CORE = {"occurrence": pl.String, "series_id": pl.String, "time": pl.Int64, "value": pl.Float64}
FIELDS = {"status": pl.String, "tag": TAG, "code": pl.Int64}
SCHEMA = CORE | {
    key: dtype for name, dtype in FIELDS.items() for key, dtype in [(name, dtype), (name + "__present", pl.Boolean)]
}


@dataclass
class Candidate:
    data: pl.DataFrame
    kind: str = "columns"
    annotations: pl.DataFrame | None = None

    def fields(self):
        # No publisher meanings were supplied by this invented fixture.
        return pl.DataFrame(
            {
                "source_name": list(FIELDS),
                "dtype": [str(t) for t in FIELDS.values()],
                "scope": ["observation"] * 3,
                "meaning": [None] * 3,
                "reference": [None] * 3,
            },
            schema_overrides={"meaning": pl.String, "reference": pl.String},
        )

    def view(self):
        if self.kind == "columns":
            return self.data
        if self.kind == "linked":
            keys = self.annotations["occurrence"]
            if keys.n_unique() != len(keys) or set(keys) != set(self.data["occurrence"]):
                raise ValueError("annotation occurrence keys must match measurements exactly")
            return self.data.join(
                self.annotations, on="occurrence", how="left", validate="1:1", maintain_order="left"
            ).select(*SCHEMA)
        if self.kind == "json":
            records = [{**row, **json.loads(row["annotations"])} for row in self.data.iter_rows(named=True)]
            return typed_rows(records).with_columns(self.data["occurrence"])
        # Long cells keep separate native typed arms, not a stringified value.
        frame = self.data
        for name in FIELDS:
            cells = self.annotations.filter(pl.col("field") == name).select(
                "occurrence", pl.col(name), pl.col("present").alias(name + "__present")
            )
            frame = frame.join(cells, on="occurrence", how="left", validate="1:1", maintain_order="left")
        return frame.select(*SCHEMA)


def typed_rows(records):
    rows = []
    for index, record in enumerate(records):
        row = {"occurrence": f"synthetic:{index}", **{name: record[name] for name in ("series_id", "time", "value")}}
        for name in FIELDS:
            value = record.get(name)
            if name == "tag" and value is not None:
                value = {
                    "kind": "list" if isinstance(value, list) else "string",
                    "string": value if isinstance(value, str) else None,
                    "strings": value if isinstance(value, list) else None,
                }
            row[name] = value
            row[name + "__present"] = name in record
        rows.append(row)
    return pl.DataFrame(rows, schema=SCHEMA)


def build(records, candidate):
    frame = typed_rows(records)
    if candidate == "columns":
        return Candidate(frame)
    core = frame.select(*CORE)
    if candidate == "linked":
        return Candidate(core, candidate, frame.select("occurrence", *[name for name in SCHEMA if name not in CORE]))
    if candidate == "long":
        cells = []
        for row in frame.iter_rows(named=True):
            for name in FIELDS:
                cells.append(
                    {
                        "occurrence": row["occurrence"],
                        "field": name,
                        "present": row[name + "__present"],
                        name: row[name],
                    }
                )
        return Candidate(
            core,
            candidate,
            pl.DataFrame(cells, schema={"occurrence": pl.String, "field": pl.String, "present": pl.Boolean} | FIELDS),
        )
    if candidate == "json":
        encoded = [json.dumps({name: record[name] for name in FIELDS if name in record}) for record in records]
        return Candidate(core.with_columns(pl.Series("annotations", encoded, dtype=pl.String)), candidate)
    raise ValueError(candidate)
