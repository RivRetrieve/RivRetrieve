"""IMGW all-daily Parquet cache acquisition and lifecycle.

On first use, all IMGW daily ZIP files from 1951 to the current year are
downloaded, parsed, and written to a single Parquet file in the user's
cache directory. Subsequent calls read from that file.

Authentication: none — public IMGW open data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import requests

from rivretrieve._internal.primitives import ProviderId

try:
    from platformdirs import user_cache_dir as _user_cache_dir
except ImportError:  # pragma: no cover
    import tempfile

    def _user_cache_dir(appname: str) -> str:  # type: ignore[misc]
        return tempfile.gettempdir()


BASE_URL = "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe"
ANNUAL_URL_TEMPLATE = BASE_URL + "/{year}/codz_{year}.zip"
MONTHLY_URL_TEMPLATE = BASE_URL + "/{year}/codz_{year}_{month:02d}.zip"

# Years from which annual ZIPs are published; earlier years have only monthly ZIPs.
ANNUAL_ZIP_FROM_YEAR = 2023

CACHE_FILENAME = "pl_imgw_daily.parquet"
_STALE_DAYS = 90
_FIRST_YEAR = 1951


@dataclass(frozen=True)
class ImgwCacheStatus:
    """Status of the local IMGW Parquet cache.

    Attributes
    ----------
    exists:
        Whether a cached Parquet file was found.
    path:
        Absolute path to the file, or None if not found.
    age_days:
        Age of the file in days (mtime), or None if not found.
    size_mb:
        File size in megabytes, or None if not found.
    stale:
        True when the file is older than the staleness threshold (90 days).
    format:
        Always ``"parquet"``.
    """

    exists: bool
    path: Path | None
    age_days: int | None
    size_mb: float | None
    stale: bool
    format: str = "parquet"


def default_cache_dir() -> Path:
    return Path(_user_cache_dir("rivretrieve")) / "pl_imgw"


@dataclass
class ImgwCacheClient:
    """Client for the local IMGW all-daily Parquet cache.

    Parameters
    ----------
    cache_dir:
        Directory where the Parquet file is stored.
    cache_path_override:
        Supply an explicit Parquet path (used in tests to skip download).
    """

    cache_dir: Path = field(default_factory=default_cache_dir)
    cache_path_override: Path | None = field(default=None)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def parquet_path(self) -> Path | None:
        """Return path to existing Parquet cache file, or None."""
        if self.cache_path_override is not None:
            return self.cache_path_override
        p = self.cache_dir / CACHE_FILENAME
        return p if p.exists() else None

    def ensure_cache(self) -> tuple[Path | None, list[_Issue]]:
        """Ensure the Parquet cache is available.

        If no cache exists, downloads all IMGW yearly ZIPs from 1951 to the
        current year, parses them, and writes a single Parquet file.

        Returns (path, issues).
        """
        from rivretrieve._internal.issues import Issue

        pid = ProviderId("pl_imgw")
        issues: list[Issue] = []

        if self.cache_path_override is not None:
            return self.cache_path_override, issues

        existing = self.parquet_path()
        if existing is not None:
            age_days = (datetime.now(UTC) - datetime.fromtimestamp(existing.stat().st_mtime, UTC)).days
            if age_days > _STALE_DAYS:
                issues.append(
                    Issue(
                        severity="info",
                        code="imgw_cache_stale",
                        message=(
                            f"Cached IMGW Parquet is {age_days} days old "
                            f"(>{_STALE_DAYS} days). The retained private cache can only be maintained from internal code."
                        ),
                        details={"path": str(existing), "age_days": age_days},
                        provider_id=pid,
                    )
                )
            return existing, issues

        # Need to build cache.
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        issues.append(
            Issue(
                severity="info",
                code="imgw_cache_build_started",
                message=(
                    "IMGW Parquet cache not found. Downloading all yearly ZIP files "
                    f"from {_FIRST_YEAR} to the current year. "
                    f"Cache directory: {self.cache_dir}"
                ),
                details={"cache_dir": str(self.cache_dir)},
                provider_id=pid,
            )
        )

        path, build_issues = self._build_cache(pid)
        issues.extend(build_issues)
        return path, issues

    def cache_status(self) -> ImgwCacheStatus:
        """Return the status of the local IMGW Parquet cache.

        Does not trigger a download. Safe to call at any time.
        """
        if self.cache_path_override is not None:
            p = self.cache_path_override
            exists = p.exists()
            if exists:
                stat = p.stat()
                age_days = (datetime.now(UTC) - datetime.fromtimestamp(stat.st_mtime, UTC)).days
                size_mb = round(stat.st_size / 1_048_576, 1)
                return ImgwCacheStatus(
                    exists=True, path=p, age_days=age_days, size_mb=size_mb, stale=age_days > _STALE_DAYS
                )
            return ImgwCacheStatus(exists=False, path=p, age_days=None, size_mb=None, stale=False)

        p = self.cache_dir / CACHE_FILENAME
        if not p.exists():
            return ImgwCacheStatus(exists=False, path=None, age_days=None, size_mb=None, stale=False)
        stat = p.stat()
        age_days = (datetime.now(UTC) - datetime.fromtimestamp(stat.st_mtime, UTC)).days
        size_mb = round(stat.st_size / 1_048_576, 1)
        return ImgwCacheStatus(exists=True, path=p, age_days=age_days, size_mb=size_mb, stale=age_days > _STALE_DAYS)

    def refresh_cache(self) -> list[_Issue]:
        """Force rebuild of the IMGW Parquet cache.

        Deletes any existing cached file and re-downloads all ZIP files.
        Returns a list of structured issues.
        """
        from rivretrieve._internal.issues import Issue

        pid = ProviderId("pl_imgw")
        issues: list[Issue] = []

        if self.cache_path_override is not None:
            issues.append(
                Issue(
                    severity="info",
                    code="imgw_refresh_skipped",
                    message="refresh_cache() has no effect when cache_path_override is set.",
                    details={"cache_path_override": str(self.cache_path_override)},
                    provider_id=pid,
                )
            )
            return issues

        existing = self.cache_dir / CACHE_FILENAME
        if existing.exists():
            existing.unlink()

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        issues.append(
            Issue(
                severity="info",
                code="imgw_cache_build_started",
                message=(f"Rebuilding IMGW Parquet cache from source. Cache directory: {self.cache_dir}"),
                details={"cache_dir": str(self.cache_dir)},
                provider_id=pid,
            )
        )

        path, build_issues = self._build_cache(pid)
        issues.extend(build_issues)
        if path is not None:
            issues.append(
                Issue(
                    severity="info",
                    code="imgw_cache_refresh_complete",
                    message=f"IMGW cache refreshed: {path}",
                    details={"path": str(path)},
                    provider_id=pid,
                )
            )
        return issues

    # ------------------------------------------------------------------ #
    # Cache build                                                          #
    # ------------------------------------------------------------------ #

    def _build_cache(self, pid: ProviderId) -> tuple[Path | None, list[_Issue]]:
        from rivretrieve._internal.issues import Issue
        from rivretrieve._internal.providers.pl_imgw.parser import parse_imgw_zip

        issues: list[Issue] = []
        s = requests.Session()
        dest = self.cache_dir / CACHE_FILENAME

        current_year = datetime.now(UTC).year
        parts: list[pl.DataFrame] = []
        failed_years: list[int] = []

        for year in range(_FIRST_YEAR, current_year + 1):
            year_parts = self._fetch_year_parts(s, year, parse_imgw_zip, issues)
            if year_parts:
                parts.extend(year_parts)
            else:
                failed_years.append(year)

        if not parts:
            issues.append(
                Issue(
                    severity="error",
                    code="imgw_cache_build_failed",
                    message="No IMGW data could be downloaded; cache not written.",
                    details={"failed_years": len(failed_years)},
                    provider_id=pid,
                )
            )
            return None, issues

        all_data = (
            pl.concat(parts, how="vertical")
            .sort(["station_id", "time"])
            .unique(subset=["station_id", "time"], keep="first")
        )

        # Write Parquet sorted for efficient predicate pushdown.
        all_data.write_parquet(dest, compression="zstd")

        if failed_years:
            issues.append(
                Issue(
                    severity="info",
                    code="imgw_cache_partial",
                    message=(
                        f"Cache built with {len(failed_years)} years that had no data (ZIP not found or HTTP error)."
                    ),
                    details={"failed_year_count": len(failed_years)},
                    provider_id=pid,
                )
            )

        return dest, issues

    def _fetch_year_parts(
        self,
        session: requests.Session,
        year: int,
        parse_imgw_zip: object,
        issues: list[_Issue],
    ) -> list[pl.DataFrame]:

        pid = ProviderId("pl_imgw")

        if year >= ANNUAL_ZIP_FROM_YEAR:
            # Try annual ZIP first.
            url = ANNUAL_URL_TEMPLATE.format(year=year)
            df = self._fetch_zip(session, url, parse_imgw_zip, pid, issues)
            if df is not None:
                return [df]
            # Fall through to monthly if annual not found (shouldn't happen for confirmed years).

        # Monthly ZIPs.
        month_parts: list[pl.DataFrame] = []
        for month in range(1, 13):
            url = MONTHLY_URL_TEMPLATE.format(year=year, month=month)
            df = self._fetch_zip(session, url, parse_imgw_zip, pid, issues, silent_404=True)
            if df is not None:
                month_parts.append(df)
        return month_parts

    def _fetch_zip(
        self,
        session: requests.Session,
        url: str,
        parse_imgw_zip: object,
        pid: ProviderId,
        issues: list[_Issue],
        *,
        silent_404: bool = False,
    ) -> pl.DataFrame | None:
        from rivretrieve._internal.issues import Issue

        try:
            resp = session.get(url, timeout=120)
            resp.raise_for_status()
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                if not silent_404:
                    issues.append(
                        Issue(
                            severity="info",
                            code="imgw_zip_not_found",
                            message=f"IMGW ZIP not found (HTTP 404): {url}",
                            details={"url": url},
                            provider_id=pid,
                        )
                    )
                return None
            issues.append(
                Issue(
                    severity="info",
                    code="imgw_zip_fetch_error",
                    message=f"IMGW ZIP fetch error: {url}",
                    details={"url": url, "exception_type": type(exc).__name__},
                    provider_id=pid,
                )
            )
            return None
        except (requests.RequestException, OSError) as exc:
            issues.append(
                Issue(
                    severity="info",
                    code="imgw_zip_fetch_error",
                    message=f"IMGW ZIP fetch error: {url}",
                    details={"url": url, "exception_type": type(exc).__name__},
                    provider_id=pid,
                )
            )
            return None

        from rivretrieve._internal.providers.pl_imgw.parser import parse_imgw_zip as _parse

        result = _parse(resp.content, station_ids=frozenset())  # empty = all stations
        if result.records.is_empty():
            return None
        return result.records


_Issue = Any
