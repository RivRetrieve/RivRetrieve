import { spawnSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import { decodeCatalogue } from "../catalogue/index";
import { dateErrors } from "./dates";
import { generateRequest } from "./pythonRequest";
import { removeStation, stationKey } from "./selection";
import { physicalFields, type FactState, type Provider, type StationRecord } from "./types";

const dates = { start: "2023-01-01", end: "2023-01-31" };
const providers: Provider[] = [
  { provider_id: "alpha", retrieval: true, bulk: false, credentials: [] },
];

function makeCatalogue(
  providerList: Provider[] = providers,
  stations: [number, string][] = [[0, "001"]],
  frequency: string | null = null,
) {
  const base = Object.fromEntries(
    physicalFields.map((f) => [f, { value: null, state: "not_established" as FactState }]),
  ) as Record<(typeof physicalFields)[number], { value: string | null; state: FactState }>;
  return decodeCatalogue({
    version: 3,
    providers: providerList,
    facts: [
      {
        ...base,
        quantity: { value: "discharge", state: "known" },
        statistic: { value: "mean", state: "known" },
        frequency: frequency ? { value: frequency, state: "known" } : { value: null, state: "not_established" },
        admission: "supported",
      },
    ],
    fact_sets: [[0]],
    stations: stations.map(([providerIdx, sid]) => [providerIdx, sid, null, null, null, null, [], 0]),
  });
}

describe("Python request generation and date validation", () => {
  it("keeps browsing changes out of selected requests and measurement conflicts", () => {
    const cat = makeCatalogue([
      { provider_id: "alpha", retrieval: true, bulk: false, credentials: [] },
      { provider_id: "beta", retrieval: true, bulk: false, credentials: [] },
    ], [[0, "001"], [1, "002"]]);
    const selected = cat.stations;
    const settings = { quantity: "discharge" };
    const expected = generateRequest(selected, settings, dates, cat);
    for (const browse of [
      { provider: "alpha", station: "001" },
      { provider: "beta", station: "002" },
      { provider: "outside", station: "not-selected" },
      {},
    ]) {
      expect(generateRequest(selected, { ...settings, ...browse }, dates, cat)).toEqual(expected);
    }
    const incompatible = generateRequest(selected, { quantity: "stage", provider: "outside" }, dates, cat);
    expect(incompatible.conflicts).toHaveLength(2);
    expect(incompatible.blockingReasons.join()).toContain("request settings");
  });

  it("blocks empty, conflicting, missing-date, invalid-date, invalid-frequency, and catalogue-only output", () => {
    const cat = makeCatalogue();
    const gauge = cat.stations[0];
    for (const selected of [[], removeStation([gauge], stationKey(gauge))]) {
      const preview = generateRequest(selected, {}, dates, cat);
      expect(preview.blockingReasons.length).toBeGreaterThan(0);
      expect(preview.code).not.toContain("rr.pick(");
      expect(preview.code).not.toContain("rr.find(");
    }
    for (const invalid of [
      { start: "", end: "" },
      { start: "2023-02-29", end: "2023-03-01" },
      { start: "2023-02-01", end: "2023-01-01" },
    ]) {
      expect(generateRequest([gauge], {}, invalid, cat).blockingReasons.length).toBeGreaterThan(0);
    }
    expect(generateRequest([gauge], { frequency: "daily" }, dates, cat).blockingReasons.join()).toContain(
      "positive ISO 8601 duration",
    );
    expect(generateRequest([gauge], { frequency: "P1D" }, dates, cat).blockingReasons.join()).toContain(
      "conflict",
    );
    const catOnly = makeCatalogue([{ ...providers[0], retrieval: false }]);
    expect(generateRequest([catOnly.stations[0]], {}, dates, catOnly).blockingReasons.join()).toContain(
      "catalogue-only",
    );
  });

  it("makes unresolved preview inert even when catalogue identifiers contain newlines", () => {
    const cat = makeCatalogue();
    const hostile: StationRecord = { ...cat.stations[0], provider_id: 'unlisted\nprint("unexpected")' };
    const preview = generateRequest([hostile], {}, dates, cat);
    expect(preview.code.split("\n").every((line) => line === "" || line.startsWith("#"))).toBe(true);
  });

  it("canonicalizes frequency in rr.find() output", () => {
    const cat = makeCatalogue(providers, [[0, "001"]], "PT1H");
    const preview = generateRequest(cat.stations, { frequency: "PT60M" }, dates, cat);
    expect(preview.blockingReasons).toEqual([]);
    expect(preview.code).toContain('frequency="PT1H"');
  });

  it.each(["combined", "fallback"])(
    "executes %s provider-qualified Python with synthetic APIs only",
    (mode) => {
      const providerDefs: Provider[] = [
        { provider_id: "ca_eccc", retrieval: true, bulk: true, credentials: [] },
        { provider_id: "pl_imgw", retrieval: true, bulk: true, credentials: [] },
        { provider_id: "br_ana", retrieval: true, bulk: false, credentials: ["ANA_IDENTIFICADOR", "ANA_SENHA"] },
        { provider_id: "no_nve", retrieval: true, bulk: false, credentials: ["NVE_API_KEY"] },
      ];
      const baseIds = ["0001", "0002", '001"\nprint("not executable")\\', "0001"];
      const stations: [number, string][] = baseIds.map((id, i) => [
        i,
        mode === "combined" ? '001"\nprint("not executable")\\' : id,
      ]);
      const cat = makeCatalogue(providerDefs, stations);
      const selected = cat.stations;
      const cataloguePairs = [
        ...selected.map((s) => [s.provider_id, s.station_id]),
        ["pl_imgw", "not-selected"],
        ["outside-selection", "0001"],
        ...(mode === "fallback" ? [["pl_imgw", "0001"]] : []),
      ];
      const preview = generateRequest([...selected, selected[0]], { quantity: "discharge" }, dates, cat);
      expect(preview.blockingReasons).toEqual([]);
      for (const name of ["ANA_IDENTIFICADOR", "ANA_SENHA", "NVE_API_KEY", "SQLITE_TMPDIR", "TMPDIR"]) {
        expect(preview.code).toContain(name);
      }
      const execution = spawnSync(
        "uv",
        [
          "run",
          "--frozen",
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
          input: JSON.stringify({ code: preview.code, catalogue: cataloguePairs }),
          encoding: "utf8",
          cwd: "../..",
        },
      );
      expect(execution.status, execution.stderr).toBe(0);
      const output = execution.stdout.trim().split("\n");
      for (const issue of ["discovery issue", "pick issue", "synthetic issue"]) {
        expect(output.filter((line) => line === issue)).toHaveLength(4);
      }
      expect(JSON.parse(output.at(-2)!)).toEqual(
        Object.fromEntries(
          selected.map((s) => [s.provider_id, [{ provider: s.provider_id, station: [s.station_id] }, dates]]),
        ),
      );
      const calls = JSON.parse(output.at(-1)!);
      expect(calls.slice(0, 2)).toEqual([["download", "ca_eccc"], ["download", "pl_imgw"]]);
      if (mode === "combined") {
        expect(calls.filter((c: unknown[]) => c[0] === "fetch")).toEqual([]);
        expect(calls.filter((c: unknown[]) => c[0] === "fetch_by_provider")).toHaveLength(1);
      } else {
        expect(calls.filter((c: unknown[]) => c[0] === "fetch")).toHaveLength(4);
        expect(calls.filter((c: unknown[]) => c[0] === "fetch_by_provider")).toEqual([]);
      }
    },
  );

  it("assigns date errors to inputs and shares them with request blocking", () => {
    const cat = makeCatalogue();
    const gauge = cat.stations[0];
    expect(dateErrors({ start: "2024-02-29", end: "" })).toEqual({});
    for (const [invalid, field] of [
      [{ start: "", end: "" }, "start"],
      [{ start: "2023-02-29", end: "" }, "start"],
      [{ start: "2023-01-01", end: "2023-02-30" }, "end"],
      [{ start: "2023-02-01", end: "2023-01-01" }, "end"],
    ] as const) {
      const errors = dateErrors(invalid);
      expect(errors[field]).toBeTruthy();
      expect(generateRequest([gauge], {}, invalid, cat).blockingReasons).toContain(errors[field]);
    }
  });

  it("renders exact single-provider and multi-provider previews with 10-ID truncation", () => {
    const cat = makeCatalogue(
      [
        { provider_id: "alpha", retrieval: true, bulk: false, credentials: [] },
        { provider_id: "beta", retrieval: true, bulk: false, credentials: [] },
        { provider_id: "gamma", retrieval: true, bulk: false, credentials: [] },
      ],
      [
        ...Array.from({ length: 9 }, (_, i): [number, string] => [0, String(i).padStart(4, "0")]),
        [1, "0009"],
        [1, "0010"],
        [2, "0011"],
      ],
    );
    const single = generateRequest([cat.stations[0]], {}, dates, cat);
    expect(single.code).toBe(`import rivretrieve as rr

selection = rr.find()
gauges = rr.pick(
    selection,
    provider="alpha",
    station=[
        "0000",
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

    const twelve = generateRequest(cat.stations, {}, dates, cat);
    expect(twelve.omittedStationCount).toBe(2);
    expect(twelve.previewCode).toContain('"gamma": [\n        … 1 more station IDs omitted\n    ],');
    expect(twelve.code).not.toContain("omitted");
    for (const st of cat.stations) expect(twelve.code).toContain(JSON.stringify(st.station_id));
  });

  it.each(["combined", "fallback"])(
    "shortened %s display cannot execute before all identifiers are restored",
    (mode) => {
      const cat = makeCatalogue(
        [
          { provider_id: "alpha", retrieval: true, bulk: true, credentials: [] },
          { provider_id: "beta", retrieval: true, bulk: false, credentials: [] },
        ],
        [
          ...Array.from({ length: 11 }, (_, i): [number, string] => [0, `gauge-${i}`]),
          ...(mode === "combined"
            ? Array.from({ length: 11 }, (_, i): [number, string] => [1, `gauge-${i}`])
            : ([[1, "later-provider"]] as [number, string][])),
        ],
      );
      const preview = generateRequest(cat.stations, {}, dates, cat);
      const run = spawnSync(
        "uv",
        [
          "run",
          "--frozen",
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
print(json.dumps(calls))
compile(source["full"],"complete.py","exec")
`,
        ],
        { input: JSON.stringify({ preview: preview.previewCode, full: preview.code }), encoding: "utf8", cwd: "../.." },
      );
      expect(run.status, run.stderr).toBe(0);
      expect(run.stdout.trim().split("\n")).toEqual(["syntax blocked", "[]"]);
      if (mode === "fallback") expect(preview.previewCode).not.toContain('"beta": []');
    },
  );
});
