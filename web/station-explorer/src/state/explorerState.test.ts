import { describe, expect, it } from "vitest";
import { decodeCatalogue } from "../catalogue/index";
import { physicalFields, type FactState } from "../domain/types";
import {
  explorerReducer,
  initialExplorerState,
  selectSafeSelectionPage,
} from "./explorerState";

function sampleCatalogue(count = 3) {
  const base = Object.fromEntries(
    physicalFields.map((f) => [f, { value: null, state: "not_established" as FactState }]),
  ) as Record<(typeof physicalFields)[number], { value: string | null; state: FactState }>;
  return decodeCatalogue({
    version: 3,
    providers: [
      { provider_id: "alpha", retrieval: true, bulk: false, credentials: [] },
      { provider_id: "beta", retrieval: true, bulk: false, credentials: [] },
    ],
    facts: [
      { ...base, quantity: { value: "discharge", state: "known" }, admission: "supported" },
      { ...base, quantity: { value: "stage", state: "known" }, admission: "supported" },
    ],
    fact_sets: [[0], [1]],
    stations: Array.from({ length: count }, (_, i) => [
      i % 2,
      String(i + 1).padStart(3, "0"),
      `Station ${i + 1}`,
      47,
      8,
      "EPSG:4326",
      [],
      i === 0 ? 0 : 1,
    ]),
  });
}

describe("explorerState reducer", () => {
  it("starts in loading state with open panel on filtering tab and transitions on load/error", () => {
    const start = initialExplorerState();
    expect(start.catalogueStatus).toBe("loading");
    expect(start.catalogue).toBeNull();
    expect(start.tab).toBe("filtering");
    expect(start.panelOpen).toBe(true);

    const cat = sampleCatalogue();
    const loaded = explorerReducer(start, { type: "CATALOGUE_LOADED", catalogue: cat });
    expect(loaded.catalogueStatus).toBe("ready");
    expect(loaded.catalogue).toBe(cat);

    const failed = explorerReducer(start, { type: "CATALOGUE_FAILED", error: "Network error" });
    expect(failed.catalogueStatus).toBe("error");
    expect(failed.error).toBe("Network error");
  });

  it("keeps browsing and clearing search independent from selection and measurement settings", () => {
    const cat = sampleCatalogue();
    let state = explorerReducer(initialExplorerState(), {
      type: "CATALOGUE_LOADED",
      catalogue: cat,
    });
    state = explorerReducer(state, {
      type: "SET_REQUEST_SETTING",
      field: "quantity",
      value: "discharge",
    });
    state = explorerReducer(state, { type: "ADD_STATIONS", stations: [cat.stations[0]] });
    state = explorerReducer(state, {
      type: "SET_BROWSE_FILTER",
      field: "provider",
      value: "beta",
    });
    state = explorerReducer(state, {
      type: "SET_BROWSE_FILTER",
      field: "station",
      value: "002",
    });
    state = explorerReducer(state, { type: "SET_COPY_STATUS", status: "Copied." });
    expect(state.selected).toHaveLength(1);
    expect(state.settings).toEqual({ quantity: "discharge" });
    expect(state.browse).toEqual({ provider: "beta", station: "002" });

    state = explorerReducer(state, { type: "CLEAR_SEARCH" });
    expect(state.browse).toEqual({});
    expect(state.settings).toEqual({ quantity: "discharge" });
    expect(state.selected).toEqual([cat.stations[0]]);
    expect(state.copyStatus).toBe("");
  });

  it("handles inspect, remove, remove incompatible, and selection page clamping", () => {
    const cat = sampleCatalogue(35);
    let state = explorerReducer(initialExplorerState(), {
      type: "CATALOGUE_LOADED",
      catalogue: cat,
    });
    state = explorerReducer(state, { type: "SET_TAB", tab: "python" });
    state = explorerReducer(state, { type: "TOGGLE_PANEL" });
    expect(state.panelOpen).toBe(false);

    state = explorerReducer(state, {
      type: "INSPECT_STATION",
      station: cat.stations[0],
    });
    expect(state.inspected).toBe(cat.stations[0]);
    expect(state.tab).toBe("filtering");
    expect(state.panelOpen).toBe(true);

    state = explorerReducer(state, { type: "ADD_STATIONS", stations: cat.stations });
    state = explorerReducer(state, { type: "SET_SELECTION_PAGE", page: 1 });
    expect(selectSafeSelectionPage(state)).toBe(1);

    state = explorerReducer(state, {
      type: "REMOVE_INCOMPATIBLE",
      conflictKeys: new Set(cat.stations.slice(1).map((s) => s.key)),
    });
    expect(state.selected).toEqual([cat.stations[0]]);
    expect(selectSafeSelectionPage(state)).toBe(0);

    state = explorerReducer(state, { type: "REMOVE_STATION", key: cat.stations[0].key });
    expect(state.selected).toEqual([]);
    state = explorerReducer(state, { type: "CLOSE_INSPECTION" });
    expect(state.inspected).toBeNull();
  });

  it("clears copyStatus on setting, date, or selection changes", () => {
    const cat = sampleCatalogue();
    let state = explorerReducer(initialExplorerState(), {
      type: "CATALOGUE_LOADED",
      catalogue: cat,
    });
    state = explorerReducer(state, { type: "SET_COPY_STATUS", status: "Copied." });
    state = explorerReducer(state, { type: "SET_DATE", field: "start", value: "2020-01-01" });
    expect(state.copyStatus).toBe("");

    state = explorerReducer(state, { type: "SET_COPY_STATUS", status: "Copied." });
    state = explorerReducer(state, { type: "SET_REQUEST_SETTING", field: "quantity", value: "" });
    expect(state.copyStatus).toBe("");

    state = explorerReducer(state, { type: "SET_COPY_STATUS", status: "Copied." });
    state = explorerReducer(state, { type: "CLEAR_SELECTION" });
    expect(state.copyStatus).toBe("");
  });
});
