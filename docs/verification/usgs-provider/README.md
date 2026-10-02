# USGS documentation verification

The provider-page checks replay retained publisher responses and compare the exact
examples and displayed outputs. A separate offline check tests catalogue prevalence
and the example station selection.

The private [source archive](https://github.com/RivRetrieve/verification-evidence)
retains the original source documents, acquisition records, example executions,
receipts and historical verification results. See the [USGS maintenance instructions](../../../maintenance/catalogue/usgs_nwis/README.md)
for external input selection and current commands.

`execute_examples.py --page PAGE --output EXTERNAL_DIRECTORY` captures a new live
execution. `source-research/acquire.py --requests REQUESTS_JSON --output EXTERNAL_DIRECTORY`
acquires the selected source documents. Keep outputs outside source checkouts and
review them before sharing. Live acquisition does not replace retained replay inputs.
