import { useEffect, useMemo, useReducer, type ComponentType } from "react";
import { loadCatalogue } from "../catalogue/loader";
import { filterCatalogueStations } from "../domain/filtering";
import { evaluateRequest, formatPythonRequest } from "../domain/pythonRequest";
import type { Conflict, Provider, StationRecord } from "../domain/types";
import { StationMap, type StationMapProps } from "../map/StationMap";
import {
  explorerReducer,
  initialExplorerState,
  selectSafeSelectionPage,
} from "../state/explorerState";
import { ExplorerPanel } from "./ExplorerPanel";
import { FilteringTab } from "./FilteringTab";
import { PythonTab } from "./PythonTab";
import { SelectionTab } from "./SelectionTab";
import "../styles/style.css";
import "../styles/panel.css";

const EMPTY_STATIONS: StationRecord[] = [];
const EMPTY_PROVIDER_MAP: ReadonlyMap<string, Provider> = new Map();

export interface ExplorerAppProps {
  MapComponent?: ComponentType<StationMapProps>;
  basemapKey?: string;
  catalogueUrl?: string;
  loadCatalogueFn?: typeof loadCatalogue;
}

/** Top-level station explorer coordinating catalogue loading, state, map, and request panel. */
export function ExplorerApp({
  MapComponent = StationMap,
  basemapKey = import.meta.env.VITE_CARTO_BASEMAP_API_KEY?.trim() || undefined,
  catalogueUrl,
  loadCatalogueFn = loadCatalogue,
}: ExplorerAppProps = {}) {
  const [state, dispatch] = useReducer(
    explorerReducer,
    undefined,
    initialExplorerState,
  );

  useEffect(() => {
    const controller = new AbortController();
    const resolvedUrl =
      catalogueUrl ?? new URL("catalogue.json", document.baseURI).toString();
    loadCatalogueFn(resolvedUrl, controller.signal)
      .then((catalogue) => dispatch({ type: "CATALOGUE_LOADED", catalogue }))
      .catch((reason: unknown) => {
        if ((reason as { name?: string })?.name !== "AbortError") {
          dispatch({ type: "CATALOGUE_FAILED", error: String(reason) });
        }
      });
    return () => controller.abort();
  }, [catalogueUrl, loadCatalogueFn]);

  const matches = useMemo(() => {
    if (!state.catalogue) return EMPTY_STATIONS;
    return filterCatalogueStations(state.catalogue, state.browse, state.settings);
  }, [state.catalogue, state.browse, state.settings]);

  const evaluation = useMemo(() => {
    if (!state.catalogue) {
      return {
        conflicts: [] as Conflict[],
        blockingReasons: [] as string[],
        groups: new Map<string, string[]>(),
        stationIds: [] as string[],
        combined: false,
        stationCount: 0,
        omittedStationCount: 0,
      };
    }
    return evaluateRequest(
      state.selected,
      state.settings,
      state.dates,
      state.catalogue,
    );
  }, [state.selected, state.settings, state.dates, state.catalogue]);

  const conflictsByKey = useMemo(
    () =>
      new Map(evaluation.conflicts.map((conflict) => [conflict.key, conflict])),
    [evaluation.conflicts],
  );

  const conflictKeys = useMemo(
    () => new Set(conflictsByKey.keys()),
    [conflictsByKey],
  );

  const selectedKeys = useMemo(() => {
    const keys = new Set<string>();
    for (let i = 0; i < state.selected.length; i++) {
      keys.add(state.selected[i].key);
    }
    return keys;
  }, [state.selected]);

  const previewCode = useMemo(() => {
    if (state.tab !== "python" || !state.catalogue) return "";
    return formatPythonRequest(
      evaluation,
      state.settings,
      state.dates,
      state.catalogue.providerById,
      10,
    );
  }, [state.tab, state.catalogue, evaluation, state.settings, state.dates]);

  async function copyFullRequest() {
    if (!state.catalogue || evaluation.blockingReasons.length) return;
    const fullCode = formatPythonRequest(
      evaluation,
      state.settings,
      state.dates,
      state.catalogue.providerById,
      Infinity,
    );
    try {
      await navigator.clipboard.writeText(fullCode);
      dispatch({
        type: "SET_COPY_STATUS",
        status: "Complete Python request copied.",
      });
    } catch {
      dispatch({
        type: "SET_COPY_STATUS",
        status: "Clipboard unavailable. Allow clipboard access and try again.",
      });
    }
  }

  if (state.catalogueStatus === "error") {
    return (
      <main>
        <h1>Station request builder</h1>
        <p role="alert">
          {state.error} Prepare the catalogue assets and reload this page.
        </p>
      </main>
    );
  }

  const safeSelectionPage = selectSafeSelectionPage(state);

  return (
    <main className="explorer">
      <MapComponent
        catalogueStations={state.catalogue?.stations ?? EMPTY_STATIONS}
        matches={matches}
        selected={state.selected}
        selectedKeys={selectedKeys}
        conflictKeys={conflictKeys}
        basemapKey={basemapKey}
        onInspect={(station) => dispatch({ type: "INSPECT_STATION", station })}
      />
      <ExplorerPanel
        panelOpen={state.panelOpen}
        tab={state.tab}
        selectedCount={state.selected.length}
        conflictCount={conflictsByKey.size}
        scrollSignal={state.inspected}
        onTogglePanel={() => dispatch({ type: "TOGGLE_PANEL" })}
        onTabChange={(tab) => dispatch({ type: "SET_TAB", tab })}
        filteringContent={
          <FilteringTab
            catalogue={state.catalogue}
            catalogueStatus={state.catalogueStatus}
            browse={state.browse}
            settings={state.settings}
            matches={matches}
            inspected={state.inspected}
            selectedKeys={selectedKeys}
            onBrowseChange={(field, value) =>
              dispatch({ type: "SET_BROWSE_FILTER", field, value })
            }
            onSettingChange={(field, value) =>
              dispatch({ type: "SET_REQUEST_SETTING", field, value })
            }
            onAddStations={(stations) =>
              dispatch({ type: "ADD_STATIONS", stations })
            }
            onRemoveStation={(key) =>
              dispatch({ type: "REMOVE_STATION", key })
            }
            onCloseInspection={() => dispatch({ type: "CLOSE_INSPECTION" })}
            onClearSearch={() => dispatch({ type: "CLEAR_SEARCH" })}
          />
        }
        selectionContent={
          <SelectionTab
            selected={state.selected}
            conflicts={conflictsByKey}
            providerById={
              state.catalogue?.providerById ?? EMPTY_PROVIDER_MAP
            }
            blockingReasonCount={evaluation.blockingReasons.length}
            page={safeSelectionPage}
            onPageChange={(page) =>
              dispatch({ type: "SET_SELECTION_PAGE", page })
            }
            onInspect={(station) =>
              dispatch({ type: "INSPECT_STATION", station })
            }
            onRemoveStation={(key) =>
              dispatch({ type: "REMOVE_STATION", key })
            }
            onRemoveIncompatible={() =>
              dispatch({ type: "REMOVE_INCOMPATIBLE", conflictKeys })
            }
            onClearSelection={() => dispatch({ type: "CLEAR_SELECTION" })}
            onPreviewPython={() =>
              dispatch({ type: "SET_TAB", tab: "python" })
            }
          />
        }
        pythonContent={
          <PythonTab
            active={state.tab === "python"}
            dates={state.dates}
            selectedCount={state.selected.length}
            omittedStationCount={evaluation.omittedStationCount}
            blockingReasons={evaluation.blockingReasons}
            previewCode={previewCode}
            copyStatus={state.copyStatus}
            onDateChange={(field, value) =>
              dispatch({ type: "SET_DATE", field, value })
            }
            onCopy={copyFullRequest}
          />
        }
      />
    </main>
  );
}
