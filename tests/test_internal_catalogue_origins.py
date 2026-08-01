import typing
from dataclasses import FrozenInstanceError

import pytest

from rivretrieve._internal.catalogue_origins import (
    CatalogueOrigin,
    Evidence,
    Field,
    NativeColumn,
    NotPublished,
)


def test_field_carries_an_exact_native_column_and_is_immutable() -> None:
    native_column = NativeColumn(" station code ")
    origin = Field(native_column)

    assert origin.native_column == " station code "
    assert isinstance(origin.native_column, NativeColumn)
    attribute = "native_column"
    with pytest.raises(FrozenInstanceError):
        setattr(origin, attribute, NativeColumn("other"))


@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_native_column_rejects_empty_names(value: str) -> None:
    with pytest.raises(ValueError, match="native column name must not be empty"):
        NativeColumn(value)


def test_field_rejects_a_bare_string_carrier() -> None:
    with pytest.raises(TypeError, match="Field.native_column must be a NativeColumn"):
        Field("station_code")  # type: ignore[arg-type]


def test_field_defers_native_table_membership_to_the_build_gate() -> None:
    origin = Field(NativeColumn("column_not_yet_fetched"))

    assert origin.native_column == "column_not_yet_fetched"


@pytest.mark.parametrize(
    "url",
    [
        "http://provider.example/documentation",
        "https://provider.example/catalogue?view=stations#fields",
    ],
)
def test_not_published_carries_http_documentation_evidence_and_is_immutable(url: str) -> None:
    evidence = Evidence(url)
    origin = NotPublished(evidence)

    assert origin.evidence == url
    assert isinstance(origin.evidence, Evidence)
    attribute = "evidence"
    with pytest.raises(FrozenInstanceError):
        setattr(origin, attribute, Evidence("https://provider.example/other"))


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "/provider-documentation",
        "ftp://provider.example/documentation",
        "https://",
        "https://provider.example/has whitespace",
    ],
)
def test_evidence_rejects_empty_or_non_http_documentation_links(value: str) -> None:
    with pytest.raises(ValueError, match=r"evidence must be an absolute HTTP\(S\) documentation link"):
        Evidence(value)


def test_not_published_requires_the_named_evidence_carrier() -> None:
    with pytest.raises(TypeError, match="NotPublished.evidence must be Evidence"):
        NotPublished("https://provider.example/documentation")  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        NotPublished()  # type: ignore[call-arg]


def test_catalogue_origin_union_contains_exactly_the_implemented_forms() -> None:
    assert typing.get_args(CatalogueOrigin.__value__) == (Field, NotPublished)


def test_field_has_value_equality_and_hashing() -> None:
    first = Field(NativeColumn("station_code"))
    equal = Field(NativeColumn("station_code"))
    different = Field(NativeColumn("station_name"))

    assert first == equal
    assert first != different
    assert hash(first) == hash(equal)
    assert {first, equal, different} == {first, different}


def test_not_published_has_value_equality_and_hashing() -> None:
    first = NotPublished(Evidence("https://provider.example/documentation"))
    equal = NotPublished(Evidence("https://provider.example/documentation"))
    different = NotPublished(Evidence("https://provider.example/catalogue"))

    assert first == equal
    assert first != different
    assert hash(first) == hash(equal)
    assert {first, equal, different} == {first, different}


def test_catalogue_origin_forms_never_compare_equal_to_each_other() -> None:
    value = "https://provider.example/documentation"

    assert Field(NativeColumn(value)) != NotPublished(Evidence(value))
