"""Publication existence comes from validated IMGW directory evidence."""

from datetime import date
from pathlib import Path

import pytest

from rivretrieve._internal.providers.pl_imgw.bulk import BASE_URL, discover_imgw_artifacts, download_imgw_history


def index(url: str, names: tuple[str, ...]) -> bytes:
    path = "/" + url.split("/", 3)[3].rstrip("/")
    links = "".join(f'<tr><td><a href="{name}">{name}</a></td></tr>' for name in names)
    return (
        f"<html><head><title>Index of {path}</title></head><body><h1>Index of {path}</h1>"
        f'<table><tr><td><a href="?C=N;O=D">Name</a></td></tr>{links}</table></body></html>'
    ).encode()


def listings(years: dict[int, tuple[str, ...]]) -> dict[str, bytes]:
    root = BASE_URL + "/"
    result = {root: index(root, tuple(f"{year}/" for year in years))}
    result.update({f"{BASE_URL}/{year}/": index(f"{BASE_URL}/{year}/", names) for year, names in years.items()})
    return result


def discover(years: dict[int, tuple[str, ...]], *, today: date = date(2026, 11, 1)):
    return discover_imgw_artifacts(today=today, read_index=listings(years).__getitem__, first_year=2022)


def test_publication_delay_uses_listing_not_completed_year() -> None:
    plan = discover({year: (f"codz_{year}.zip",) for year in range(2022, 2026)})
    assert [item.filename for item in plan] == [f"codz_{year}.zip" for year in range(2022, 2026)]


def test_monthly_partial_history_continues_annual_form_in_any_year() -> None:
    plan = discover({2022: ("codz_2022.zip",), 2023: ("codz_2023_02.zip", "codz_2023_01.zip")})
    assert [item.filename for item in plan] == ["codz_2022.zip", "codz_2023_01.zip", "codz_2023_02.zip"]


def test_empty_trailing_directory_is_not_publication() -> None:
    plan = discover({2022: ("codz_2022.zip",), 2023: (), 2024: ("zjaw_2024.zip",)})
    assert [item.filename for item in plan] == ["codz_2022.zip"]


def test_partial_current_hydrological_year_does_not_wait_for_annual_completion() -> None:
    plan = discover({2022: ("codz_2022_01.zip",)}, today=date(2021, 12, 1))
    assert plan[0].filename == "codz_2022_01.zip"


@pytest.mark.parametrize("years", [{}, {2022: ()}, {2022: ("zjaw_2022.zip",)}])
def test_no_supported_history_fails(years) -> None:
    with pytest.raises(ValueError, match="no supported daily history"):
        discover(years)


@pytest.mark.parametrize(
    "years",
    [
        {2023: ("codz_2023.zip",)},
        {2022: ("codz_2022_02.zip",)},
        {2022: ("codz_2022_01.zip", "codz_2022_03.zip")},
        {2022: ("codz_2022.zip",), 2024: ("codz_2024.zip",)},
        {2022: ("codz_2022.zip",), 2023: (), 2024: ("codz_2024.zip",)},
        {2022: ("codz_2022_01.zip",), 2023: ("codz_2023.zip",)},
    ],
)
def test_missing_initial_or_interior_period_is_not_trailing_delay(years) -> None:
    with pytest.raises(ValueError, match="gap"):
        discover(years)


@pytest.mark.parametrize(
    "names,reason",
    [
        (("codz_2022.zip", "codz_2022_01.zip"), "overlap"),
        (("codz_2022.zip", "codz_2022_12.zip"), "overlap"),
        (("codz_2022.zip", "codz_2022.zip"), "duplicate"),
        (("codz_2022_01.zip", "codz_2022_01.zip"), "duplicate"),
        (("codz_2022_00.zip",), "invalid hydrological month"),
        (("codz_2022_13.zip",), "invalid hydrological month"),
        (("codz_2023.zip",), "publication directory"),
        (("codz_2022.csv",), "unsupported daily archive"),
        (("codz_2022.tar.gz",), "unsupported daily archive"),
        (("codz_2022_1.zip",), "unsupported daily archive"),
        (("codz_2022_revised.zip",), "unsupported daily archive"),
        (("daily/",), "unsupported daily archive"),
        (("https://other.example/codz_2022.zip",), "unsupported link"),
    ],
)
def test_unsupported_duplicate_or_ambiguous_artifacts_fail(names, reason) -> None:
    with pytest.raises(ValueError, match=reason):
        discover({2022: names})


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: b"<html><body>Service temporarily unavailable</body></html>",
        lambda body: body.replace(b"Index of /data/", b"Index of /wrong/"),
        lambda body: body.replace(b"</html>", b""),
        lambda body: body.replace(b"</table>", b""),
        lambda body: body.replace(b"2022/</a>", b"2023/</a>"),
        lambda body: body.replace(b'<a href="2022/">', b'<a href="2022/" href="2023/">'),
        lambda body: body.replace(b"<table>", b"<table>\xff"),
    ],
)
def test_invalid_root_discovery_response_fails(mutate) -> None:
    responses = listings({2022: ("codz_2022.zip",)})
    responses[BASE_URL + "/"] = mutate(responses[BASE_URL + "/"])
    with pytest.raises(ValueError, match="IMGW directory index"):
        discover_imgw_artifacts(today=date(2026, 11, 1), read_index=responses.__getitem__, first_year=2022)


def test_duplicate_year_directory_fails() -> None:
    root = BASE_URL + "/"
    with pytest.raises(ValueError, match="duplicate link"):
        discover_imgw_artifacts(
            today=date(2026, 11, 1), read_index=lambda url: index(root, ("2022/", "2022/")), first_year=2022
        )


def test_future_archive_coverage_is_not_plausible_publication() -> None:
    with pytest.raises(ValueError, match="unfinished publication period"):
        discover({2022: ("codz_2022.zip",)}, today=date(2022, 1, 1))


@pytest.mark.parametrize("failure_at", [BASE_URL + "/", BASE_URL + "/2022/", BASE_URL + "/2023/"])
def test_discovery_failure_cleans_owned_scratch_without_artifact_transfer(tmp_path: Path, failure_at: str) -> None:
    responses = listings({2022: ("codz_2022.zip",), 2023: ("codz_2023.zip",)})
    prior = tmp_path / "publisher-artifact.download-codz_2021.zip"
    prior.write_bytes(b"preserved recovery input")
    unrelated = tmp_path / ".imgw-publication-existing"
    unrelated.mkdir()
    (unrelated / "index.html").write_bytes(b"preserved evidence")
    calls = []

    def transfer(url: str, target: Path) -> None:
        calls.append(url)
        target.write_bytes(b"partial index")
        if url == failure_at:
            raise OSError("listing transfer failed")
        target.write_bytes(responses[url])

    with pytest.raises(OSError, match="listing transfer failed"):
        download_imgw_history(
            tmp_path / "publisher-artifact.download", today=date(2026, 11, 1), transfer=transfer, first_year=2022
        )
    assert all(url.endswith("/") for url in calls)
    assert set(tmp_path.iterdir()) == {prior, unrelated}
    assert prior.read_bytes() == b"preserved recovery input"
    assert (unrelated / "index.html").read_bytes() == b"preserved evidence"


def test_download_refuses_dangling_preexisting_target_without_touching_link(tmp_path: Path) -> None:
    base = tmp_path / "publisher-artifact.download"
    target = base.with_name(base.name + "-codz_2022.zip")
    outside = tmp_path / "not-yet-existing.zip"
    target.symlink_to(outside)
    responses = listings({2022: ("codz_2022.zip",)})

    def transfer(url: str, path: Path) -> None:
        path.write_bytes(responses[url])

    with pytest.raises(FileExistsError, match="already exists"):
        download_imgw_history(base, today=date(2026, 11, 1), transfer=transfer, first_year=2022)
    assert target.is_symlink()
    assert not outside.exists()
