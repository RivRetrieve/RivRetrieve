export const physicalFields = [
  "quantity",
  "frequency",
  "statistic",
  "temporal_support",
  "day_definition",
  "timestamp_anchor",
  "time_zone",
  "vertical_reference",
  "vertical_datum",
] as const;
export const filterFields = [
  "provider",
  "station",
  ...physicalFields,
  "variant",
  "series_id",
] as const;
export type PhysicalField = (typeof physicalFields)[number];
export type FilterField = (typeof filterFields)[number];
export type Filters = Partial<Record<FilterField, string>>;
export type FactState = "known" | "source_silent" | "not_established";
export type Series = Partial<Record<PhysicalField, string | null>> &
  Partial<Record<`${PhysicalField}_state`, FactState>> & {
    admission: "supported" | "unsupported";
    series_id: string;
    variant: string | null;
    published_id: string | null;
  };
export interface Station {
  provider_id: string;
  station_id: string;
  station_name: string | null;
  latitude: number | null;
  longitude: number | null;
  crs: string | null;
  series: Series[];
}
export interface Provider {
  name?: string;
  provider_id: string;
  retrieval: boolean;
  bulk: boolean;
  credentials: string[];
}
export interface RequestDates {
  start: string;
  end: string;
}
export interface Conflict {
  key: string;
  station: Station;
  reasons: string[];
}
export interface RequestPreview {
  code: string;
  previewCode: string;
  omittedStationCount: number;
  blockingReasons: string[];
  conflicts: Conflict[];
}

export function stationKey(
  station: Pick<Station, "provider_id" | "station_id">,
): string {
  return JSON.stringify([station.provider_id, station.station_id]);
}
function fieldValues(
  station: Station,
  series: Series,
  field: FilterField,
): (string | null | undefined)[] {
  if (field === "provider") return [station.provider_id];
  if (field === "station") return [station.station_id];
  if (field === "variant") return [series.variant, series.published_id];
  if (physicalFields.includes(field as PhysicalField)) {
    const state = series[`${field as PhysicalField}_state`];
    if (state && state !== "known") return [null];
  }
  return [series[field as keyof Series]];
}
function activeFilters(filters: Filters): [FilterField, string][] {
  return filterFields.flatMap((field) =>
    filters[field] === undefined
      ? []
      : [[field, filters[field]!] as [FilterField, string]],
  );
}
export function matchesStation(station: Station, filters: Filters): boolean {
  return station.series.some(
    (series) =>
      series.admission === "supported" &&
      activeFilters(filters).every(([field, value]) =>
        fieldValues(station, series, field).includes(value),
      ),
  );
}
export function filterStations(
  stations: Station[],
  filters: Filters,
): Station[] {
  return stations.filter((station) => matchesStation(station, filters));
}
export function addStations(
  selected: Station[],
  additions: Station[],
): Station[] {
  return [
    ...new Map(
      [...selected, ...additions].map((station) => [
        stationKey(station),
        station,
      ]),
    ).values(),
  ];
}
export function removeStation(selected: Station[], key: string): Station[] {
  return selected.filter((station) => stationKey(station) !== key);
}
export function selectionConflicts(
  selected: Station[],
  filters: Filters,
): Conflict[] {
  return selected
    .filter((station) => !matchesStation(station, filters))
    .map((station) => {
      const reasons = activeFilters(filters).flatMap(([field, requested]) => {
        const values = station.series.flatMap((series) =>
          fieldValues(station, series, field),
        );
        if (values.includes(requested)) return [];
        const known = [
          ...new Set(values.filter((value): value is string => value != null)),
        ];
        return [
          known.length
            ? `${field}: requested ${JSON.stringify(requested)}; catalogue lists ${known.map((value) => JSON.stringify(value)).join(", ")}.${values.some((value) => value == null) ? " Other facts are not established." : ""}`
            : `${field} is not established in the catalogue; it cannot match ${JSON.stringify(requested)}.`,
        ];
      });
      if (!station.series.length) {
        reasons.push(
          "No source series is established for this catalogue entry. It cannot match the current discovery request.",
        );
      } else if (
        !station.series.some((series) => series.admission === "supported")
      ) {
        reasons.push(
          "The catalogue establishes no fact segment with supported numeric admission for this gauge.",
        );
      }
      if (!reasons.length)
        reasons.push(
          "No single supported catalogue series and fact segment matches this combination of filters.",
        );
      return { key: stationKey(station), station, reasons };
    });
}

function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.slice(0, 4) === "0000")
    return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return (
    Number.isFinite(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === value
  );
}
// JSON string escaping also produces Python string literals (not JSON booleans/null).
function pythonString(value: string): string {
  return JSON.stringify(value)
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}
export function generateRequest(
  selected: Station[],
  filters: Filters,
  dates: RequestDates,
  providers: Provider[],
  catalogueStations: Station[],
): RequestPreview {
  const conflicts = selectionConflicts(selected, filters);
  const blockingReasons: string[] = [];
  if (!selected.length)
    blockingReasons.push(
      "Select at least one gauge. An empty selection must not become an unrestricted request.",
    );
  if (conflicts.length)
    blockingReasons.push(
      `${conflicts.length} selected gauge(s) conflict with the filters. Change filters or remove non-matching gauges.`,
    );
  if (!validDate(dates.start))
    blockingReasons.push("Enter a valid start date (YYYY-MM-DD).");
  if (dates.end && !validDate(dates.end))
    blockingReasons.push("Enter a valid end date (YYYY-MM-DD).");
  if (validDate(dates.start) && validDate(dates.end) && dates.start > dates.end)
    blockingReasons.push("Start date must not be after end date.");
  const groups = new Map<string, string[]>();
  for (const station of addStations([], selected)) {
    const group = groups.get(station.provider_id) ?? [];
    group.push(station.station_id);
    groups.set(station.provider_id, group);
  }
  for (const id of groups.keys()) {
    const provider = providers.find((item) => item.provider_id === id);
    if (!provider)
      blockingReasons.push(`${id}: retrieval capability is not established.`);
    else if (!provider.retrieval)
      blockingReasons.push(
        `${id} is catalogue-only. Remove its gauges to generate a retrieval request.`,
      );
  }
  const selectedKeys = new Set(selected.map(stationKey));
  const stationIds = [
    ...new Set(selected.map((station) => station.station_id)),
  ];
  const selectedIds = new Set(stationIds);
  const hasCrossPair = catalogueStations.some(
    (station) =>
      groups.has(station.provider_id) &&
      selectedIds.has(station.station_id) &&
      !selectedKeys.has(stationKey(station)),
  );
  const combined = groups.size > 1 && !hasCrossPair;
  const writeCode = (limit: number) => {
    const lines = ["import rivretrieve as rr", ""];
    for (const id of groups.keys()) {
      const provider = providers.find((item) => item.provider_id === id);
      if (provider?.credentials.length)
        lines.push(
          `# ${pythonString(id)} credentials: ${provider.credentials.map(pythonString).join(", ")}.`,
        );
      if (provider?.bulk) {
        lines.push(
          "# National archive preparation uses bandwidth and disk space.",
        );
        if (id === "ca_eccc")
          lines.push(
            "# Set SQLITE_TMPDIR and TMPDIR to suitable scratch directories.",
          );
        lines.push(`rr.download(${pythonString(id)})`);
      }
    }
    const args = activeFilters(filters).map(
      ([field, value]) => `${field}=${pythonString(value)}`,
    );
    const findCall = `selection = rr.find(${args.join(", ")})`;
    lines.push(
      findCall.length <= 72
        ? findCall
        : [
            "selection = rr.find(",
            ...args.map((arg) => `    ${arg},`),
            ")",
          ].join("\n"),
    );
    const fetchCall = (target: string, method: string, indent = "") =>
      [
        `${indent}${target} = rr.${method}(`,
        `${indent}    gauges,`,
        `${indent}    start=${pythonString(dates.start)},`,
        `${indent}    end=${dates.end ? pythonString(dates.end) : "None"},`,
        `${indent})`,
      ].join("\n");
    let remaining = limit;
    const stationList = (stations: string[]) => {
      const visible = stations.slice(0, remaining);
      remaining -= visible.length;
      const rows = visible.map((id) => `        ${pythonString(id)},`);
      const omitted = stations.length - visible.length;
      // A displayed omission is deliberately invalid Python, never a wildcard [].
      // Parsing the whole preview fails before imports, downloads or retrieval.
      if (omitted) rows.push(`        … ${omitted} more station IDs omitted`);
      return rows.length ? `[\n${rows.join("\n")}\n    ]` : "[]";
    };
    if (combined) {
      lines.push(
        "gauges = rr.pick(",
        "    selection,",
        `    provider=[${Array.from(groups.keys()).map(pythonString).join(", ")}],`,
        `    station=${stationList(stationIds)},`,
        ")",
        fetchCall("results_by_provider", "fetch_by_provider"),
        "for result in results_by_provider.values():",
        "    for issue in result.issues:",
        "        print(issue)",
        "",
        "# for provider, result in results_by_provider.items():",
        '#     result.to_polars().write_csv(f"observations_{provider}.csv")',
      );
    } else if (groups.size > 1) {
      lines.push(
        "# Keep provider/station pairs exact where IDs overlap.",
        "stations_by_provider = {",
        ...Array.from(groups, ([id, stations]) => {
          return `    ${pythonString(id)}: ${stationList(stations)},`;
        }),
        "}",
        "results_by_provider = {}",
        "for provider, station_ids in stations_by_provider.items():",
        "    gauges = rr.pick(",
        "        selection, provider=provider, station=station_ids,",
        "    )",
        fetchCall("result", "fetch", "    "),
        "    results_by_provider[provider] = result",
        "    for issue in result.issues:",
        "        print(issue)",
        "",
        "# for provider, result in results_by_provider.items():",
        '#     result.to_polars().write_csv(f"observations_{provider}.csv")',
      );
    } else if (groups.size === 1) {
      const [id, stations] = Array.from(groups)[0];
      lines.push(
        "gauges = rr.pick(",
        "    selection,",
        `    provider=${pythonString(id)},`,
        `    station=${stationList(stations)},`,
        ")",
        fetchCall("results", "fetch"),
        "for issue in results.issues:",
        "    print(issue)",
        "",
        '# results.to_polars().write_csv("observations.csv")',
      );
    }
    let code = lines.join("\n");
    if (blockingReasons.length) {
      // Keep the unresolved request visible, but make even a manual preview copy inert.
      code = [
        "# UNRESOLVED REQUEST: copy/export is blocked.",
        ...blockingReasons.flatMap((reason) =>
          reason.split(/\r\n|\r|\n/).map((line) => `# ${line}`),
        ),
        "",
        ...code.split("\n").map((line) => `# ${line}`),
      ].join("\n");
    }
    return code;
  };
  const stationCount = combined
    ? stationIds.length
    : Array.from(groups.values()).reduce(
        (count, stations) => count + stations.length,
        0,
      );
  return {
    code: writeCode(Infinity),
    previewCode: writeCode(10),
    omittedStationCount: Math.max(0, stationCount - 10),
    blockingReasons,
    conflicts,
  };
}
