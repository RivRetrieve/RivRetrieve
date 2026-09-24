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

// Support both instant navigation (document$) and standard DOMContentLoaded
if (typeof document$ !== "undefined") {
  document$.subscribe(initCopyPageButton);
} else {
  document.addEventListener("DOMContentLoaded", initCopyPageButton);
}
