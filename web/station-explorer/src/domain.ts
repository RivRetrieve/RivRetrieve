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
export type BrowseFilters = Pick<Filters, "provider" | "station">;
export type RequestSettings = Omit<Filters, "provider" | "station">;
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
  water_body_names?: string[];
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

const ELAPSED_RE = /^PT(?:([0-9]+)H)?(?:([0-9]+)M)?(?:([0-9]+)S)?$/;
const CALENDAR_DAYS_RE = /^P(?:([0-9]+)W)?(?:([0-9]+)D)?$/;
const CALENDAR_MONTHS_RE = /^P(?:([0-9]+)Y)?(?:([0-9]+)M)?$/;

function parseOptionalBigInt(raw: string | undefined): bigint {
  return raw === undefined ? 0n : BigInt(raw);
}

export function canonicalizeFrequency(raw: string): string | null {
  const elapsed = ELAPSED_RE.exec(raw);
  if (
    elapsed &&
    (elapsed[1] !== undefined ||
      elapsed[2] !== undefined ||
      elapsed[3] !== undefined)
  ) {
    const totalSeconds =
      parseOptionalBigInt(elapsed[1]) * 3600n +
      parseOptionalBigInt(elapsed[2]) * 60n +
      parseOptionalBigInt(elapsed[3]);
    if (totalSeconds <= 0n) return null;
    if (totalSeconds % 3600n === 0n) return `PT${totalSeconds / 3600n}H`;
    if (totalSeconds % 60n === 0n) return `PT${totalSeconds / 60n}M`;
    return `PT${totalSeconds}S`;
  }
  const days = CALENDAR_DAYS_RE.exec(raw);
  if (days && (days[1] !== undefined || days[2] !== undefined)) {
    const totalDays =
      parseOptionalBigInt(days[1]) * 7n + parseOptionalBigInt(days[2]);
    if (totalDays <= 0n) return null;
    if (totalDays % 7n === 0n) return `P${totalDays / 7n}W`;
    return `P${totalDays}D`;
  }
  const months = CALENDAR_MONTHS_RE.exec(raw);
  if (months && (months[1] !== undefined || months[2] !== undefined)) {
    const totalMonths =
      parseOptionalBigInt(months[1]) * 12n + parseOptionalBigInt(months[2]);
    if (totalMonths <= 0n) return null;
    if (totalMonths % 12n === 0n) return `P${totalMonths / 12n}Y`;
    return `P${totalMonths}M`;
  }
  return null;
}

export function frequencyError(raw: string | undefined): string | null {
  if (raw === undefined || raw === "") return null;
  if (canonicalizeFrequency(raw) !== null) return null;
  return 'Enter a positive ISO 8601 duration in one family, such as "PT15M", "PT1H", "P1D", "P1W", "P1M", or "P1Y".';
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
  const raw = series[field as keyof Series];
  if (field === "frequency" && typeof raw === "string") {
    return [canonicalizeFrequency(raw) ?? raw];
  }
  return [raw];
}
function activeFilters(filters: Filters): [FilterField, string][] {
  return filterFields.flatMap((field) =>
    filters[field] === undefined
      ? []
      : [[field, filters[field]!] as [FilterField, string]],
  );
}
export function matchesStation(station: Station, filters: Filters): boolean {
  const entries = activeFilters(filters);
  const resolved: [FilterField, string][] = [];
  for (const [field, value] of entries) {
    if (field === "frequency") {
      const canonical = canonicalizeFrequency(value);
      if (canonical === null) return false;
      resolved.push([field, canonical]);
    } else {
      resolved.push([field, value]);
    }
  }
  return station.series.some(
    (series) =>
      series.admission === "supported" &&
      resolved.every(([field, value]) =>
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
function requestSettings({
  provider: _provider,
  station: _station,
  ...settings
}: Filters): RequestSettings {
  return settings;
}
export function selectionConflicts(
  selected: Station[],
  filters: Filters,
): Conflict[] {
  const settings = requestSettings(filters);
  return selected
    .filter((station) => !matchesStation(station, settings))
    .map((station) => {
      const reasons = activeFilters(settings).flatMap(([field, requested]) => {
        let target = requested;
        if (field === "frequency") {
          const err = frequencyError(requested);
          if (err) return [err];
          target = canonicalizeFrequency(requested) ?? requested;
        }
        const values = station.series.flatMap((series) =>
          fieldValues(station, series, field),
        );
        if (values.includes(target)) return [];
        const known = [
          ...new Set(values.filter((value): value is string => value != null)),
        ];
        return [
          known.length
            ? `${field}: requested ${JSON.stringify(target)}; catalogue lists ${known.map((value) => JSON.stringify(value)).join(", ")}.${values.some((value) => value == null) ? " Other facts are not established." : ""}`
            : `${field} is not established in the catalogue; it cannot match ${JSON.stringify(target)}.`,
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
          "No single supported catalogue series and fact segment matches this combination of request settings.",
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
export function dateErrors(
  dates: RequestDates,
): Partial<Record<keyof RequestDates, string>> {
  const errors: Partial<Record<keyof RequestDates, string>> = {};
  if (!validDate(dates.start))
    errors.start = "Enter a valid start date (YYYY-MM-DD).";
  if (dates.end && !validDate(dates.end))
    errors.end = "Enter a valid end date (YYYY-MM-DD).";
  if (validDate(dates.start) && validDate(dates.end) && dates.start > dates.end)
    errors.end = "Start date must not be after end date.";
  return errors;
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
  const settings = requestSettings(filters);
  const conflicts = selectionConflicts(selected, settings);
  const blockingReasons: string[] = [];
  if (!selected.length)
    blockingReasons.push(
      "Select at least one gauge. An empty selection must not become an unrestricted request.",
    );
  if (conflicts.length)
    blockingReasons.push(
      `${conflicts.length} selected ${conflicts.length === 1 ? "gauge conflicts" : "gauges conflict"} with the request settings. Change request settings or remove non-matching gauges.`,
    );
  blockingReasons.push(...Object.values(dateErrors(dates)));
  const freqError = frequencyError(settings.frequency);
  if (freqError) blockingReasons.push(freqError);
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
  const stationIds = [
    ...new Set(selected.map((station) => station.station_id)),
  ];
  // Combined lists are exact only when every provider selects every listed ID.
  const combined =
    groups.size > 1 &&
    Array.from(groups.values()).every(
      (ids) => ids.length === stationIds.length,
    );
  const writeCode = (limit: number) => {
    if (!selected.length)
      return "# Select at least one gauge to build a request.";
    const lines = ["import rivretrieve as rr", ""];
    for (const id of groups.keys()) {
      const provider = providers.find((item) => item.provider_id === id);
      if (provider?.credentials.length)
        lines.push(
          `# ${pythonString(id)} credentials: ${provider.credentials.map(pythonString).join(", ")}.`,
          "# https://rivretrieve.github.io/usage/#supplied-credentials",
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
    const args = activeFilters(settings).map(
      ([field, value]) =>
        `${field}=${pythonString(field === "frequency" ? (canonicalizeFrequency(value) ?? value) : value)}`,
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
