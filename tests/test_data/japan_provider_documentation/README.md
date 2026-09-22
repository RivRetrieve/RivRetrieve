# Japan provider documentation recordings

Captured on 2026-09-21 through the public `jp_mlit` provider using native
`RecordingTransport`, after the recording-encoding fix in PR #326.

These are the HTML prerequisite and its publisher-linked DAT response for station
`305071285512040`, daily discharge (KIND 7), annual source window 2020. The guide
requests only 2020-01-10 through 2020-01-11. The source file also reports 17 missing
slots outside that interval.

`tests/test_jp_mlit_documentation.py` executes the page's exact snippets and compares
the displayed outputs. It replays this pair for the bypass and initial cache calls,
then checks that the repeated explicit-series request makes no further source calls.
Replay tests establish saved-source behavior, not current reachability or permission.
