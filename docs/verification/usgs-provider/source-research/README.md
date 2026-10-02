# USGS source documents

Original documents, request lists, receipts and acquisition context are retained in
the private [source archive](https://github.com/RivRetrieve/verification-evidence).

For a new acquisition, pass an explicit request-list JSON file to `acquire.py`
with `--requests`, and a new external directory with `--output`. The request list
maps document names to URLs. The tool saves unchanged response bytes in gzip
containers and records response hashes and acquisition facts. Keep the original
acquisition intact. See [maintenance instructions](../../../../maintenance/catalogue/usgs_nwis/README.md).
