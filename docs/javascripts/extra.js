/**
 * Handles icon-only "Copy page text" button across regular page loads and MkDocs instant navigation.
 */
function initCopyPageButton() {
  const btn = document.getElementById("copy-page-btn");
  if (!btn || btn.dataset.copyInitialized === "true") return;

  btn.dataset.copyInitialized = "true";

  btn.addEventListener("click", async function (e) {
    e.preventDefault();

    const rawEl = document.getElementById("__raw_page_markdown__");
    let textToCopy = "";

    if (rawEl && rawEl.value) {
      textToCopy = rawEl.value;
    } else {
      const contentEl = document.querySelector("article.md-content__inner");
      textToCopy = contentEl ? contentEl.innerText : "";
    }

    try {
      await navigator.clipboard.writeText(textToCopy);
      const idleIcon = btn.querySelector("#copy-icon-idle");
      const successIcon = btn.querySelector("#copy-icon-success");

      if (idleIcon) idleIcon.style.display = "none";
      if (successIcon) successIcon.style.display = "inline-block";
      btn.classList.add("copied");
      btn.setAttribute("title", "Copied to clipboard!");

      setTimeout(() => {
        if (idleIcon) idleIcon.style.display = "inline-block";
        if (successIcon) successIcon.style.display = "none";
        btn.classList.remove("copied");
        btn.setAttribute("title", "Copy page text for LLM");
      }, 2000);
    } catch (err) {
      console.error("Failed to copy page text to clipboard:", err);
    }
  });
}

/** Add a site-only shortcut while keeping the README disclosure usable on GitHub. */
function initCopyAgentPromptButton() {
  const disclosure = document.getElementById("agent-prompt");
  const code = disclosure?.querySelector("pre code");
  if (!code || document.getElementById("copy-agent-prompt-btn")) return;

  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = "copy-agent-prompt-btn";
  btn.className = "md-button";
  btn.textContent = "Copy agent prompt";
  btn.setAttribute("aria-live", "polite");
  disclosure.before(btn);
  btn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(code.textContent);
      btn.textContent = "Copied!";
    } catch (err) {
      btn.textContent = "Copy failed. Open the prompt to copy it manually.";
      console.error("Failed to copy agent prompt to clipboard:", err);
    }
    setTimeout(() => { btn.textContent = "Copy agent prompt"; }, 2000);
  });
}

function initCopyButtons() {
  initCopyPageButton();
  initCopyAgentPromptButton();
}

// Support both instant navigation (document$) and standard DOMContentLoaded
if (typeof document$ !== "undefined") {
  document$.subscribe(initCopyButtons);
} else {
  document.addEventListener("DOMContentLoaded", initCopyButtons);
}
