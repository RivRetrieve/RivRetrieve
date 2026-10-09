import { captureClipboardWrites } from "./clipboard";
import { test, expect } from "@playwright/test";

const fields = [
  "quantity",
  "frequency",
  "statistic",
  "temporal_support",
  "day_definition",
  "timestamp_anchor",
  "time_zone",
  "vertical_reference",
  "vertical_datum",
];
const fact = (quantity: string, frequency: string | null) => ({
  ...Object.fromEntries(
    fields.map((field) => [
      field,
      {
        value:
          field === "quantity"
            ? quantity
            : field === "frequency"
              ? frequency
              : null,
        state:
          field === "quantity" || (field === "frequency" && frequency)
            ? "known"
            : "not_established",
      },
    ]),
  ),
  admission: "supported",
});
const fixture = {
  version: 1,
  providers: [
    { provider_id: "alpha", retrieval: true, bulk: false, credentials: [] },
    {
      provider_id: "beta",
      retrieval: true,
      bulk: true,
      credentials: ["SOURCE_KEY"],
    },
    {
      provider_id: "catalogue",
      retrieval: false,
      bulk: false,
      credentials: [],
    },
  ],
  stations: [
    [0, "001", "River one", 10, 10, "EPSG:4326"],
    [1, "001", "Other provider", 20, 20, "unknown"],
    [2, "C", "Catalogue gauge", null, null, null],
    [0, "empty", "No series described", 15, 15, "EPSG:4326"],
  ],
  facts: [fact("discharge", "daily"), fact("stage", null)],
  series: [
    [0, "series-a", "raw", "published-a", [0]],
    [1, "series-b", null, null, [1]],
    [2, "series-c", null, null, [0]],
  ],
};
test.beforeEach(async ({ page }) => {
  await captureClipboardWrites(page);
  await page.route("**/catalogue.json", (route) =>
    route.fulfill({ json: fixture }),
  );
  await page.route("https://tile.openstreetmap.org/**", (route) =>
    route.abort(),
  );
  await page.route("https://a.basemaps.cartocdn.com/**", (route) =>
    route.abort(),
  );
});

test("inspection and exact-pair selection survive changed filters", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/");
  const copy = page.getByRole("button", { name: "Copy Python request" });
  await page.getByRole("tab", { name: "Python", exact: true }).click();
  await expect(copy).toBeDisabled();
  await page.getByRole("tab", { name: "Filtering", exact: true }).click();
  await page.getByLabel("Start date", { exact: true }).fill("2020-01-01");
  await page.getByLabel("End date", { exact: true }).fill("2020-01-02");
  await page.getByLabel("provider", { exact: true }).selectOption("alpha");
  await page.getByRole("button", { name: "Zoom to matches" }).click();
  const map = page.getByLabel("Gauge map", { exact: true });
  const box = await map.boundingBox();
  await map.click({ position: { x: box!.width / 2, y: box!.height / 2 } });
  await expect(
    page.getByRole("tab", { name: "Selection (0)", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Add gauge", exact: true }).click();
  await page.getByLabel("provider", { exact: true }).selectOption("beta");
  await page.getByRole("tab", { name: /Selection/ }).click();
  await expect(page.getByTestId("selection-counts")).toHaveText(
    "0 matching · 1 conflicting",
  );
  await page.getByRole("tab", { name: "Python", exact: true }).click();
  await expect(copy).toBeDisabled();
  await expect(page.getByLabel("Python request")).toContainText(
    "UNRESOLVED REQUEST",
  );
  await page.getByRole("tab", { name: "Filtering", exact: true }).click();
  await page
    .getByRole("button", { name: "Add all matches", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Clear filters", exact: true })
    .click();
  await page.getByRole("tab", { name: "Python", exact: true }).click();
  await expect(copy).toBeEnabled();
  await copy.click();
  const code = await page.evaluate(() => navigator.clipboard.readText());
  expect(code).toContain('provider="alpha"');
  expect(code).toContain('provider="beta"');
  expect(code.match(/"001",/g)).toHaveLength(2);
  expect(code).toContain('rr.download("beta")');
  expect(code).toContain("SOURCE_KEY");
  await page.getByRole("tab", { name: "Filtering", exact: true }).click();
  await page.getByText("More filters", { exact: true }).click();
  await page.getByLabel("frequency", { exact: true }).fill("daily");
  await page.getByRole("tab", { name: /Selection/ }).click();
  await expect(
    page.getByText(/frequency is not established in the catalogue/),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Remove non-matching gauges" })
    .click();
  await page
    .getByRole("button", { name: "Remove alpha / 001", exact: true })
    .click();
  await page.getByRole("tab", { name: "Python", exact: true }).click();
  await expect(copy).toBeDisabled();
  await expect(page.getByLabel("Python request")).not.toContainText("rr.pick(");
});

test("catalogue-only selection blocks output", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("provider", { exact: true }).selectOption("catalogue");
  await page
    .getByRole("button", { name: "Add all matches", exact: true })
    .click();
  await page.getByRole("tab", { name: /Selection/ }).click();
  await expect(page.getByTestId("selection-counts")).toHaveText(
    "1 matching · 0 conflicting",
  );
  await expect(
    page.getByText("⚠ Unsupported observation retrieval (catalogue only)."),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Python", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Copy Python request" }),
  ).toBeDisabled();
  await page.getByRole("tab", { name: /Selection/ }).click();
  await page
    .getByRole("button", { name: "Clear selection", exact: true })
    .click();
});

test("map fills viewport with one compact tabbed panel", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(
    page.getByRole("tab", { name: "Filtering", exact: true }),
  ).toBeVisible();
  const box = await page.getByLabel("Gauge map", { exact: true }).boundingBox();
  expect(box!.width).toBeGreaterThan(1400);
  expect(box!.height).toBeGreaterThan(880);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollHeight <= window.innerHeight,
    ),
  ).toBe(true);
});

test("basemap failures are visible without hiding catalogue gauges", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByText(
      "Some basemap tiles are unavailable. Gauge points remain visible.",
    ),
  ).toBeVisible();
  await expect(page.getByTestId("match-count")).toHaveText("3 matching gauges");
});

test("native clusters zoom and spiderfy co-located provider identities", async ({
  page,
}) => {
  const grouped = structuredClone(fixture);
  grouped.stations[1][3] = 10;
  grouped.stations[1][4] = 10;
  await page.route("**/catalogue.json", (route) =>
    route.fulfill({ json: grouped }),
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "Zoom to matches", exact: true })
    .click();
  const cluster = page.locator(".marker-cluster").first();
  await expect(cluster).toHaveText("2");
  await cluster.click();
  await expect(page.locator("canvas.station-points")).toHaveAttribute(
    "data-spiderfied",
    "2",
  );
  await page
    .getByRole("button", { name: "Inspect beta / 001", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Gauge details" }),
  ).toContainText("beta / 001");
  await expect(
    page.getByRole("tab", { name: "Selection (0)", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Gauge in this group", { exact: true }),
  ).toHaveCount(0);
});

test("reduced Filtering panel owns dates and omits removed UI", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("tab", { name: "Filtering", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Start date", { exact: true })).toBeVisible();
  await expect(page.getByLabel("End date", { exact: true })).toBeVisible();
  await page.getByText("More filters", { exact: true }).click();
  for (const label of [
    "day definition",
    "timestamp anchor",
    "time zone",
    "vertical reference",
    "vertical datum",
    "variant",
    "series id",
  ])
    await expect(page.getByLabel(label, { exact: true })).toHaveCount(0);
  await expect(
    page.getByText("Browse gauge list", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("About this catalogue", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText(/Catalogue series and physical facts/),
  ).toHaveCount(0);
  await expect(
    page.getByText(/Source wall-clock dates; both endpoints/),
  ).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Date documentation", exact: true }),
  ).toHaveAttribute("href", "../../usage/#time-labels-and-request-windows");
  await page.getByLabel("Start date", { exact: true }).fill("2020-01-01");
  await expect(page.getByTestId("match-count")).toHaveText("3 matching gauges");
  await page.getByRole("tab", { name: "Python", exact: true }).click();
  await expect(
    page.getByLabel("Start date", { exact: true }),
  ).not.toBeVisible();
});

test("outside-world space is not reported as a tile failure", async ({
  page,
}) => {
  await page.setViewportSize({ width: 2600, height: 900 });
  await page.route(
    /https:\/\/(?:tile\.openstreetmap\.org|a\.basemaps\.cartocdn\.com)\//,
    (route) =>
      route.fulfill({
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l1sAAAAASUVORK5CYII=",
          "base64",
        ),
      }),
  );
  await page.goto("/");
  await expect
    .poll(() => page.locator(".leaflet-tile-loaded").count())
    .toBeGreaterThan(0);
  const view = page.locator("canvas.station-points");
  while (Number(await view.getAttribute("data-zoom")) > 3) {
    const before = Number(await view.getAttribute("data-zoom"));
    await page.getByRole("button", { name: "Zoom out", exact: true }).click();
    await expect
      .poll(async () => Number(await view.getAttribute("data-zoom")))
      .toBeLessThan(before);
  }
  await expect(view).toHaveAttribute("data-zoom", "3");
  await expect(
    page.getByRole("button", { name: "Zoom out", exact: true }),
  ).toHaveAttribute("aria-disabled", "true");
  await expect(
    page.getByText(
      "Some basemap tiles are unavailable. Gauge points remain visible.",
    ),
  ).toHaveCount(0);
});

test("Python preview highlights syntax while clipboard stays exact plain code", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/");
  await page.getByLabel("Start date", { exact: true }).fill("2020-01-01");
  await page.getByLabel("provider", { exact: true }).selectOption("alpha");
  await page
    .getByRole("button", { name: "Add all matches", exact: true })
    .click();
  await page.getByRole("tab", { name: "Python", exact: true }).click();
  const code = page.getByLabel("Python request");
  await expect(code.locator(".token.keyword").first()).toHaveText("import");
  await expect(code.locator(".token.string").first()).toBeVisible();
  const plain = await code.textContent();
  await page.getByRole("button", { name: "Copy Python request" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(plain);
  await page.getByRole("tab", { name: "Filtering", exact: true }).click();
  await page.getByLabel("provider", { exact: true }).selectOption("beta");
  await page
    .getByRole("button", { name: "Add all matches", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Clear filters", exact: true })
    .click();
  await page.getByRole("tab", { name: "Python", exact: true }).click();
  const multi = await code.textContent();
  await page.getByRole("button", { name: "Copy Python request" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(multi);
  expect(multi).toContain("results_by_provider");
});

test("initial view is around Switzerland without narrowing discovery or selecting gauges", async ({
  page,
}) => {
  await page.goto("/");
  const view = page.locator("canvas.station-points");
  await expect
    .poll(async () => Number(await view.getAttribute("data-center-lat")))
    .toBeGreaterThan(46);
  expect(Number(await view.getAttribute("data-center-lat"))).toBeLessThan(48);
  expect(Number(await view.getAttribute("data-center-lng"))).toBeGreaterThan(6);
  expect(Number(await view.getAttribute("data-center-lng"))).toBeLessThan(11);
  expect(Number(await view.getAttribute("data-zoom"))).toBeGreaterThanOrEqual(
    6,
  );
  await expect(page.getByLabel("provider", { exact: true })).toHaveValue("");
  await expect(page.getByTestId("match-count")).toHaveText("3 matching gauges");
  await expect(
    page.getByRole("tab", { name: "Selection (0)", exact: true }),
  ).toBeVisible();
});

test("initial mobile view keeps Switzerland above the bottom panel", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const canvas = page.locator("canvas.station-points");
  await expect(canvas).toHaveAttribute("data-zoom", /^[0-9]+$/);
  const center = await canvas.evaluate((node) => ({
    lat: Number(node.dataset.centerLat),
    lng: Number(node.dataset.centerLng),
    zoom: Number(node.dataset.zoom),
  }));
  const map = (await page
    .getByLabel("Gauge map", { exact: true })
    .boundingBox())!;
  const panel = (await page
    .getByRole("complementary", { name: "Gauge request panel" })
    .boundingBox())!;
  const world = 256 * 2 ** center.zoom;
  const mercatorY = (latitude: number) => {
    const radians = (latitude * Math.PI) / 180;
    return (
      ((1 - Math.log(Math.tan(radians) + 1 / Math.cos(radians)) / Math.PI) /
        2) *
      world
    );
  };
  // Bern is an independent Swiss reference point, not a map implementation value.
  const bernX = map.x + map.width / 2 + ((7.4474 - center.lng) / 360) * world;
  const bernY =
    map.y + map.height / 2 + mercatorY(46.948) - mercatorY(center.lat);
  expect(bernX).toBeGreaterThan(map.x + 20);
  expect(bernX).toBeLessThan(map.x + map.width - 20);
  expect(bernY).toBeGreaterThan(map.y + 80);
  expect(bernY).toBeLessThan(panel.y - 20);
});

test("configured CARTO changes style without resetting the map or selection", async ({
  page,
}) => {
  const styles: string[] = [];
  await page.route("https://a.basemaps.cartocdn.com/**", (route) => {
    styles.push(new URL(route.request().url()).pathname.split("/")[1]);
    return route.abort();
  });
  await page.goto("/");
  const map = page.getByLabel("Gauge map", { exact: true });
  await expect(map).toHaveAttribute("data-basemap", "light_all");
  await expect(
    page.getByRole("link", { name: "CARTO", exact: true }),
  ).toBeVisible();
  await page.getByLabel("provider", { exact: true }).selectOption("alpha");
  await page
    .getByRole("button", { name: "Add all matches", exact: true })
    .click();
  const canvas = page.locator("canvas.station-points");
  const zoom = Number(await canvas.getAttribute("data-zoom"));
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect(canvas).toHaveAttribute("data-zoom", String(zoom + 1));
  const before = await canvas.evaluate((node) => [
    node.dataset.centerLat,
    node.dataset.centerLng,
    node.dataset.zoom,
  ]);
  await page.evaluate(() => {
    document.documentElement.dataset.mdColorScheme = "slate";
  });
  await expect(map).toHaveAttribute("data-basemap", "dark_all");
  await expect(page.locator(".leaflet-tile-pane > .leaflet-layer")).toHaveCount(
    1,
  );
  expect(
    await canvas.evaluate((node) => [
      node.dataset.centerLat,
      node.dataset.centerLng,
      node.dataset.zoom,
    ]),
  ).toEqual(before);
  await expect(
    page.getByRole("tab", { name: "Selection (1)", exact: true }),
  ).toBeVisible();
  expect(styles).toContain("light_all");
  expect(styles).toContain("dark_all");
});

test("native cluster click separates nearby gauges as zoom increases", async ({
  page,
}) => {
  const nearby = structuredClone(fixture);
  nearby.stations[1][3] = 10;
  nearby.stations[1][4] = 10.001;
  await page.route("**/catalogue.json", (route) =>
    route.fulfill({ json: nearby }),
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "Zoom to matches", exact: true })
    .click();
  const before = Number(
    await page.locator("canvas.station-points").getAttribute("data-zoom"),
  );
  await page.locator(".marker-cluster").first().click();
  await expect
    .poll(async () =>
      Number(
        await page.locator("canvas.station-points").getAttribute("data-zoom"),
      ),
    )
    .toBeGreaterThan(before);
  await expect(
    page.getByRole("button", { name: "Inspect alpha / 001", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Inspect beta / 001", exact: true }),
  ).toBeVisible();
});

test("theme switch safely retires pending tile loads", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", () => errors.push("pageerror"));
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("https://a.basemaps.cartocdn.com/**", async (route) => {
    if (new URL(route.request().url()).pathname.startsWith("/light_all/"))
      await gate;
    try {
      await route.fulfill({
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l1sAAAAASUVORK5CYII=",
          "base64",
        ),
      });
    } catch {
      /* The retired layer may cancel its request. */
    }
  });
  try {
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.locator(".map")).toHaveAttribute(
      "data-basemap",
      "light_all",
    );
    await page.evaluate(() => {
      document.documentElement.dataset.mdColorScheme = "slate";
    });
    await expect(page.locator(".map")).toHaveAttribute(
      "data-basemap",
      "dark_all",
    );
    release();
    await expect
      .poll(() => page.locator(".leaflet-tile-loaded").count())
      .toBeGreaterThan(0);
    await expect(
      page.locator(".leaflet-tile-pane > .leaflet-layer"),
    ).toHaveCount(1);
    expect(errors).toEqual([]);
  } finally {
    release();
  }
});
