"""Positive, negative and edge cases for GET /v1/disk/resources/public."""

from __future__ import annotations

import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import pytest
import requests

from yandex_disk_api import YandexDiskClient

from .conftest import assert_error_response, unique_child, upload_test_file

pytestmark = pytest.mark.integration


def collect_public_resources(
    client: YandexDiskClient,
    *,
    resource_type: str | None = None,
    page_size: int = 1000,
    max_pages: int = 10,
) -> list[dict[str, object]]:
    """Collect bounded pages without assuming the public list is empty."""
    items: list[dict[str, object]] = []
    offset = 0
    for _ in range(max_pages):
        page = client.list_public_resources(
            limit=page_size,
            offset=offset,
            resource_type=resource_type,
        ).json()["items"]
        items.extend(page)
        if len(page) < page_size:
            return items
        offset += len(page)

    pytest.fail(f"Public listing exceeded {max_pages * page_size} resources")


def wait_for_public_paths(
    client: YandexDiskClient,
    expected_paths: set[str],
    *,
    present: bool = True,
    resource_type: str | None = None,
    timeout: float = 20.0,
) -> list[dict[str, object]]:
    """Poll the global public index until test paths appear or disappear."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        items = collect_public_resources(client, resource_type=resource_type)
        listed_paths = {str(item["path"]) for item in items}
        matches = expected_paths <= listed_paths
        if matches is present:
            return items
        time.sleep(0.25)

    state = "appear in" if present else "disappear from"
    pytest.fail(f"Paths did not {state} public list: {expected_paths}")


@contextmanager
def temporarily_published(
    client: YandexDiskClient,
    paths: Sequence[str],
) -> Iterator[None]:
    """Publish only test resources and always remove their public links."""
    published: list[str] = []
    try:
        for path in paths:
            response = client.publish_resource(path)
            assert response.status_code == requests.codes.ok
            published.append(path)
        yield
    finally:
        for path in reversed(published):
            client.unpublish_resource(path, expected_statuses={200, 404})


def test_public_resources_happy_path_lists_published_folder(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: a published folder appears with a public URL."""
    folder_path = unique_child(sandbox_path, "public-happy")
    disk_client.create_folder(folder_path)

    with temporarily_published(disk_client, [folder_path]):
        items = wait_for_public_paths(disk_client, {folder_path})
        item = next(item for item in items if item["path"] == folder_path)

        assert item["type"] == "dir"
        assert str(item["public_url"]).startswith("https://")
        assert item["public_key"]


def test_public_resources_type_filter_separates_files_and_folders(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: type=file and type=dir return matching resources."""
    folder_path = unique_child(sandbox_path, "public-dir")
    file_path = f"{unique_child(sandbox_path, 'public-file')}.txt"
    disk_client.create_folder(folder_path)
    upload_test_file(disk_client, file_path, b"public file")

    with temporarily_published(disk_client, [folder_path, file_path]):
        files = wait_for_public_paths(
            disk_client,
            {file_path},
            resource_type="file",
        )
        folders = wait_for_public_paths(
            disk_client,
            {folder_path},
            resource_type="dir",
        )

        assert all(item["type"] == "file" for item in files)
        assert all(item["type"] == "dir" for item in folders)


def test_public_resources_pagination_returns_disjoint_pages(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive boundary: limit and offset split the public list."""
    paths = [unique_child(sandbox_path, f"public-page-{index}") for index in range(4)]
    for path in paths:
        disk_client.create_folder(path)

    with temporarily_published(disk_client, paths):
        wait_for_public_paths(disk_client, set(paths))
        first = disk_client.list_public_resources(limit=2, offset=0).json()
        second = disk_client.list_public_resources(limit=2, offset=2).json()
        first_paths = {item["path"] for item in first["items"]}
        second_paths = {item["path"] for item in second["items"]}

        assert first["limit"] == second["limit"] == 2
        assert first["offset"] == 0
        assert second["offset"] == 2
        assert len(first["items"]) == len(second["items"]) == 2
        assert first_paths.isdisjoint(second_paths)


def test_public_resources_fields_limits_response(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: fields limits both envelope and item attributes."""
    folder_path = unique_child(sandbox_path, "public-fields")
    disk_client.create_folder(folder_path)

    with temporarily_published(disk_client, [folder_path]):
        wait_for_public_paths(disk_client, {folder_path})
        response = disk_client.list_public_resources(
            fields="limit,offset,items.name,items.path",
            limit=1,
            offset=0,
        )
        payload = response.json()

        assert set(payload) == {"limit", "offset", "items"}
        assert payload["limit"] == 1
        assert payload["offset"] == 0
        assert len(payload["items"]) == 1
        assert set(payload["items"][0]) == {"name", "path"}


def test_public_resources_supports_unicode_name(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: Unicode resource names are returned intact."""
    folder_path = unique_child(sandbox_path, "папка публикация")
    disk_client.create_folder(folder_path)

    with temporarily_published(disk_client, [folder_path]):
        items = wait_for_public_paths(disk_client, {folder_path})
        item = next(item for item in items if item["path"] == folder_path)

        assert item["name"] == folder_path.rsplit("/", maxsplit=1)[1]


def test_public_resources_large_offset_returns_empty_items(
    disk_client: YandexDiskClient,
) -> None:
    """Edge case: a very large offset returns an empty page."""
    response = disk_client.list_public_resources(limit=1, offset=1_000_000)

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
def test_public_resources_rejects_non_numeric_pagination(
    disk_client: YandexDiskClient,
    parameter: str,
    value: str,
) -> None:
    """Negative: pagination parameters must be numeric."""
    kwargs = {parameter: value, "expected_statuses": {400}}

    response = disk_client.list_public_resources(**kwargs)

    assert_error_response(response, requests.codes.bad_request)


def test_public_resources_rejects_unknown_type(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: type must be file or dir."""
    response = disk_client.list_public_resources(
        resource_type="definitely-invalid",
        expected_statuses={400},
    )

    assert_error_response(response, requests.codes.bad_request)


def test_public_resources_with_invalid_token_returns_401(
    unauthorized_disk_client: YandexDiskClient,
) -> None:
    """Negative: invalid OAuth credentials cannot list public resources."""
    response = unauthorized_disk_client.list_public_resources(
        expected_statuses={401},
    )

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"


def test_unpublished_resource_disappears_from_public_list(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: removing a public link updates the global public list."""
    folder_path = unique_child(sandbox_path, "public-remove")
    disk_client.create_folder(folder_path)
    disk_client.publish_resource(folder_path)
    wait_for_public_paths(disk_client, {folder_path})

    response = disk_client.unpublish_resource(folder_path)

    assert response.status_code == requests.codes.ok
    wait_for_public_paths(
        disk_client,
        {folder_path},
        present=False,
    )
