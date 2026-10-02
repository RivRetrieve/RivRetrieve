"""Register source-free test selection before pytest parses command options."""

pytest_plugins = ("tests._distribution", "tests._evidence_selection")
