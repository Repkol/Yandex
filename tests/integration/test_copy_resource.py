"""Positive, negative and edge cases for POST /v1/disk/resources/copy."""

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
)

pytestmark = pytest.mark.integration


def assert_successful_copy(response: requests.Response) -> None:
    """Assert either documented synchronous or asynchronous copy success."""
    assert response.status_code in {
        requests.codes.created,
        requests.codes.accepted,
    }
    payload = response.json()
    assert payload["method"] == "GET"
    assert payload["href"].startswith("https://")


def test_copy_folder_happy_path(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: copy an existing folder to a free destination path."""
    source_path = unique_child(sandbox_path, "copy-source")
    destination_path = unique_child(sandbox_path, "copy-destination")
    disk_client.create_folder(source_path)

    response = disk_client.copy_resource(source_path, destination_path)
    assert_successful_copy(response)
    wait_for_operation(disk_client, response)
    wait_for_resource_state(disk_client, destination_path, exists=True)
    metadata = disk_client.get_resource(destination_path).json()

    assert metadata["path"] == destination_path
    assert metadata["type"] == "dir"


def test_copy_file_preserves_hash_and_size(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: a copied file has the same md5 and size as its source."""
    source_path = f"{unique_child(sandbox_path, 'copy-file-source')}.txt"
    destination_path = f"{unique_child(sandbox_path, 'copy-file-result')}.txt"
    source = upload_test_file(disk_client, source_path, b"copy this exact content")

    response = disk_client.copy_resource(source_path, destination_path)
    assert_successful_copy(response)
    wait_for_operation(disk_client, response)
    destination = disk_client.get_resource(destination_path).json()

    assert destination["type"] == "file"
    assert destination["md5"] == source["md5"]
    assert destination["size"] == source["size"]


def test_copy_folder_preserves_nested_content(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive boundary: copying a folder recursively copies its children."""
    source_path = unique_child(sandbox_path, "copy-tree")
    destination_path = unique_child(sandbox_path, "copy-tree-result")
    disk_client.create_folder(source_path)
    disk_client.create_folder(f"{source_path}/nested")

    response = disk_client.copy_resource(source_path, destination_path)
    assert_successful_copy(response)
    wait_for_operation(disk_client, response)
    wait_for_resource_state(
        disk_client,
        f"{destination_path}/nested",
        exists=True,
    )

    copied = disk_client.get_resource(destination_path).json()
    assert [item["name"] for item in copied["_embedded"]["items"]] == ["nested"]


def test_copy_resource_force_async_returns_202(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: force_async guarantees an operation link."""
    source_path = unique_child(sandbox_path, "copy-async")
    destination_path = unique_child(sandbox_path, "copy-async-result")
    disk_client.create_folder(source_path)

    response = disk_client.copy_resource(
        source_path,
        destination_path,
        force_async=True,
    )

    assert response.status_code == requests.codes.accepted
    assert_successful_copy(response)
    wait_for_operation(disk_client, response)
    wait_for_resource_state(disk_client, destination_path, exists=True)


def test_copy_resource_fields_limits_link_response(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: fields limits attributes in the returned Link object."""
    source_path = unique_child(sandbox_path, "copy-fields")
    destination_path = unique_child(sandbox_path, "copy-fields-result")
    disk_client.create_folder(source_path)

    response = disk_client.copy_resource(
        source_path,
        destination_path,
        fields="href,method",
    )
    wait_for_operation(disk_client, response)

    assert_successful_copy(response)
    assert set(response.json()) == {"href", "method"}


def test_copy_resource_supports_unicode_and_spaces(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: source and destination paths are correctly encoded."""
    source_path = unique_child(sandbox_path, "источник копии")
    destination_path = unique_child(sandbox_path, "результат копии")
    disk_client.create_folder(source_path)

    response = disk_client.copy_resource(source_path, destination_path)
    assert_successful_copy(response)
    wait_for_operation(disk_client, response)
    metadata = disk_client.get_resource(destination_path).json()

    assert metadata["path"] == destination_path
    assert metadata["name"] == destination_path.rsplit("/", maxsplit=1)[1]


def test_copy_resource_overwrite_replaces_existing_file(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: overwrite=true replaces an occupied destination."""
    source_path = f"{unique_child(sandbox_path, 'overwrite-source')}.txt"
    destination_path = f"{unique_child(sandbox_path, 'overwrite-target')}.txt"
    source = upload_test_file(disk_client, source_path, b"new source value")
    destination_before = upload_test_file(
        disk_client,
        destination_path,
        b"old destination value",
    )
    assert source["md5"] != destination_before["md5"]

    response = disk_client.copy_resource(
        source_path,
        destination_path,
        overwrite=True,
    )
    assert_successful_copy(response)
    wait_for_operation(disk_client, response)
    destination_after = disk_client.get_resource(destination_path).json()

    assert destination_after["md5"] == source["md5"]
    assert destination_after["size"] == source["size"]


def test_copy_without_overwrite_returns_409_and_preserves_destination(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: an existing destination is not replaced by default."""
    source_path = f"{unique_child(sandbox_path, 'conflict-source')}.txt"
    destination_path = f"{unique_child(sandbox_path, 'conflict-target')}.txt"
    upload_test_file(disk_client, source_path, b"source")
    destination_before = upload_test_file(
        disk_client,
        destination_path,
        b"destination",
    )

    response = disk_client.copy_resource(
        source_path,
        destination_path,
        expected_statuses={409},
    )

    assert_error_response(response, requests.codes.conflict)
    destination_after = disk_client.get_resource(destination_path).json()
    assert destination_after["md5"] == destination_before["md5"]


def test_copy_missing_source_returns_404(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: a source path must point to an existing resource."""
    source_path = unique_child(sandbox_path, "missing-copy-source")
    destination_path = unique_child(sandbox_path, "missing-copy-result")

    response = disk_client.copy_resource(
        source_path,
        destination_path,
        expected_statuses={404},
    )

    payload = assert_error_response(response, requests.codes.not_found)
    assert payload["error"] == "DiskNotFoundError"


def test_copy_to_missing_parent_is_rejected(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: the destination's direct parent must exist."""
    source_path = unique_child(sandbox_path, "copy-parent-source")
    missing_parent = unique_child(sandbox_path, "copy-missing-parent")
    destination_path = f"{missing_parent}/result"
    disk_client.create_folder(source_path)

    response = disk_client.copy_resource(
        source_path,
        destination_path,
        expected_statuses={409},
    )

    payload = assert_error_response(response, requests.codes.conflict)
    assert payload["error"] == "DiskPathDoesntExistsError"


def test_copy_without_required_from_returns_400(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: omitting the required from parameter is rejected."""
    destination_path = unique_child(sandbox_path, "copy-without-source")

    response = disk_client.copy_resource(
        None,
        destination_path,
        expected_statuses={400},
    )

    payload = assert_error_response(response, requests.codes.bad_request)
    assert payload["error"] == "FieldValidationError"


def test_copy_without_required_path_returns_400(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: omitting the required destination path is rejected."""
    source_path = unique_child(sandbox_path, "copy-without-path")
    disk_client.create_folder(source_path)

    response = disk_client.copy_resource(
        source_path,
        None,
        expected_statuses={400},
    )

    payload = assert_error_response(response, requests.codes.bad_request)
    assert payload["error"] == "FieldValidationError"


def test_copy_with_invalid_token_returns_401_and_creates_nothing(
    disk_client: YandexDiskClient,
    unauthorized_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: invalid OAuth credentials cannot copy a resource."""
    source_path = unique_child(sandbox_path, "unauthorized-copy")
    destination_path = unique_child(sandbox_path, "unauthorized-copy-result")
    disk_client.create_folder(source_path)

    response = unauthorized_disk_client.copy_resource(
        source_path,
        destination_path,
        expected_statuses={401},
    )

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"
    missing = disk_client.get_resource(destination_path, expected_statuses={404})
    assert missing.status_code == requests.codes.not_found
