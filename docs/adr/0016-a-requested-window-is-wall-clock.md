# A requested window is wall-clock, and a zone-carrying endpoint is refused

A window a caller asks for is closed at both ends and expressed as wall-clock time in the
calendar each station's own source publishes. Asking two gauges for July asks each for
its own July, not for one shared stretch of world time. A bare date denotes a whole day,
so `end="2020-07-31"` reaches the last instant of the 31st while `end="2020-07-31 00:00"`
stops at midnight. An endpoint carrying a time zone — `datetime.now(UTC)`, the idiom
everyone reaches for — raises rather than being reinterpreted.

The alternative was real and initially attractive: accept a zone-carrying endpoint as a
genuinely different question, an absolute interval on the world's timeline, which is
useful for comparing two basins during one storm. It dies on ADR 0005 and ADR 0007. An
absolute interval can only be placed against a [[station timezone]], five of the thirteen
sources publish none, and this project does not derive one from coordinates. That mode
would therefore work on some countries and silently return nothing on others — a
capability that evaporates by geography is worse than one never offered.

Wall clock also removes a hole rather than adding a rule. Under UTC comparison, a station
whose zone is unknown cannot be clipped at all, and `convert` retained its rows unclipped
behind a warning. Wall clock compares to wall clock without needing a zone on either
side, so those rows are now clipped correctly and the warning is deleted.

The accepted cost is that `datetime.now(UTC) - timedelta(days=7)` raises on someone's
first day with the library. The error names the rule and the one-line fix, which teaches
the promise better than documentation would, and a caller wanting an absolute interval
converts the returned `time` and `time_zone` afterwards — exactly the operation ADR 0006
already defines. This is settled before v0.1.0 reaches PyPI, where it is free; after
publication it would not be.
