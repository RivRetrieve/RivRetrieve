# Japan documentation replay inputs

The private source archive retains the original documentation verification report
and the paired recordings used by `tests/test_jp_mlit_documentation.py`.
Follow [verification evidence](../../../docs/maintenance/evidence.md) to retrieve
exact inputs. Set `RIVRETRIEVE_TEST_EVIDENCE_ROOT` to the external directory with
repository-relative paths, including the two recordings under
`tests/test_data/japan_provider_documentation/`.

```sh
uv run pytest tests/test_jp_mlit_documentation.py -q --tb=no -p no:cacheprovider
```

Keep test temporary files and full output outside source checkouts. Missing
recordings fail the check; the test does not download replacement responses.

The replay checks the provider page's example against the retained response pair.
Its absent-slot expectation protects the distinction between an unpopulated
source slot and a published numeric value. RivRetrieve must not fill those slots
with invented observations. Replay verifies behavior against the selected
recordings, not current service availability.
