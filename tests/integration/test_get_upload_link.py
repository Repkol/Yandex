"""Positive, negative and edge cases for GET /v1/disk/resources/upload."""

from __future__ import annotations

from hashlib import md5

import pytest
import requests

from yandex_disk_api import YandexDiskClient

from .conftest import (
    assert_error_response,
    unique_child,
    upload_test_file,
)

pytestmark = pytest.mark.integration


def assert_upload_link(
    response: requests.Response,
    *,
    expected_fields: set[str] | None = None,
) -> str:
    """Assert a documented upload Link and return its temporary URL."""
    assert response.status_code == requests.codes.ok
    assert response.headers["Content-Type"].startswith("application/json")
    payload = response.json()
    if expected_fields is not None:
        assert set(payload) == expected_fields
    assert payload["method"] == "PUT"
    assert str(payload["href"]).startswith("https://")
    if "templated" in payload:
        assert payload["templated"] is False
    if "operation_id" in payload:
        assert isinstance(payload["operation_id"], str)
    return str(payload["href"])


def put_file_content(url: str, content: bytes) -> requests.Response:
    """Upload bytes without forwarding the API client's OAuth header."""
    return requests.put(url, data=content, timeout=30)


def test_get_upload_link_happy_path_uploads_exact_content(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: obtain a link and upload exact file bytes with PUT."""
    file_path = f"{unique_child(sandbox_path, 'upload-happy')}.txt"
    content = b"exact content uploaded through a temporary URL"

    response = disk_client.get_upload_link(file_path)
    upload = put_file_content(assert_upload_link(response), content)
    metadata = disk_client.get_resource(file_path).json()

    assert upload.status_code == requests.codes.created
    assert metadata["path"] == file_path
    assert metadata["type"] == "file"
    assert metadata["size"] == len(content)
    assert metadata["md5"] == md5(content).hexdigest()


def test_get_upload_link_fields_limits_response(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: fields limits attributes without invalidating the URL."""
    file_path = f"{unique_child(sandbox_path, 'upload-fields')}.txt"

    response = disk_client.get_upload_link(
        file_path,
        fields="href,method",
    )
    upload = put_file_content(
        assert_upload_link(
            response,
            expected_fields={"href", "method"},
        ),
        b"fields",
    )

    assert upload.status_code == requests.codes.created
    assert disk_client.get_resource(file_path).json()["size"] == len(b"fields")


def test_get_upload_link_overwrite_replaces_existing_file(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: overwrite=true replaces an existing file."""
    file_path = f"{unique_child(sandbox_path, 'upload-overwrite')}.txt"
    before = upload_test_file(disk_client, file_path, b"old content")
    new_content = b"new replacement content"

    response = disk_client.get_upload_link(file_path, overwrite=True)
    upload = put_file_content(assert_upload_link(response), new_content)
    after = disk_client.get_resource(file_path).json()

    assert upload.status_code == requests.codes.created
    assert after["md5"] == md5(new_content).hexdigest()
    assert after["md5"] != before["md5"]
    assert after["size"] == len(new_content)


def test_get_upload_link_supports_unicode_and_spaces(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: Unicode and spaces in a destination path are preserved."""
    file_path = f"{unique_child(sandbox_path, 'загрузка файла')}.txt"
    content = "данные файла".encode()

    response = disk_client.get_upload_link(file_path)
    upload = put_file_content(assert_upload_link(response), content)
    metadata = disk_client.get_resource(file_path).json()

    assert upload.status_code == requests.codes.created
    assert metadata["path"] == file_path
    assert metadata["name"] == file_path.rsplit("/", maxsplit=1)[1]


def test_get_upload_link_accepts_empty_file(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: an empty request body creates a zero-byte file."""
    file_path = f"{unique_child(sandbox_path, 'upload-empty')}.txt"

    response = disk_client.get_upload_link(file_path)
    upload = put_file_content(assert_upload_link(response), b"")
    metadata = disk_client.get_resource(file_path).json()

    assert upload.status_code == requests.codes.created
    assert metadata["size"] == 0
    assert metadata["md5"] == md5(b"").hexdigest()


def test_get_upload_link_existing_file_without_overwrite_returns_409(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: overwrite is disabled by default for an occupied path."""
    file_path = f"{unique_child(sandbox_path, 'upload-conflict')}.txt"
    before = upload_test_file(disk_client, file_path, b"keep original")

    response = disk_client.get_upload_link(
        file_path,
        expected_statuses={409},
    )

    assert_error_response(response, requests.codes.conflict)
    after = disk_client.get_resource(file_path).json()
    assert after["md5"] == before["md5"]
    assert after["size"] == before["size"]


def test_get_upload_link_without_required_path_returns_400(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: path is a required query parameter."""
    response = disk_client.get_upload_link(
        None,
        expected_statuses={400},
    )

    payload = assert_error_response(response, requests.codes.bad_request)
    assert payload["error"] == "FieldValidationError"


def test_get_upload_link_to_missing_parent_is_rejected(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: the destination's direct parent must exist."""
    missing_parent = unique_child(sandbox_path, "upload-missing-parent")
    file_path = f"{missing_parent}/result.txt"

    response = disk_client.get_upload_link(
        file_path,
        expected_statuses={409},
    )

    payload = assert_error_response(response, requests.codes.conflict)
    assert payload["error"] == "DiskPathDoesntExistsError"


def test_get_upload_link_cannot_replace_directory(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative edge: overwrite=true cannot replace a directory with a file."""
    folder_path = unique_child(sandbox_path, "upload-over-dir")
    disk_client.create_folder(folder_path)

    response = disk_client.get_upload_link(
        folder_path,
        overwrite=True,
        expected_statuses={409},
    )

    assert_error_response(response, requests.codes.conflict)
    assert disk_client.get_resource(folder_path).json()["type"] == "dir"


def test_get_upload_link_with_invalid_token_returns_401(
    unauthorized_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: invalid OAuth credentials cannot obtain an upload URL."""
    file_path = f"{unique_child(sandbox_path, 'unauthorized-upload')}.txt"

    response = unauthorized_disk_client.get_upload_link(
        file_path,
        expected_statuses={401},
    )

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"
