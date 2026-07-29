"""Positive, negative and edge cases for /v1/disk/trash/resources."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

import pytest
import requests

from yandex_disk_api import YandexDiskClient

from .conftest import (
    assert_error_response,
    unique_child,
    upload_test_file,
    wait_for_operation,
    wait_for_resource_state,
    wait_for_trash_resource_state,
    wait_for_trashed_origin,
)

pytestmark = pytest.mark.integration


def assert_successful_trash_deletion(response: requests.Response) -> None:
    """Assert documented synchronous or asynchronous Trash deletion."""
    assert response.status_code in {
        requests.codes.accepted,
        requests.codes.no_content,
    }
    if response.status_code == requests.codes.accepted:
        payload = response.json()
        assert payload["method"] == "GET"
        assert str(payload["href"]).startswith("https://")
    else:
        assert response.content == b""


def _move_to_trash(
    client: YandexDiskClient,
    origin_path: str,
) -> dict[str, object]:
    deletion = client.delete_resource(origin_path)
    assert_successful_trash_deletion(deletion)
    wait_for_operation(client, deletion, timeout=60.0)
    wait_for_resource_state(client, origin_path, exists=False, timeout=60.0)
    return wait_for_trashed_origin(client, origin_path, timeout=60.0)


def _cleanup_trashed_resource(
    client: YandexDiskClient,
    trash_path: str,
) -> None:
    current = client.get_trash_resource(
        trash_path,
        expected_statuses={200, 404},
    )
    if current.status_code == requests.codes.not_found:
        return
    deletion = client.delete_trash_resource(
        trash_path,
        force_async=True,
        expected_statuses={202, 204, 404, 423},
    )
    if deletion.status_code == requests.codes.not_found:
        return
    if deletion.status_code == requests.codes.locked:
        wait_for_trash_resource_state(
            client,
            trash_path,
            exists=False,
            timeout=60.0,
        )
        return
    wait_for_operation(client, deletion, timeout=60.0)
    wait_for_trash_resource_state(
        client,
        trash_path,
        exists=False,
        timeout=60.0,
    )


@contextmanager
def temporary_trashed_file(
    client: YandexDiskClient,
    sandbox_path: str,
    prefix: str,
    *,
    content: bytes = b"trash fixture",
) -> Iterator[dict[str, object]]:
    """Create one file, move it to Trash and always remove the Trash item."""
    origin_path = f"{unique_child(sandbox_path, prefix)}.txt"
    original = upload_test_file(client, origin_path, content)
    trashed = _move_to_trash(client, origin_path)
    trash_path = str(trashed["path"])
    try:
        yield {
            "origin_path": origin_path,
            "original": original,
            "trashed": trashed,
            "trash_path": trash_path,
        }
    finally:
        _cleanup_trashed_resource(client, trash_path)


@pytest.fixture(scope="module")
def trashed_unicode_file(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> Iterator[dict[str, object]]:
    """One immutable Unicode file shared by GET scenarios."""
    with temporary_trashed_file(
        disk_client,
        sandbox_path,
        "корзина файл",
        content="содержимое".encode(),
    ) as resource:
        yield resource


@pytest.fixture(scope="module")
def trashed_folder(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> Iterator[dict[str, object]]:
    """One trashed folder with ordered children shared by GET scenarios."""
    origin_path = unique_child(sandbox_path, "trash-folder")
    disk_client.create_folder(origin_path)
    children = {}
    for name in ("c.txt", "a.txt", "b.txt"):
        children[name] = upload_test_file(
            disk_client,
            f"{origin_path}/{name}",
            name.encode(),
        )

    trashed = _move_to_trash(disk_client, origin_path)
    trash_path = str(trashed["path"])
    try:
        yield {
            "origin_path": origin_path,
            "children": children,
            "trashed": trashed,
            "trash_path": trash_path,
        }
    finally:
        _cleanup_trashed_resource(disk_client, trash_path)


def test_get_trash_root_happy_path_contains_deleted_resource(
    disk_client: YandexDiskClient,
    trashed_unicode_file: dict[str, object],
) -> None:
    """Happy Path: omitted path returns the Trash root and recent item."""
    response = disk_client.get_trash_resource(
        limit=100,
        sort="-deleted",
    )

    assert response.status_code == requests.codes.ok
    assert response.headers["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["type"] == "dir"
    assert payload["path"] == "trash:/"
    assert payload["_embedded"]["limit"] == 100
    assert any(
        item.get("origin_path") == trashed_unicode_file["origin_path"]
        for item in payload["_embedded"]["items"]
    )


def test_get_trashed_file_metadata_happy_path(
    disk_client: YandexDiskClient,
    trashed_unicode_file: dict[str, object],
) -> None:
    """Happy Path: direct path returns deleted file metadata."""
    response = disk_client.get_trash_resource(
        str(trashed_unicode_file["trash_path"]),
    )

    payload = response.json()
    original = trashed_unicode_file["original"]
    assert isinstance(original, dict)
    assert payload["type"] == "file"
    assert payload["path"] == trashed_unicode_file["trash_path"]
    assert payload["origin_path"] == trashed_unicode_file["origin_path"]
    assert payload["md5"] == original["md5"]
    assert payload["size"] == original["size"]
    assert datetime.fromisoformat(payload["deleted"].replace("Z", "+00:00"))


def test_get_trashed_folder_returns_nested_items(
    disk_client: YandexDiskClient,
    trashed_folder: dict[str, object],
) -> None:
    """Positive: a trashed folder exposes its nested resources."""
    payload = disk_client.get_trash_resource(
        str(trashed_folder["trash_path"]),
        limit=10,
    ).json()

    assert payload["type"] == "dir"
    assert payload["origin_path"] == trashed_folder["origin_path"]
    assert {item["name"] for item in payload["_embedded"]["items"]} == {
        "a.txt",
        "b.txt",
        "c.txt",
    }


def test_get_trash_resource_fields_limits_response(
    disk_client: YandexDiskClient,
    trashed_unicode_file: dict[str, object],
) -> None:
    """Positive: fields limits metadata to requested attributes."""
    response = disk_client.get_trash_resource(
        str(trashed_unicode_file["trash_path"]),
        fields="path,name,origin_path,deleted",
    )

    assert set(response.json()) == {
        "path",
        "name",
        "origin_path",
        "deleted",
    }


def test_get_trash_folder_supports_pagination_and_sort(
    disk_client: YandexDiskClient,
    trashed_folder: dict[str, object],
) -> None:
    """Positive: limit, offset and sort page through nested resources."""
    trash_path = str(trashed_folder["trash_path"])
    first = disk_client.get_trash_resource(
        trash_path,
        limit=1,
        offset=0,
        sort="created",
    ).json()["_embedded"]
    second = disk_client.get_trash_resource(
        trash_path,
        limit=1,
        offset=1,
        sort="created",
    ).json()["_embedded"]

    assert first["limit"] == second["limit"] == 1
    assert first["offset"] == 0
    assert second["offset"] == 1
    assert len(first["items"]) == len(second["items"]) == 1
    assert first["items"][0]["path"] != second["items"][0]["path"]
    assert first["items"][0]["name"] in trashed_folder["children"]
    assert second["items"][0]["name"] in trashed_folder["children"]
    assert first["items"][0]["created"] <= second["items"][0]["created"]


def test_get_trash_folder_large_offset_returns_empty_items(
    disk_client: YandexDiskClient,
    trashed_folder: dict[str, object],
) -> None:
    """Edge: an offset beyond the folder size returns an empty page."""
    embedded = disk_client.get_trash_resource(
        str(trashed_folder["trash_path"]),
        limit=10,
        offset=1_000_000,
    ).json()["_embedded"]

    assert embedded["offset"] == 1_000_000
    assert embedded["items"] == []


def test_get_trash_resource_preserves_unicode_name_and_origin(
    disk_client: YandexDiskClient,
    trashed_unicode_file: dict[str, object],
) -> None:
    """Edge: Unicode and spaces survive moving a file to Trash."""
    payload = disk_client.get_trash_resource(
        str(trashed_unicode_file["trash_path"]),
    ).json()

    assert payload["name"].startswith("корзина файл-")
    assert payload["origin_path"] == trashed_unicode_file["origin_path"]


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("limit", "not-a-number"),
        ("offset", "not-a-number"),
    ],
)
def test_get_trash_resource_rejects_non_numeric_pagination(
    disk_client: YandexDiskClient,
    parameter: str,
    value: str,
) -> None:
    """Negative: limit and offset must be numeric."""
    kwargs = {parameter: value}
    response = disk_client.get_trash_resource(
        "trash:/",
        expected_statuses={400},
        **kwargs,
    )

    assert_error_response(response, requests.codes.bad_request)


def test_get_trash_resource_rejects_unsupported_sort(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: Trash sorting supports dates but not resource names."""
    response = disk_client.get_trash_resource(
        "trash:/",
        sort="name",
        expected_statuses={400},
    )

    payload = assert_error_response(response, requests.codes.bad_request)
    assert payload["error"] == "FieldValidationError"


def test_get_missing_trash_resource_returns_404(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: an unknown Trash path cannot be read."""
    response = disk_client.get_trash_resource(
        "trash:/definitely-missing-api-test-resource",
        expected_statuses={404},
    )

    payload = assert_error_response(response, requests.codes.not_found)
    assert payload["error"] == "DiskNotFoundError"


def test_get_trash_resource_with_invalid_token_returns_401(
    unauthorized_disk_client: YandexDiskClient,
) -> None:
    """Negative: Trash metadata requires valid OAuth credentials."""
    response = unauthorized_disk_client.get_trash_resource(
        expected_statuses={401},
    )

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"


def test_delete_trashed_file_happy_path(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: permanently remove one selected file from Trash."""
    with temporary_trashed_file(
        disk_client,
        sandbox_path,
        "empty-trash-file",
    ) as resource:
        trash_path = str(resource["trash_path"])
        response = disk_client.delete_trash_resource(trash_path)

        assert_successful_trash_deletion(response)
        wait_for_operation(disk_client, response, timeout=60.0)
        wait_for_trash_resource_state(
            disk_client,
            trash_path,
            exists=False,
            timeout=60.0,
        )


def test_delete_trashed_folder_removes_nested_content(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: deleting a Trash folder removes its nested files."""
    origin_path = unique_child(sandbox_path, "empty-trash-folder")
    disk_client.create_folder(origin_path)
    upload_test_file(disk_client, f"{origin_path}/nested.txt", b"nested")
    trashed = _move_to_trash(disk_client, origin_path)
    trash_path = str(trashed["path"])

    try:
        response = disk_client.delete_trash_resource(trash_path)
        assert_successful_trash_deletion(response)
        wait_for_operation(disk_client, response, timeout=60.0)
        wait_for_trash_resource_state(
            disk_client,
            trash_path,
            exists=False,
            timeout=60.0,
        )
    finally:
        _cleanup_trashed_resource(disk_client, trash_path)


def test_delete_trash_resource_force_async_returns_202(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: force_async=true returns an operation Link."""
    with temporary_trashed_file(
        disk_client,
        sandbox_path,
        "empty-trash-async",
    ) as resource:
        trash_path = str(resource["trash_path"])
        response = disk_client.delete_trash_resource(
            trash_path,
            force_async=True,
        )

        assert response.status_code == requests.codes.accepted
        assert_successful_trash_deletion(response)
        wait_for_operation(disk_client, response, timeout=60.0)
        wait_for_trash_resource_state(
            disk_client,
            trash_path,
            exists=False,
            timeout=60.0,
        )


def test_delete_trash_resource_fields_keeps_required_async_link_shape(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge: templated remains in Link even when fields omits it."""
    with temporary_trashed_file(
        disk_client,
        sandbox_path,
        "empty-trash-fields",
    ) as resource:
        trash_path = str(resource["trash_path"])
        response = disk_client.delete_trash_resource(
            trash_path,
            fields="href,method",
            force_async=True,
        )

        assert response.status_code == requests.codes.accepted
        wait_for_operation(disk_client, response, timeout=60.0)
        wait_for_trash_resource_state(
            disk_client,
            trash_path,
            exists=False,
            timeout=60.0,
        )
        assert set(response.json()) == {"href", "method", "templated"}


def test_delete_trash_resource_supports_unicode_path(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge: a generated Unicode Trash path is encoded correctly."""
    with temporary_trashed_file(
        disk_client,
        sandbox_path,
        "удалить из корзины",
    ) as resource:
        trash_path = str(resource["trash_path"])
        response = disk_client.delete_trash_resource(trash_path)

        assert_successful_trash_deletion(response)
        wait_for_operation(disk_client, response, timeout=60.0)
        wait_for_trash_resource_state(
            disk_client,
            trash_path,
            exists=False,
            timeout=60.0,
        )


def test_delete_missing_trash_resource_returns_404(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: a missing Trash item cannot be deleted."""
    response = disk_client.delete_trash_resource(
        "trash:/definitely-missing-delete-api-test-resource",
        expected_statuses={404},
    )

    payload = assert_error_response(response, requests.codes.not_found)
    assert payload["error"] == "DiskNotFoundError"


def test_delete_trash_resource_rejects_invalid_force_async(
    disk_client: YandexDiskClient,
    trashed_unicode_file: dict[str, object],
) -> None:
    """Negative: force_async must be a boolean."""
    trash_path = str(trashed_unicode_file["trash_path"])
    response = disk_client.delete_trash_resource(
        trash_path,
        force_async="not-a-boolean",
        expected_statuses={400},
    )

    assert_error_response(response, requests.codes.bad_request)
    assert disk_client.get_trash_resource(trash_path).status_code == requests.codes.ok


def test_delete_trash_resource_with_invalid_token_preserves_item(
    disk_client: YandexDiskClient,
    unauthorized_disk_client: YandexDiskClient,
    trashed_unicode_file: dict[str, object],
) -> None:
    """Negative: invalid OAuth credentials cannot empty a Trash item."""
    trash_path = str(trashed_unicode_file["trash_path"])
    response = unauthorized_disk_client.delete_trash_resource(
        trash_path,
        expected_statuses={401},
    )

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"
    assert disk_client.get_trash_resource(trash_path).status_code == requests.codes.ok


def test_delete_same_trash_resource_twice_returns_404(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge: a second DELETE reports that the Trash item is gone."""
    with temporary_trashed_file(
        disk_client,
        sandbox_path,
        "empty-trash-twice",
    ) as resource:
        trash_path = str(resource["trash_path"])
        first = disk_client.delete_trash_resource(trash_path)
        assert_successful_trash_deletion(first)
        wait_for_operation(disk_client, first, timeout=60.0)
        wait_for_trash_resource_state(
            disk_client,
            trash_path,
            exists=False,
            timeout=60.0,
        )

        second = disk_client.delete_trash_resource(
            trash_path,
            expected_statuses={404},
        )
        assert_error_response(second, requests.codes.not_found)
