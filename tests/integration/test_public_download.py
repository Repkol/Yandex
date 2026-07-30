"""Cases for GET /v1/disk/public/resources/download."""

from __future__ import annotations

from io import BytesIO
from zipfile import is_zipfile

import pytest
import requests

from yandex_disk_api import YandexDiskClient

from .conftest import (
    assert_error_response,
    temporarily_published_resource,
    unique_child,
    upload_test_file,
    wait_for_public_resource_state,
)

pytestmark = pytest.mark.integration


def assert_public_download_link(
    response: requests.Response,
    *,
    expected_fields: set[str] | None = None,
) -> str:
    """Assert a public download Link and return its direct URL."""
    assert response.status_code == requests.codes.ok
    assert response.headers["Content-Type"].startswith("application/json")
    payload = response.json()
    if expected_fields is not None:
        assert set(payload) == expected_fields
    assert payload["method"] == "GET"
    assert str(payload["href"]).startswith("https://")
    if "templated" in payload:
        assert payload["templated"] is False
    return str(payload["href"])


def download_without_oauth(url: str) -> requests.Response:
    """Download from the temporary public URL without OAuth."""
    return requests.get(url, timeout=30)


def test_public_download_happy_path_returns_exact_file(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: download exact bytes using only a public key."""
    file_path = f"{unique_child(sandbox_path, 'public-download-happy')}.txt"
    content = b"exact bytes from public download"
    upload_test_file(disk_client, file_path, content)

    with temporarily_published_resource(disk_client, file_path) as private:
        public_key = str(private["public_key"])
        wait_for_public_resource_state(
            public_disk_client,
            public_key,
            present=True,
        )
        response = public_disk_client.get_public_download_link(public_key)
        download = download_without_oauth(assert_public_download_link(response))

        assert download.status_code == requests.codes.ok
        assert download.content == content


def test_public_download_accepts_public_url(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: public_url can be used instead of public_key."""
    file_path = f"{unique_child(sandbox_path, 'public-url-download')}.txt"
    content = b"download through a public URL"
    upload_test_file(disk_client, file_path, content)

    with temporarily_published_resource(disk_client, file_path) as private:
        wait_for_public_resource_state(
            public_disk_client,
            str(private["public_key"]),
            present=True,
        )
        response = public_disk_client.get_public_download_link(
            str(private["public_url"]),
        )
        download = download_without_oauth(assert_public_download_link(response))

        assert download.status_code == requests.codes.ok
        assert download.content == content


def test_public_download_nested_file_from_folder(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: path downloads a nested file from a public folder."""
    folder_path = unique_child(sandbox_path, "public-download-nested")
    file_path = f"{folder_path}/nested/file.txt"
    content = b"nested public download"
    disk_client.create_folder(folder_path)
    disk_client.create_folder(f"{folder_path}/nested")
    upload_test_file(disk_client, file_path, content)

    with temporarily_published_resource(disk_client, folder_path) as private:
        public_key = str(private["public_key"])
        wait_for_public_resource_state(
            public_disk_client,
            public_key,
            path="/nested/file.txt",
            present=True,
        )
        response = public_disk_client.get_public_download_link(
            public_key,
            path="/nested/file.txt",
        )
        download = download_without_oauth(assert_public_download_link(response))

        assert download.status_code == requests.codes.ok
        assert download.content == content


def test_public_download_fields_limits_link_response(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: fields limits Link attributes without breaking download."""
    file_path = f"{unique_child(sandbox_path, 'public-download-fields')}.txt"
    content = b"public fields"
    upload_test_file(disk_client, file_path, content)

    with temporarily_published_resource(disk_client, file_path) as private:
        public_key = str(private["public_key"])
        wait_for_public_resource_state(
            public_disk_client,
            public_key,
            present=True,
        )
        response = public_disk_client.get_public_download_link(
            public_key,
            fields="href,method",
        )
        download = download_without_oauth(
            assert_public_download_link(
                response,
                expected_fields={"href", "method"},
            )
        )

        assert download.status_code == requests.codes.ok
        assert download.content == content


def test_public_download_supports_unicode_nested_path(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: Unicode and spaces in nested path are encoded correctly."""
    folder_path = unique_child(sandbox_path, "public-download-unicode")
    file_path = f"{folder_path}/папка/файл юникод имя.txt"
    content = "публичные данные".encode()
    disk_client.create_folder(folder_path)
    disk_client.create_folder(f"{folder_path}/папка")
    upload_test_file(disk_client, file_path, content)

    with temporarily_published_resource(disk_client, folder_path) as private:
        public_key = str(private["public_key"])
        wait_for_public_resource_state(
            public_disk_client,
            public_key,
            path="/папка/файл юникод имя.txt",
            present=True,
        )
        response = public_disk_client.get_public_download_link(
            public_key,
            path="/папка/файл юникод имя.txt",
        )
        download = download_without_oauth(assert_public_download_link(response))

        assert download.status_code == requests.codes.ok
        assert download.content == content


def test_public_download_empty_file(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: a zero-byte public file has a working link."""
    file_path = f"{unique_child(sandbox_path, 'public-download-empty')}.txt"
    upload_test_file(disk_client, file_path, b"")

    with temporarily_published_resource(disk_client, file_path) as private:
        public_key = str(private["public_key"])
        wait_for_public_resource_state(
            public_disk_client,
            public_key,
            present=True,
        )
        response = public_disk_client.get_public_download_link(public_key)
        download = download_without_oauth(assert_public_download_link(response))

        assert download.status_code == requests.codes.ok
        assert download.content == b""


def test_public_download_folder_returns_zip(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: the public root folder is downloaded as a ZIP archive."""
    folder_path = unique_child(sandbox_path, "public-download-folder")
    disk_client.create_folder(folder_path)
    upload_test_file(disk_client, f"{folder_path}/inside.txt", b"inside")

    with temporarily_published_resource(disk_client, folder_path) as private:
        public_key = str(private["public_key"])
        wait_for_public_resource_state(
            public_disk_client,
            public_key,
            present=True,
        )
        response = public_disk_client.get_public_download_link(public_key)
        download = download_without_oauth(assert_public_download_link(response))

        assert download.status_code == requests.codes.ok
        assert is_zipfile(BytesIO(download.content))


def test_public_download_without_key_returns_400(
    public_disk_client: YandexDiskClient,
) -> None:
    """Negative: public_key is required."""
    response = public_disk_client.get_public_download_link(
        None,
        expected_statuses={400},
    )

    assert_error_response(response, requests.codes.bad_request)


def test_public_download_rejects_malformed_key(
    public_disk_client: YandexDiskClient,
) -> None:
    """Negative: an explicitly empty public key is invalid."""
    response = public_disk_client.get_public_download_link(
        "",
        expected_statuses={400},
    )

    assert_error_response(response, requests.codes.bad_request)


def test_public_download_unknown_key_returns_404(
    public_disk_client: YandexDiskClient,
) -> None:
    """Negative: a well-formed but unknown key has no download link."""
    response = public_disk_client.get_public_download_link(
        "not-a-public-key",
        expected_statuses={404},
    )

    payload = assert_error_response(response, requests.codes.not_found)
    assert payload["error"] == "DiskNotFoundError"


def test_public_download_missing_nested_path_returns_404(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: a missing nested file has no public download link."""
    folder_path = unique_child(sandbox_path, "public-download-missing")
    disk_client.create_folder(folder_path)

    with temporarily_published_resource(disk_client, folder_path) as private:
        public_key = str(private["public_key"])
        wait_for_public_resource_state(
            public_disk_client,
            public_key,
            present=True,
        )
        response = public_disk_client.get_public_download_link(
            public_key,
            path="/missing.txt",
            expected_statuses={404},
        )

        assert_error_response(response, requests.codes.not_found)


def test_revoked_public_key_has_no_download_link(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative edge: unpublish invalidates public download access."""
    file_path = f"{unique_child(sandbox_path, 'public-download-revoked')}.txt"
    upload_test_file(disk_client, file_path, b"revoked")

    with temporarily_published_resource(disk_client, file_path) as private:
        public_key = str(private["public_key"])
        wait_for_public_resource_state(
            public_disk_client,
            public_key,
            present=True,
        )

    wait_for_public_resource_state(
        public_disk_client,
        public_key,
        present=False,
    )
    response = public_disk_client.get_public_download_link(
        public_key,
        expected_statuses={404},
    )

    assert_error_response(response, requests.codes.not_found)
