# The engine drives the pipeline

Today a provider module exposes `observations(request) -> ObservationResult`, so the
provider runs all four stages and the engine only dispatches to it. Since convert and
assemble belong to the engine, the engine becomes the caller instead: a provider package
exposes `fetch`, `parse` and a declaration, exposes no `observations`, and the engine
invokes the provider's code at the two stages the provider contributes while performing
the other two itself.

The reason is that ordering has to be structural rather than remembered. The review's
guarantee in §5.3 is that a provider cannot clip before aligning "because a provider never
clips at all", and that is only true if the provider never holds the sequence. Under the
rejected alternative — the provider drives and calls engine helpers for convert and
assemble — every helper is available at every point, correct ordering becomes a convention
thirteen authors must each observe, and the defect the Program exists to remove is one
misplaced call away from returning. The engine is then the single place the order of steps
is written down, which is also what makes the order inspectable.

The accepted cost is that a provider can no longer do anything the four stages do not
anticipate. An exotic source must express itself as fetch and parse rather than as its own
pipeline. The evidence across the thirteen is that this is not restrictive: what varies is
how bytes are obtained and how a format is decoded, which is exactly what the two provider
stages are.
