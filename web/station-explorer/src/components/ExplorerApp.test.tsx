// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { decodeCatalogue } from "../catalogue/index";
import { physicalFields, type FactState, type StationCatalogue } from "../domain/types";
import type { StationMapProps } from "../map/StationMap";
import { ExplorerApp } from "./ExplorerApp";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

function sampleCatalogue(): StationCatalogue {
  const base = Object.fromEntries(
    physicalFields.map((f) => [f, { value: null, state: "not_established" as FactState }]),
  ) as Record<(typeof physicalFields)[number], { value: string | null; state: FactState }>;
  return decodeCatalogue({
    version: 3,
    providers: [
      { provider_id: "alpha", name: "Alpha", retrieval: true, bulk: false, credentials: [] },
      { provider_id: "cat", name: "Catalogue Only", retrieval: false, bulk: false, credentials: [] },
    ],
    facts: [
      {
        ...base,
        quantity: { value: "discharge", state: "known" },
        frequency: { value: "P1D", state: "known" },
        admission: "supported",
      },
      {
        ...base,
        quantity: { value: "stage", state: "known" },
        admission: "supported",
      },
    ],
    fact_sets: [[0], [1]],
    stations: [
      [0, "001", "Alpha One", 47, 8, "EPSG:4326", ["Aare"], 0],
      [0, "002", "Alpha Two", 47.1, 8.1, "EPSG:4269", [], 1],
      [1, "003", "Cat Only", 47.2, 8.2, "unknown", [], 0],
    ],
  });
}

function MockMap({ matches, selected, onInspect }: StationMapProps) {
  return (
    <div data-testid="mock-map" data-matches={matches.length} data-selected={selected.length}>
      {matches[0] && (
        <button type="button" onClick={() => onInspect(matches[0])}>
          Mock inspect first
        </button>
      )}
    </div>
  );
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => {
    root.unmount();
  });
  host.remove();
});

function setInputValue(input: HTMLInputElement | HTMLSelectElement, value: string) {
  const proto =
    input instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")!.set!;
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("ExplorerApp integration", () => {
  it("mounts the map immediately while catalogue loads, then populates controls and preserves workflow", async () => {
    let resolveCatalogue!: (cat: StationCatalogue) => void;
    const loadFn = vi.fn(
      () =>
        new Promise<StationCatalogue>((resolve) => {
          resolveCatalogue = resolve;
        }),
    );

    const writeText = vi.fn(async (_text: string) => {});
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    await act(async () => {
      root.render(
        <ExplorerApp
          MapComponent={MockMap}
          loadCatalogueFn={loadFn}
          catalogueUrl="http://127.0.0.1/catalogue.json"
        />,
      );
    });

    // Map mounts immediately while catalogue is still loading
    expect(host.querySelector('[data-testid="mock-map"]')).not.toBeNull();
    expect(host.querySelector('[role="status"]')?.textContent).toContain("Loading public catalogue");
    expect(host.querySelector('[data-testid="match-count"]')).toBeNull();

    const catalogue = sampleCatalogue();
    await act(async () => {
      resolveCatalogue(catalogue);
    });

    expect(host.querySelector('[data-testid="match-count"]')?.textContent).toBe("3 matching gauges");

    // Inspect via mock map and add single gauge
    await act(async () => {
      host.querySelector<HTMLButtonElement>('[data-testid="mock-map"] button')!.click();
    });
    expect(host.querySelector('[aria-label="Gauge details"]')?.textContent).toContain("alpha / 001");
    await act(async () => {
      const addBtn = Array.from(host.querySelectorAll("button")).find(
        (b) => b.textContent === "Add gauge",
      )!;
      addBtn.click();
    });
    expect(host.textContent).toContain("Selection (1)");

    // Filter by provider and clear search -> selection and settings preserved
    await act(async () => {
      setInputValue(host.querySelector<HTMLInputElement>('[aria-label="Quantity"]')!, "discharge");
      setInputValue(host.querySelector<HTMLSelectElement>('[aria-label="Provider"]')!, "cat");
    });
    expect(host.querySelector('[data-testid="match-count"]')?.textContent).toBe("1 matching gauge");

    await act(async () => {
      Array.from(host.querySelectorAll("button"))
        .find((b) => b.textContent === "Clear search")!
        .click();
    });
    expect(host.querySelector<HTMLInputElement>('[aria-label="Quantity"]')!.value).toBe("discharge");
    expect(host.querySelector('[data-testid="match-count"]')?.textContent).toBe("2 matching gauges");

    // Invalid frequency displays inline error and blocks copy
    await act(async () => {
      setInputValue(host.querySelector<HTMLInputElement>('[aria-label="Frequency"]')!, "daily");
    });
    expect(host.querySelector("#frequency-error")?.textContent).toContain("positive ISO 8601 duration");

    await act(async () => {
      setInputValue(host.querySelector<HTMLInputElement>('[aria-label="Frequency"]')!, "P1D");
    });
    expect(host.querySelector("#frequency-error")).toBeNull();

    // Switch to Python tab, enter start date, copy full code lazily
    await act(async () => {
      Array.from(host.querySelectorAll<HTMLButtonElement>('[role="tab"]'))
        .find((t) => t.textContent === "Python")!
        .click();
    });
    await act(async () => {
      setInputValue(host.querySelector<HTMLInputElement>('[aria-label="Start date"]')!, "2020-01-01");
    });
    await act(async () => {
      Array.from(host.querySelectorAll("button"))
        .find((b) => b.textContent === "Copy Python request")!
        .click();
    });
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText.mock.calls[0][0]).toContain('provider="alpha"');
    expect(writeText.mock.calls[0][0]).toContain('"001"');
    expect(writeText.mock.calls[0][0]).toContain('frequency="P1D"');
  });

  it("renders alert on catalogue load failure", async () => {
    const loadFn = vi.fn(async () => {
      throw new Error("Catalogue loading failed (500).");
    });
    await act(async () => {
      root.render(
        <ExplorerApp
          MapComponent={MockMap}
          loadCatalogueFn={loadFn}
          catalogueUrl="http://127.0.0.1/catalogue.json"
        />,
      );
    });
    expect(host.querySelector('[role="alert"]')?.textContent).toContain(
      "Catalogue loading failed (500).",
    );
  });
});
