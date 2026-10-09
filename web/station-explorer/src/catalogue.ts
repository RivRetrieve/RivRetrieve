import {
  physicalFields,
  type FactState,
  type Provider,
  type Series,
  type Station,
} from "./domain";

type Fact = { value: string | null; state: FactState };
type Profile = Record<(typeof physicalFields)[number], Fact> & {
  admission: "supported" | "unsupported";
};
interface CompactCatalogue {
  version: number;
  providers: Provider[];
  stations: [
    number,
    string,
    string | null,
    number | null,
    number | null,
    string | null,
  ][];
  facts: Profile[];
  series: [number, string, string | null, string | null, number[]][];
}

/** Expand shared physical profiles without joining facts across segments. */
export function expandCatalogue(data: CompactCatalogue): {
  stations: Station[];
  providers: Provider[];
} {
  if (data.version !== 1)
    throw new Error("Unsupported catalogue format. Regenerate the catalogue.");
  const stations: Station[] = data.stations.map(
    ([provider, station_id, station_name, latitude, longitude, crs]) => {
      if (!data.providers[provider])
        throw new Error("Catalogue station references a missing provider.");
      return {
        provider_id: data.providers[provider].provider_id,
        station_id,
        station_name,
        latitude,
        longitude,
        crs,
        series: [],
      };
    },
  );
  for (const [
    stationIndex,
    series_id,
    variant,
    published_id,
    profiles,
  ] of data.series) {
    const station = stations[stationIndex];
    if (!station)
      throw new Error("Catalogue series references a missing station.");
    for (const index of profiles) {
      const facts = data.facts[index];
      if (!facts)
        throw new Error("Catalogue series references missing physical facts.");
      const series: Series = {
        series_id,
        variant,
        published_id,
        admission: facts.admission,
      };
      for (const field of physicalFields) {
        series[field] = facts[field].value;
        series[`${field}_state`] = facts[field].state;
      }
      station.series.push(series);
    }
  }
  return { stations, providers: data.providers };
}
