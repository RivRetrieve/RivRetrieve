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
  const lines = [
    "import rivretrieve as rr",
    "",
    "# Catalogue listings do not guarantee observations in these dates.",
    "# Dates use source wall-clock labels; a date-only end includes the whole day.",
    "# Source responses may reveal additional matching series unless explicitly restricted.",
  ];
  if (!dates.end)
    lines.push(
      "# end=None uses the caller machine's current local date when Python runs.",
      "# The start must not be after that date.",
    );
  const args = activeFilters(filters).map(
    ([field, value]) => `    ${field}=${pythonString(value)},`,
  );
  lines.push(
    "selection = rr.find(",
    ...args,
    ")",
    "for issue in selection.issues:",
    "    print(issue)",
    "",
  );
  if (groups.size > 1) lines.push("results_by_provider = {}", "");
  for (const [id, stations] of groups) {
    const provider = providers.find((item) => item.provider_id === id);
    if (provider?.credentials.length) {
      lines.push(
        `# Required credentials for ${pythonString(id)}: ${provider.credentials.map(pythonString).join(", ")}.`,
        "# Set them in the process environment or working-directory .env file.",
        "# Keep secret values out of this script and the browser.",
      );
    }
    if (provider?.bulk) {
      lines.push(
        "# Download and compile the national archive. This can use substantial bandwidth and disk space.",
      );
      if (id === "ca_eccc")
        lines.push(
          "# Set SQLITE_TMPDIR and TMPDIR to suitable scratch directories before starting Python.",
        );
      lines.push(`rr.download(${pythonString(id)})`, "");
    }
    lines.push(
      "gauges = rr.pick(",
      "    selection,",
      `    provider=${pythonString(id)},`,
      "    station=[",
      ...stations.map((station) => `        ${pythonString(station)},`),
      "    ],",
      ")",
      "for issue in gauges.issues:",
      "    print(issue)",
      `results = rr.fetch(gauges, start=${pythonString(dates.start)}, end=${dates.end ? pythonString(dates.end) : "None"})`,
      "# Inspect issues even when observation rows are returned.",
      "for issue in results.issues:",
      "    print(issue)",
    );
    if (groups.size > 1)
      lines.push(`results_by_provider[${pythonString(id)}] = results`);
    lines.push("");
  }
  if (groups.size === 1)
    lines.push(
      "# To save the observations as CSV:",
      '# results.to_polars().write_csv("observations.csv")',
    );
  else if (groups.size > 1)
    lines.push(
      "# To save observations as one CSV per provider:",
      "# for provider, result in results_by_provider.items():",
      '#     result.to_polars().write_csv(f"observations_{provider}.csv")',
    );
  let code = lines.join("\n");
  if (blockingReasons.length) {
    // Keep the unresolved request visible, but make even a manual preview copy inert.
    code = [
      "# UNRESOLVED REQUEST: copy/export is blocked.",
      ...blockingReasons.flatMap((reason) =>
        reason.split(/\r\n|\r|\n/).map((line) => `# ${line}`),
      ),
      "",
      ...lines.map((line) => `# ${line}`),
    ].join("\n");
  }
  return { code, blockingReasons, conflicts };
}
