const osmAttribution =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

/** Resolve a tile source without changing the map or its selection. */
export function basemapTiles(
  scheme: string | undefined,
  key: string | undefined,
) {
  if (!key)
    return {
      style: "osm",
      url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      attribution: osmAttribution,
    };
  const style = scheme === "slate" ? "dark_all" : "light_all";
  return {
    style,
    url: `https://a.basemaps.cartocdn.com/${style}/{z}/{x}/{y}.png?key=${encodeURIComponent(key)}`,
    attribution: `${osmAttribution}, &copy; <a href="https://carto.com/attributions">CARTO</a>`,
  };
}
