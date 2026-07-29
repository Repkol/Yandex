"""Positive, negative and edge cases for GET /resources/last-uploaded."""

from __future__ import annotations

import time
from uuid import uuid4

import pytest
import requests

from yandex_disk_api import YandexDiskClient

from .conftest import assert_error_response, upload_test_file
from .test_list_files import ONE_PIXEL_PNG

pytestmark = pytest.mark.integration


def wait_for_recent_paths(
    client: YandexDiskClient,
    expected_paths: set[str],
    *,
    media_type: str | None = None,
    timeout: float = 20.0,
) -> list[dict[str, object]]:
    """Poll the recent-file index until all unique test paths appear."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        items = client.list_last_uploaded(
            limit=1000,
            media_type=media_type,
        ).json()["items"]
        listed_paths = {str(item["path"]) for item in items}
        if expected_paths <= listed_paths:
            return items
        time.sleep(0.25)

    pytest.fail(f"Paths did not appear in last-uploaded list: {expected_paths}")


def test_last_uploaded_happy_path_contains_new_file(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: a newly uploaded file appears in the recent list."""
    file_path = f"{sandbox_path}/recent-happy-{uuid4().hex}.txt"
    upload_test_file(disk_client, file_path, b"newest file")

    items = wait_for_recent_paths(disk_client, {file_path})

    assert items[0]["path"] == file_path
    assert items[0]["type"] == "file"


def test_last_uploaded_orders_newer_file_before_older_file(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: files are returned in descending upload-time order."""
    older_path = f"{sandbox_path}/recent-older-{uuid4().hex}.txt"
    newer_path = f"{sandbox_path}/recent-newer-{uuid4().hex}.txt"
    upload_test_file(disk_client, older_path, b"older")
    time.sleep(1.1)
    upload_test_file(disk_client, newer_path, b"newer")

    items = wait_for_recent_paths(disk_client, {older_path, newer_path})
    listed_paths = [item["path"] for item in items]

    assert listed_paths.index(newer_path) < listed_paths.index(older_path)


def test_last_uploaded_fields_and_limit_shape_response(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: fields and limit constrain the response."""
    file_path = f"{sandbox_path}/recent-fields-{uuid4().hex}.txt"
    upload_test_file(disk_client, file_path, b"fields")
    wait_for_recent_paths(disk_client, {file_path})

    response = disk_client.list_last_uploaded(
        fields="limit,items.name,items.path",
        limit=1,
    )
    payload = response.json()

    assert response.status_code == requests.codes.ok
    assert set(payload) == {"limit", "items"}
    assert payload["limit"] == 1
    assert len(payload["items"]) == 1
    assert set(payload["items"][0]) == {"name", "path"}


def test_last_uploaded_media_type_filters_images(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: media_type=image includes a newly uploaded image."""
    file_path = f"{sandbox_path}/recent-image-{uuid4().hex}.png"
    metadata = upload_test_file(disk_client, file_path, ONE_PIXEL_PNG)
    assert metadata["media_type"] == "image"

    items = wait_for_recent_paths(
        disk_client,
        {file_path},
        media_type="image",
    )

    assert all(item["media_type"] == "image" for item in items)


def test_last_uploaded_supports_unicode_filename(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: Unicode filename is returned without corruption."""
    file_path = f"{sandbox_path}/новый файл-{uuid4().hex}.txt"
    upload_test_file(disk_client, file_path, "данные".encode())

    items = wait_for_recent_paths(disk_client, {file_path})
    item = next(item for item in items if item["path"] == file_path)

    assert item["name"] == file_path.rsplit("/", maxsplit=1)[1]


def test_last_uploaded_rejects_non_numeric_limit(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: limit must be numeric."""
    response = disk_client.list_last_uploaded(
        limit="not-a-number",
        expected_statuses={400},
    )

    assert_error_response(response, requests.codes.bad_request)


def test_last_uploaded_rejects_unknown_media_type(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: media_type must use a supported enum value."""
    response = disk_client.list_last_uploaded(
        media_type="definitely-invalid",
        expected_statuses={400},
    )

    assert_error_response(response, requests.codes.bad_request)


def test_last_uploaded_with_invalid_token_returns_401(
    unauthorized_disk_client: YandexDiskClient,
) -> None:
    """Negative: invalid OAuth credentials cannot list recent files."""
    response = unauthorized_disk_client.list_last_uploaded(
        expected_statuses={401},
    )

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"
