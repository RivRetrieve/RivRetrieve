# Source terms finding — jp_mlit

Agency: MLIT Water Information System
Country: Japan
Status: not-started

Read `../BRIEF.md` first. The one rule: write down what the agency says, never what it
means. Every quote must be copied out of a page you recorded.

## Candidate pages (UNVERIFIED — leads only)

| URL | Page title | Lang | Why a candidate |
|---|---|---|---|
| http://www1.river.go.jp/caution.html | 利用規約等 | ja | The site's own "terms etc." page — a link hub, not the terms document itself |
| http://www1.river.go.jp/WDBrules_20251210.pdf | ウェブDB利用規約, dated 2025-12-10 | ja | **Current** terms PDF, linked from caution.html; contains an explicit 出典の記載 (source-citation) clause |
| http://www1.river.go.jp/WDBrules_20240125.pdf | same document, earlier version | ja | Still live and what search engines surface — **record the 2025 one, not this** |

**Read this before you start on Japan.**

- `www1.river.go.jp` **blocks non-browser clients**: plain fetches get 403 with "This site
  prohibits data acquisition using tools, etc." `record.py` will fail. Save these pages by
  hand from your browser (**Save As → Web Page, HTML only**) into `pages/`, and write a JSON
  sidecar by hand with the url, the UTC instant and the sha256 — or ask for help; do not skip it.
- The site is **frameset-based** and served in **EUC-JP**, so titles look garbled in
  UTF-8 tools. That is an encoding artefact, not a wrong page.
- The current terms document is a **PDF**. The checker cannot machine-verify a quote inside a
  PDF, so it will tell you to explain that in Notes. Quote it accurately anyway.

## licence

- Page URL:
- Recording:
- Retrieved (UTC):
- Language:
- Agency publishes nothing: no

The exact sentence stating the terms, in its original language, copied not retyped:

```text
```

## citation

- Page URL:
- Recording:
- Retrieved (UTC):
- Language:
- Agency publishes nothing: no

The exact wording the agency asks to be credited with:

```text
```

## Notes

Where you looked, what defeated you, anything the next reader needs. Say if a page was
behind a login, needed a browser, or was only available through a third party.
