import { addStations, removeStation, removeStationKeys } from "../domain/selection";
import type {
  BrowseFilters,
  FilterField,
  RequestDates,
  RequestSettings,
  StationCatalogue,
  StationRecord,
} from "../domain/types";

export const SELECTION_PAGE_SIZE = 30;
export type ExplorerTab = "filtering" | "selection" | "python";

export interface ExplorerState {
  catalogueStatus: "loading" | "ready" | "error";
  catalogue: StationCatalogue | null;
  error: string;
  browse: BrowseFilters;
  settings: RequestSettings;
  selected: StationRecord[];
  inspected: StationRecord | null;
  dates: RequestDates;
  tab: ExplorerTab;
  panelOpen: boolean;
  selectionPage: number;
  copyStatus: string;
}

export type ExplorerAction =
  | { type: "CATALOGUE_LOADED"; catalogue: StationCatalogue }
  | { type: "CATALOGUE_FAILED"; error: string }
  | { type: "SET_BROWSE_FILTER"; field: "provider" | "station"; value: string }
  | { type: "CLEAR_SEARCH" }
  | {
      type: "SET_REQUEST_SETTING";
      field: Exclude<FilterField, "provider" | "station">;
      value: string;
    }
  | { type: "ADD_STATIONS"; stations: StationRecord[] }
  | { type: "REMOVE_STATION"; key: string }
  | { type: "REMOVE_INCOMPATIBLE"; conflictKeys: ReadonlySet<string> }
  | { type: "CLEAR_SELECTION" }
  | { type: "INSPECT_STATION"; station: StationRecord }
  | { type: "CLOSE_INSPECTION" }
  | { type: "SET_DATE"; field: keyof RequestDates; value: string }
  | { type: "SET_TAB"; tab: ExplorerTab }
  | { type: "TOGGLE_PANEL" }
  | { type: "SET_SELECTION_PAGE"; page: number }
  | { type: "SET_COPY_STATUS"; status: string };

export function initialExplorerState(): ExplorerState {
  return {
    catalogueStatus: "loading",
    catalogue: null,
    error: "",
    browse: {},
    settings: {},
    selected: [],
    inspected: null,
    dates: { start: "", end: "" },
    tab: "filtering",
    panelOpen: true,
    selectionPage: 0,
    copyStatus: "",
  };
}

export function selectSafeSelectionPage(state: ExplorerState): number {
  const maxPage = Math.max(
    0,
    Math.ceil(state.selected.length / SELECTION_PAGE_SIZE) - 1,
  );
  return Math.min(state.selectionPage, maxPage);
}

/** Authoritative state transition owner for the station explorer. */
export function explorerReducer(
  state: ExplorerState,
  action: ExplorerAction,
): ExplorerState {
  switch (action.type) {
    case "CATALOGUE_LOADED":
      return {
        ...state,
        catalogueStatus: "ready",
        catalogue: action.catalogue,
        error: "",
      };
    case "CATALOGUE_FAILED":
      return {
        ...state,
        catalogueStatus: "error",
        error: action.error,
      };
    case "SET_BROWSE_FILTER": {
      const nextBrowse = { ...state.browse };
      if (action.value === "") delete nextBrowse[action.field];
      else nextBrowse[action.field] = action.value;
      return { ...state, browse: nextBrowse, copyStatus: "" };
    }
    case "CLEAR_SEARCH":
      return { ...state, browse: {}, copyStatus: "" };
    case "SET_REQUEST_SETTING": {
      const nextSettings = { ...state.settings };
      if (action.value === "") delete nextSettings[action.field];
      else nextSettings[action.field] = action.value;
      return { ...state, settings: nextSettings, copyStatus: "" };
    }
    case "ADD_STATIONS":
      return {
        ...state,
        selected: addStations(state.selected, action.stations),
        copyStatus: "",
      };
    case "REMOVE_STATION":
      return {
        ...state,
        selected: removeStation(state.selected, action.key),
        selectionPage: 0,
        copyStatus: "",
      };
    case "REMOVE_INCOMPATIBLE":
      return {
        ...state,
        selected: removeStationKeys(state.selected, action.conflictKeys),
        selectionPage: 0,
        copyStatus: "",
      };
    case "CLEAR_SELECTION":
      return {
        ...state,
        selected: [],
        selectionPage: 0,
        copyStatus: "",
      };
    case "INSPECT_STATION":
      return {
        ...state,
        inspected: action.station,
        tab: "filtering",
        panelOpen: true,
      };
    case "CLOSE_INSPECTION":
      return { ...state, inspected: null };
    case "SET_DATE":
      return {
        ...state,
        dates: { ...state.dates, [action.field]: action.value },
        copyStatus: "",
      };
    case "SET_TAB":
      return { ...state, tab: action.tab };
    case "TOGGLE_PANEL":
      return { ...state, panelOpen: !state.panelOpen };
    case "SET_SELECTION_PAGE":
      return { ...state, selectionPage: Math.max(0, action.page) };
    case "SET_COPY_STATUS":
      return { ...state, copyStatus: action.status };
  }
}
