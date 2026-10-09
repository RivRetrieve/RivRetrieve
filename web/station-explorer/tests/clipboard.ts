import type { Page } from "@playwright/test";

/** Observe successful writes from this page, never the user's system clipboard. */
export async function captureClipboardWrites(page: Page) {
  await page.addInitScript(() => {
    if (!navigator.clipboard) return;
    const write = navigator.clipboard.writeText.bind(navigator.clipboard);
    const owner = window.top ?? window;
    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText(value: string) {
          const pending = write(value).then(() => {
            Reflect.set(owner, "__copiedRequest", value);
          });
          Reflect.set(owner, "__requestCopyPending", pending);
          return pending;
        },
        async readText() {
          await Reflect.get(owner, "__requestCopyPending");
          return Reflect.get(owner, "__copiedRequest") ?? "";
        },
      },
    });
  });
}
