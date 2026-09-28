import json
import os
from pathlib import Path


def pytest_runtest_logreport(report):
    with Path(os.environ["RR_TIMING_LOG"]).open("a") as stream:
        stream.write(
            json.dumps(
                {"nodeid": report.nodeid, "when": report.when, "duration": report.duration, "outcome": report.outcome}
            )
            + "\n"
        )
