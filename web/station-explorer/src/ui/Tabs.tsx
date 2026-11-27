import {
  createContext,
  useContext,
  useId,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from "react";

interface TabsContextValue {
  baseId: string;
  value: string;
  onValueChange: (value: string) => void;
  registerTab: (value: string, el: HTMLButtonElement | null) => void;
  getTabOrder: () => string[];
  focusTab: (value: string) => void;
}

const TabsContext = createContext<TabsContextValue | null>(null);

function useTabsContext(): TabsContextValue {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error("Tabs parts must be rendered inside <Tabs>");
  return ctx;
}

export function Tabs({
  value,
  onValueChange,
  children,
}: {
  value: string;
  onValueChange: (value: string) => void;
  children: ReactNode;
}) {
  const baseId = useId();
  const listRef = useRef<HTMLDivElement | null>(null);
  const tabRefs = useRef(new Map<string, HTMLButtonElement>());

  const registerTab = (tabValue: string, el: HTMLButtonElement | null) => {
    if (el) tabRefs.current.set(tabValue, el);
    else tabRefs.current.delete(tabValue);
  };

  const getTabOrder = () => {
    const buttons = Array.from(
      listRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]') ??
        [],
    );
    return buttons
      .map((btn) => btn.dataset.tabValue)
      .filter((v): v is string => v !== undefined);
  };

  const focusTab = (tabValue: string) => {
    tabRefs.current.get(tabValue)?.focus();
  };

  return (
    <TabsContext.Provider
      value={{
        baseId,
        value,
        onValueChange,
        registerTab,
        getTabOrder,
        focusTab,
      }}
    >
      <TabsListContainerContext.Provider value={listRef}>
        {children}
      </TabsListContainerContext.Provider>
    </TabsContext.Provider>
  );
}

const TabsListContainerContext =
  createContext<React.RefObject<HTMLDivElement | null> | null>(null);

export function TabsList({
  className,
  "aria-label": ariaLabel,
  children,
}: {
  className?: string;
  "aria-label": string;
  children: ReactNode;
}) {
  const listRef = useContext(TabsListContainerContext);
  return (
    <div
      ref={listRef}
      className={className}
      role="tablist"
      aria-label={ariaLabel}
    >
      {children}
    </div>
  );
}

export function TabsTab({
  value,
  children,
}: {
  value: string;
  children: ReactNode;
}) {
  const ctx = useTabsContext();
  const selected = ctx.value === value;
  const tabId = `${ctx.baseId}-tab-${value}`;
  const panelId = `${ctx.baseId}-panel-${value}`;

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const order = ctx.getTabOrder();
    const index = order.indexOf(value);
    if (index < 0 || !order.length) return;
    let nextValue: string | undefined;
    if (event.key === "ArrowRight") {
      nextValue = order[(index + 1) % order.length];
    } else if (event.key === "ArrowLeft") {
      nextValue = order[(index - 1 + order.length) % order.length];
    } else if (event.key === "Home") {
      nextValue = order[0];
    } else if (event.key === "End") {
      nextValue = order[order.length - 1];
    }
    if (nextValue !== undefined) {
      event.preventDefault();
      ctx.onValueChange(nextValue);
      ctx.focusTab(nextValue);
    }
  };

  return (
    <button
      ref={(el) => ctx.registerTab(value, el)}
      id={tabId}
      type="button"
      role="tab"
      data-tab-value={value}
      aria-selected={selected}
      aria-controls={panelId}
      tabIndex={selected ? 0 : -1}
      onClick={() => ctx.onValueChange(value)}
      onKeyDown={handleKeyDown}
    >
      {children}
    </button>
  );
}

export function TabsPanel({
  value,
  children,
}: {
  value: string;
  children: ReactNode;
}) {
  const ctx = useTabsContext();
  const selected = ctx.value === value;
  const tabId = `${ctx.baseId}-tab-${value}`;
  const panelId = `${ctx.baseId}-panel-${value}`;
  return (
    <div
      id={panelId}
      role="tabpanel"
      aria-labelledby={tabId}
      hidden={!selected}
    >
      {children}
    </div>
  );
}
