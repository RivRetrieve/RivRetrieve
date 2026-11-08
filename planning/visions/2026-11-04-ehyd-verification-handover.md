# eHYD verification handover

Finish Freddy’s outstanding controlled verification handover for Austria’s eHYD
provider. The implementation and user documentation are already on `port/at-ehyd`.
The remaining outcome is accepted verification evidence, not a provider redesign.

This vision completes [#615](https://github.com/RivRetrieve/RivRetrieve/issues/615)
and [#617](https://github.com/RivRetrieve/RivRetrieve/issues/617) once their acceptance
conditions below are met. [#614](https://github.com/RivRetrieve/RivRetrieve/issues/614)
is completed context; do not reopen it or repeat its accepted work without cause.
The governing handover is Freddy’s latest comment on #617, superseding the older
revision pairs in the individual issues. Provider coordination remains in
[#525](https://github.com/RivRetrieve/RivRetrieve/issues/525).

## Existing evidence and exact revisions

Use the handover’s full revision pair:

- RivRetrieve: `39fdef2687db89036962ba0fafefdeeecace36cb`.
- `RivRetrieve/verification-evidence`: `7d15e2bc380bed380a03f84c1239a2ec4fb635db`.

Review those exact executable revisions before using private evidence or
credentials. Follow `docs/maintenance/evidence.md` and the private archive README
at the selected revision. Do not substitute mutable branch tips.

[Private archive PR #59](https://github.com/RivRetrieve/verification-evidence/pull/59)
already retained #614’s sanitized catalogue and origin/rebuild receipts under
`acceptance/2026-11-03-at-ehyd-verification/`. The runs passed 7 public + 1 private
and 3 public + 1 private checks respectively, without skips. Separate fresh outputs
avoided the tests’ shared product-directory collision without code changes.
Reuse those receipts for #617’s catalogue/series-identity coverage. Their later
publication does not change the archive revision used for execution.

## Remaining work

Run the private archive coordinator on a standard `uv` setup, using clean reviewed
checkouts and a fresh restricted output directory outside source checkouts:

```sh
uv run --isolated --locked python -B verify.py \
  --reviewed-archive-sha 7d15e2bc380bed380a03f84c1239a2ec4fb635db \
  --code-checkout /path/to/reviewed-rivretrieve \
  --reviewed-code-sha 39fdef2687db89036962ba0fafefdeeecace36cb \
  --output /path/to/new-restricted-retrieval-output \
  --tests -- \
  tests/test_at_ehyd_retrieval_recorded.py \
  tests/test_at_ehyd_recorded_public.py \
  tests/test_at_ehyd_documentation.py \
  tests/test_public_representative_source_series.py \
  -k at_ehyd
```

This selects retrieval recordings, public replay, documentation and shared
source-series checks, together with their required private source certification.
Freddy ran underlying checks directly because a system-level `uv` index override
blocked isolated environment creation. Those direct runs do not replace this
outstanding controlled receipt.

Inspect the coordinator result and its requested test selection. Missing inputs,
failed checks or skipped requested checks block acceptance. Investigate failures;
do not weaken checks, replace originals with derived data, or treat setup failure
as a provider defect. Keep implementation unchanged unless a genuine defect is
established. If a correction changes an executable revision, review the correction
and rerun affected acceptance against explicit new revisions, retaining the reason
and earlier evidence. Do not claim that the original pinned run passed.

Review and retain only the sanitized `public-summary.json` receipt in the private
archive’s existing acceptance directory, with a concise update linking the reused
#614 receipts and the new retrieval result. Preserve existing records. Keep raw
source bodies, credentials, detailed logs, caches and restricted receipts out of
public GitHub records and distribution packages.

## Completion and boundaries

- Verify the sanitized retrieval receipt and acceptance update are merged into
  the private archive and identify the exact revisions and successful checks.
- For #615, link the accepted retrieval evidence and close the issue only after
  the controlled run succeeds without skipped requested checks.
- For #617, reconcile that result with #614’s accepted receipts and the existing
  Step 6 verification record. Resolve or report any remaining mandatory gaps
  before closing it. Recorded replay is not a new live-service observation.
- Confirm all seven prerequisite efforts (#612–#618) are closed before reporting
  [#619](https://github.com/RivRetrieve/RivRetrieve/issues/619) as unblocked.

This work does not perform or close #619. Thiago owns the final review, and merging
`port/at-ehyd` into `main` requires his explicit approval. Do not add new provider
scope, redesign retrieval, repeat the external LamaH comparison, or infer broader
source certification than the selected checks establish.

Publication of this vision leaves #615 and #617 open. Its implementation delivers
the verification receipts and issue completion described above, not a port merge.
