/** Check whether raw coordinates and CRS are displayable on the WGS84 exploration map. */
export function isPlottableCoordinates(
  latitude: number | null,
  longitude: number | null,
  crs: string | null,
): boolean {
  return (
    latitude !== null &&
    longitude !== null &&
    Number.isFinite(latitude) &&
    Number.isFinite(longitude) &&
    Math.abs(latitude) <= 90 &&
    Math.abs(longitude) <= 180 &&
    (crs === "EPSG:4326" ||
      crs === "EPSG:4269" ||
      crs === "unknown" ||
      crs === null)
  );
}
