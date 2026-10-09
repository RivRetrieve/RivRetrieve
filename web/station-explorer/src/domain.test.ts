import { spawnSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import {
  matchesStation,
  addStations,
  removeStation,
  stationKey,
  selectionConflicts,
  generateRequest,
  physicalFields,
  type Station,
} from "./domain";

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

it("executes complete provider-qualified Python with synthetic APIs only", () => {
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
  const preview = generateRequest(
    selected,
    { quantity: "discharge" },
    dates,
    declarations,
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
    return types.SimpleNamespace(issues=())
def pick(selection, **filters):
    calls.append(["pick", filters])
    return types.SimpleNamespace(issues=(), filters=filters)
def fetch(selection, **dates):
    calls.append(["fetch", selection.filters, dates])
    return types.SimpleNamespace(issues=("synthetic issue",))
def download(provider):
    calls.append(["download", provider])
sys.modules["rivretrieve"] = types.SimpleNamespace(find=find, pick=pick, fetch=fetch, download=download)
exec(compile(payload["code"], "generated.py", "exec"))
print(json.dumps(calls))
`,
    ],
    {
      input: JSON.stringify({ code: preview.code }),
      encoding: "utf8",
      cwd: "../..",
    },
  );
  expect(execution.status, execution.stderr).toBe(0);
  const output = execution.stdout.trim().split("\n");
  expect(output.filter((line) => line === "synthetic issue")).toHaveLength(4);
  const calls = JSON.parse(output.at(-1)!);
  expect(calls.filter((call: unknown[]) => call[0] === "find")).toEqual([
    ["find", { quantity: "discharge" }],
  ]);
  expect(calls.filter((call: unknown[]) => call[0] === "download")).toEqual([
    ["download", "ca_eccc"],
    ["download", "pl_imgw"],
  ]);
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
});
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
  expect(preview.code).toContain("caller machine");
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
