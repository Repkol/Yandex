"""Positive, negative and edge cases for GET /v1/disk/resources."""

from __future__ import annotations

import pytest
import requests

from yandex_disk_api import YandexDiskClient

from .conftest import assert_error_response, unique_child

pytestmark = pytest.mark.integration


def test_get_resource_happy_path_returns_folder_metadata(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: an existing directory returns its metadata and children."""
    folder_path = unique_child(sandbox_path, "get-happy")
    disk_client.create_folder(folder_path)

    response = disk_client.get_resource(folder_path)
    payload = response.json()

    assert response.status_code == requests.codes.ok
    assert payload["path"] == folder_path
    assert payload["name"] == folder_path.rsplit("/", maxsplit=1)[1]
    assert payload["type"] == "dir"
    assert payload["_embedded"]["path"] == folder_path
    assert payload["_embedded"]["items"] == []


def test_get_resource_handles_unicode_and_spaces_in_path(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: requests must correctly encode a non-ASCII resource path."""
    folder_path = unique_child(sandbox_path, "папка пробел")
    disk_client.create_folder(folder_path)

    response = disk_client.get_resource(folder_path)

    assert response.status_code == requests.codes.ok
    assert response.json()["path"] == folder_path
    assert response.json()["name"] == folder_path.rsplit("/", maxsplit=1)[1]


def test_get_resource_fields_limits_response_attributes(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: fields returns only the requested top-level attributes."""
    response = disk_client.get_resource(
        sandbox_path,
        fields="name,path,type",
    )

    assert response.status_code == requests.codes.ok
    assert response.json() == {
        "name": sandbox_path.removeprefix("disk:/"),
        "path": sandbox_path,
        "type": "dir",
    }


def test_get_resource_paginates_and_sorts_children(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: limit, offset and sort produce a stable child page."""
    folder_path = unique_child(sandbox_path, "pagination")
    disk_client.create_folder(folder_path)
    child_names = ["item-a", "item-b", "item-c"]
    for name in child_names:
        disk_client.create_folder(f"{folder_path}/{name}")

    response = disk_client.get_resource(
        folder_path,
        limit=2,
        offset=1,
        sort="name",
    )
    embedded = response.json()["_embedded"]

    assert response.status_code == requests.codes.ok
    assert embedded["total"] == 3
    assert embedded["limit"] == 2
    assert embedded["offset"] == 1
    assert [item["name"] for item in embedded["items"]] == child_names[1:]


def test_get_resource_offset_beyond_last_child_returns_empty_page(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Boundary: offset larger than total is valid and returns no items."""
    folder_path = unique_child(sandbox_path, "large-offset")
    disk_client.create_folder(folder_path)
    disk_client.create_folder(f"{folder_path}/only-child")

    response = disk_client.get_resource(folder_path, limit=1, offset=100)
    embedded = response.json()["_embedded"]

    assert response.status_code == requests.codes.ok
    assert embedded["total"] == 1
    assert embedded["offset"] == 100
    assert embedded["items"] == []


def test_get_resource_without_required_path_returns_400(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: omitting the required path query parameter is rejected."""
    response = disk_client.get_resource(None, expected_statuses={400})

    payload = assert_error_response(response, requests.codes.bad_request)
    assert payload["error"] == "FieldValidationError"


def test_get_resource_with_non_numeric_limit_returns_400(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative boundary: limit must be a number."""
    response = disk_client.get_resource(
        sandbox_path,
        limit="not-a-number",
        expected_statuses={400},
    )

    assert_error_response(response, requests.codes.bad_request)


def test_get_resource_for_missing_path_returns_404(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: a syntactically valid but absent resource is not found."""
    missing_path = unique_child(sandbox_path, "missing-get")

    response = disk_client.get_resource(missing_path, expected_statuses={404})

    payload = assert_error_response(response, requests.codes.not_found)
    assert payload["error"] == "DiskNotFoundError"


def test_get_resource_with_invalid_token_returns_401(
    unauthorized_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: invalid OAuth credentials are rejected."""
    response = unauthorized_disk_client.get_resource(
        sandbox_path,
        expected_statuses={401},
    )

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"
