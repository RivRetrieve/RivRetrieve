# A retired legacy pipeline is archived, not deleted

Eleven of the thirteen providers became catalogue-only before they were ported: their
pre-engine observation pipelines stopped being reachable, but the ports that replace them
have not been written. Those pipelines are kept, readable, under
`reference/legacy_observations/<provider>/`, each with the tests and payload fixtures it
was written against and a README recording the ref they came from and every original path.

The reason is that porting a provider begins by reading how its source actually behaves.
The endpoint a provider calls, the shape of the request it builds, the headers and token
it sends, the fields it picks out of the response — none of that is derivable from the
engine's contract, and only some of it is in the provider port notes. `ch_foen` is the
worked example: its Influx endpoint appears in the retired `observation_client.py` and
nowhere in `docs/provider_ports/ch_foen.md`, which cites an external repository rather
than this one.

Deletion was the original plan and it is the rejected alternative. It is not wrong about
the code — a retired pipeline is superseded, and git preserves it exactly. It is wrong
about how the knowledge is reached. After deletion, an agent or contributor opening
`providers/ch_foen/` finds only catalogue files and no signal that an implementation ever
existed; recovering it means knowing to run `git show` against a ref nobody wrote down.
The knowledge stays recoverable and stops being discoverable, and the two are not the same
property.

The accepted cost is real: roughly 141 files of code that nothing imports, sitting in the
tree and looking exactly like cruft. That is paid for by excluding the tree from Ruff, ty,
pytest collection and both distributions, so it cannot break a gate or reach a user, and
by deleting each provider's subtree as that provider is ported — the archive shrinks to
nothing as the work it exists to serve completes.

The exclusion is itself asserted by a test rather than merely configured, because an
exclusion that silently stops applying would put unmaintained code back into the enforced
tree.
