import { useEffect, useRef, type ReactNode } from "react";
import type { ExplorerTab } from "../state/explorerState";
import { Tabs, TabsList, TabsPanel, TabsTab } from "../ui/Tabs";

interface ExplorerPanelProps {
  panelOpen: boolean;
  tab: ExplorerTab;
  selectedCount: number;
  conflictCount: number;
  scrollSignal: unknown;
  onTogglePanel: () => void;
  onTabChange: (tab: ExplorerTab) => void;
  filteringContent: ReactNode;
  selectionContent: ReactNode;
  pythonContent: ReactNode;
}

/** Floating/docked request panel hosting Filtering, Selection, and Python tabs. */
export function ExplorerPanel({
  panelOpen,
  tab,
  selectedCount,
  conflictCount,
  scrollSignal,
  onTogglePanel,
  onTabChange,
  filteringContent,
  selectionContent,
  pythonContent,
}: ExplorerPanelProps) {
  const panelContent = useRef<HTMLDivElement>(null);
  useEffect(() => {
    panelContent.current?.scrollTo?.({ top: 0 });
  }, [tab, scrollSignal]);

  return (
    <>
      <button
        type="button"
        className="panel-toggle"
        onClick={onTogglePanel}
        aria-expanded={panelOpen}
      >
        {panelOpen
          ? "Hide panel"
          : `Gauges · ${selectedCount.toLocaleString()} selected`}
      </button>
      <aside
        className={panelOpen ? "panel" : "panel hidden"}
        aria-label="Gauge request panel"
      >
        <Tabs
          value={tab}
          onValueChange={(next) => onTabChange(next as ExplorerTab)}
        >
          <TabsList className="tabs" aria-label="Request steps">
            <TabsTab value="filtering">Filtering</TabsTab>
            <TabsTab value="selection">
              Selection ({selectedCount.toLocaleString()})
              {conflictCount ? " ⚠" : ""}
            </TabsTab>
            <TabsTab value="python">Python</TabsTab>
          </TabsList>
          <div className="panel-content" ref={panelContent}>
            <TabsPanel value="filtering">{filteringContent}</TabsPanel>
            <TabsPanel value="selection">{selectionContent}</TabsPanel>
            <TabsPanel value="python">{pythonContent}</TabsPanel>
          </div>
        </Tabs>
      </aside>
    </>
  );
}
