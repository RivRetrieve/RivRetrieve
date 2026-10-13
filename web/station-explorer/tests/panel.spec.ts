import { test, expect } from "@playwright/test";
import { captureClipboardWrites } from "./clipboard";

test.use({ hasTouch: true });

// Small synthetic catalogue: repeated IDs remain provider-qualified, names may be absent.
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
const fixture = {
  version: 2,
  providers: [
    {
      name: "Alpha Hydrology",
      provider_id: "alpha",
      retrieval: true,
      bulk: false,
      credentials: [],
    },
    {
      provider_id: "catalogue",
      retrieval: false,
      bulk: false,
      credentials: [],
    },
  ],
  stations: [
    [
      0,
      "001",
      "River at the old bridge with a long published station name",
      47,
      8,
      "EPSG:4326",
      ["Mår", "MÅRVATN"],
    ],
    [1, "001", null, null, null, null, []],
  ],
  facts: [
    {
      ...Object.fromEntries(
        fields.map((field) => [
          field,
          {
            value: field === "quantity" ? "discharge" : null,
            state: field === "quantity" ? "known" : "not_established",
          },
        ]),
      ),
      admission: "supported",
    },
  ],
  series: [
    [0, "a", null, null, [0]],
    [1, "b", null, null, [0]],
  ],
};

test.beforeEach(async ({ page }) => {
  await page.route("**/catalogue.json", (route) =>
    route.fulfill({ json: fixture }),
  );
  await page.route(
    /https:\/\/(?:tile\.openstreetmap\.org|a\.basemaps\.cartocdn\.com)\//,
    (route) => route.abort(),
  );
});

test("selection cards expose names, qualified identities, state and separate actions", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Add all matches", exact: true })
    .click();
  await page.getByRole("tab", { name: /Selection/ }).click();
  const alpha = page
    .locator(".selection-list li")
    .filter({ hasText: "alpha / 001" });
  await expect(alpha).toContainText(
    "River at the old bridge with a long published station name",
  );
  await expect(alpha).toContainText("Matches measurement settings");
  const other = page
    .locator(".selection-list li")
    .filter({ hasText: "catalogue / 001" });
  await expect(other).toContainText("Station name not established");
  await expect(other).toContainText("catalogue only");
  const inspect = alpha.getByRole("button", {
    name: "Inspect selected alpha / 001",
    exact: true,
  });
  await inspect.focus();
  await expect(inspect).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("region", { name: "Gauge details" }),
  ).toContainText("alpha / 001");
  await page.getByLabel("Provider", { exact: true }).selectOption("alpha");
  await page.getByRole("tab", { name: /Selection/ }).click();
  await expect(other).toContainText("Matches measurement settings");
  await other
    .getByRole("button", { name: "Remove catalogue / 001", exact: true })
    .click();
  await expect(other).toHaveCount(0);
  await expect(alpha).toBeVisible();
});

test("panel gives desktop cards space and retains a half-height mobile map view", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const panel = page.getByRole("complementary", {
    name: "Gauge request panel",
  });
  await expect(panel).toBeVisible();
  expect((await panel.boundingBox())!.width).toBeGreaterThanOrEqual(450);
  expect((await panel.boundingBox())!.width).toBeLessThanOrEqual(470);
  await page
    .getByRole("button", { name: "Add all matches", exact: true })
    .click();
  await page.getByRole("tab", { name: /Selection/ }).click();
  await page.setViewportSize({ width: 800, height: 844 });
  const medium = (await panel.boundingBox())!;
  expect(medium.y).toBeGreaterThanOrEqual(844 / 2 - 24);
  expect(medium.height).toBeLessThanOrEqual(422);
  await page.setViewportSize({ width: 390, height: 844 });
  const box = (await panel.boundingBox())!;
  expect(box.width).toBeLessThanOrEqual(390);
  // Half-height panel plus the existing 24px attribution clearance.
  expect(box.y).toBeGreaterThanOrEqual(844 / 2 - 24);
  expect(box.height).toBeLessThanOrEqual(422);
  expect(
    await panel.evaluate((node) => node.scrollWidth <= node.clientWidth),
  ).toBe(true);
  const card = page.locator(".selection-list li").first();
  expect(
    await card.evaluate((node) => node.scrollWidth <= node.clientWidth),
  ).toBe(true);
  await card
    .getByRole("button", { name: "Remove alpha / 001", exact: true })
    .click();
  await expect(
    page.getByRole("tab", { name: "Selection (1)", exact: true }),
  ).toBeVisible();
});

test("Python tab limits displayed gauge IDs while copying the full selection", async ({
  page,
  context,
}) => {
  await captureClipboardWrites(page);
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const many = {
    ...fixture,
    stations: Array.from({ length: 12 }, (_, i) => [
      0,
      `gauge-${String(i).padStart(2, "0")}`,
      `River ${i}`,
      47,
      8,
      "EPSG:4326",
      [],
    ]),
    series: Array.from({ length: 12 }, (_, i) => [
      i,
      `series-${i}`,
      null,
      null,
      [0],
    ]),
  };
  await page.route("**/catalogue.json", (route) =>
    route.fulfill({ json: many }),
  );
  await page.goto("/");
  await page.getByRole("tab", { name: "Python", exact: true }).click();
  await page.getByLabel("Start date", { exact: true }).fill("2020-01-01");
  await page.getByRole("tab", { name: "Filtering", exact: true }).click();
  await page
    .getByRole("button", { name: "Add all matches", exact: true })
    .click();
  await page.getByRole("tab", { name: "Python", exact: true }).click();
  const code = page.getByLabel("Python request");
  await expect(code).not.toContainText('"gauge-10"');
  await expect(code).not.toContainText('"gauge-11"');
  await expect(
    page.getByText("10 gauge IDs shown. Copy includes all 12 gauges.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Show complete preview", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Copy Python request", exact: true })
    .click();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  for (let i = 0; i < 12; i++)
    expect(copied).toContain(`"gauge-${String(i).padStart(2, "0")}"`);
});

for (const [crs, warning] of [
  ["unknown", "Unknown CRS. Plotted as EPSG:4326 for exploration only."],
  [
    "EPSG:4269",
    "NAD83 (EPSG:4269) coordinates displayed on the WGS84 basemap without a datum transformation. Approximate location only.",
  ],
]) {
  test(`coordinate warning for ${crs} is available on hover, focus and tap`, async ({
    page,
  }) => {
    const uncertain = structuredClone(fixture);
    uncertain.stations[0][5] = crs;
    await page.route("**/catalogue.json", (route) =>
      route.fulfill({ json: uncertain }),
    );
    await page.goto("/");
    await page
      .getByRole("button", { name: "Add all matches", exact: true })
      .click();
    await page.getByRole("tab", { name: /Selection/ }).click();
    await page
      .getByRole("button", {
        name: "Inspect selected alpha / 001",
        exact: true,
      })
      .click();
    const details = page.getByRole("region", { name: "Gauge details" });
    const trigger = details.getByRole("button", {
      name: "Coordinate reference warning",
      exact: true,
    });
    const tooltip = details.getByRole("tooltip");
    await expect(trigger).toBeVisible();
    await expect(tooltip).toBeHidden();
    await trigger.hover();
    await expect(tooltip).toHaveText(warning);
    await page.getByRole("tab", { name: "Filtering", exact: true }).hover();
    await expect(tooltip).toBeHidden();
    await trigger.focus();
    await expect(tooltip).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(tooltip).toBeHidden();
    await trigger.tap(); // Touch activation must not depend on hover.
    await expect(tooltip).toBeVisible();
    await page.getByRole("button", { name: "Close gauge details" }).focus();
    await expect(tooltip).toBeHidden();
  });
}

test("Python preview mounts only while the Python tab is active", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("tab", { name: "Filtering", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".python-preview")).toHaveCount(0);
  await page.getByRole("tab", { name: "Python", exact: true }).click();
  await expect(page.getByLabel("Python request")).toBeVisible();
  await page.getByRole("tab", { name: "Filtering", exact: true }).click();
  await expect(page.locator(".python-preview")).toHaveCount(0);
});

test("mobile inspection puts add action and water body before browsing controls", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByLabel("Provider", { exact: true }).selectOption("alpha");
  await expect(
    page.getByLabel("Provider", { exact: true }).locator("option:checked"),
  ).toHaveText("Alpha Hydrology (alpha)");
  await page.getByRole("button", { name: "Zoom to matches" }).click();
  await page.getByRole("button", { name: "Hide panel" }).click();
  await page
    .getByRole("button", { name: "Inspect alpha / 001", exact: true })
    .click();
  const details = page.getByRole("region", { name: "Gauge details" });
  await expect(details).toContainText("Water body: Mår · MÅRVATN");
  const add = details.getByRole("button", { name: "Add gauge", exact: true });
  const panel = page.locator(".panel-content");
  const bounds = (await panel.boundingBox())!;
  const action = (await add.boundingBox())!;
  expect(action.y).toBeGreaterThanOrEqual(bounds.y);
  expect(action.y + action.height).toBeLessThanOrEqual(
    bounds.y + bounds.height,
  );
  await add.click();
  await expect(
    page.getByRole("tab", { name: "Selection (1)", exact: true }),
  ).toBeVisible();
});

test("retrieval date errors are beside inputs and block copying without changing matches", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Provider", { exact: true }).selectOption("alpha");
  await page
    .getByRole("button", { name: "Add all matches", exact: true })
    .click();
  await page.getByRole("tab", { name: "Python", exact: true }).click();
  const start = page.getByLabel("Start date", { exact: true });
  const end = page.getByLabel("End date", { exact: true });
  const copy = page.getByRole("button", { name: "Copy Python request" });
  await expect(start).toHaveAttribute("aria-invalid", "true");
  await expect(start).toHaveAccessibleDescription(/valid start date/);
  await expect(copy).toBeDisabled();
  await start.fill("2020-02-02");
  await end.fill("2020-02-01");
  await expect(end).toHaveAccessibleDescription(/must not be after/);
  await expect(copy).toBeDisabled();
  await end.fill("2020-02-03");
  await expect(end).toHaveAttribute("aria-invalid", "false");
  await expect(copy).toBeEnabled();
  await page.getByRole("tab", { name: "Filtering", exact: true }).click();
  await expect(page.getByTestId("match-count")).toHaveText("1 matching gauge");
});
