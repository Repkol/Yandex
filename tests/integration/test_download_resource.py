"""Positive, negative and edge cases for GET /v1/disk/resources/download."""

from __future__ import annotations

from io import BytesIO
from zipfile import is_zipfile

import pytest
import requests

from yandex_disk_api import YandexDiskClient

from .conftest import assert_error_response, unique_child, upload_test_file

pytestmark = pytest.mark.integration


def assert_download_link(response: requests.Response) -> str:
    """Assert a documented Link response and return its direct URL."""
    assert response.status_code == requests.codes.ok
    payload = response.json()
    assert payload["method"] == "GET"
    assert payload["href"].startswith("https://")
    assert payload["templated"] is False
    return payload["href"]


def download_without_oauth(url: str) -> requests.Response:
    """Use the temporary URL without forwarding the OAuth header."""
    return requests.get(url, timeout=30)


def test_get_download_link_happy_path_downloads_exact_file_content(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: the temporary link downloads the original bytes."""
    file_path = f"{unique_child(sandbox_path, 'download-happy')}.txt"
    content = b"downloaded content must match exactly"
    upload_test_file(disk_client, file_path, content)

    response = disk_client.get_download_link(file_path)
    direct_download = download_without_oauth(assert_download_link(response))

    assert direct_download.status_code == requests.codes.ok
    assert direct_download.content == content


def test_get_download_link_fields_limits_response(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: fields limits attributes in the returned Link object."""
    file_path = f"{unique_child(sandbox_path, 'download-fields')}.txt"
    upload_test_file(disk_client, file_path, b"fields")

    response = disk_client.get_download_link(
        file_path,
        fields="href,method",
    )

    assert response.status_code == requests.codes.ok
    assert set(response.json()) == {"href", "method"}
    assert response.json()["method"] == "GET"


def test_get_download_link_supports_unicode_and_spaces(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: a Unicode file path is correctly encoded."""
    file_path = f"{unique_child(sandbox_path, 'файл для скачивания')}.txt"
    content = "Содержимое файла".encode()
    upload_test_file(disk_client, file_path, content)

    response = disk_client.get_download_link(file_path)
    direct_download = download_without_oauth(assert_download_link(response))

    assert direct_download.status_code == requests.codes.ok
    assert direct_download.content == content


def test_get_download_link_for_empty_file(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Boundary: an empty file still has a valid downloadable link."""
    file_path = f"{unique_child(sandbox_path, 'download-empty')}.txt"
    upload_test_file(disk_client, file_path, b"")

    response = disk_client.get_download_link(file_path)
    direct_download = download_without_oauth(assert_download_link(response))

    assert direct_download.status_code == requests.codes.ok
    assert direct_download.content == b""


def test_get_download_link_without_required_path_returns_400(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: omitting the required path parameter is rejected."""
    response = disk_client.get_download_link(None, expected_statuses={400})

    payload = assert_error_response(response, requests.codes.bad_request)
    assert payload["error"] == "FieldValidationError"


def test_get_download_link_for_missing_file_returns_404(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: a missing file has no download link."""
    missing_path = f"{unique_child(sandbox_path, 'missing-download')}.txt"

    response = disk_client.get_download_link(
        missing_path,
        expected_statuses={404},
    )

    payload = assert_error_response(response, requests.codes.not_found)
    assert payload["error"] == "DiskNotFoundError"


def test_get_download_link_for_directory_returns_zip_archive(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Observed edge case: a folder is downloaded as a ZIP archive."""
    folder_path = unique_child(sandbox_path, "download-folder")
    disk_client.create_folder(folder_path)

    response = disk_client.get_download_link(folder_path)
    direct_download = download_without_oauth(assert_download_link(response))

    assert direct_download.status_code == requests.codes.ok
    assert is_zipfile(BytesIO(direct_download.content))


def test_get_download_link_with_invalid_token_returns_401(
    unauthorized_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: invalid OAuth credentials cannot request a direct link."""
    response = unauthorized_disk_client.get_download_link(
        f"{sandbox_path}/irrelevant.txt",
        expected_statuses={401},
    )

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"
