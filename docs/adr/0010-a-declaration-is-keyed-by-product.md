# A declaration is keyed by product, not by stage

A provider's `config.py` groups everything true about one product into one record, rather
than spreading those facts across parallel mappings keyed by the same product ids:

```text
ProviderConfig ≔ { zone, products : Map<ProductId, ProductConfig>, cache : CacheConfig | none }
ProductConfig  ≔ { coordinates : SourceCoordinates, unit : Unit, semantics : Instant | Daily }
```

This overturns the arrangement in `docs/design/provider-redesign-review.md` §3.5, which
groups the declaration by stage — a `ConvertConfig` holding units and time semantics,
alongside a separate mapping of source coordinates. The reason is the one that document
already gives one level down, when it puts the day definition inside `time_semantics`
rather than in a parallel dict, "so there is no second dict keyed by the same product ids
that could fall out of step with the first." That argument does not stop at time
semantics: coordinates, unit and semantics are all per-product, and a stage-keyed layout
splits one product's three facts across three places that nothing requires to agree.

Concretely, under the rejected arrangement a contributor adds a product to `coordinates`
and to `units` and forgets `semantics`; fetch works, parse works, and convert reaches a
product it has no semantics for, on the one provider-product nobody tested. A
`ProductConfig` cannot be constructed without all three fields, so a product is either
fully declared or absent, and half-declared becomes unrepresentable rather than merely
discouraged.

`zone` stays at the top level because it is a fact about the source rather than about any
one product, and `cache` stays optional because only `ca_eccc` and `pl_imgw` have one.
