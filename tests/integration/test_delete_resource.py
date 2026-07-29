"""Positive, negative and edge cases for DELETE /v1/disk/resources."""

from __future__ import annotations

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


def assert_successful_deletion(response: requests.Response) -> None:
    """Assert either documented synchronous or asynchronous success."""
    assert response.status_code in {
        requests.codes.accepted,
        requests.codes.no_content,
    }
    if response.status_code == requests.codes.accepted:
        payload = response.json()
        assert payload["method"] == "GET"
        assert payload["href"].startswith("https://")
    else:
        assert response.content == b""


def test_delete_resource_happy_path_permanently(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: permanently delete one existing empty directory."""
    folder_path = unique_child(sandbox_path, "delete-happy")
    disk_client.create_folder(folder_path)

    response = disk_client.delete_resource(folder_path, permanently=True)
    assert_successful_deletion(response)
    wait_for_operation(disk_client, response)
    wait_for_resource_state(disk_client, folder_path, exists=False)


def test_delete_resource_default_moves_folder_to_trash(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: omitted permanently uses the documented Trash default."""
    folder_path = unique_child(sandbox_path, "delete-to-trash")
    folder_name = folder_path.rsplit("/", maxsplit=1)[1]
    disk_client.create_folder(folder_path)

    response = disk_client.delete_resource(folder_path)
    assert_successful_deletion(response)
    wait_for_operation(disk_client, response)
    wait_for_resource_state(disk_client, folder_path, exists=False)

    trashed = wait_for_trashed_origin(disk_client, folder_path)
    trash_path = str(trashed["path"])
    try:
        assert trashed["name"] == folder_name
        assert trashed["origin_path"] == folder_path
        assert trash_path.startswith(f"trash:/{folder_name}_")
    finally:
        cleanup = disk_client.delete_trash_resource(trash_path)
        wait_for_operation(disk_client, cleanup)
        wait_for_trash_resource_state(disk_client, trash_path, exists=False)


def test_delete_resource_force_async_returns_202_for_non_empty_folder(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: force_async guarantees an operation link."""
    folder_path = unique_child(sandbox_path, "delete-async")
    disk_client.create_folder(folder_path)
    disk_client.create_folder(f"{folder_path}/nested")

    response = disk_client.delete_resource(
        folder_path,
        force_async=True,
        permanently=True,
    )

    assert response.status_code == requests.codes.accepted
    assert_successful_deletion(response)
    wait_for_operation(disk_client, response)
    wait_for_resource_state(disk_client, folder_path, exists=False)


def test_delete_file_with_matching_md5(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive boundary: a file is deleted when its md5 matches."""
    file_path = unique_child(sandbox_path, "matching-md5.txt")
    metadata = upload_test_file(disk_client, file_path, b"known test content")

    response = disk_client.delete_resource(
        file_path,
        md5=str(metadata["md5"]),
        permanently=True,
    )

    assert_successful_deletion(response)
    wait_for_operation(disk_client, response)
    wait_for_resource_state(disk_client, file_path, exists=False)


def test_delete_folder_with_md5_returns_400_and_preserves_resource(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: md5 validation is only supported for files."""
    folder_path = unique_child(sandbox_path, "folder-md5")
    disk_client.create_folder(folder_path)

    response = disk_client.delete_resource(
        folder_path,
        md5="0" * 32,
        permanently=True,
        expected_statuses={400},
    )

    assert_error_response(response, requests.codes.bad_request)
    assert disk_client.get_resource(folder_path).status_code == requests.codes.ok


def test_delete_file_with_wrong_md5_returns_409_and_preserves_resource(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: a mismatched md5 causes a conflict without deleting data."""
    file_path = unique_child(sandbox_path, "wrong-md5.txt")
    metadata = upload_test_file(disk_client, file_path, b"another known value")
    wrong_md5 = "0" * 32
    assert metadata["md5"] != wrong_md5

    response = disk_client.delete_resource(
        file_path,
        md5=wrong_md5,
        permanently=True,
        expected_statuses={409},
    )

    assert_error_response(response, requests.codes.conflict)
    assert disk_client.get_resource(file_path).status_code == requests.codes.ok


def test_delete_resource_without_required_path_returns_400(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: omitting the required path query parameter is rejected."""
    response = disk_client.delete_resource(
        None,
        permanently=True,
        expected_statuses={400},
    )

    payload = assert_error_response(response, requests.codes.bad_request)
    assert payload["error"] == "FieldValidationError"


def test_delete_missing_resource_returns_404(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: deleting a path that does not exist returns not found."""
    missing_path = unique_child(sandbox_path, "missing-delete")

    response = disk_client.delete_resource(
        missing_path,
        permanently=True,
        expected_statuses={404},
    )

    payload = assert_error_response(response, requests.codes.not_found)
    assert payload["error"] == "DiskNotFoundError"


def test_delete_resource_with_invalid_token_returns_401_and_preserves_resource(
    disk_client: YandexDiskClient,
    unauthorized_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: invalid OAuth credentials cannot delete a resource."""
    folder_path = unique_child(sandbox_path, "unauthorized-delete")
    disk_client.create_folder(folder_path)

    response = unauthorized_disk_client.delete_resource(
        folder_path,
        permanently=True,
        expected_statuses={401},
    )

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"
    assert disk_client.get_resource(folder_path).status_code == requests.codes.ok


def test_delete_same_resource_twice_returns_404_on_second_call(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: DELETE is not idempotent at the response-code level."""
    folder_path = unique_child(sandbox_path, "delete-twice")
    disk_client.create_folder(folder_path)

    first = disk_client.delete_resource(folder_path, permanently=True)
    assert_successful_deletion(first)
    wait_for_operation(disk_client, first)
    wait_for_resource_state(disk_client, folder_path, exists=False)

    second = disk_client.delete_resource(
        folder_path,
        permanently=True,
        expected_statuses={404},
    )
    assert_error_response(second, requests.codes.not_found)
