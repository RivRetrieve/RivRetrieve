# Return native time by default, offer UTC as best-effort

RivRetrieve returns timestamps as the provider published them, rather than converting
everything to UTC. Guaranteeing UTC would require us to know the correct source zone
for every provider, and we cannot: some sources do not document it, and for
multi-timezone countries the zone a provider stamps is not necessarily the zone of the
gauge. Converting on an assumed zone produces timestamps that are silently wrong by a
fixed offset and look entirely plausible, which is a worse failure than not converting
at all. UTC is therefore offered where the source zone is documented, and withheld
where it is not, putting it in the same tier of promise as our best-effort catalogue
columns.

## Consequence: the requested window is still aligned and clipped internally

The output representation and the window arithmetic are separate decisions. A user's
`start` and `end` are still resolved against a single aligned representation, and
clipping is still the last step of the convert stage, performed after alignment and in
one shared place. Returning native time does not push that work back into the
providers.

This matters because the alternative already shipped as a bug twice. Comparing a user's
window against a provider's timestamps without first putting both on the same clock
drops rows at one edge of the window and admits rows outside it at the other, with no
error, no warning, and a plausible row count. Fetch therefore over-fetches a padded day
on each side so no boundary row is missing from the response before the precise clip
trims the excess.
