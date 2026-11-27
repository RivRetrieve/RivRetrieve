import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { captureClipboardWrites } from "./clipboard";
import { test, expect, type FrameLocator } from "@playwright/test";

interface BuiltCatalogueSummary {
  providerOptions: string[];
  totalMatching: number;
  totalClustered: number;
  usgsMatching: number;
  usgsClustered: number;
}

let cachedSummary: BuiltCatalogueSummary | null = null;

function readBuiltCatalogueSummary(): BuiltCatalogueSummary {
  if (cachedSummary) return cachedSummary;
  const cataloguePath = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../../../docs/assets/station-explorer/catalogue.json",
  );
  const raw = JSON.parse(fs.readFileSync(cataloguePath, "utf8")) as {
    version: number;
    providers: Array<{ provider_id: string }>;
    facts: Array<{ admission: string }>;
    fact_sets: number[][];
    stations: Array<
      [
        number,
        string,
        string | null,
        number | null,
        number | null,
        string | null,
        string[],
        number,
      ]
    >;
  };
  if (raw.version !== 3) {
    throw new Error(`Expected v3 catalogue at ${cataloguePath}, got ${raw.version}`);
  }
  const supportedSet = new Uint8Array(raw.fact_sets.length);
  for (let i = 0; i < raw.fact_sets.length; i++) {
    if (raw.fact_sets[i].some((fi) => raw.facts[fi]?.admission === "supported")) {
      supportedSet[i] = 1;
    }
  }
  const usgsIdx = raw.providers.findIndex((p) => p.provider_id === "usgs_nwis");
  let totalMatching = 0;
  let totalClustered = 0;
  let usgsMatching = 0;
  let usgsClustered = 0;
  for (const st of raw.stations) {
    if (!supportedSet[st[7]]) continue;
    totalMatching++;
    const isUsgs = st[0] === usgsIdx;
    if (isUsgs) usgsMatching++;
    const lat = st[3];
    const lon = st[4];
    const crs = st[5];
    if (
      lat !== null &&
      lon !== null &&
      Number.isFinite(lat) &&
      Number.isFinite(lon) &&
      Math.abs(lat) <= 90 &&
      Math.abs(lon) <= 180 &&
      (crs === "EPSG:4326" || crs === "EPSG:4269" || crs === "unknown" || crs === null)
    ) {
      totalClustered++;
      if (isUsgs) usgsClustered++;
    }
  }
  cachedSummary = {
    providerOptions: ["", ...raw.providers.map((p) => p.provider_id)],
    totalMatching,
    totalClustered,
    usgsMatching,
    usgsClustered,
  };
  return cachedSummary;
}

async function waitForPaintedMap(
  app: FrameLocator,
  options: { expectedClustered?: number; expectVisibleMarkers?: boolean } = {},
) {
  const { expectedClustered, expectVisibleMarkers = true } = options;
  await expect
    .poll(
      async () =>
        app.locator(".map").evaluate(
          (map, { expected, requireVisible }) => {
            const canvas = map
              .closest(".map-shell")
              ?.querySelector<HTMLCanvasElement>("canvas.station-points");
            const clustered = Number(canvas?.dataset.clustered ?? -1);
            if (expected !== undefined && clustered !== expected) return false;
            if (
              requireVisible &&
              clustered > 0 &&
              map.querySelectorAll(".marker-cluster, .gauge-point").length === 0
            ) {
              return false;
            }
            return clustered >= 0;
          },
          { expected: expectedClustered, requireVisible: expectVisibleMarkers },
        ),
      { timeout: 60000, message: "Stations rendered on map" },
    )
    .toBe(true);
  await app
    .locator(".map")
    .evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    );
}

test("built explorer offers only supported providers", async ({ page }) => {
  test.skip(!process.env.DOCS_URL, "Set DOCS_URL for prepared MkDocs preview.");
  const summary = readBuiltCatalogueSummary();
  for (const required of ["ch_foen", "usgs_nwis", "cl_dga", "no_nve", "fr_hubeau"]) {
    expect(summary.providerOptions).toContain(required);
  }
  for (const excluded of ["za_dws", "jp_mlit"]) {
    expect(summary.providerOptions).not.toContain(excluded);
  }

  await page.goto(`${process.env.DOCS_URL}/map/`);
  const providers = page
    .frameLocator("#station-explorer")
    .getByLabel("Provider", { exact: true });
  await expect
    .poll(() =>
      providers
        .locator("option")
        .evaluateAll((options) =>
          options.map((option) => (option as HTMLOptionElement).value),
        ),
    )
    .toEqual(summary.providerOptions);
});

async function waitForBasemap(app: FrameLocator) {
  await expect
    .poll(
      () =>
        app.locator(".map").evaluate((map) => {
          const bounds = map.getBoundingClientRect();
          const tiles = [
            ...map.querySelectorAll<HTMLImageElement>(".leaflet-tile"),
          ].filter((tile) => {
            const r = tile.getBoundingClientRect();
            return (
              r.right > bounds.left &&
              r.left < bounds.right &&
              r.bottom > bounds.top &&
              r.top < bounds.bottom
            );
          });
          return (
            tiles.length > 0 &&
            tiles.every(
              (tile) =>
                tile.complete &&
                tile.naturalWidth > 0 &&
                Number(getComputedStyle(tile).opacity) >= 0.99,
            )
          );
        }),
      { timeout: 15000, message: "Visible basemap tiles finish loading" },
    )
    .toBe(true);
}

test.beforeEach(async ({ page }) => {
  await captureClipboardWrites(page);
});

test("full catalogue and USGS points work in the viewport docs map", async ({
  page,
  context,
}) => {
  test.skip(!process.env.DOCS_URL, "Set DOCS_URL for prepared MkDocs preview.");
  test.setTimeout(90000);
  const summary = readBuiltCatalogueSummary();
  const expectedMatchText = `${summary.totalMatching.toLocaleString()} matching gauges`;
  const expectedUsgsText = `${summary.usgsMatching.toLocaleString()} matching gauges`;

  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.setViewportSize({ width: 1600, height: 1100 });
  const requests: string[] = [];
  const explorerRequests: string[] = [];
  const errors: string[] = [];
  page.on("request", (r) => {
    const parsed = new URL(r.url());
    const safe =
      parsed.origin +
      "/" +
      (parsed.hostname === "a.basemaps.cartocdn.com"
        ? parsed.pathname.split("/")[1]
        : "");
    requests.push(safe);
    if (r.frame().url().includes("/assets/station-explorer/"))
      explorerRequests.push(safe);
  });
  page.on("pageerror", () => errors.push("pageerror"));

  const start = Date.now();
  await page.goto(`${process.env.DOCS_URL}/map/`);
  const app = page.frameLocator("#station-explorer");
  await expect(app.getByTestId("match-count")).toHaveText(expectedMatchText, {
    timeout: 60000,
  });
  const initialMs = Date.now() - start;
  await waitForPaintedMap(app, {
    expectedClustered: summary.totalClustered,
    expectVisibleMarkers: true,
  });
  const initialPaintMs = Date.now() - start;
  await expect(app.locator("canvas.station-points")).toHaveAttribute(
    "data-drawn",
    /^[1-9][0-9]+$/,
  );

  await expect(app.locator(".map")).toHaveAttribute(
    "data-basemap",
    "light_all",
  );
  await expect(
    app.getByRole("link", { name: "CARTO", exact: true }),
  ).toBeVisible();
  const iframeBox = await page.locator("#station-explorer").boundingBox();
  expect(iframeBox!.width).toBeGreaterThan(1500);
  expect(iframeBox!.height).toBeGreaterThan(950);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollHeight <= innerHeight + 2,
    ),
  ).toBe(true);
  await expect(app.getByLabel("Provider", { exact: true })).toHaveValue("");
  const initialView = app.locator("canvas.station-points");
  expect(
    Number(await initialView.getAttribute("data-center-lat")),
  ).toBeGreaterThan(46);
  expect(
    Number(await initialView.getAttribute("data-center-lat")),
  ).toBeLessThan(48);
  expect(
    Number(await initialView.getAttribute("data-center-lng")),
  ).toBeGreaterThan(6);
  expect(
    Number(await initialView.getAttribute("data-center-lng")),
  ).toBeLessThan(11);
  await waitForBasemap(app);
  if (process.env.EVIDENCE_DIR)
    await page.screenshot({
      path: `${process.env.EVIDENCE_DIR}/docs-desktop.png`,
    });

  const filterStart = Date.now();
  await app.getByLabel("Provider", { exact: true }).selectOption("usgs_nwis");
  await expect(app.getByTestId("match-count")).toHaveText(expectedUsgsText);
  const filterMs = Date.now() - filterStart;
  await waitForPaintedMap(app, {
    expectedClustered: summary.usgsClustered,
    expectVisibleMarkers: false,
  });
  const filterPaintMs = Date.now() - filterStart;
  expect(filterPaintMs).toBeLessThan(2000);

  await app
    .getByRole("button", { name: "Zoom to matches", exact: true })
    .click();
  const candidates = app.locator(".marker-cluster");
  const hittable = () =>
    candidates.evaluateAll((nodes) =>
      nodes.findIndex((node) => {
        const r = node.getBoundingClientRect();
        const hit = document.elementFromPoint(
          r.x + r.width / 2,
          r.y + r.height / 2,
        );
        return !!hit && node.contains(hit);
      }),
    );
  await expect.poll(hittable).toBeGreaterThanOrEqual(0);
  const cluster = candidates.nth(await hittable());
  const zoomBefore = Number(
    await app.locator("canvas.station-points").getAttribute("data-zoom"),
  );
  const clusterStart = Date.now();
  await cluster.click();
  await expect
    .poll(async () =>
      Number(
        await app.locator("canvas.station-points").getAttribute("data-zoom"),
      ),
    )
    .toBeGreaterThan(zoomBefore);
  await waitForPaintedMap(app, { expectVisibleMarkers: true });
  const clusterZoomMs = Date.now() - clusterStart;

  await app.getByLabel("Station", { exact: true }).fill("07374000");
  await expect(app.getByTestId("match-count")).toHaveText("1 matching gauge");
  await app.getByRole("button", { name: "Zoom to matches" }).click();
  await expect(app.locator("canvas.station-points")).toHaveAttribute(
    "data-drawn",
    "1",
  );
  const map = app.getByLabel("Gauge map", { exact: true });
  const box = await map.boundingBox();
  await map.click({ position: { x: box!.width / 2, y: box!.height / 2 } });
  await expect(
    app.getByRole("region", { name: "Gauge details" }),
  ).toBeVisible();
  await expect(
    app.getByRole("button", { name: "Coordinate reference warning", exact: true }),
  ).toHaveCount(0);
  await expect(
    app.getByRole("tab", { name: "Selection (0)", exact: true }),
  ).toBeVisible();
  await app.getByRole("button", { name: "Add gauge", exact: true }).click();
  await app.getByRole("tab", { name: "Python", exact: true }).click();
  await app.getByLabel("Start date", { exact: true }).fill("2020-01-01");
  await app.getByLabel("End date", { exact: true }).fill("2020-01-02");
  await app.getByRole("tab", { name: "Filtering", exact: true }).click();
  await expect(app.getByTestId("match-count")).toHaveText("1 matching gauge");
  await app.getByRole("tab", { name: "Python", exact: true }).click();
  await expect(
    app.getByRole("button", { name: "Copy Python request" }),
  ).toBeEnabled();
  await app.getByRole("tab", { name: "Filtering", exact: true }).click();
  await app.getByLabel("Quantity", { exact: true }).fill("not-a-quantity");
  await expect(app.locator("canvas.station-points")).toHaveAttribute(
    "data-drawn",
    "1",
  );
  await app.getByRole("tab", { name: /Selection/ }).click();
  await expect(app.getByTestId("selection-counts")).toHaveText(
    "0 matching · 1 conflicting",
  );
  await app.getByRole("tab", { name: "Python", exact: true }).click();
  await expect(
    app.getByRole("button", { name: "Copy Python request" }),
  ).toBeDisabled();
  await app.getByRole("tab", { name: "Filtering", exact: true }).click();
  await app.getByLabel("Quantity", { exact: true }).fill("");
  await app.getByLabel("Station", { exact: true }).fill("");

  const addStart = Date.now();
  await app
    .getByRole("button", { name: "Add all matches", exact: true })
    .click();
  await expect(
    app.getByRole("tab", {
      name: `Selection (${summary.usgsMatching.toLocaleString()})`,
      exact: true,
    }),
  ).toBeVisible();
  const addAllMs = Date.now() - addStart;
  await waitForPaintedMap(app, {
    expectedClustered: 0,
    expectVisibleMarkers: false,
  });
  const addAllPaintMs = Date.now() - addStart;
  expect(addAllPaintMs).toBeLessThan(2000);

  await app.getByRole("tab", { name: "Python", exact: true }).click();
  await app.getByRole("button", { name: "Copy Python request" }).click();
  const code = await page.evaluate(() => navigator.clipboard.readText());
  const allIds = JSON.parse(
    code.match(/station=(\[[\s\S]*?\])/)![1].replace(/,\s*]$/, "]"),
  ) as string[];
  expect(allIds).toHaveLength(summary.usgsMatching);
  expect(new Set(allIds).size).toBe(summary.usgsMatching);
  expect(code).toContain('"07374000"');
  expect(code).not.toContain("<span");
  expect(code).not.toContain("Preview shortened");
  const shown = await app.getByLabel("Python request").textContent();
  expect(shown).not.toBe(code);
  const shownIds = shown!.match(/"[0-9]+"/g) ?? [];
  expect(shownIds).toHaveLength(10);
  await expect(
    app.getByText(
      `Copy includes all ${summary.usgsMatching.toLocaleString()} gauges`,
    ),
  ).toBeVisible();
  await expect(
    app.getByRole("button", { name: "Show complete preview", exact: true }),
  ).toHaveCount(0);
  await app.getByRole("tab", { name: /Selection/ }).click();
  await app
    .getByRole("button", { name: "Clear selection", exact: true })
    .click();
  await app.getByRole("tab", { name: "Filtering", exact: true }).click();
  await app.getByLabel("Provider", { exact: true }).selectOption("no_nve");
  await app.getByLabel("Station", { exact: true }).fill("16.24.0");
  await expect(app.getByTestId("match-count")).toHaveText("1 matching gauge");
  await app.getByRole("button", { name: "Zoom to matches" }).click();
  await app
    .getByRole("button", { name: "Inspect no_nve / 16.24.0", exact: true })
    .click();
  await expect(
    app.getByRole("region", { name: "Gauge details" }),
  ).toContainText("Water body: Mår · MÅRVATN");
  await expect(
    app.getByText(/Unknown CRS\. Plotted as EPSG:4326/),
  ).toBeHidden();
  await app
    .getByRole("button", { name: "Coordinate reference warning", exact: true })
    .focus();
  await expect(
    app.getByText(/Unknown CRS\. Plotted as EPSG:4326/),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await app.getByRole("button", { name: "Clear search", exact: true }).click();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(app.getByTestId("match-count")).toHaveText(expectedMatchText, {
    timeout: 60000,
  });
  await waitForPaintedMap(app, {
    expectedClustered: summary.totalClustered,
    expectVisibleMarkers: true,
  });
  await waitForBasemap(app);
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
  await expect
    .poll(() =>
      page
        .frameLocator("#station-explorer")
        .locator("body")
        .evaluate(() => document.documentElement.scrollHeight <= innerHeight),
    )
    .toBe(true);
  if (process.env.EVIDENCE_DIR)
    await page.screenshot({
      path: `${process.env.EVIDENCE_DIR}/docs-mobile.png`,
    });
  await app.getByLabel("Provider", { exact: true }).selectOption("ch_foen");
  await app.getByLabel("Station", { exact: true }).fill("2004");
  await app.getByRole("button", { name: "Zoom to matches" }).click();
  await app.getByRole("button", { name: "Hide panel" }).click();
  await app
    .getByRole("button", { name: "Inspect ch_foen / 2004", exact: true })
    .click();
  const mobileDetails = app.getByRole("region", { name: "Gauge details" });
  await expect(mobileDetails).toContainText("Water body: Murtensee");
  const mobileAdd = mobileDetails.getByRole("button", {
    name: "Add gauge",
    exact: true,
  });
  const contentBox = (await app.locator(".panel-content").boundingBox())!;
  const addBox = (await mobileAdd.boundingBox())!;
  expect(addBox.y).toBeGreaterThanOrEqual(contentBox.y);
  expect(addBox.y + addBox.height).toBeLessThanOrEqual(
    contentBox.y + contentBox.height,
  );
  await mobileAdd.click();
  await expect(
    app.getByRole("tab", { name: "Selection (1)", exact: true }),
  ).toBeVisible();
  if (process.env.EVIDENCE_DIR)
    await page.screenshot({
      path: `${process.env.EVIDENCE_DIR}/docs-mobile-inspection.png`,
    });

  await app.getByRole("tab", { name: "Python", exact: true }).click();
  await app
    .getByRole("link", { name: "Date documentation", exact: true })
    .click();
  await expect(page).toHaveURL(/\/usage\/#time-labels-and-request-windows$/);
  const origins = [...new Set(requests.map((url) => new URL(url).origin))];
  console.log(
    JSON.stringify({
      initialMs,
      initialPaintMs,
      filterMs,
      filterPaintMs,
      clusterZoomMs,
      addAllMs,
      addAllPaintMs,
      iframeWidth: iframeBox!.width,
      origins,
      requestCount: requests.length,
      errors,
    }),
  );
  expect(
    explorerRequests.filter(
      (url) =>
        !url.startsWith("http://127.0.0.1:") &&
        !url.startsWith("https://tile.openstreetmap.org/") &&
        !url.startsWith("https://a.basemaps.cartocdn.com/"),
    ),
  ).toEqual([]);
  expect(
    origins.filter(
      (origin) =>
        !origin.startsWith("http://127.0.0.1:") &&
        ![
          "https://tile.openstreetmap.org",
          "https://a.basemaps.cartocdn.com",
          "https://fonts.googleapis.com",
          "https://fonts.gstatic.com",
          "https://api.github.com",
        ].includes(origin),
    ),
  ).toEqual([]);
  expect(errors).toEqual([]);
});

test("explorer and Python syntax follow the existing docs palette without losing view or selection", async ({
  page,
}) => {
  test.skip(!process.env.DOCS_URL, "Set DOCS_URL for prepared MkDocs preview.");
  const summary = readBuiltCatalogueSummary();
  const expectedMatchText = `${summary.totalMatching.toLocaleString()} matching gauges`;

  const errors: string[] = [];
  const tileFailures: string[] = [];
  page.on("pageerror", () => errors.push("pageerror"));
  page.on("requestfailed", (request) => {
    const url = new URL(request.url());
    if (
      [
        "https://tile.openstreetmap.org",
        "https://a.basemaps.cartocdn.com",
      ].includes(url.origin) &&
      request.failure()?.errorText !== "net::ERR_ABORTED"
    )
      tileFailures.push(
        url.origin +
          (url.hostname === "a.basemaps.cartocdn.com"
            ? "/" + url.pathname.split("/")[1]
            : "") +
          ":failed",
      );
  });
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.origin === "https://a.basemaps.cartocdn.com" && !response.ok())
      tileFailures.push(
        url.origin + "/" + url.pathname.split("/")[1] + ":" + response.status(),
      );
  });
  await page.setViewportSize({ width: 1600, height: 1100 });
  await page.goto(`${process.env.DOCS_URL}/map/`);
  const app = page.frameLocator("#station-explorer");
  await expect(app.getByTestId("match-count")).toHaveText(expectedMatchText, {
    timeout: 60000,
  });
  const view = () =>
    app
      .locator("canvas.station-points")
      .evaluate((node) => [
        node.dataset.centerLat,
        node.dataset.centerLng,
        node.dataset.zoom,
      ]);
  await page.locator('label[title="Switch to dark mode"]').click();
  await expect(page.locator("body")).toHaveAttribute(
    "data-md-color-scheme",
    "slate",
  );
  await expect(app.locator(".map")).toHaveAttribute("data-basemap", "dark_all");
  await expect(app.locator(".leaflet-tile-pane > .leaflet-layer")).toHaveCount(
    1,
  );
  const dark = await page
    .locator("body")
    .evaluate((node) => getComputedStyle(node).backgroundColor);
  await expect(app.locator(".panel")).toHaveCSS("background-color", dark);
  await expect(app.locator(".leaflet-container")).toHaveCSS(
    "background-color",
    dark,
  );
  await expect(app.getByLabel("Station", { exact: true })).toHaveCSS(
    "background-color",
    dark,
  );
  await waitForBasemap(app);
  if (process.env.EVIDENCE_DIR)
    await page.screenshot({
      path: `${process.env.EVIDENCE_DIR}/docs-dark.png`,
    });
  const beforeZoom = Number((await view())[2]);
  await app.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect.poll(async () => Number((await view())[2])).toBe(beforeZoom + 1);
  await app.getByLabel("Provider", { exact: true }).selectOption("ch_foen");
  await app.getByLabel("Station", { exact: true }).fill("2004");
  await app.getByRole("tab", { name: "Python", exact: true }).click();
  await app.getByLabel("Start date", { exact: true }).fill("2020-01-01");
  await app.getByRole("tab", { name: "Filtering", exact: true }).click();
  await app
    .getByRole("button", { name: "Zoom to matches", exact: true })
    .click();
  await expect.poll(async () => Number((await view())[2])).toBe(12);
  const initial = await view();
  await app
    .getByRole("button", { name: "Add all matches", exact: true })
    .click();
  await app.getByRole("tab", { name: /Selection/ }).click();
  await expect(app.locator(".selection-card")).toHaveCount(1);
  await waitForBasemap(app);
  if (process.env.EVIDENCE_DIR)
    await page.screenshot({
      path: `${process.env.EVIDENCE_DIR}/selection-dark.png`,
    });
  await app.getByRole("tab", { name: "Python", exact: true }).click();
  const code = app.getByLabel("Python request");
  await expect(
    code
      .locator("span")
      .filter({ hasText: /^import$/ })
      .first(),
  ).toHaveText("import");
  await expect(
    code
      .locator("span")
      .filter({ hasText: /^import$/ })
      .first(),
  ).toHaveCSS("color", "rgb(197, 134, 192)");
  const original = await code.textContent();
  await waitForBasemap(app);
  if (process.env.EVIDENCE_DIR)
    await page.screenshot({
      path: `${process.env.EVIDENCE_DIR}/python-dark.png`,
    });
  await page.locator('label[title="Switch to light mode"]').click();
  await expect(page.locator("body")).toHaveAttribute(
    "data-md-color-scheme",
    "default",
  );
  await expect(app.locator(".map")).toHaveAttribute(
    "data-basemap",
    "light_all",
  );
  await expect(app.locator(".leaflet-tile-pane > .leaflet-layer")).toHaveCount(
    1,
  );
  const light = await page
    .locator("body")
    .evaluate((node) => getComputedStyle(node).backgroundColor);
  await expect(app.locator(".panel")).toHaveCSS("background-color", light);
  await expect(app.locator(".leaflet-container")).toHaveCSS(
    "background-color",
    light,
  );
  await expect(
    code
      .locator("span")
      .filter({ hasText: /^import$/ })
      .first(),
  ).toHaveCSS("color", "rgb(175, 0, 219)");
  expect(await code.textContent()).toBe(original);
  const after = (await view()).map(Number);
  expect(after[2]).toBe(Number(initial[2]));
  // Leaflet rounds the projected center when invalidating size; allow one pixel,
  // while a reset or meaningful pan still fails this view-preservation check.
  const degreesPerPixel = 360 / (256 * 2 ** after[2]);
  expect(Math.abs(after[0] - Number(initial[0]))).toBeLessThan(degreesPerPixel);
  expect(Math.abs(after[1] - Number(initial[1]))).toBeLessThan(degreesPerPixel);
  await expect(
    app.getByRole("tab", { name: "Selection (1)", exact: true }),
  ).toBeVisible();
  await expect(
    app.getByRole("button", { name: /light mode|dark mode/ }),
  ).toHaveCount(0);
  await waitForBasemap(app);
  if (process.env.EVIDENCE_DIR)
    await page.screenshot({
      path: `${process.env.EVIDENCE_DIR}/python-light.png`,
    });
  await app.getByRole("tab", { name: /Selection/ }).click();
  if (process.env.EVIDENCE_DIR)
    await page.screenshot({
      path: `${process.env.EVIDENCE_DIR}/selection-light.png`,
    });
  await page.locator('label[title="Switch to dark mode"]').click();
  await page.getByRole("link", { name: "Usage", exact: true }).first().click();
  await expect(page.locator("#station-explorer")).toHaveCount(0);
  expect(
    (await page.locator(".md-content__inner").boundingBox())!.width,
  ).toBeLessThan(1100);
  await page
    .getByRole("link", { name: "Station Map", exact: true })
    .first()
    .click();
  await expect(app.getByTestId("match-count")).toHaveText(expectedMatchText, {
    timeout: 60000,
  });
  await expect(app.locator(".panel")).toHaveCSS("background-color", dark);
  expect(
    (await page.locator("#station-explorer").boundingBox())!.width,
  ).toBeGreaterThan(1500);
  console.log(JSON.stringify({ tileFailures }));
  expect(errors).toEqual([]);
});
