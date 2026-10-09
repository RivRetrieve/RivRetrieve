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
  const filterStart = Date.now();
  await app.getByLabel("provider", { exact: true }).selectOption("usgs_nwis");
  await expect(app.getByTestId("match-count")).toHaveText(
    "26,201 matching gauges",
  );
  const filterMs = Date.now() - filterStart;
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
  await app.getByRole("tab", { name: "Python", exact: true }).click();
  await app.getByLabel("Start date", { exact: true }).fill("2020-01-01");
  await app.getByLabel("End date", { exact: true }).fill("2020-01-02");
  await expect(
    app.getByRole("button", { name: "Copy Python request" }),
  ).toBeEnabled();
  await app.getByRole("tab", { name: "Discover", exact: true }).click();
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
  await app.getByRole("tab", { name: "Discover", exact: true }).click();
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
  await app.getByRole("tab", { name: /Selection/ }).click();
  await app
    .getByRole("button", { name: "Clear selection", exact: true })
    .click();
  await app.getByRole("tab", { name: "Discover", exact: true }).click();
  await app.getByRole("button", { name: "Clear filters", exact: true }).click();
  await app.getByRole("button", { name: "Close gauge details" }).click();
  await app.getByRole("button", { name: "Zoom to matches" }).click();
  await expect
    .poll(() => app.locator(".leaflet-tile-loaded").count())
    .toBeGreaterThan(0);
  await page.waitForLoadState("networkidle");
  if (process.env.EVIDENCE_DIR)
    await page.screenshot({
      path: `${process.env.EVIDENCE_DIR}/docs-desktop.png`,
    });
  await page.setViewportSize({ width: 390, height: 844 });
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
