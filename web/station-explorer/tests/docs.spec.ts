import { test, expect } from "@playwright/test";
test("full catalogue and USGS points work in the viewport docs map", async ({
  page,
  context,
}) => {
  test.skip(!process.env.DOCS_URL, "Set DOCS_URL for prepared MkDocs preview.");
  test.setTimeout(90000);
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.setViewportSize({ width: 1600, height: 1100 });
  const requests: string[] = [];
  const explorerRequests: string[] = [];
  const errors: string[] = [];
  page.on("request", (r) => {
    requests.push(r.url());
    if (r.frame().url().includes("/assets/station-explorer/"))
      explorerRequests.push(r.url());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  const start = Date.now();
  await page.goto(`${process.env.DOCS_URL}/map/`);
  const app = page.frameLocator("#station-explorer");
  await expect(app.getByTestId("match-count")).toHaveText(
    "77,020 matching gauges",
    { timeout: 60000 },
  );
  await expect(app.locator("canvas.station-points")).toHaveAttribute(
    "data-drawn",
    /^[1-9][0-9]+$/,
  );
  const initialMs = Date.now() - start;
  const iframeBox = await page.locator("#station-explorer").boundingBox();
  expect(iframeBox!.width).toBeGreaterThan(1500);
  expect(iframeBox!.height).toBeGreaterThan(950);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollHeight <= innerHeight + 2,
    ),
  ).toBe(true);
  await expect(app.getByLabel("provider", { exact: true })).toHaveValue("");
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
  await page.waitForLoadState("networkidle");
  if (process.env.EVIDENCE_DIR)
    await page.screenshot({
      path: `${process.env.EVIDENCE_DIR}/docs-desktop.png`,
    });
  const filterStart = Date.now();
  await app.getByLabel("provider", { exact: true }).selectOption("usgs_nwis");
  await expect(app.getByTestId("match-count")).toHaveText(
    "26,201 matching gauges",
  );
  const filterMs = Date.now() - filterStart;
  await app
    .getByRole("button", { name: "Zoom to matches", exact: true })
    .click();
  const cluster = app.getByRole("button", { name: /Zoom to group of/ }).first();
  await expect(cluster).toBeVisible();
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
  const clusterZoomMs = Date.now() - clusterStart;
  await app.getByLabel("station", { exact: true }).fill("07374000");
  await expect(app.getByTestId("match-count")).toHaveText("1 matching gauges");
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
    app.getByText(/NAD83.*without a datum transformation/),
  ).toBeVisible();
  await expect(
    app.getByRole("tab", { name: "Selection (0)", exact: true }),
  ).toBeVisible();
  await app.getByRole("button", { name: "Add gauge", exact: true }).click();
  await app.getByLabel("Start date", { exact: true }).fill("2020-01-01");
  await app.getByLabel("End date", { exact: true }).fill("2020-01-02");
  await expect(app.getByTestId("match-count")).toHaveText("1 matching gauges");
  await app.getByRole("tab", { name: "Python", exact: true }).click();
  await expect(
    app.getByRole("button", { name: "Copy Python request" }),
  ).toBeEnabled();
  await app.getByRole("tab", { name: "Filtering", exact: true }).click();
  await app.getByLabel("quantity", { exact: true }).fill("not-a-quantity");
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
  await app.getByLabel("quantity", { exact: true }).fill("");
  await app.getByLabel("station", { exact: true }).fill("");
  const addStart = Date.now();
  await app
    .getByRole("button", { name: "Add all matches", exact: true })
    .click();
  await expect(
    app.getByRole("tab", { name: "Selection (26,201)", exact: true }),
  ).toBeVisible();
  const addAllMs = Date.now() - addStart;
  await app.getByRole("tab", { name: "Python", exact: true }).click();
  await app.getByRole("button", { name: "Copy Python request" }).click();
  const code = await page.evaluate(() => navigator.clipboard.readText());
  expect(code.match(/^        ".*",$/gm)).toHaveLength(26201);
  expect(code).toContain('"07374000"');
  expect(code).not.toContain("<span");
  expect(code).not.toContain("Preview shortened");
  await app
    .getByRole("button", { name: "Show complete preview", exact: true })
    .click();
  expect(await app.getByLabel("Python request").textContent()).toBe(code);
  await app.getByRole("tab", { name: /Selection/ }).click();
  await app
    .getByRole("button", { name: "Clear selection", exact: true })
    .click();
  await app.getByRole("tab", { name: "Filtering", exact: true }).click();
  await app.getByRole("button", { name: "Clear filters", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(app.getByTestId("match-count")).toHaveText(
    "77,020 matching gauges",
    { timeout: 60000 },
  );
  await page.waitForLoadState("networkidle");
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
  await app
    .getByRole("link", { name: "Date documentation", exact: true })
    .click();
  await expect(page).toHaveURL(/\/usage\/#time-labels-and-request-windows$/);
  const origins = [...new Set(requests.map((url) => new URL(url).origin))];
  console.log(
    JSON.stringify({
      initialMs,
      filterMs,
      clusterZoomMs,
      addAllMs,
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
        !url.startsWith("https://tile.openstreetmap.org/"),
    ),
  ).toEqual([]);
  expect(
    origins.filter(
      (origin) =>
        !origin.startsWith("http://127.0.0.1:") &&
        ![
          "https://tile.openstreetmap.org",
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
  const errors: string[] = [];
  const tileFailures: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("requestfailed", (request) => {
    if (request.url().startsWith("https://tile.openstreetmap.org/"))
      tileFailures.push(request.failure()?.errorText ?? "failed");
  });
  await page.setViewportSize({ width: 1600, height: 1100 });
  await page.goto(`${process.env.DOCS_URL}/map/`);
  const app = page.frameLocator("#station-explorer");
  await expect(app.getByTestId("match-count")).toHaveText(
    "77,020 matching gauges",
    { timeout: 60000 },
  );
  const view = () =>
    app
      .locator("canvas.station-points")
      .evaluate((node) => [
        node.dataset.centerLat,
        node.dataset.centerLng,
        node.dataset.zoom,
      ]);
  const keywordColor = () =>
    page.evaluate(() => {
      const sample = document.createElement("span");
      sample.style.color = "var(--md-code-hl-keyword-color)";
      document.body.append(sample);
      const result = getComputedStyle(sample).color;
      sample.remove();
      return result;
    });
  await page.locator('label[title="Switch to dark mode"]').click();
  await expect(page.locator("body")).toHaveAttribute(
    "data-md-color-scheme",
    "slate",
  );
  const dark = await page
    .locator("body")
    .evaluate((node) => getComputedStyle(node).backgroundColor);
  await expect(app.locator(".panel")).toHaveCSS("background-color", dark);
  await expect(app.locator(".leaflet-container")).toHaveCSS(
    "background-color",
    dark,
  );
  await expect(app.getByLabel("station", { exact: true })).toHaveCSS(
    "background-color",
    dark,
  );
  await page.waitForLoadState("networkidle");
  if (process.env.EVIDENCE_DIR)
    await page.screenshot({
      path: `${process.env.EVIDENCE_DIR}/docs-dark.png`,
    });
  const beforeZoom = Number((await view())[2]);
  await app.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect.poll(async () => Number((await view())[2])).toBe(beforeZoom + 1);
  const initial = await view();
  await app.getByLabel("provider", { exact: true }).selectOption("ch_foen");
  await app.getByLabel("station", { exact: true }).fill("2004");
  await app.getByLabel("Start date", { exact: true }).fill("2020-01-01");
  await app
    .getByRole("button", { name: "Add all matches", exact: true })
    .click();
  await app.getByRole("tab", { name: "Python", exact: true }).click();
  const code = app.getByLabel("Python request");
  await expect(code.locator(".token.keyword").first()).toHaveText("import");
  await expect(code.locator(".token.keyword").first()).toHaveCSS(
    "color",
    await keywordColor(),
  );
  const original = await code.textContent();
  if (process.env.EVIDENCE_DIR)
    await page.screenshot({
      path: `${process.env.EVIDENCE_DIR}/python-dark.png`,
    });
  await page.locator('label[title="Switch to light mode"]').click();
  await expect(page.locator("body")).toHaveAttribute(
    "data-md-color-scheme",
    "default",
  );
  const light = await page
    .locator("body")
    .evaluate((node) => getComputedStyle(node).backgroundColor);
  await expect(app.locator(".panel")).toHaveCSS("background-color", light);
  await expect(app.locator(".leaflet-container")).toHaveCSS(
    "background-color",
    light,
  );
  await expect(code.locator(".token.keyword").first()).toHaveCSS(
    "color",
    await keywordColor(),
  );
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
  if (process.env.EVIDENCE_DIR)
    await page.screenshot({
      path: `${process.env.EVIDENCE_DIR}/python-light.png`,
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
  await expect(app.getByTestId("match-count")).toHaveText(
    "77,020 matching gauges",
    { timeout: 60000 },
  );
  await expect(app.locator(".panel")).toHaveCSS("background-color", dark);
  expect(
    (await page.locator("#station-explorer").boundingBox())!.width,
  ).toBeGreaterThan(1500);
  console.log(JSON.stringify({ tileFailures }));
  expect(errors).toEqual([]);
});
