# Agent onboarding prompt

Related issue: https://github.com/RivRetrieve/RivRetrieve/issues/438

## Outcome

After installation, a user can click **Copy agent prompt** on the documentation
homepage, paste the prompt into a coding agent, and continue working with
RivRetrieve. This is a lean v0.1.0 documentation feature, not a package release
operation. It helps agents use the public library, not contribute to its internals.

Keep installation and the existing quick start in the root README. Add a small
agent-onboarding section immediately after installation. Do not introduce a
separate Getting started page or reorganise the documentation. The homepage
should make this path easy to discover without expanding into an agent manual.
Users who need installation help can already copy the setup page into their agent.

## Settled experience and content

The site offers a simple button that copies the approved prompt below. Copy the
orientation text itself, not just an instruction to fetch another prompt. Keep
the same content accessible from the GitHub README with a usable copyable
representation; GitHub does not execute custom site JavaScript. Choose the
smallest rendering mechanism that serves both surfaces without maintaining two
independent prompt texts.

Assume the agent has web access for v0.1.0, as Dynamical's onboarding does. Do not
build a browsing capability interview, offline bundle, or fallback workflow.
Revisit this if users report problems. Links must nevertheless resolve to usable,
public documentation. Do not assume that appending `.md` works on this site.

Use progressive disclosure: explain the library's purpose, show one API example,
preserve essential interpretation rules, and direct the agent to relevant
references when needed. Do not require it to read all documentation. There is no
packaged skill, full duplicated API manual, generic agent coaching, or compulsory
live sample download. The example teaches the API shape rather than commanding
execution. Check the existing project installation with an import and installed
version; report actual setup failure without an automatic upgrade. Do not add an
installation ritual to the agent prompt.

Onboarding must not start an interview or ask what the user wants to build.
Continue an existing task; if none exists, give a brief readiness acknowledgement.
The setup check must not turn into an approval ceremony.

The user approved this exact draft. Preserve its substance and wording unless a
necessary correction is brought back for human review:

```text
Use RivRetrieve to find and retrieve river discharge, stage, and water
temperature observations from national and regional agencies.

Check that rivretrieve imports in the project's Python environment and
note its version. If setup fails, report the error. Do not upgrade it
automatically.

Typical workflow:
import rivretrieve as rr

gauges = rr.find(
    provider="usgs_nwis", quantity="discharge",
    frequency="daily", statistic="mean",
)
selected = rr.pick(gauges, station=["07374000"])
result = rr.fetch(selected, start="2023-01-01", end="2023-01-01")

# Inspect observations, retrieval issues, and source-series outcomes.
result.data
result.issues
rr.series(result)

This illustrates the API; only retrieve data needed for the user's task.
Catalogue searches are offline; fetching contacts providers.

RivRetrieve harmonises units and structure. It does not perform quality
control, gap filling, or aggregation. Read timestamps with their time-zone
information. Returned rows do not imply complete coverage or no failures.

Consult documentation as needed:
- Usage, selections, results, credentials:
  https://rivretrieve.github.io/usage/
- Exact API signatures and returned types:
  https://rivretrieve.github.io/reference/
- Provider-specific access and interpretation:
  follow the relevant provider page from https://rivretrieve.github.io/

Continue the user's task without onboarding questions. If no task was
given, briefly confirm readiness.
```

## Repository facts and implementation boundaries

- `docs/hooks.py:on_pre_build` reads root `README.md`, adjusts links and writes
  `docs/index.md`. `mkdocs.yml` uses that page as Home. Edit the README source,
  not the generated homepage as an independent document.
- Material for MkDocs supplies code-block copy buttons through `content.code.copy`.
- `docs/javascripts/extra.js` separately implements the whole-page “Copy page text
  for LLM” button. It copies embedded raw Markdown when present, otherwise article
  text, and handles ordinary loads and MkDocs instant navigation. Review its
  template integration and actual copied content before extending it. Keep this
  existing feature usable for people giving setup instructions to their agents.
  Limit changes to what this onboarding feature or discovered copy defects need.
- `.github/workflows/deploy-docs.yml` builds this repository with
  `uv run mkdocs build --strict` and publishes `site/` to the external
  `RivRetrieve/RivRetrieve.github.io` repository. That repository contains deployment
  output, not documentation authoring sources. Use the existing pipeline.
- The existing usage guide, public API reference and provider pages are the
  detailed references. Keep URLs and example calls aligned with them.
- Follow repository documentation guidance for human-facing prose. Keep the agent
  prompt concise and factual, without making unsupported source interpretations.

No library API, provider behavior, data product, dependency policy, release version,
or private evidence collection changes are part of this work. No new skill
publication or separate agent distribution system is needed. A standalone hosted
prompt endpoint is not required for the agreed full-text copy experience.

## Human review gates

These gates apply to implementation. Publishing this vision does not approve the
future README wording or rendered interface, and does not authorize implementation.

1. **README review:** present the proposed README diff and onboarding placement
   for the user to review personally. Pause for approval before treating that
   content as accepted. Keep the change small and preserve existing installation
   and quick-start usefulness.
2. **Browsable local preview:** build and serve the documentation locally, give
   the user its working URL, and leave the preview available for their inspection.
   The user must be able to browse the homepage and linked documentation, not only
   see screenshots or a build log. Ask for review of layout and wording, and pause.
3. **Copy and interaction acceptance:** let the user try the prompt button and
   whole-page copying in the local preview. Demonstrate that the prompt copied is
   the approved text and that navigation does not break either feature. Obtain
   explicit acceptance before presenting the implementation as ready to land.

The preview and interaction reviews can occur in one review session, but neither
may be replaced by automated tests. Revisions affecting accepted content or
behavior must be shown again. Technical preparation and ordinary affected checks
need no step-by-step approval. Do not merge the implementation or deploy it before
these human gates are satisfied and the applicable landing workflow authorizes it.

## Evidence of completion

- README changes are narrow and human-approved. The generated homepage places the
  copyable agent prompt after installation and remains readable on GitHub and the site.
- The copied prompt matches the approved content; links reach the intended public
  pages; API calls and installation check agree with the public package interface.
- The prompt button works on first load and after MkDocs instant navigation.
  Whole-page copying remains useful and does not silently omit installation text
  or include unintended interface content. Check the rendered template and clipboard
  result rather than infer success from JavaScript source alone.
- The user has browsed the running local site and accepted the visible result and
  copy interactions. Record that approval separately from automated verification.
- Run affected source-independent documentation checks and a strict MkDocs build
  through `uv`. Add focused coverage at the simplest sufficient level for changed
  copying/rendering behavior; do not create a broad new testing framework.
- Verify the standard build includes all needed prompt content and assets. No
  provider retrieval or private archive access is needed for this documentation-only
  outcome. Do not run the illustrative live fetch merely to validate onboarding.

Keep the work proportional: a short prompt, a small README addition, and the minimum
site integration needed to copy it reliably.
