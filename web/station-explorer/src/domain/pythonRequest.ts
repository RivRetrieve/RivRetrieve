import { dateErrors } from "./dates";
import { selectionConflicts } from "./filtering";
import { canonicalizeFrequency, frequencyError } from "./frequency";
import {
  physicalFields,
  type Filters,
  type Provider,
  type RequestDates,
  type RequestEvaluation,
  type RequestPreview,
  type RequestSettings,
  type StationCatalogue,
  type StationRecord,
} from "./types";

// JSON string escaping also produces Python string literals (not JSON booleans/null).
function pythonString(value: string): string {
  return JSON.stringify(value)
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

function requestSettings(filters: Filters): RequestSettings {
  const { provider: _provider, station: _station, ...settings } = filters;
  return settings;
}

function activeSettingEntries(settings: RequestSettings): [string, string][] {
  const entries: [string, string][] = [];
  for (const field of physicalFields) {
    const value = settings[field];
    if (value !== undefined && value !== "") entries.push([field, value]);
  }
  return entries;
}

/** Evaluate conflicts, date/frequency validity, provider capability, and exact grouping without formatting full code. */
export function evaluateRequest(
  selected: StationRecord[],
  filters: Filters,
  dates: RequestDates,
  catalogue: Pick<StationCatalogue, "facts" | "factSets" | "providerById">,
): RequestEvaluation {
  const settings = requestSettings(filters);
  const conflicts = selectionConflicts(
    selected,
    settings,
    catalogue.facts,
    catalogue.factSets,
  );
  const blockingReasons: string[] = [];
  if (!selected.length) {
    blockingReasons.push(
      "Select at least one gauge. An empty selection must not become an unrestricted request.",
    );
  }
  if (conflicts.length) {
    blockingReasons.push(
      `${conflicts.length} selected ${conflicts.length === 1 ? "gauge conflicts" : "gauges conflict"} with the request settings. Change request settings or remove non-matching gauges.`,
    );
  }
  blockingReasons.push(...Object.values(dateErrors(dates)));
  const freqErr = frequencyError(settings.frequency);
  if (freqErr) blockingReasons.push(freqErr);

  const seenKeys = new Set<string>();
  const groups = new Map<string, string[]>();
  const uniqueStationIds = new Set<string>();
  for (let i = 0; i < selected.length; i++) {
    const station = selected[i];
    if (seenKeys.has(station.key)) continue;
    seenKeys.add(station.key);
    uniqueStationIds.add(station.station_id);
    let group = groups.get(station.provider_id);
    if (!group) {
      group = [];
      groups.set(station.provider_id, group);
    }
    group.push(station.station_id);
  }

  for (const id of groups.keys()) {
    const provider = catalogue.providerById.get(id);
    if (!provider) {
      blockingReasons.push(`${id}: retrieval capability is not established.`);
    } else if (!provider.retrieval) {
      blockingReasons.push(
        `${id} is catalogue-only. Remove its gauges to generate a retrieval request.`,
      );
    }
  }

  const stationIds = Array.from(uniqueStationIds);
  // Combined lists are exact only when every provider selects every listed ID.
  let combined = groups.size > 1;
  if (combined) {
    for (const ids of groups.values()) {
      if (ids.length !== stationIds.length) {
        combined = false;
        break;
      }
    }
  }

  let stationCount = 0;
  if (combined) {
    stationCount = stationIds.length;
  } else {
    for (const ids of groups.values()) stationCount += ids.length;
  }

  return {
    conflicts,
    blockingReasons,
    groups,
    stationIds,
    combined,
    stationCount,
    omittedStationCount: Math.max(0, stationCount - 10),
  };
}

/** Format a Python retrieval script from a precomputed evaluation, capping displayed IDs to `limit`. */
export function formatPythonRequest(
  evaluation: RequestEvaluation,
  filters: Filters,
  dates: RequestDates,
  providerById: ReadonlyMap<string, Provider>,
  limit: number,
): string {
  if (!evaluation.groups.size) {
    return "# Select at least one gauge to build a request.";
  }

  const settings = requestSettings(filters);
  const lines = ["import rivretrieve as rr", ""];
  for (const id of evaluation.groups.keys()) {
    const provider = providerById.get(id);
    if (provider?.credentials.length) {
      lines.push(
        `# ${pythonString(id)} credentials: ${provider.credentials.map(pythonString).join(", ")}.`,
        "# https://rivretrieve.github.io/usage/#supplied-credentials",
      );
    }
    if (provider?.bulk) {
      lines.push(
        "# National archive preparation uses bandwidth and disk space.",
      );
      if (id === "ca_eccc") {
        lines.push(
          "# Set SQLITE_TMPDIR and TMPDIR to suitable scratch directories.",
        );
      }
      lines.push(`rr.download(${pythonString(id)})`);
    }
  }

  const args = activeSettingEntries(settings).map(
    ([field, value]) =>
      `${field}=${pythonString(field === "frequency" ? (canonicalizeFrequency(value) ?? value) : value)}`,
  );
  const findCall = `selection = rr.find(${args.join(", ")})`;
  lines.push(
    findCall.length <= 72
      ? findCall
      : ["selection = rr.find(", ...args.map((arg) => `    ${arg},`), ")"].join(
          "\n",
        ),
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
    const visible =
      remaining === Infinity ? stations : stations.slice(0, remaining);
    if (remaining !== Infinity) remaining -= visible.length;
    const rows = visible.map((id) => `        ${pythonString(id)},`);
    const omitted = stations.length - visible.length;
    // A displayed omission is deliberately invalid Python, never a wildcard [].
    // Parsing the whole preview fails before imports, downloads or retrieval.
    if (omitted) rows.push(`        … ${omitted} more station IDs omitted`);
    return rows.length ? `[\n${rows.join("\n")}\n    ]` : "[]";
  };

  if (evaluation.combined) {
    lines.push(
      "gauges = rr.pick(",
      "    selection,",
      `    provider=[${Array.from(evaluation.groups.keys()).map(pythonString).join(", ")}],`,
      `    station=${stationList(evaluation.stationIds)},`,
      ")",
      fetchCall("results_by_provider", "fetch_by_provider"),
      "for result in results_by_provider.values():",
      "    for issue in result.issues:",
      "        print(issue)",
      "",
      "# for provider, result in results_by_provider.items():",
      '#     result.to_polars().write_csv(f"observations_{provider}.csv")',
    );
  } else if (evaluation.groups.size > 1) {
    lines.push(
      "# Keep provider/station pairs exact where IDs overlap.",
      "stations_by_provider = {",
      ...Array.from(
        evaluation.groups,
        ([id, stations]) => `    ${pythonString(id)}: ${stationList(stations)},`,
      ),
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
  } else {
    const [id, stations] = Array.from(evaluation.groups)[0];
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
  if (evaluation.blockingReasons.length) {
    // Keep the unresolved request visible, but make even a manual preview copy inert.
    code = [
      "# UNRESOLVED REQUEST: copy/export is blocked.",
      ...evaluation.blockingReasons.flatMap((reason) =>
        reason.split(/\r\n|\r|\n/).map((line) => `# ${line}`),
      ),
      "",
      ...code.split("\n").map((line) => `# ${line}`),
    ].join("\n");
  }
  return code;
}

/** Evaluate and format both shortened preview and full Python request. */
export function generateRequest(
  selected: StationRecord[],
  filters: Filters,
  dates: RequestDates,
  catalogue: Pick<StationCatalogue, "facts" | "factSets" | "providerById">,
): RequestPreview {
  const evaluation = evaluateRequest(selected, filters, dates, catalogue);
  return {
    code: formatPythonRequest(
      evaluation,
      filters,
      dates,
      catalogue.providerById,
      Infinity,
    ),
    previewCode: formatPythonRequest(
      evaluation,
      filters,
      dates,
      catalogue.providerById,
      10,
    ),
    omittedStationCount: evaluation.omittedStationCount,
    blockingReasons: evaluation.blockingReasons,
    conflicts: evaluation.conflicts,
  };
}
