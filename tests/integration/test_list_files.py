"""Positive, negative and edge cases for GET /v1/disk/resources/files."""

from __future__ import annotations

import time
from base64 import b64decode
from uuid import uuid4

import pytest
import requests

from yandex_disk_api import YandexDiskClient

from .conftest import assert_error_response, unique_child, upload_test_file

pytestmark = pytest.mark.integration

ONE_PIXEL_PNG = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAusB9Wl2nAAAAABJRU5ErkJggg=="
)


def collect_flat_files(
    client: YandexDiskClient,
    *,
    media_type: str | None = None,
    sort: str | None = None,
    page_size: int = 1000,
    max_pages: int = 10,
) -> list[dict[str, object]]:
    """Collect bounded pages without assuming the test account is empty."""
    items: list[dict[str, object]] = []
    offset = 0
    for _ in range(max_pages):
        page = client.list_files(
            limit=page_size,
            media_type=media_type,
            offset=offset,
            sort=sort,
        ).json()["items"]
        items.extend(page)
        if len(page) < page_size:
            return items
        offset += len(page)

    pytest.fail(f"Flat file listing exceeded {max_pages * page_size} resources")


def wait_for_flat_paths(
    client: YandexDiskClient,
    expected_paths: set[str],
    *,
    media_type: str | None = None,
    timeout: float = 20.0,
) -> list[dict[str, object]]:
    """Poll the global file index until all unique test paths appear."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        items = collect_flat_files(client, media_type=media_type)
        listed_paths = {str(item["path"]) for item in items}
        if expected_paths <= listed_paths:
            return items
        time.sleep(0.25)

    pytest.fail(f"Paths did not appear in flat file list: {expected_paths}")


def wait_for_media_index_path(
    client: YandexDiskClient,
    path: str,
    *,
    media_type: str,
    timeout: float,
) -> list[dict[str, object]]:
    """Poll the slower media index until one exact test path is returned."""
    deadline = time.monotonic() + timeout
    last_item_count = 0
    while time.monotonic() < deadline:
        items = collect_flat_files(client, media_type=media_type)
        last_item_count = len(items)
        if any(item.get("path") == path for item in items):
            return items

        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(2.0, remaining))

    pytest.fail(
        f"Path {path!r} did not appear in media_type={media_type!r} index "
        f"in {timeout} seconds; last item count: {last_item_count}"
    )


def test_list_files_happy_path_returns_files_but_not_folders(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: the flat endpoint lists files from nested directories."""
    folder_path = unique_child(sandbox_path, "flat-folder")
    file_path = f"{folder_path}/flat-file-{uuid4().hex}.txt"
    disk_client.create_folder(folder_path)
    upload_test_file(disk_client, file_path, b"flat list fixture")

    items = wait_for_flat_paths(disk_client, {file_path})
    listed_paths = {item["path"] for item in items}

    assert file_path in listed_paths
    assert folder_path not in listed_paths
    assert all(item["type"] == "file" for item in items)


def test_list_files_default_order_is_by_name(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: uniquely named test files appear in ascending name order."""
    batch = uuid4().hex
    paths = [
        f"{sandbox_path}/000-flat-{batch}-{suffix}.txt" for suffix in ("a", "b", "c")
    ]
    for path in paths:
        upload_test_file(disk_client, path, path.encode())

    items = wait_for_flat_paths(disk_client, set(paths))
    listed_test_paths = [item["path"] for item in items if item["path"] in paths]

    assert listed_test_paths == paths


def test_list_files_pagination_returns_disjoint_pages(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive boundary: limit and offset split one stable ordering."""
    paths = []
    for index in range(4):
        path = f"{sandbox_path}/pagination-{uuid4().hex}-{index}.txt"
        upload_test_file(disk_client, path, str(index).encode())
        paths.append(path)
    wait_for_flat_paths(disk_client, set(paths))

    first = disk_client.list_files(limit=2, offset=0, sort="name").json()
    second = disk_client.list_files(limit=2, offset=2, sort="name").json()
    first_paths = {item["path"] for item in first["items"]}
    second_paths = {item["path"] for item in second["items"]}

    assert first["limit"] == 2
    assert first["offset"] == 0
    assert second["limit"] == 2
    assert second["offset"] == 2
    assert len(first["items"]) == len(second["items"]) == 2
    assert first_paths.isdisjoint(second_paths)


def test_list_files_fields_limits_response(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: fields limits both envelope and item attributes."""
    file_path = f"{sandbox_path}/flat-fields-{uuid4().hex}.txt"
    upload_test_file(disk_client, file_path, b"fields")
    wait_for_flat_paths(disk_client, {file_path})

    response = disk_client.list_files(
        fields="limit,offset,items.name,items.path",
        limit=1,
        offset=0,
    )
    payload = response.json()

    assert response.status_code == requests.codes.ok
    assert set(payload) == {"limit", "offset", "items"}
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert len(payload["items"]) == 1
    assert set(payload["items"][0]) == {"name", "path"}


def test_list_files_media_type_filters_images(
    disk_client: YandexDiskClient,
    sandbox_path: str,
    media_index_timeout: float,
) -> None:
    """Positive: media_type=image returns the uploaded image."""
    file_path = f"{sandbox_path}/000-flat-image-{uuid4().hex}.png"
    metadata = upload_test_file(disk_client, file_path, ONE_PIXEL_PNG)
    assert metadata["media_type"] == "image"

    wait_for_flat_paths(disk_client, {file_path})
    items = wait_for_media_index_path(
        disk_client,
        file_path,
        media_type="image",
        timeout=media_index_timeout,
    )

    assert items
    assert file_path in {item["path"] for item in items}
    assert all(item["media_type"] == "image" for item in items)


def test_list_files_offset_beyond_end_returns_empty_items(
    disk_client: YandexDiskClient,
) -> None:
    """Edge case: a very large offset is valid and returns an empty page."""
    response = disk_client.list_files(limit=1, offset=1_000_000)

    assert response.status_code == requests.codes.ok
    assert response.json()["offset"] == 1_000_000
    assert response.json()["items"] == []


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("limit", "not-a-number"),
        ("offset", "not-a-number"),
    ],
)
def test_list_files_rejects_non_numeric_pagination(
    disk_client: YandexDiskClient,
    parameter: str,
    value: str,
) -> None:
    """Negative: pagination parameters must be numeric."""
    kwargs = {parameter: value, "expected_statuses": {400}}

    response = disk_client.list_files(**kwargs)

    assert_error_response(response, requests.codes.bad_request)


def test_list_files_rejects_unknown_media_type(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: media_type must use a supported enum value."""
    response = disk_client.list_files(
        media_type="definitely-invalid",
        expected_statuses={400},
    )

    assert_error_response(response, requests.codes.bad_request)


def test_list_files_with_invalid_token_returns_401(
    unauthorized_disk_client: YandexDiskClient,
) -> None:
    """Negative: invalid OAuth credentials cannot list private files."""
    response = unauthorized_disk_client.list_files(expected_statuses={401})

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"
