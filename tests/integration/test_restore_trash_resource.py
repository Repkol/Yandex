"""Cases for PUT /v1/disk/trash/resources/restore."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

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


def assert_restore_link(
    response: requests.Response,
    *,
    expected_fields: set[str] | None = None,
) -> dict[str, object]:
    """Assert documented synchronous or asynchronous restore Link."""
    assert response.status_code in {
        requests.codes.created,
        requests.codes.accepted,
    }
    assert response.headers["Content-Type"].startswith("application/json")
    payload = response.json()
    if expected_fields is not None:
        assert set(payload) == expected_fields
    assert payload["method"] == "GET"
    assert str(payload["href"]).startswith("https://")
    return payload


def _move_to_trash(
    client: YandexDiskClient,
    origin_path: str,
) -> dict[str, object]:
    deletion = client.delete_resource(origin_path)
    assert deletion.status_code in {
        requests.codes.accepted,
        requests.codes.no_content,
    }
    wait_for_operation(client, deletion, timeout=60.0)
    wait_for_resource_state(client, origin_path, exists=False, timeout=60.0)
    return wait_for_trashed_origin(client, origin_path, timeout=60.0)


def _trashed_items_for_origin(
    client: YandexDiskClient,
    origin_path: str,
) -> list[dict[str, object]]:
    matches = []
    offset = 0
    while True:
        embedded = client.get_trash_resource(
            "trash:/",
            limit=1000,
            offset=offset,
        ).json()["_embedded"]
        matches.extend(
            item for item in embedded["items"] if item.get("origin_path") == origin_path
        )
        offset += len(embedded["items"])
        if offset >= embedded["total"] or not embedded["items"]:
            return matches


def _cleanup_trashed_origin(
    client: YandexDiskClient,
    origin_path: str,
) -> None:
    """Permanently remove only Trash entries created for one unique origin."""
    for item in _trashed_items_for_origin(client, origin_path):
        trash_path = str(item["path"])
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            deletion = client.delete_trash_resource(
                trash_path,
                force_async=True,
                expected_statuses={202, 204, 404, 423},
            )
            if deletion.status_code == requests.codes.locked:
                time.sleep(0.5)
                continue
            if deletion.status_code != requests.codes.not_found:
                wait_for_operation(client, deletion, timeout=60.0)
            wait_for_trash_resource_state(
                client,
                trash_path,
                exists=False,
                timeout=60.0,
            )
            break
        else:
            pytest.fail(f"Could not clean test Trash resource {trash_path!r}")


@contextmanager
def temporary_trashed_file(
    client: YandexDiskClient,
    sandbox_path: str,
    prefix: str,
    *,
    content: bytes = b"restore fixture",
) -> Iterator[dict[str, object]]:
    """Create one file in Trash and clean any Trash entries for its origin."""
    origin_path = f"{unique_child(sandbox_path, prefix)}.txt"
    original = upload_test_file(client, origin_path, content)
    trashed = _move_to_trash(client, origin_path)
    try:
        yield {
            "origin_path": origin_path,
            "original": original,
            "trash_path": str(trashed["path"]),
            "trashed": trashed,
        }
    finally:
        _cleanup_trashed_origin(client, origin_path)


@pytest.fixture(scope="module")
def shared_trashed_file(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> Iterator[dict[str, object]]:
    """One unchanged Trash item shared by non-mutating negative cases."""
    with temporary_trashed_file(
        disk_client,
        sandbox_path,
        "restore-negative-shared",
    ) as resource:
        yield resource


def test_restore_file_happy_path(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: restore a file to its original path."""
    with temporary_trashed_file(
        disk_client,
        sandbox_path,
        "restore-happy",
        content=b"exact restored content",
    ) as resource:
        origin_path = str(resource["origin_path"])
        trash_path = str(resource["trash_path"])
        response = disk_client.restore_trash_resource(trash_path)

        assert_restore_link(response)
        wait_for_operation(disk_client, response, timeout=60.0)
        wait_for_resource_state(
            disk_client,
            origin_path,
            exists=True,
            timeout=60.0,
        )
        wait_for_trash_resource_state(
            disk_client,
            trash_path,
            exists=False,
            timeout=60.0,
        )
        original = resource["original"]
        assert isinstance(original, dict)
        restored = disk_client.get_resource(origin_path).json()
        assert restored["md5"] == original["md5"]
        assert restored["size"] == original["size"]


def test_restore_folder_preserves_nested_content(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: restoring a folder recursively restores its children."""
    origin_path = unique_child(sandbox_path, "restore-folder")
    nested_path = f"{origin_path}/nested/file.txt"
    disk_client.create_folder(origin_path)
    disk_client.create_folder(f"{origin_path}/nested")
    nested = upload_test_file(disk_client, nested_path, b"nested restore")
    trashed = _move_to_trash(disk_client, origin_path)
    trash_path = str(trashed["path"])

    try:
        response = disk_client.restore_trash_resource(trash_path)
        assert_restore_link(response)
        wait_for_operation(disk_client, response, timeout=60.0)
        wait_for_resource_state(
            disk_client,
            nested_path,
            exists=True,
            timeout=60.0,
        )
        assert disk_client.get_resource(nested_path).json()["md5"] == nested["md5"]
    finally:
        _cleanup_trashed_origin(disk_client, origin_path)


def test_restore_resource_with_new_name(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: name restores a resource under a different filename."""
    with temporary_trashed_file(
        disk_client,
        sandbox_path,
        "restore-rename-source",
    ) as resource:
        origin_path = str(resource["origin_path"])
        parent = origin_path.rsplit("/", maxsplit=1)[0]
        restored_path = f"{parent}/restored-name.txt"
        response = disk_client.restore_trash_resource(
            str(resource["trash_path"]),
            name="restored-name.txt",
        )

        assert_restore_link(response)
        wait_for_operation(disk_client, response, timeout=60.0)
        wait_for_resource_state(
            disk_client,
            restored_path,
            exists=True,
            timeout=60.0,
        )
        assert disk_client.get_resource(restored_path).json()["name"] == (
            "restored-name.txt"
        )
        assert (
            disk_client.get_resource(
                origin_path,
                expected_statuses={404},
            ).status_code
            == requests.codes.not_found
        )


def test_restore_resource_force_async_returns_202(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: force_async=true returns and completes an operation."""
    with temporary_trashed_file(
        disk_client,
        sandbox_path,
        "restore-async",
    ) as resource:
        origin_path = str(resource["origin_path"])
        response = disk_client.restore_trash_resource(
            str(resource["trash_path"]),
            force_async=True,
        )

        assert response.status_code == requests.codes.accepted
        assert_restore_link(response)
        wait_for_operation(disk_client, response, timeout=60.0)
        wait_for_resource_state(
            disk_client,
            origin_path,
            exists=True,
            timeout=60.0,
        )


def test_restore_resource_fields_limits_link(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: fields limits the returned Link object."""
    with temporary_trashed_file(
        disk_client,
        sandbox_path,
        "restore-fields",
    ) as resource:
        response = disk_client.restore_trash_resource(
            str(resource["trash_path"]),
            fields="href,method",
        )

        assert_restore_link(
            response,
            expected_fields={"href", "method"},
        )
        wait_for_operation(disk_client, response, timeout=60.0)


def test_restore_resource_supports_unicode_name_and_path(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge: Unicode Trash path and restored name are encoded correctly."""
    with temporary_trashed_file(
        disk_client,
        sandbox_path,
        "восстановить файл",
        content="данные восстановления".encode(),
    ) as resource:
        origin_path = str(resource["origin_path"])
        parent = origin_path.rsplit("/", maxsplit=1)[0]
        restored_name = "возвращённый файл.txt"
        restored_path = f"{parent}/{restored_name}"
        response = disk_client.restore_trash_resource(
            str(resource["trash_path"]),
            name=restored_name,
        )

        assert_restore_link(response)
        wait_for_operation(disk_client, response, timeout=60.0)
        wait_for_resource_state(
            disk_client,
            restored_path,
            exists=True,
            timeout=60.0,
        )
        assert disk_client.get_resource(restored_path).json()["name"] == restored_name


def test_restore_with_overwrite_replaces_existing_file(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: overwrite=true replaces a resource at the original path."""
    with temporary_trashed_file(
        disk_client,
        sandbox_path,
        "restore-overwrite",
        content=b"original from trash",
    ) as resource:
        origin_path = str(resource["origin_path"])
        original = resource["original"]
        assert isinstance(original, dict)
        replacement = upload_test_file(
            disk_client,
            origin_path,
            b"temporary replacement",
        )
        assert replacement["md5"] != original["md5"]

        response = disk_client.restore_trash_resource(
            str(resource["trash_path"]),
            overwrite=True,
        )

        assert_restore_link(response)
        wait_for_operation(disk_client, response, timeout=60.0)
        restored = disk_client.get_resource(origin_path).json()
        assert restored["md5"] == original["md5"]


@pytest.mark.parametrize("overwrite", [None, False])
def test_restore_conflict_auto_renames_without_overwrite(
    disk_client: YandexDiskClient,
    sandbox_path: str,
    overwrite: bool | None,
) -> None:
    """Edge: overwrite omitted or false preserves both files by renaming."""
    with temporary_trashed_file(
        disk_client,
        sandbox_path,
        "restore-conflict",
        content=b"trashed original",
    ) as resource:
        origin_path = str(resource["origin_path"])
        trash_path = str(resource["trash_path"])
        parent, filename = origin_path.rsplit("/", maxsplit=1)
        stem, extension = filename.rsplit(".", maxsplit=1)
        renamed_path = f"{parent}/{stem} (1).{extension}"
        trashed_original = resource["original"]
        assert isinstance(trashed_original, dict)
        existing = upload_test_file(
            disk_client,
            origin_path,
            b"keep existing",
        )

        response = disk_client.restore_trash_resource(
            trash_path,
            overwrite=overwrite,
        )

        assert_restore_link(response)
        wait_for_operation(disk_client, response, timeout=60.0)
        wait_for_resource_state(
            disk_client,
            renamed_path,
            exists=True,
            timeout=60.0,
        )
        assert disk_client.get_resource(origin_path).json()["md5"] == existing["md5"]
        assert (
            disk_client.get_resource(renamed_path).json()["md5"]
            == (trashed_original["md5"])
        )
        assert (
            disk_client.get_trash_resource(
                trash_path,
                expected_statuses={404},
            ).status_code
            == requests.codes.not_found
        )


def test_restore_without_required_path_returns_400(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: path is a required query parameter."""
    response = disk_client.restore_trash_resource(
        None,
        expected_statuses={400},
    )

    payload = assert_error_response(response, requests.codes.bad_request)
    assert payload["error"] == "FieldValidationError"


def test_restore_empty_path_returns_400(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: an explicitly empty path is invalid."""
    response = disk_client.restore_trash_resource(
        "",
        expected_statuses={400},
    )

    assert_error_response(response, requests.codes.bad_request)


def test_restore_trash_root_is_rejected(
    disk_client: YandexDiskClient,
) -> None:
    """Negative edge: the Trash root itself is not restorable."""
    response = disk_client.restore_trash_resource(
        "trash:/",
        expected_statuses={400, 404},
    )

    assert response.status_code in {
        requests.codes.bad_request,
        requests.codes.not_found,
    }
    assert_error_response(response, response.status_code)


def test_restore_missing_trash_resource_returns_404(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: a missing Trash resource cannot be restored."""
    response = disk_client.restore_trash_resource(
        "trash:/definitely-missing-restore-api-test-resource",
        expected_statuses={404},
    )

    payload = assert_error_response(response, requests.codes.not_found)
    assert payload["error"] == "DiskNotFoundError"


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("force_async", "not-a-boolean"),
        ("overwrite", "not-a-boolean"),
    ],
)
def test_restore_rejects_invalid_boolean_parameters(
    disk_client: YandexDiskClient,
    shared_trashed_file: dict[str, object],
    parameter: str,
    value: str,
) -> None:
    """Negative: force_async and overwrite must be boolean values."""
    kwargs = {parameter: value}
    trash_path = str(shared_trashed_file["trash_path"])
    response = disk_client.restore_trash_resource(
        trash_path,
        expected_statuses={400},
        **kwargs,
    )

    assert_error_response(response, requests.codes.bad_request)
    assert disk_client.get_trash_resource(trash_path).status_code == requests.codes.ok


def test_restore_with_invalid_token_preserves_trash_resource(
    disk_client: YandexDiskClient,
    unauthorized_disk_client: YandexDiskClient,
    shared_trashed_file: dict[str, object],
) -> None:
    """Negative: invalid OAuth credentials cannot restore a resource."""
    trash_path = str(shared_trashed_file["trash_path"])
    response = unauthorized_disk_client.restore_trash_resource(
        trash_path,
        expected_statuses={401},
    )

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"
    assert disk_client.get_trash_resource(trash_path).status_code == requests.codes.ok


def test_restore_same_resource_twice_returns_404(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge: the Trash path becomes invalid after successful restoration."""
    with temporary_trashed_file(
        disk_client,
        sandbox_path,
        "restore-twice",
    ) as resource:
        trash_path = str(resource["trash_path"])
        first = disk_client.restore_trash_resource(trash_path)
        assert_restore_link(first)
        wait_for_operation(disk_client, first, timeout=60.0)
        wait_for_trash_resource_state(
            disk_client,
            trash_path,
            exists=False,
            timeout=60.0,
        )

        second = disk_client.restore_trash_resource(
            trash_path,
            expected_statuses={404},
        )
        assert_error_response(second, requests.codes.not_found)
