import type { StationCatalogue } from "../domain/types";
import { decodeCatalogue, type WireCatalogueV3 } from "./wire";

/** Fetch and decode the offline public station catalogue JSON snapshot. */
export async function loadCatalogue(
  url: string,
  signal: AbortSignal,
  fetchImpl: typeof fetch = fetch,
): Promise<StationCatalogue> {
  const response = await fetchImpl(url, { signal });
  if (!response.ok) {
    throw new Error(`Catalogue loading failed (${response.status}).`);
  }
  const wire = (await response.json()) as WireCatalogueV3;
  return decodeCatalogue(wire);
}
