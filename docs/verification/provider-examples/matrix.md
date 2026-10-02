# Provider verification checks

Retained recordings, catalogue rebuilds and live examples check different
properties. Keep their results separate:

| Check | What it establishes |
| --- | --- |
| Recording replay | Parser and retrieval behavior against exact retained responses. |
| Offline catalogue rebuild | Agreement between verified native inputs, reviewed declarations and packaged products. |
| Documentation examples | Whether the published examples execute and agree with their displayed output at the time of the run. |
| Bulk compilation | Whether selected publisher artifacts compile and pass store certification. |

A successful Python process can still return failed source issues or no
observations. Inspect those results before accepting a live example. A catalogue
listing does not establish observation availability.

The historical all-provider execution matrix is preserved in the private
[source archive](../../maintenance/evidence.md). It records results at its named
revisions and does not establish current service availability. Retrieve its exact
collection outside source checkouts when reviewing that verification record.

See [example verification](README.md) for current execution instructions and
[implementation checks](implementation-tests.md) for the separate historical
regression record.
