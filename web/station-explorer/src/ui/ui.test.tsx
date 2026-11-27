// @vitest-environment jsdom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Tabs, TabsList, TabsPanel, TabsTab } from "./Tabs";
import { CoordinateWarning } from "./CoordinateWarning";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => {
    root.unmount();
  });
  host.remove();
});

function TabsHarness() {
  const [tab, setTab] = useState<"filtering" | "selection" | "python">("filtering");
  return (
    <Tabs value={tab} onValueChange={(next) => setTab(next as typeof tab)}>
      <TabsList className="tabs" aria-label="Request steps">
        <TabsTab value="filtering">Filtering</TabsTab>
        <TabsTab value="selection">Selection</TabsTab>
        <TabsTab value="python">Python</TabsTab>
      </TabsList>
      <TabsPanel value="filtering">Filtering body</TabsPanel>
      <TabsPanel value="selection">Selection body</TabsPanel>
      <TabsPanel value="python">Python body</TabsPanel>
    </Tabs>
  );
}

describe("Tabs primitive", () => {
  it("exposes WAI-ARIA relationships, roving tabindex, click, and arrow/home/end keyboard navigation", () => {
    act(() => {
      root.render(<TabsHarness />);
    });

    const tabs = Array.from(host.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
    const panels = Array.from(host.querySelectorAll<HTMLElement>('[role="tabpanel"]'));
    expect(tabs).toHaveLength(3);
    expect(panels).toHaveLength(3);

    expect(tabs[0].getAttribute("aria-selected")).toBe("true");
    expect(tabs[0].tabIndex).toBe(0);
    expect(tabs[1].tabIndex).toBe(-1);
    expect(panels[0].hidden).toBe(false);
    expect(panels[1].hidden).toBe(true);
    expect(tabs[0].getAttribute("aria-controls")).toBe(panels[0].id);
    expect(panels[0].getAttribute("aria-labelledby")).toBe(tabs[0].id);

    // ArrowRight moves to Selection and focuses it
    act(() => {
      tabs[0].focus();
      tabs[0].dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });
    expect(tabs[1].getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(tabs[1]);
    expect(panels[1].hidden).toBe(false);

    // End jumps to Python
    act(() => {
      tabs[1].dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true }));
    });
    expect(tabs[2].getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(tabs[2]);

    // ArrowRight wraps to Filtering
    act(() => {
      tabs[2].dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(tabs[0]);

    // ArrowLeft wraps to Python
    act(() => {
      tabs[0].dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }));
    });
    expect(tabs[2].getAttribute("aria-selected")).toBe("true");

    // Home jumps to Filtering
    act(() => {
      tabs[2].dispatchEvent(new KeyboardEvent("keydown", { key: "Home", bubbles: true }));
    });
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");

    // Click switches tab
    act(() => {
      tabs[1].click();
    });
    expect(tabs[1].getAttribute("aria-selected")).toBe("true");
    expect(panels[1].hidden).toBe(false);
  });
});

describe("CoordinateWarning primitive", () => {
  it("opens on hover, focus, and click/tap and closes on mouseleave, Escape, and blur", () => {
    act(() => {
      root.render(
        <div>
          <CoordinateWarning>Unknown CRS warning text</CoordinateWarning>
          <button type="button">Outside</button>
        </div>,
      );
    });

    const wrapper = host.querySelector<HTMLElement>(".coordinate-warning")!;
    const trigger = host.querySelector<HTMLButtonElement>(".coordinate-warning-trigger")!;
    const tooltip = host.querySelector<HTMLElement>('[role="tooltip"]')!;
    const outside = host.querySelectorAll<HTMLButtonElement>("button")[1];

    expect(tooltip.hidden).toBe(true);
    expect(trigger.getAttribute("aria-describedby")).toBe(tooltip.id);

    // Hover open & leave close
    act(() => {
      wrapper.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    });
    expect(tooltip.hidden).toBe(false);
    act(() => {
      wrapper.dispatchEvent(new MouseEvent("mouseout", { bubbles: true, relatedTarget: outside }));
    });
    expect(tooltip.hidden).toBe(true);

    // Focus open & Escape close
    act(() => {
      trigger.focus();
      trigger.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    });
    expect(tooltip.hidden).toBe(false);
    act(() => {
      trigger.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(tooltip.hidden).toBe(true);

    // Click/tap open & blur close
    act(() => {
      trigger.click();
    });
    expect(tooltip.hidden).toBe(false);
    act(() => {
      outside.focus();
      trigger.dispatchEvent(new FocusEvent("focusout", { bubbles: true, relatedTarget: outside }));
    });
    expect(tooltip.hidden).toBe(true);
  });
});
