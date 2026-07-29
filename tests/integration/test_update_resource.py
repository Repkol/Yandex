"""Positive, negative and edge cases for PATCH /v1/disk/resources."""

from __future__ import annotations

import pytest
import requests

from yandex_disk_api import YandexDiskClient

from .conftest import assert_error_response, unique_child, upload_test_file

pytestmark = pytest.mark.integration


def test_update_resource_happy_path_sets_custom_properties(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: set custom properties on an existing folder."""
    folder_path = unique_child(sandbox_path, "update-happy")
    properties = {"owner": "api-tests", "status": "ready"}
    disk_client.create_folder(folder_path)

    response = disk_client.update_resource(
        folder_path,
        {"custom_properties": properties},
    )
    persisted = disk_client.get_resource(folder_path).json()

    assert response.status_code == requests.codes.ok
    assert response.json()["path"] == folder_path
    assert response.json()["custom_properties"] == properties
    assert persisted["custom_properties"] == properties


def test_update_resource_fields_limits_response(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: fields limits the response to requested attributes."""
    folder_path = unique_child(sandbox_path, "update-fields")
    properties = {"test_case": "fields"}
    disk_client.create_folder(folder_path)

    response = disk_client.update_resource(
        folder_path,
        {"custom_properties": properties},
        fields="path,custom_properties",
    )

    assert response.status_code == requests.codes.ok
    assert response.json() == {
        "path": folder_path,
        "custom_properties": properties,
    }


def test_update_resource_supports_unicode_property_value(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: property values preserve Unicode and emoji."""
    folder_path = unique_child(sandbox_path, "update-unicode")
    properties = {"greeting": "Привет, мир! 🚀"}
    disk_client.create_folder(folder_path)

    response = disk_client.update_resource(
        folder_path,
        {"custom_properties": properties},
    )

    assert response.status_code == requests.codes.ok
    assert response.json()["custom_properties"] == properties


def test_update_resource_overwrites_one_property_and_preserves_another(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: PATCH changes named keys without replacing the whole map."""
    folder_path = unique_child(sandbox_path, "update-merge")
    disk_client.create_folder(folder_path)
    disk_client.update_resource(
        folder_path,
        {"custom_properties": {"stable": "keep", "mutable": "before"}},
    )

    response = disk_client.update_resource(
        folder_path,
        {"custom_properties": {"mutable": "after"}},
    )

    assert response.status_code == requests.codes.ok
    assert response.json()["custom_properties"] == {
        "stable": "keep",
        "mutable": "after",
    }


def test_update_resource_null_removes_one_custom_property(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: null removes a key while leaving other keys intact."""
    folder_path = unique_child(sandbox_path, "update-remove")
    disk_client.create_folder(folder_path)
    disk_client.update_resource(
        folder_path,
        {"custom_properties": {"keep": "value", "remove": "value"}},
    )

    response = disk_client.update_resource(
        folder_path,
        {"custom_properties": {"remove": None}},
    )

    assert response.status_code == requests.codes.ok
    assert response.json()["custom_properties"] == {"keep": "value"}


def test_update_resource_empty_properties_is_noop(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Boundary: an empty property map succeeds without changing values."""
    folder_path = unique_child(sandbox_path, "update-empty")
    properties = {"existing": "value"}
    disk_client.create_folder(folder_path)
    disk_client.update_resource(
        folder_path,
        {"custom_properties": properties},
    )

    response = disk_client.update_resource(
        folder_path,
        {"custom_properties": {}},
    )

    assert response.status_code == requests.codes.ok
    assert response.json()["custom_properties"] == properties


def test_update_resource_works_for_file(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: custom properties can be assigned to a file."""
    file_path = f"{unique_child(sandbox_path, 'update-file')}.txt"
    upload_test_file(disk_client, file_path, b"file with custom properties")

    response = disk_client.update_resource(
        file_path,
        {"custom_properties": {"kind": "fixture"}},
    )

    assert response.status_code == requests.codes.ok
    assert response.json()["type"] == "file"
    assert response.json()["custom_properties"] == {"kind": "fixture"}


def test_update_resource_without_required_path_returns_400(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: omitting the required path query parameter is rejected."""
    response = disk_client.update_resource(
        None,
        {"custom_properties": {"key": "value"}},
        expected_statuses={400},
    )

    payload = assert_error_response(response, requests.codes.bad_request)
    assert payload["error"] == "FieldValidationError"


def test_update_resource_with_invalid_properties_type_returns_400(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: custom_properties must be a JSON object."""
    response = disk_client.update_resource(
        sandbox_path,
        {"custom_properties": ["not", "an", "object"]},
        expected_statuses={400},
    )

    assert_error_response(response, requests.codes.bad_request)


def test_update_resource_without_body_is_noop(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Observed edge case: absent body succeeds and preserves properties."""
    folder_path = unique_child(sandbox_path, "update-no-body")
    properties = {"existing": "value"}
    disk_client.create_folder(folder_path)
    disk_client.update_resource(
        folder_path,
        {"custom_properties": properties},
    )

    response = disk_client.update_resource(
        folder_path,
        None,
    )

    assert response.status_code == requests.codes.ok
    assert response.json()["custom_properties"] == properties


def test_update_missing_resource_returns_404(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: metadata cannot be assigned to an absent resource."""
    missing_path = unique_child(sandbox_path, "missing-update")

    response = disk_client.update_resource(
        missing_path,
        {"custom_properties": {"key": "value"}},
        expected_statuses={404},
    )

    payload = assert_error_response(response, requests.codes.not_found)
    assert payload["error"] == "DiskNotFoundError"


def test_update_resource_with_invalid_token_returns_401_and_preserves_data(
    disk_client: YandexDiskClient,
    unauthorized_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: invalid OAuth credentials cannot modify properties."""
    folder_path = unique_child(sandbox_path, "unauthorized-update")
    original = {"status": "original"}
    disk_client.create_folder(folder_path)
    disk_client.update_resource(
        folder_path,
        {"custom_properties": original},
    )

    response = unauthorized_disk_client.update_resource(
        folder_path,
        {"custom_properties": {"status": "changed"}},
        expected_statuses={401},
    )

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"
    assert disk_client.get_resource(folder_path).json()["custom_properties"] == original


def test_update_resource_with_unsupported_content_type_returns_415(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: the endpoint only accepts an application/json body."""
    response = disk_client.update_resource(
        sandbox_path,
        '{"custom_properties":{"key":"value"}}',
        content_type="text/plain",
        expected_statuses={415},
    )

    assert_error_response(response, requests.codes.unsupported_media_type)
