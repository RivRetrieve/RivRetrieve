"""HYDAT SQLite client for ca_eccc observations.

On first use, the latest HYDAT SQLite database (~1 GB zip) is downloaded from
the ECCC collaboration server and cached in the user's cache directory.
Subsequent calls reuse the cached file.

Authentication: none — public Government of Canada open data.
"""

from __future__ import annotations

import io
import sqlite3
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from rivretrieve._internal.primitives import ProviderId

try:
    from platformdirs import user_cache_dir as _user_cache_dir
except ImportError:  # pragma: no cover
    import tempfile

    def _user_cache_dir(appname: str) -> str:  # type: ignore[misc]
        return tempfile.gettempdir()


HYDAT_URL_TEMPLATE = "https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/Hydat_sqlite3_{date}.zip"
HYDAT_SQLITE_NAMES = ("Hydat.sqlite3", "hydat.sqlite3", "HYDAT.sqlite3")
_STALE_DAYS = 90
_MAX_PROBE_DAYS = 365


@dataclass(frozen=True)
class CacheStatus:
    """Status of the local HYDAT SQLite cache.

    Attributes
    ----------
    exists:
        Whether a cached SQLite file was found.
    path:
        Absolute path to the SQLite file, or None if not found.
    age_days:
        Age of the file in days (based on mtime), or None if not found.
    size_mb:
        File size in megabytes, or None if not found.
    stale:
        True when the file is older than the staleness threshold (90 days).
    format:
        Storage format identifier — always ``"sqlite"`` for HYDAT.
    """

    exists: bool
    path: Path | None
    age_days: int | None
    size_mb: float | None
    stale: bool
    format: str = "sqlite"


# ---------------------------------------------------------------------------
# Cache-dir helpers
# ---------------------------------------------------------------------------


def default_cache_dir() -> Path:
    return Path(_user_cache_dir("rivretrieve")) / "ca_eccc"


def _find_sqlite(cache_dir: Path) -> Path | None:
    for name in HYDAT_SQLITE_NAMES:
        p = cache_dir / name
        if p.exists():
            return p
    # Also accept any date-stamped name produced by extraction.
    for p in cache_dir.glob("Hydat_sqlite3_*.sqlite3"):
        return p
    return None


# ---------------------------------------------------------------------------
# URL probe (R-style backward HEAD scan — no HTML scraping)
# ---------------------------------------------------------------------------


def _probe_latest_url(
    transport: _HeadTransport | None = None,
    max_back_days: int = _MAX_PROBE_DAYS,
) -> str | None:
    t = transport or _default_head_transport
    today = date.today()
    for days_back in range(max_back_days + 1):
        d = today - timedelta(days=days_back)
        url = HYDAT_URL_TEMPLATE.format(date=d.strftime("%Y%m%d"))
        try:
            status = t(url)
            if 200 <= status < 300:
                return url
        except (requests.RequestException, OSError):
            continue
    return None


def _default_head_transport(url: str) -> int:
    resp = requests.head(url, timeout=15, allow_redirects=True)
    return resp.status_code


_HeadTransport = Any  # Callable[[str], int]


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------


@dataclass
class HydatClient:
    """Client for the local HYDAT SQLite database.

    Parameters
    ----------
    cache_dir:
        Directory where the SQLite file is stored.  Defaults to
        ``platformdirs.user_cache_dir("rivretrieve") / "ca_eccc"``.
    db_path_override:
        Supply an explicit SQLite path (used in tests to skip download).
    head_transport:
        Callable(url) -> HTTP status code; injectable for testing the URL
        probe path without real network.
    """

    cache_dir: Path = field(default_factory=default_cache_dir)
    db_path_override: Path | None = field(default=None)
    head_transport: _HeadTransport | None = field(default=None)

    # Session-level caches.
    _table_cache: dict[str, list[dict[str, object]]] = field(default_factory=dict, init=False, repr=False)
    _symbol_cache: dict[str, dict[str, str]] = field(default_factory=dict, init=False, repr=False)

    def sqlite_path(self) -> Path | None:
        """Return path to existing SQLite file, or None."""
        if self.db_path_override is not None:
            return self.db_path_override
        return _find_sqlite(self.cache_dir)

    def ensure_database(self) -> tuple[Path | None, list[_Issue]]:
        """Ensure HYDAT SQLite is available.

        Returns (path, issues).  If download is needed, issues contains an
        ``info``-severity ``hydat_download_started`` entry.  On failure, path
        is None and issues contains a ``hydat_download_failed`` error.
        """
        from rivretrieve._internal.issues import Issue
        from rivretrieve._internal.primitives import ProviderId

        pid = ProviderId("ca_eccc")
        issues: list[Issue] = []

        if self.db_path_override is not None:
            return self.db_path_override, issues

        existing = _find_sqlite(self.cache_dir)
        if existing is not None:
            age_days = (datetime.now(UTC) - datetime.fromtimestamp(existing.stat().st_mtime, UTC)).days
            if age_days > _STALE_DAYS:
                issues.append(
                    Issue(
                        severity="info",
                        code="hydat_stale",
                        message=(
                            f"Cached HYDAT database is {age_days} days old "
                            f"(>{_STALE_DAYS} days). Consider refreshing by deleting "
                            f"{existing} and re-running observations."
                        ),
                        details={"path": str(existing), "age_days": age_days},
                        provider_id=pid,
                    )
                )
            return existing, issues

        # Need to download.
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        issues.append(
            Issue(
                severity="info",
                code="hydat_download_started",
                message=(
                    "HYDAT SQLite database not found in cache. "
                    "Downloading from ECCC (~1 GB zip, may take several minutes). "
                    f"Cache directory: {self.cache_dir}"
                ),
                details={"cache_dir": str(self.cache_dir)},
                provider_id=pid,
            )
        )

        url = _probe_latest_url(transport=self.head_transport)
        if url is None:
            issues.append(
                Issue(
                    severity="error",
                    code="hydat_download_failed",
                    message="Could not find a valid HYDAT download URL after probing the last year.",
                    details={"template": HYDAT_URL_TEMPLATE},
                    provider_id=pid,
                )
            )
            return None, issues

        sqlite_path = self._download_and_extract(url, issues, pid)
        return sqlite_path, issues

    def _download_and_extract(
        self,
        url: str,
        issues: list[_Issue],
        pid: ProviderId,
    ) -> Path | None:
        from rivretrieve._internal.issues import Issue

        try:
            resp = requests.get(url, timeout=600, stream=True)
            resp.raise_for_status()
            raw = resp.content
        except (requests.RequestException, OSError) as exc:
            issues.append(
                Issue(
                    severity="error",
                    code="hydat_download_failed",
                    message=f"HYDAT download failed: {exc}",
                    details={"url": url, "exception_type": type(exc).__name__},
                    provider_id=pid,
                )
            )
            return None

        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                for name in zf.namelist():
                    if name.lower().endswith(".sqlite3"):
                        dest = self.cache_dir / Path(name).name
                        dest.write_bytes(zf.read(name))
                        return dest
        except (zipfile.BadZipFile, OSError) as exc:
            issues.append(
                Issue(
                    severity="error",
                    code="hydat_download_failed",
                    message=f"HYDAT zip extraction failed: {exc}",
                    details={"url": url, "exception_type": type(exc).__name__},
                    provider_id=pid,
                )
            )
            return None

        issues.append(
            Issue(
                severity="error",
                code="hydat_download_failed",
                message="HYDAT zip contained no .sqlite3 file.",
                details={"url": url},
                provider_id=pid,
            )
        )
        return None

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def cache_status(self) -> CacheStatus:
        """Return the status of the local HYDAT SQLite cache.

        Does not trigger a download. Safe to call at any time.
        """
        if self.db_path_override is not None:
            p = self.db_path_override
            exists = p.exists()
            if exists:
                stat = p.stat()
                age_days = (datetime.now(UTC) - datetime.fromtimestamp(stat.st_mtime, UTC)).days
                size_mb = round(stat.st_size / 1_048_576, 1)
                return CacheStatus(
                    exists=True, path=p, age_days=age_days, size_mb=size_mb, stale=age_days > _STALE_DAYS
                )
            return CacheStatus(exists=False, path=p, age_days=None, size_mb=None, stale=False)

        p = _find_sqlite(self.cache_dir)
        if p is None:
            return CacheStatus(exists=False, path=None, age_days=None, size_mb=None, stale=False)
        stat = p.stat()
        age_days = (datetime.now(UTC) - datetime.fromtimestamp(stat.st_mtime, UTC)).days
        size_mb = round(stat.st_size / 1_048_576, 1)
        return CacheStatus(exists=True, path=p, age_days=age_days, size_mb=size_mb, stale=age_days > _STALE_DAYS)

    def refresh_cache(self) -> list[_Issue]:
        """Force re-download of the HYDAT SQLite database.

        Deletes any existing cached file and downloads the latest release.
        Returns a list of structured issues (info on success, error on failure).
        Blocks until complete (~1 GB download, may take several minutes).
        """
        from rivretrieve._internal.issues import Issue

        pid = ProviderId("ca_eccc")
        issues: list[Issue] = []

        if self.db_path_override is not None:
            issues.append(
                Issue(
                    severity="info",
                    code="hydat_refresh_skipped",
                    message="refresh_cache() has no effect when db_path_override is set.",
                    details={"db_path_override": str(self.db_path_override)},
                    provider_id=pid,
                )
            )
            return issues

        # Delete existing file if present.
        existing = _find_sqlite(self.cache_dir)
        if existing is not None:
            existing.unlink(missing_ok=True)
            self._symbol_cache.clear()
            self._table_cache.clear()

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        issues.append(
            Issue(
                severity="info",
                code="hydat_download_started",
                message=(
                    "Downloading latest HYDAT SQLite from ECCC (~1 GB, may take several minutes). "
                    f"Cache directory: {self.cache_dir}"
                ),
                details={"cache_dir": str(self.cache_dir)},
                provider_id=pid,
            )
        )

        url = _probe_latest_url(transport=self.head_transport)
        if url is None:
            issues.append(
                Issue(
                    severity="error",
                    code="hydat_download_failed",
                    message="Could not find a valid HYDAT download URL after probing the last year.",
                    details={"template": HYDAT_URL_TEMPLATE},
                    provider_id=pid,
                )
            )
            return issues

        result = self._download_and_extract(url, issues, pid)
        if result is not None:
            issues.append(
                Issue(
                    severity="info",
                    code="hydat_refresh_complete",
                    message=f"HYDAT cache refreshed successfully: {result}",
                    details={"path": str(result)},
                    provider_id=pid,
                )
            )
        return issues

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def query_daily_table(
        self,
        sqlite_path: Path,
        table_name: str,
        station_id: str,
        start_year: int,
        end_year: int,
    ) -> list[dict[str, object]]:
        """Query DLY_FLOWS or DLY_LEVELS for one station and year range.

        Returns raw row dicts (column name → value).
        Results are NOT cached — each call hits the SQLite file directly,
        which is fast because STATION_NUMBER is indexed.
        """
        conn = sqlite3.connect(str(sqlite_path))
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                f"SELECT * FROM {table_name} WHERE STATION_NUMBER = ? AND YEAR BETWEEN ? AND ?",  # noqa: S608
                (station_id, start_year, end_year),
            )
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def query_data_symbols(self, sqlite_path: Path) -> dict[str, str]:
        """Return {SYMBOL_ID: SYMBOL_EN} from DATA_SYMBOLS table.

        Cached for the session (small lookup table).
        """
        cache_key = str(sqlite_path)
        if cache_key in self._symbol_cache:
            return self._symbol_cache[cache_key]

        conn = sqlite3.connect(str(sqlite_path))
        conn.row_factory = sqlite3.Row
        try:
            try:
                cur = conn.execute("SELECT SYMBOL_ID, SYMBOL_EN FROM DATA_SYMBOLS")
                mapping: dict[str, str] = {str(r["SYMBOL_ID"]): str(r["SYMBOL_EN"]) for r in cur.fetchall()}
            except sqlite3.OperationalError:
                mapping = {}
        finally:
            conn.close()

        self._symbol_cache[cache_key] = mapping
        return mapping


# Type alias so issue_codes module does not need to be imported here.
_Issue = Any
