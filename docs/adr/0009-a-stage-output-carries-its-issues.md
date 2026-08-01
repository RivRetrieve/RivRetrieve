# A stage output carries its issues

Every provider-facing stage returns its value together with the issues found producing it,
in one envelope the engine accumulates across the four stages:

```text
WithIssues<A> ≔ { value : A, issues : Issue[] }
```

An issue is a fact about the data; an exception is a violation of the contract. A station
returning 404, a window holding no observations, a zone that could not be established —
all issues, all non-fatal, all returned. A parse handing back a frame with the wrong
columns is an exception, because the seam is broken and there is no result worth
assembling. Severity is already `info | warning | error`, so an issue also records what
merely deserves saying: a unit was converted, fewer rows arrived than the window asked for.

The point of the shape is that partial success survives. Four stations return data and the
fifth 404s: the value holds four stations' rows and the issues explain the fifth, and
neither half is discarded. When every station fails the result is an empty frame with the
issues that explain it — never an exception, because "this station published nothing for
this window" is an answer about the world rather than a malfunction, and it is frequently
the true one.

Two alternatives were rejected. Railway-oriented `Either` short-circuits: a failure diverts
off the happy path and skips the remaining stages, which discards the rows that did
succeed and changes the type based on how well things went, pushing that branch onto every
caller. Bare exceptions with no envelope make one absent station discard four good ones,
and leave a provider author choosing privately between logging, warning, raising and
swallowing — which is what the thirteen do inconsistently today. This shape is a Writer
rather than an Either: both tracks stay live and the logs concatenate.
