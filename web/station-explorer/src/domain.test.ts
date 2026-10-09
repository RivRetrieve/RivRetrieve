import { spawnSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import {
  matchesStation,
  addStations,
  removeStation,
  stationKey,
  selectionConflicts,
  generateRequest as generateWithCatalogue,
  physicalFields,
  type Station,
} from "./domain";

// Most cases use the selected synthetic rows as their complete catalogue.
const generateRequest = (
  selected: Station[],
  filters: Parameters<typeof generateWithCatalogue>[1],
  dates: Parameters<typeof generateWithCatalogue>[2],
  providers: Parameters<typeof generateWithCatalogue>[3],
  catalogue: Station[] = selected,
) => generateWithCatalogue(selected, filters, dates, providers, catalogue);

const gauge: Station = {
  provider_id: "alpha",
  station_id: "001",
  station_name: null,
  latitude: null,
  longitude: null,
  crs: null,
  series: [
    {
      series_id: "s1",
      variant: "raw",
      published_id: "published",
      admission: "supported",
      quantity: "discharge",
      frequency: null,
      statistic: "mean",
    },
  ],
};

describe("catalogue discovery", () => {
  it("matches exact scalar facts and published variant identifiers, never unknown facts", () => {
    expect(
      matchesStation(gauge, { quantity: "discharge", variant: "published" }),
    ).toBe(true);
    expect(matchesStation(gauge, { quantity: "Discharge" })).toBe(false);
    expect(matchesStation(gauge, { frequency: "daily" })).toBe(false);
  });
});

const dates = { start: "2023-01-01", end: "2023-01-31" };
const providers = [
  { provider_id: "alpha", retrieval: true, bulk: false, credentials: [] },
];
it("preserves provider-qualified selection and never clears selection with filters", () => {
  const other = { ...gauge, provider_id: "beta" };
  const selected = addStations([gauge], [gauge, other]);
  expect(selected.map(stationKey)).toEqual([
    '["alpha","001"]',
    '["beta","001"]',
  ]);
  expect(
    selectionConflicts(selected, { frequency: "daily" })[0].reasons[0],
  ).toContain("not established");
  expect(selected).toHaveLength(2);
  expect(
    removeStation(
      removeStation(selected, stationKey(other)),
      stationKey(gauge),
    ),
  ).toEqual([]);
});
it("requires all filters on one supported fact segment", () => {
  const split: Station = {
    ...gauge,
    series: [
      gauge.series[0],
      { ...gauge.series[0], quantity: "stage", frequency: "daily" },
    ],
  };
  expect(
    matchesStation(split, { quantity: "discharge", frequency: "daily" }),
  ).toBe(false);
  expect(
    selectionConflicts([split], {
      quantity: "discharge",
      frequency: "daily",
    })[0].reasons[0],
  ).toContain("combination");
  expect(
    matchesStation(
      { ...gauge, series: [{ ...gauge.series[0], admission: "unsupported" }] },
      {},
    ),
  ).toBe(false);
});
it("blocks empty, conflicting, missing-date, invalid-date and catalogue-only output", () => {
  for (const selected of [[], removeStation([gauge], stationKey(gauge))]) {
    const preview = generateRequest(selected, {}, dates, providers);
    expect(preview.blockingReasons.length).toBeGreaterThan(0);
    expect(preview.code).not.toContain("rr.pick(");
  }
  for (const invalid of [
    { start: "", end: "" },
    { start: "2023-02-29", end: "2023-03-01" },
    { start: "2023-02-01", end: "2023-01-01" },
  ]) {
    expect(
      generateRequest([gauge], {}, invalid, providers).blockingReasons.length,
    ).toBeGreaterThan(0);
  }
  expect(
    generateRequest(
      [gauge],
      { frequency: "daily" },
      dates,
      providers,
    ).blockingReasons.join(),
  ).toContain("conflict");
  expect(
    generateRequest([gauge], {}, dates, [
      { ...providers[0], retrieval: false },
    ]).blockingReasons.join(),
  ).toContain("catalogue-only");
});

it("makes unresolved preview inert even when catalogue identifiers contain newlines", () => {
  const hostile = { ...gauge, provider_id: 'unlisted\nprint("unexpected")' };
  const preview = generateRequest([hostile], {}, dates, providers);
  expect(
    preview.code
      .split("\n")
      .every((line) => line === "" || line.startsWith("#")),
  ).toBe(true);
});

it.each(["combined", "fallback"])(
  "executes %s provider-qualified Python with synthetic APIs only",
  (mode) => {
    const selected = [
      { ...gauge, provider_id: "ca_eccc", station_id: "0001" },
      { ...gauge, provider_id: "pl_imgw", station_id: "0002" },
      {
        ...gauge,
        provider_id: "br_ana",
        station_id: '001"\nprint("not executable")\\',
      },
      { ...gauge, provider_id: "no_nve", station_id: "0001" },
    ];
    const declarations = selected.map((station) => ({
      provider_id: station.provider_id,
      retrieval: true,
      bulk: ["ca_eccc", "pl_imgw"].includes(station.provider_id),
      credentials:
        station.provider_id === "br_ana"
          ? ["ANA_IDENTIFICADOR", "ANA_SENHA"]
          : station.provider_id === "no_nve"
            ? ["NVE_API_KEY"]
            : [],
    }));
    const catalogue = [
      ...selected,
      { ...gauge, provider_id: "pl_imgw", station_id: "not-selected" },
      { ...gauge, provider_id: "outside-selection", station_id: "0001" },
      ...(mode === "fallback"
        ? [{ ...gauge, provider_id: "pl_imgw", station_id: "0001" }]
        : []),
    ];
    const preview = generateRequest(
      [...selected, selected[0]],
      { quantity: "discharge" },
      dates,
      declarations,
      catalogue,
    );
    expect(preview.blockingReasons).toEqual([]);
    for (const name of [
      "ANA_IDENTIFICADOR",
      "ANA_SENHA",
      "NVE_API_KEY",
      "SQLITE_TMPDIR",
      "TMPDIR",
    ])
      expect(preview.code).toContain(name);
    expect(preview.code).toContain("#     result.to_polars().write_csv(");
    const execution = spawnSync(
      "uv",
      [
        "run",
        "python",
        "-c",
        `
import json, sys, types
payload = json.load(sys.stdin)
calls = []
def find(**filters):
    calls.append(["find", filters])
    return types.SimpleNamespace(issues=("discovery issue",), pairs=payload["catalogue"])
def pick(selection, **filters):
    calls.append(["pick", filters])
    providers = filters["provider"]
    providers = [providers] if isinstance(providers,str) else providers
    ids = filters["station"]
    pairs = [(p,s) for p,s in selection.pairs if (not providers or p in providers) and (not ids or s in ids)]
    return types.SimpleNamespace(issues=selection.issues + ("pick issue",), filters=filters, pairs=pairs)
def fetch(selection, **dates):
    calls.append(["fetch", selection.filters, dates])
    actual={"provider":selection.filters["provider"], "station":[s for p,s in selection.pairs]}
    return types.SimpleNamespace(issues=selection.issues + ("synthetic issue",), filters=actual, dates=dates)
def fetch_by_provider(selection, **dates):
    calls.append(["fetch_by_provider", selection.filters, dates])
    return {provider: types.SimpleNamespace(
        issues=selection.issues + ("synthetic issue",),
        filters={"provider": provider, "station": [station for p, station in selection.pairs if p == provider]},
        dates=dates,
    ) for provider in dict.fromkeys(p for p,s in selection.pairs)}
def download(provider):
    calls.append(["download", provider])
sys.modules["rivretrieve"] = types.SimpleNamespace(find=find, pick=pick, fetch=fetch, fetch_by_provider=fetch_by_provider, download=download)
namespace = {}
exec(compile(payload["code"], "generated.py", "exec"), namespace)
print(json.dumps({provider: [result.filters, result.dates] for provider, result in namespace["results_by_provider"].items()}))
print(json.dumps(calls))
`,
      ],
      {
        input: JSON.stringify({
          code: preview.code,
          catalogue: catalogue.map((station) => [
            station.provider_id,
            station.station_id,
          ]),
        }),
        encoding: "utf8",
        cwd: "../..",
      },
    );
    expect(execution.status, execution.stderr).toBe(0);
    const output = execution.stdout.trim().split("\n");
    for (const issue of ["discovery issue", "pick issue", "synthetic issue"])
      expect(output.filter((line) => line === issue)).toHaveLength(4);
    expect(JSON.parse(output.at(-2)!)).toEqual(
      Object.fromEntries(
        selected.map((station) => [
          station.provider_id,
          [
            { provider: station.provider_id, station: [station.station_id] },
            dates,
          ],
        ]),
      ),
    );
    const calls = JSON.parse(output.at(-1)!);
    expect(calls.slice(0, 2)).toEqual([
      ["download", "ca_eccc"],
      ["download", "pl_imgw"],
    ]);
    expect(calls.filter((call: unknown[]) => call[0] === "find")).toEqual([
      ["find", { quantity: "discharge" }],
    ]);
    expect(calls.filter((call: unknown[]) => call[0] === "download")).toEqual([
      ["download", "ca_eccc"],
      ["download", "pl_imgw"],
    ]);
    if (mode === "combined") {
      const filters = {
        provider: ["ca_eccc", "pl_imgw", "br_ana", "no_nve"],
        station: ["0001", "0002", selected[2].station_id],
      };
      expect(calls.filter((call: unknown[]) => call[0] === "pick")).toEqual([
        ["pick", filters],
      ]);
      expect(
        calls.filter((call: unknown[]) => call[0] === "fetch_by_provider"),
      ).toEqual([["fetch_by_provider", filters, dates]]);
      expect(calls.filter((call: unknown[]) => call[0] === "fetch")).toEqual(
        [],
      );
    } else {
      expect(calls.filter((call: unknown[]) => call[0] === "pick")).toEqual(
        selected.map((station) => [
          "pick",
          { provider: station.provider_id, station: [station.station_id] },
        ]),
      );
      expect(calls.filter((call: unknown[]) => call[0] === "fetch")).toEqual(
        selected.map((station) => [
          "fetch",
          { provider: station.provider_id, station: [station.station_id] },
          dates,
        ]),
      );
      expect(
        calls.filter((call: unknown[]) => call[0] === "fetch_by_provider"),
      ).toEqual([]);
    }
  },
);
it("retains every selected ID in long code and leaves CSV export commented", () => {
  const selected = Array.from({ length: 2000 }, (_, index) => ({
    ...gauge,
    station_id: String(index).padStart(6, "0"),
  }));
  const preview = generateRequest(
    selected,
    {},
    { start: "2024-02-29", end: "2024-02-29" },
    providers,
  );
  expect(preview.blockingReasons).toEqual([]);
  for (const station of selected)
    expect(preview.code).toContain(JSON.stringify(station.station_id));
  expect(preview.code).toContain(
    '# results.to_polars().write_csv("observations.csv")',
  );
  expect(preview.code).not.toMatch(/^results\.to_polars/m);
});
it("distinguishes a known literal unknown from an unestablished fact and intersects identities", () => {
  const station: Station = {
    ...gauge,
    series: [
      { ...gauge.series[0], time_zone: "unknown", time_zone_state: "known" },
    ],
  };
  expect(
    matchesStation(station, {
      time_zone: "unknown",
      variant: "published",
      series_id: "s1",
    }),
  ).toBe(true);
  expect(matchesStation(station, { variant: "raw", series_id: "other" })).toBe(
    false,
  );
  expect(
    matchesStation(
      {
        ...station,
        series: [{ ...station.series[0], time_zone_state: "not_established" }],
      },
      { time_zone: "unknown" },
    ),
  ).toBe(false);
});

it.each(physicalFields)(
  "matches %s as an exact scalar on established facts",
  (field) => {
    const station: Station = {
      ...gauge,
      series: [
        {
          ...gauge.series[0],
          [field]: "source value",
          [`${field}_state`]: "known",
        },
      ],
    };
    expect(matchesStation(station, { [field]: "source value" })).toBe(true);
    expect(matchesStation(station, { [field]: "source" })).toBe(false);
    expect(matchesStation(station, { [field]: "SOURCE VALUE" })).toBe(false);
    expect(
      matchesStation(
        {
          ...station,
          series: [
            {
              ...station.series[0],
              [field]: null,
              [`${field}_state`]: "source_silent",
            },
          ],
        },
        { [field]: "source value" },
      ),
    ).toBe(false);
  },
);
it("keeps provider and station restrictions exact, including leading zeros", () => {
  expect(matchesStation(gauge, { provider: "alpha", station: "001" })).toBe(
    true,
  );
  expect(matchesStation(gauge, { provider: "beta" })).toBe(false);
  expect(matchesStation(gauge, { station: "1" })).toBe(false);
});

it("leaves optional end to Python runtime and never invents a date", () => {
  const preview = generateRequest(
    [gauge],
    {},
    { start: "2023-01-01", end: "" },
    providers,
  );
  expect(preview.blockingReasons).toEqual([]);
  expect(preview.code).toContain("end=None");
  expect(preview.code).not.toContain("caller machine");
  expect(
    generateRequest(
      [gauge],
      {},
      { start: "2023-01-01", end: "2023-02-30" },
      providers,
    ).blockingReasons.length,
  ).toBeGreaterThan(0);
});

it("explains a selected catalogue entry with no source series without discarding it", () => {
  const station = { ...gauge, series: [] };
  expect(selectionConflicts([station], {})[0].reasons).toContain(
    "No source series is established for this catalogue entry. It cannot match the current discovery request.",
  );
});

it("combines non-overlapping provider identities in one native retrieval", () => {
  const selected = [
    gauge,
    { ...gauge, provider_id: "beta", station_id: "002" },
  ];
  const preview = generateRequest(selected, { quantity: "discharge" }, dates, [
    ...providers,
    { ...providers[0], provider_id: "beta" },
  ]);
  expect(preview.code).toBe(`import rivretrieve as rr

selection = rr.find(quantity="discharge")
gauges = rr.pick(
    selection,
    provider=["alpha", "beta"],
    station=[
        "001",
        "002",
    ],
)
results_by_provider = rr.fetch_by_provider(
    gauges,
    start="2023-01-01",
    end="2023-01-31",
)
for result in results_by_provider.values():
    for issue in result.issues:
        print(issue)

# for provider, result in results_by_provider.items():
#     result.to_polars().write_csv(f"observations_{provider}.csv")`);
});

it("combines an ID selected in both providers but falls back for an unselected cross-pair", () => {
  const beta = { ...gauge, provider_id: "beta" };
  const declarations = [...providers, { ...providers[0], provider_id: "beta" }];
  const shared = generateRequest([gauge, beta], {}, dates, declarations);
  expect(shared.code).toContain('provider=["alpha", "beta"]');
  expect(shared.code).toContain('station=[\n        "001",\n    ]');
  expect(shared.code).toContain("rr.fetch_by_provider(");
  const selected = [gauge, { ...beta, station_id: "002" }];
  const crossed = generateRequest(selected, {}, dates, declarations, [
    ...selected,
    beta,
  ]);
  expect(crossed.code).not.toContain("rr.fetch_by_provider(");
  expect(crossed.code).toContain('"alpha": [\n        "001",\n    ]');
  expect(crossed.code).toContain('"beta": [\n        "002",\n    ]');
  expect(crossed.code).toContain(
    "# Keep provider/station pairs exact where IDs overlap.",
  );
});

it("renders an unrestricted discovery but exact single-provider pick without a loop", () => {
  expect(generateRequest([gauge], {}, dates, providers).code)
    .toBe(`import rivretrieve as rr

selection = rr.find()
gauges = rr.pick(
    selection,
    provider="alpha",
    station=[
        "001",
    ],
)
results = rr.fetch(
    gauges,
    start="2023-01-01",
    end="2023-01-31",
)
for issue in results.issues:
    print(issue)

# results.to_polars().write_csv("observations.csv")`);
});

it("limits only displayed IDs to ten, preserving provider keys and omitted counts", () => {
  const selected = Array.from({ length: 12 }, (_, index) => ({
    ...gauge,
    provider_id: index < 9 ? "alpha" : index < 11 ? "beta" : "gamma",
    station_id: String(index).padStart(4, "0"),
  }));
  const declarations = ["alpha", "beta", "gamma"].map((provider_id) => ({
    ...providers[0],
    provider_id,
  }));
  const ten = generateRequest(selected.slice(0, 10), {}, dates, declarations, [
    ...selected,
    { ...gauge, provider_id: "gamma", station_id: "0000" },
  ]);
  expect(ten.previewCode).toBe(ten.code);
  expect(ten.omittedStationCount).toBe(0);
  const eleven = generateRequest(
    selected.slice(0, 11),
    {},
    dates,
    declarations,
    [...selected, { ...gauge, provider_id: "beta", station_id: "0000" }],
  );
  expect(eleven.omittedStationCount).toBe(1);
  expect(eleven.previewCode).toContain(
    '"beta": [\n        "0009",\n        … 1 more station IDs omitted\n    ],',
  );
  const twelve = generateRequest(selected, {}, dates, declarations, [
    ...selected,
    { ...gauge, provider_id: "gamma", station_id: "0000" },
  ]);
  expect(twelve.omittedStationCount).toBe(2);
  expect(twelve.previewCode).toContain(
    '"gamma": [\n        … 1 more station IDs omitted\n    ],',
  );
  for (const station of selected.slice(0, 10))
    expect(twelve.previewCode).toContain(JSON.stringify(station.station_id));
  for (const station of selected.slice(10))
    expect(twelve.previewCode).not.toContain(
      JSON.stringify(station.station_id),
    );
  for (const station of selected)
    expect(twelve.code).toContain(JSON.stringify(station.station_id));
  expect(twelve.code).not.toContain("omitted");
});

it("limits a single-provider display and keeps blocked previews inert", () => {
  const selected = Array.from({ length: 11 }, (_, index) => ({
    ...gauge,
    station_id: String(index).padStart(4, "0"),
  }));
  const preview = generateRequest(selected, {}, dates, providers);
  expect(preview.omittedStationCount).toBe(1);
  expect(preview.previewCode).toContain("… 1 more station IDs omitted");
  expect(preview.previewCode).not.toContain('"0010"');
  expect(preview.code).toContain('"0010"');
  const blocked = generateRequest(
    selected,
    { frequency: "daily" },
    dates,
    providers,
  );
  expect(
    blocked.previewCode
      .split("\n")
      .every((line) => !line || line.startsWith("#")),
  ).toBe(true);
});

it("counts deduplicated IDs in a combined preview", () => {
  const alpha = Array.from({ length: 11 }, (_, i) => ({
    ...gauge,
    station_id: String(i).padStart(4, "0"),
  }));
  const selected = [
    ...alpha,
    ...alpha.map((station) => ({ ...station, provider_id: "beta" })),
  ];
  const preview = generateRequest(selected, {}, dates, [
    ...providers,
    { ...providers[0], provider_id: "beta" },
  ]);
  expect(preview.omittedStationCount).toBe(1);
  expect(preview.previewCode).toContain('provider=["alpha", "beta"]');
  expect(preview.previewCode).toContain("… 1 more station IDs omitted");
  expect(preview.previewCode).not.toContain('"0010"');
  expect(preview.code).toContain('"0010"');
});

it.each(["combined", "fallback"])(
  "shortened %s display cannot execute before all identifiers are restored",
  (mode) => {
    const selected = [
      ...Array.from({ length: 11 }, (_, i) => ({
        ...gauge,
        provider_id: "alpha",
        station_id: `gauge-${i}`,
      })),
      { ...gauge, provider_id: "beta", station_id: "later-provider" },
    ];
    const declarations = [
      { provider_id: "alpha", retrieval: true, bulk: true, credentials: [] },
      { provider_id: "beta", retrieval: true, bulk: false, credentials: [] },
    ];
    const complete =
      mode === "fallback"
        ? [
            ...selected,
            { ...gauge, provider_id: "alpha", station_id: "later-provider" },
          ]
        : selected;
    const preview = generateRequest(
      selected,
      {},
      dates,
      declarations,
      complete,
    );
    const run = spawnSync(
      "uv",
      [
        "run",
        "python",
        "-c",
        `
import json,sys,types
source=json.load(sys.stdin)
calls=[]
def forbidden(*args,**kwargs):
    calls.append("called")
    raise RuntimeError("preview reached an external operation")
sys.modules["rivretrieve"]=types.SimpleNamespace(find=forbidden,pick=forbidden,fetch=forbidden,fetch_by_provider=forbidden,download=forbidden)
try:
    exec(source["preview"],{})
except SyntaxError:
    print("syntax blocked")
except Exception:
    print("external operation reached")
print(json.dumps(calls))
compile(source["full"],"complete.py","exec")
`,
      ],
      {
        input: JSON.stringify({
          preview: preview.previewCode,
          full: preview.code,
        }),
        encoding: "utf8",
        cwd: "../..",
      },
    );
    expect(run.status, run.stderr).toBe(0);
    expect(run.stdout.trim().split("\n")).toEqual(["syntax blocked", "[]"]);
    if (mode === "fallback")
      expect(preview.previewCode).not.toContain('"beta": []');
  },
);
