# Unknown is a first-class state

Everywhere RivRetrieve reports something a source might not tell us, "we do not know"
is a representable value rather than a gap to be filled. It is distinct from zero, from
empty, and from a default, and it is never resolved by assumption or by computing a
value the source never published.

This came out of three separate deadlocks that all had the same shape. We cannot always
establish a provider's timezone, so UTC became an offer rather than a guarantee. We
cannot always establish which 24 hours a daily value covers, so the day definition is
declared rather than defaulted to midnight. We cannot always establish a stage datum,
and it may vary over time. In each case the alternatives were to guess a sensible
default or to compute the value ourselves, and both produce output that is silently
wrong while looking entirely plausible, which is the failure mode this library exists
to avoid.

Making unknown legitimate everywhere has a practical consequence: the design does not
have to wait on a survey of what the thirteen sources document. That survey changes
what gets populated, not what gets built.
