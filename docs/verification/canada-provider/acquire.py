import datetime
import logging
import os
import platform
import time
import rivretrieve as rr
logging.basicConfig(level=logging.INFO)
print("started", datetime.datetime.now(datetime.UTC).isoformat(), flush=True)
print("python", platform.python_version(), "rivretrieve", rr.__version__, flush=True)
print("cache", os.environ["RIVRETRIEVE_CACHE_DIR"], flush=True)
start = time.monotonic()
store = rr.download("ca_eccc")
print("elapsed_seconds", time.monotonic() - start, flush=True)
print("store", store, flush=True)
print("status", rr.cache_status("ca_eccc"), flush=True)
