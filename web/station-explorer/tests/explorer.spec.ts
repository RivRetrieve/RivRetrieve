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
  await page.route("**/catalogue.json", (route) =>
    route.fulfill({ json: fixture }),
  );
  await page.route("https://tile.openstreetmap.org/**", (route) =>
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
  await page.getByLabel("Start date", { exact: true }).fill("2020-01-01");
  await page.getByLabel("End date", { exact: true }).fill("2020-01-02");
  await page.getByRole("tab", { name: "Discover", exact: true }).click();
  await page.getByText("Browse gauge list", { exact: true }).click();
  await page
    .getByRole("button", { name: "Inspect alpha / 001", exact: true })
    .click();
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
  await page.getByRole("tab", { name: "Discover", exact: true }).click();
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
  await page.getByRole("tab", { name: "Discover", exact: true }).click();
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

test("catalogue-only and zero-series entries remain inspectable and block output", async ({
  page,
}) => {
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
  await page.getByRole("tab", { name: "Discover", exact: true }).click();
  await page
    .getByRole("button", { name: "Clear filters", exact: true })
    .click();
  await page.getByText("Browse gauge list", { exact: true }).click();
  await page
    .getByLabel("Include entries without matching series", { exact: false })
    .check();
  await page
    .getByRole("button", { name: "Inspect alpha / empty", exact: true })
    .click();
  await page.getByRole("button", { name: "Add gauge", exact: true }).click();
  await page.getByRole("tab", { name: /Selection/ }).click();
  await expect(page.getByTestId("selection-counts")).toHaveText(
    "0 matching · 1 conflicting",
  );
  await expect(
    page.getByText(
      "No source series is established for this catalogue entry. It cannot match the current discovery request.",
    ),
  ).toBeVisible();
});

test("map fills viewport with one compact tabbed panel", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(
    page.getByRole("tab", { name: "Discover", exact: true }),
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

test("counted groups zoom, then expose co-located gauges individually", async ({
  page,
}) => {
  const grouped = structuredClone(fixture);
  grouped.stations[1][3] = 10;
  grouped.stations[1][4] = 10;
  await page.route("**/catalogue.json", (route) =>
    route.fulfill({ json: grouped }),
  );
  await page.goto("/");
  const group = page.getByRole("button", {
    name: "Zoom to group of 2 gauges",
    exact: true,
  });
  await expect(group).toBeVisible();
  await group.click();
  await expect(page.locator("canvas.station-points")).toHaveAttribute(
    "data-zoom",
    "18",
  );
  await group.click();
  await expect(
    page.getByText("2 gauges in the clicked group.", { exact: false }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Inspect beta / 001", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Gauge details" }),
  ).toContainText("beta / 001");
  await expect(
    page.getByRole("tab", { name: "Selection (0)", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Clear filters", exact: true })
    .click();
  await expect(
    page.getByText("2 gauges in the clicked group.", { exact: false }),
  ).toHaveCount(0);
  await group.click();
  await page
    .getByLabel("Include entries without matching series", { exact: false })
    .check();
  await expect(
    page.getByText("2 gauges in the clicked group.", { exact: false }),
  ).toHaveCount(0);
});
