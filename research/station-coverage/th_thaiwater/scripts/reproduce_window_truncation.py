"""Retired historical public-window acquisition entry point.

The historical summary did not record the padded source request. Its unrestricted
provider/product selection could silently expand to the full station inventory after
catalogue integration. Retained exact acquisitions now govern the explanation; this
entry point must not issue new source requests or overwrite that historical account.
"""


def main() -> None:
    raise SystemExit(
        "This historical acquisition script is retired. Use the retained governing evidence "
        "and the explicit-root offline verifier in HANDOFF.md. New source recordings require "
        "an explicitly bounded reviewed capture plan."
    )


if __name__ == "__main__":
    main()
