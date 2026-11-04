"""Session-owned built distributions for installed, offline packaging checks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from tarfile import open as open_tar
from tempfile import TemporaryDirectory

import pytest

_SHARED_WORKSPACE_ENV = "_RIVRETRIEVE_XDIST_DIST_WORKSPACE"

# Static relative weights for long-pole tests so parallel xdist workers start
# heavy cross-catalogue and installed-wheel checks immediately across distinct
# cores while keeping fast tests at the stealable tail of each worker queue.
_XDIST_HEAVY_NODE_COSTS: tuple[tuple[str, int], ...] = (
    ("tests/test_packaging_carries_catalogues.py::", 280),
    ("tests/test_catalogue_descriptor.py::test_reference_loader_extracts_all_five_evidence_relations[br_ana]", 235),
    ("tests/test_station_metadata_areas.py::test_all_selected_gauges_remain_visible_offline", 180),
    ("tests/test_station_metadata_packaging.py::test_installed_station_metadata_offline[sdist-wheel]", 145),
    ("tests/test_station_metadata.py::test_offline_public_api_mixed_scope", 130),
    ("tests/test_catalogue_evidence.py::test_complete_ordered_provenance_roundtrip[br_ana]", 110),
    (
        "tests/test_deferred_provider_acquisition_gate.py::"
        "test_acquisition_provenance_v2_rejects_legacy_and_mixed_withheld_shapes",
        108,
    ),
    ("tests/test_catalogue_descriptor.py::test_reference_loader_extracts_all_five_evidence_relations[fr_hubeau]", 102),
    (
        "tests/test_deferred_provider_acquisition_gate.py::"
        "test_brazil_discovery_exposes_only_documented_adopted_products",
        100,
    ),
    (
        "tests/test_attested_acquisition_request_urls.py::"
        "test_france_catalogue_capture_names_all_exact_recorded_requests",
        84,
    ),
    ("tests/test_station_catalogue_export.py::test_export_offers_only_supported_countries", 78),
    ("tests/test_acquisition_provenance_lineage.py::test_every_v2_acquisition_has_exact_typed_instant_semantics", 76),
    (
        "tests/test_packaging_excludes_catalogue_build_inputs.py::"
        "test_distribution_keeps_only_runtime_catalogues[sdist-wheel]",
        74,
    ),
    ("tests/test_discovery.py::test_products_returns_exact_global_vocabulary_and_every_provider_subset", 74),
    ("tests/test_station_metadata_packaging.py::test_installed_station_metadata_offline[wheel]", 70),
    ("tests/test_catalogue_evidence.py::test_historical_projection_rejects_changed_current_producer[br_ana]", 69),
    ("tests/test_coverage_map.py::test_catalogue_counts_match_readme_and_observation_capabilities", 68),
    ("tests/test_french_artifact_boundaries.py::test_current_bundle_refuses_retired_publication_service", 60),
    ("tests/test_provider_declaration.py::test_default_registration_is_idempotent", 58),
    ("tests/test_supporting_documentation.py::test_station_metadata_markdown", 56),
    (
        "tests/test_no_nve_catalogue.py::test_brazil_certified_candidates_are_selectable_without_inferred_availability",
        55,
    ),
    (
        "tests/test_fourteenth_provider.py::"
        "test_new_catalogue_only_provider_requires_only_its_directory_and_manifest_line",
        54,
    ),
    (
        "tests/test_deferred_provider_acquisition_gate.py::"
        "test_brazil_selection_retains_unknown_candidate_reason_and_source_evidence",
        53,
    ),
    (
        "tests/test_french_publication_services.py::test_public_discovery_keeps_overlapping_station_identity_separate",
        53,
    ),
    ("tests/test_french_artifact_boundaries.py::test_current_context_only_empty_bundle_round_trip", 52),
    ("tests/test_discovery.py::test_products_result_is_not_a_catalogue_or_dataframe", 47),
    ("tests/test_documentation_examples.py::test_usage_selection_bundle_roundtrip", 45),
    ("tests/store/test_remote_store.py::test_remote_accumulate_selective_read_and_partition_reuse", 45),
    (
        "tests/test_fr_hydroportail_catalogue_generation.py::test_packaged_catalogue_exposes_independent_source_variants",
        43,
    ),
    ("tests/test_ba_fhmzbih_module.py::test_ba_fhmzbih_catalogue_and_live_declaration", 43),
    ("tests/test_discovery.py::test_providers_empty_registry_returns_default_providers", 42),
    ("tests/test_ch_foen_official_public.py::test_offline_selection_reaches_anonymous_official_retrieval", 42),
    ("tests/test_package.py::test_all_packaged_catalogues_expose_exact_reduced_carriers", 41),
    ("tests/test_packaged_provider_snapshots.py::test_dws_catalogue_refuses_observation_retrieval", 40),
    ("tests/test_station_metadata.py::test_public_aligned_lists_preserve_every_source_entry", 40),
    ("tests/test_discovery.py::test_products_unknown_provider_raises_loudly", 39),
    ("tests/test_ch_foen_catalogue_access.py::test_swiss_discovery_is_offline", 38),
    ("tests/test_public_credentials.py::test_import_and_open_provider_discovery_need_no_credentials", 37),
    ("tests/test_documentation.py::test_camels_example_selects_documented_gauges_without_network", 37),
    ("tests/test_catalogue_evidence.py::test_complete_ordered_provenance_roundtrip[fr_hubeau]", 37),
    ("tests/test_catalogue_evidence_memory.py::test_national_normalization_releases_row_buffers_before_closure", 36),
    ("tests/test_provider_architecture_contracts.py::test_registry_matches_declared_provider_kinds", 36),
    ("tests/test_discovery.py::test_south_african_station_discovery_is_not_offered", 36),
)


def _physical_cpu_count() -> int | None:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        allowed = os.sched_getaffinity(0) if hasattr(os, "sched_getaffinity") else None
        cores: set[tuple[str, str]] = set()
        processor: int | None = None
        physical_id: str | None = None
        core_id: str | None = None
        for raw_line in (*cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines(), ""):
            line = raw_line.strip()
            if not line:
                if (
                    processor is not None
                    and (allowed is None or processor in allowed)
                    and physical_id is not None
                    and core_id is not None
                ):
                    cores.add((physical_id, core_id))
                processor = None
                physical_id = None
                core_id = None
                continue
            key, sep, value = line.partition(":")
            if not sep:
                continue
            key = key.strip()
            value = value.strip()
            if key == "processor":
                processor = int(value) if value.isdigit() else None
            elif key == "physical id":
                physical_id = value
            elif key == "core id":
                core_id = value
        if cores:
            return len(cores)
    if sys.platform == "darwin":
        result = subprocess.run(["sysctl", "-n", "hw.physicalcpu"], check=False, text=True, capture_output=True)
        if result.returncode == 0 and result.stdout.strip().isdigit():
            return max(1, int(result.stdout.strip()))
    return None


@pytest.hookimpl(optionalhook=True, tryfirst=True)
def pytest_xdist_auto_num_workers(config: pytest.Config) -> int | None:
    if os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS"):
        return None
    if getattr(config.option, "numprocesses", None) != "auto":
        return None
    return _physical_cpu_count()


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node: object) -> None:
    config = getattr(node, "config", None)
    workerinput = getattr(node, "workerinput", None)
    if config is not None and isinstance(workerinput, dict):
        workerinput["dist_mode"] = str(getattr(config.option, "dist", "no"))


def _heavy_item_cost(item: pytest.Item) -> int:
    nodeid = item.nodeid
    for prefix, cost in _XDIST_HEAVY_NODE_COSTS:
        if nodeid.startswith(prefix):
            return cost
    fixturenames = getattr(item, "fixturenames", ())
    if (
        "installed_distribution" in fixturenames
        or "direct_distribution" in fixturenames
        or "sdist_distribution" in fixturenames
    ):
        return 35
    return 0


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> Iterator[None]:
    yield
    if (
        config.getoption("collectonly", False)
        or config.getoption("evidence_plan", None)
        or config.getoption("evidence_plan_check", None)
    ):
        return
    workerinput = getattr(config, "workerinput", None)
    if isinstance(workerinput, dict):
        worker_count = int(workerinput.get("workercount", 0))
        dist_mode = str(workerinput.get("dist_mode", "no"))
    else:
        tx = getattr(config.option, "tx", None) or ()
        dist_mode = str(getattr(config.option, "dist", "no"))
        worker_count = len(tx) if dist_mode != "no" else 0
    if worker_count < 2 or len(items) <= worker_count or dist_mode not in {"worksteal", "load"}:
        return
    heavy: list[tuple[int, int, pytest.Item]] = []
    light: list[pytest.Item] = []
    for index, item in enumerate(items):
        cost = _heavy_item_cost(item)
        if cost > 0:
            heavy.append((-cost, index, item))
        else:
            light.append(item)
    if not heavy:
        return
    heavy.sort()
    if dist_mode == "worksteal":
        remaining = len(items)
        slice_sizes: list[int] = []
        for idx in range(worker_count):
            size = remaining // (worker_count - idx)
            slice_sizes.append(size)
            remaining -= size
        buckets: list[list[pytest.Item]] = [[] for _ in range(worker_count)]
        loads = [0] * worker_count
        overflow: list[pytest.Item] = []
        for neg_cost, _, item in heavy:
            candidates = [idx for idx in range(worker_count) if len(buckets[idx]) < slice_sizes[idx]]
            if not candidates:
                overflow.append(item)
                continue
            target = min(candidates, key=lambda idx: (loads[idx], idx))
            buckets[target].append(item)
            loads[target] -= neg_cost
        tail_pool = overflow + light
        cursor = 0
        for idx in range(worker_count):
            needed = slice_sizes[idx] - len(buckets[idx])
            if needed > 0:
                buckets[idx].extend(tail_pool[cursor : cursor + needed])
                cursor += needed
        reordered = [item for bucket in buckets for item in bucket]
    else:
        reordered = [item for _, _, item in heavy] + light
    assert len(reordered) == len(items)
    items[:] = reordered


def _uv_executable() -> str:
    resolved = shutil.which("uv")
    if resolved is not None:
        return resolved
    candidate = Path(sys.executable).with_name("uv")
    return str(candidate) if candidate.is_file() else "uv"


def pytest_configure(config: pytest.Config) -> None:
    if hasattr(config, "workerinput"):
        return
    numprocesses = getattr(config.option, "numprocesses", None)
    if not numprocesses:
        os.environ.pop(_SHARED_WORKSPACE_ENV, None)
        return
    if "POLARS_MAX_THREADS" not in os.environ:
        if isinstance(numprocesses, int) and numprocesses > 0:
            workers = numprocesses
        elif numprocesses == "auto":
            workers = _physical_cpu_count() or os.cpu_count() or 1
        else:
            workers = os.cpu_count() or 1
        threads = max(1, (os.cpu_count() or 2) // max(1, workers))
        os.environ["POLARS_MAX_THREADS"] = str(threads)
        config._set_polars_max_threads = True  # type: ignore[attr-defined]
    repository = Path(__file__).resolve().parents[1]
    checks = repository / ".worktrees" / "distribution-checks"
    checks.mkdir(parents=True, exist_ok=True)
    shared = TemporaryDirectory(prefix="installed-xdist-", dir=checks)
    config._shared_distribution_workspace = shared  # type: ignore[attr-defined]
    os.environ[_SHARED_WORKSPACE_ENV] = shared.name


def pytest_sessionfinish(session: pytest.Session) -> None:
    if getattr(session.config, "_set_polars_max_threads", False):
        os.environ.pop("POLARS_MAX_THREADS", None)
    shared = getattr(session.config, "_shared_distribution_workspace", None)
    if shared is not None:
        os.environ.pop(_SHARED_WORKSPACE_ENV, None)
        shared.cleanup()


@dataclass(frozen=True)
class InstalledDistribution:
    wheel: Path
    sdist: Path | None
    python: Path
    execution: Path

    def verify(self, source: str) -> None:
        # Each verifier gets a new process, working directory and HOME, while the
        # installed distribution remains a read-only input shared by the session.
        with TemporaryDirectory(prefix="verify-", dir=self.execution) as temporary:
            run(
                [str(self.python), "-I", "-B", "-c", source],
                cwd=Path(temporary),
                env={"PATH": os.environ["PATH"], "HOME": temporary},
            )


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, env=env, check=False, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="session")
def distribution_workspace(record_testsuite_property) -> Iterator[Path]:
    shared = os.environ.get(_SHARED_WORKSPACE_ENV)
    if shared is not None and hasattr(os, "fork"):
        record_testsuite_property("distribution_workspace", shared)
        yield Path(shared)
        return
    repository = Path(__file__).resolve().parents[1]
    checks = repository / ".worktrees" / "distribution-checks"
    checks.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="installed-", dir=checks) as temporary:
        record_testsuite_property("distribution_workspace", temporary)
        yield Path(temporary)


def _build_and_install(
    workspace: Path,
    *,
    from_sdist: bool,
    record_testsuite_property: Callable[[str, object], None],
) -> InstalledDistribution:
    repository = Path(__file__).resolve().parents[1]
    workspace.mkdir()
    dist = workspace / "dist"
    source = repository
    sdist = None
    uv = _uv_executable()
    # Use the backend installed from the lock. Isolated build dependency resolution
    # needs registry metadata that a fresh locked sync need not cache. The built
    # package is still installed and verified in a separate offline environment.
    build = [uv, "build", "--offline", "--force-pep517", "--no-build-isolation", "--python", sys.executable]
    if from_sdist:
        run([*build, "--sdist", "--out-dir", str(dist)], cwd=source)
        archives = tuple(dist.glob("rivretrieve-*.tar.gz"))
        assert len(archives) == 1
        sdist = archives[0]
        extracted = workspace / "extracted"
        with open_tar(sdist, "r:gz") as archive:
            archive.extractall(extracted, filter="data")
        sources = tuple(extracted.iterdir())
        assert len(sources) == 1
        source = sources[0]
        record_testsuite_property("source_copy", str(source))
    run([*build, "--wheel", "--out-dir", str(dist)], cwd=source)
    wheels = tuple(dist.glob("rivretrieve-*.whl"))
    assert len(wheels) == 1

    environment = workspace / "environment"
    execution = workspace / "execution"
    execution.mkdir()
    run([uv, "venv", "--offline", "--python", sys.executable, str(environment)], cwd=execution)
    python = environment / "bin" / "python"
    run([uv, "pip", "install", "--offline", "--no-deps", "--python", str(python), str(wheels[0])], cwd=execution)
    sites = tuple((environment / "lib").glob("python*/site-packages"))
    assert len(sites) == 1
    record_testsuite_property("installed_package", str(sites[0] / "rivretrieve"))
    # Reuse dependency directories without executing the project's editable .pth files.
    dependencies = list(
        dict.fromkeys(
            str(Path(path).resolve())
            for path in sys.path
            if Path(path).is_absolute() and Path(path).name == "site-packages" and Path(path).is_dir()
        )
    )
    assert dependencies
    assert all(not Path(path).is_relative_to(repository / "src") for path in dependencies)
    (sites[0] / "dependencies.pth").write_text("\n".join(dependencies) + "\n")
    return InstalledDistribution(wheels[0], sdist, python, execution)


def _shared_or_build(
    distribution_workspace: Path,
    kind: str,
    *,
    from_sdist: bool,
    record_testsuite_property: Callable[[str, object], None],
) -> InstalledDistribution:
    workspace = distribution_workspace / kind
    if os.environ.get(_SHARED_WORKSPACE_ENV) is None or not hasattr(os, "fork"):
        return _build_and_install(workspace, from_sdist=from_sdist, record_testsuite_property=record_testsuite_property)
    import fcntl

    lock_path = distribution_workspace / f".{kind}.lock"
    ready_path = workspace / ".ready.json"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if ready_path.is_file():
            payload = json.loads(ready_path.read_text(encoding="utf-8"))
            if payload.get("source_copy") is not None:
                record_testsuite_property("source_copy", payload["source_copy"])
            record_testsuite_property("installed_package", payload["installed_package"])
            return InstalledDistribution(
                wheel=Path(payload["wheel"]),
                sdist=None if payload["sdist"] is None else Path(payload["sdist"]),
                python=Path(payload["python"]),
                execution=Path(payload["execution"]),
            )
        if workspace.exists():
            shutil.rmtree(workspace)
        recorded: dict[str, object] = {}

        def capture_property(key: str, value: object) -> None:
            recorded[key] = value
            record_testsuite_property(key, value)

        built = _build_and_install(workspace, from_sdist=from_sdist, record_testsuite_property=capture_property)
        ready_path.write_text(
            json.dumps(
                {
                    "wheel": str(built.wheel),
                    "sdist": None if built.sdist is None else str(built.sdist),
                    "python": str(built.python),
                    "execution": str(built.execution),
                    "source_copy": recorded.get("source_copy"),
                    "installed_package": recorded["installed_package"],
                }
            ),
            encoding="utf-8",
        )
        return built


@pytest.fixture(scope="session")
def direct_distribution(distribution_workspace: Path, record_testsuite_property) -> InstalledDistribution:
    return _shared_or_build(
        distribution_workspace, "wheel", from_sdist=False, record_testsuite_property=record_testsuite_property
    )


@pytest.fixture(scope="session")
def sdist_distribution(distribution_workspace: Path, record_testsuite_property) -> InstalledDistribution:
    return _shared_or_build(
        distribution_workspace, "sdist-wheel", from_sdist=True, record_testsuite_property=record_testsuite_property
    )


@pytest.fixture
def installed_distribution(request: pytest.FixtureRequest) -> InstalledDistribution:
    fixture = {"wheel": "direct_distribution", "sdist-wheel": "sdist_distribution"}[request.param]
    return request.getfixturevalue(fixture)
