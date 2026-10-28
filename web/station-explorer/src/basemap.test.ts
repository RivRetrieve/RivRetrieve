import { expect, it } from "vitest";
import { basemapTiles } from "./basemap";
it("uses the public client key for the docs scheme and preserves attribution", () => {
  const light = basemapTiles("default", "synthetic-test-key");
  const dark = basemapTiles("slate", "synthetic-test-key");
  expect(light.url).toBe(
    "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png?key=synthetic-test-key",
  );
  expect(dark.url).toBe(
    "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png?key=synthetic-test-key",
  );
  expect(dark.attribution).toContain("CARTO");
  expect(dark.attribution).toContain("OpenStreetMap");
});
it("keeps unconfigured development usable without pretending CARTO is enabled", () => {
  expect(basemapTiles("slate", undefined).style).toBe("osm");
  expect(basemapTiles("default", "").url).toBe(
    "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  );
});
