"""Positive, negative and edge cases for PUT /v1/disk/resources."""

from __future__ import annotations

import pytest
import requests

from yandex_disk_api import YandexDiskClient

from .conftest import assert_error_response, unique_child

pytestmark = pytest.mark.integration


def test_create_folder_happy_path_under_existing_parent(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: create an empty directory under an existing parent."""
    folder_path = unique_child(sandbox_path, "create-happy")

    response = disk_client.create_folder(folder_path)
    metadata = disk_client.get_resource(folder_path).json()

    assert response.status_code == requests.codes.created
    assert response.json()["method"] == "GET"
    assert response.json()["href"].startswith("https://")
    assert metadata["path"] == folder_path
    assert metadata["type"] == "dir"
    assert metadata["_embedded"]["items"] == []


def test_create_folder_supports_unicode_and_spaces(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: path encoding preserves Unicode and spaces."""
    folder_path = unique_child(sandbox_path, "новая папка")

    response = disk_client.create_folder(folder_path)
    metadata = disk_client.get_resource(folder_path).json()

    assert response.status_code == requests.codes.created
    assert metadata["path"] == folder_path
    assert metadata["name"] == folder_path.rsplit("/", maxsplit=1)[1]


def test_create_folder_fields_limits_link_response(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: fields limits attributes in the returned Link object."""
    folder_path = unique_child(sandbox_path, "create-fields")

    response = disk_client.create_folder(
        folder_path,
        fields="href,method",
    )

    assert response.status_code == requests.codes.created
    assert set(response.json()) == {"href", "method"}
    assert response.json()["method"] == "GET"


def test_create_nested_folder_when_direct_parent_exists(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive boundary: nested creation works one level at a time."""
    parent_path = unique_child(sandbox_path, "create-parent")
    child_path = f"{parent_path}/child"
    disk_client.create_folder(parent_path)

    response = disk_client.create_folder(child_path)

    assert response.status_code == requests.codes.created
    assert disk_client.get_resource(child_path).json()["type"] == "dir"


def test_create_folder_without_required_path_returns_400(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: omitting the required path query parameter is rejected."""
    response = disk_client.create_folder(None, expected_statuses={400})

    payload = assert_error_response(response, requests.codes.bad_request)
    assert payload["error"] == "FieldValidationError"


def test_create_folder_with_empty_path_returns_400(
    disk_client: YandexDiskClient,
) -> None:
    """Negative boundary: an explicitly empty path is invalid."""
    response = disk_client.create_folder("", expected_statuses={400})

    payload = assert_error_response(response, requests.codes.bad_request)
    assert payload["error"] == "FieldValidationError"


def test_create_folder_with_missing_parent_is_rejected(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: the direct parent directory must already exist."""
    missing_parent = unique_child(sandbox_path, "missing-parent")
    child_path = f"{missing_parent}/child"

    response = disk_client.create_folder(
        child_path,
        expected_statuses={409},
    )

    payload = assert_error_response(response, requests.codes.conflict)
    assert payload["error"] == "DiskPathDoesntExistsError"
    missing = disk_client.get_resource(child_path, expected_statuses={404})
    assert missing.status_code == requests.codes.not_found


def test_create_duplicate_folder_returns_409(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: a directory cannot be created at an occupied path."""
    folder_path = unique_child(sandbox_path, "create-duplicate")
    disk_client.create_folder(folder_path)

    response = disk_client.create_folder(
        folder_path,
        expected_statuses={409},
    )

    payload = assert_error_response(response, requests.codes.conflict)
    assert payload["error"] == "DiskPathPointsToExistentDirectoryError"


def test_create_folder_with_invalid_token_returns_401(
    unauthorized_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: invalid OAuth credentials cannot create a directory."""
    folder_path = unique_child(sandbox_path, "unauthorized-create")

    response = unauthorized_disk_client.create_folder(
        folder_path,
        expected_statuses={401},
    )

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"


def test_create_folder_at_disk_root_returns_409(
    disk_client: YandexDiskClient,
) -> None:
    """Boundary: the Disk root already exists and cannot be recreated."""
    response = disk_client.create_folder(
        "disk:/",
        expected_statuses={409},
    )

    payload = assert_error_response(response, requests.codes.conflict)
    assert payload["error"] == "DiskPathDoesntExistsError"
