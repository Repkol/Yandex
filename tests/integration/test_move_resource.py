"""Positive, negative and edge cases for POST /v1/disk/resources/move."""

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


def assert_successful_move(response: requests.Response) -> None:
    """Assert either documented synchronous or asynchronous move success."""
    assert response.status_code in {
        requests.codes.created,
        requests.codes.accepted,
    }
    payload = response.json()
    assert payload["method"] == "GET"
    assert payload["href"].startswith("https://")


def assert_source_moved(
    client: YandexDiskClient,
    source_path: str,
    destination_path: str,
) -> dict[str, object]:
    """Assert source disappearance and return destination metadata."""
    wait_for_resource_state(client, source_path, exists=False)
    wait_for_resource_state(client, destination_path, exists=True)
    missing = client.get_resource(source_path, expected_statuses={404})
    assert missing.status_code == requests.codes.not_found
    return client.get_resource(destination_path).json()


def test_move_folder_happy_path(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: move an existing folder to a free path."""
    source_path = unique_child(sandbox_path, "move-source")
    destination_path = unique_child(sandbox_path, "move-destination")
    disk_client.create_folder(source_path)

    response = disk_client.move_resource(source_path, destination_path)
    assert_successful_move(response)
    wait_for_operation(disk_client, response)
    metadata = assert_source_moved(disk_client, source_path, destination_path)

    assert metadata["path"] == destination_path
    assert metadata["type"] == "dir"


def test_move_file_preserves_hash_and_size(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: moving a file preserves its md5 and size."""
    source_path = f"{unique_child(sandbox_path, 'move-file-source')}.txt"
    destination_path = f"{unique_child(sandbox_path, 'move-file-result')}.txt"
    source = upload_test_file(disk_client, source_path, b"move exact content")

    response = disk_client.move_resource(source_path, destination_path)
    assert_successful_move(response)
    wait_for_operation(disk_client, response)
    destination = assert_source_moved(
        disk_client,
        source_path,
        destination_path,
    )

    assert destination["type"] == "file"
    assert destination["md5"] == source["md5"]
    assert destination["size"] == source["size"]


def test_move_folder_preserves_nested_content(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive boundary: moving a folder keeps all nested resources."""
    source_path = unique_child(sandbox_path, "move-tree")
    destination_path = unique_child(sandbox_path, "move-tree-result")
    disk_client.create_folder(source_path)
    disk_client.create_folder(f"{source_path}/nested")

    response = disk_client.move_resource(source_path, destination_path)
    assert_successful_move(response)
    wait_for_operation(disk_client, response)
    assert_source_moved(disk_client, source_path, destination_path)

    nested = disk_client.get_resource(f"{destination_path}/nested")
    assert nested.status_code == requests.codes.ok
    assert nested.json()["type"] == "dir"


def test_move_resource_force_async_returns_202(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: force_async guarantees an operation link."""
    source_path = unique_child(sandbox_path, "move-async")
    destination_path = unique_child(sandbox_path, "move-async-result")
    disk_client.create_folder(source_path)

    response = disk_client.move_resource(
        source_path,
        destination_path,
        force_async=True,
    )

    assert response.status_code == requests.codes.accepted
    assert_successful_move(response)
    wait_for_operation(disk_client, response)
    assert_source_moved(disk_client, source_path, destination_path)


def test_move_resource_fields_limits_link_response(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: fields limits attributes in the returned Link object."""
    source_path = unique_child(sandbox_path, "move-fields")
    destination_path = unique_child(sandbox_path, "move-fields-result")
    disk_client.create_folder(source_path)

    response = disk_client.move_resource(
        source_path,
        destination_path,
        fields="href,method",
    )
    wait_for_operation(disk_client, response)

    assert_successful_move(response)
    assert set(response.json()) == {"href", "method"}
    assert_source_moved(disk_client, source_path, destination_path)


def test_move_resource_supports_unicode_and_spaces(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: source and destination paths are correctly encoded."""
    source_path = unique_child(sandbox_path, "папка начало")
    destination_path = unique_child(sandbox_path, "папка результат")
    disk_client.create_folder(source_path)

    response = disk_client.move_resource(source_path, destination_path)
    assert_successful_move(response)
    wait_for_operation(disk_client, response)
    metadata = assert_source_moved(disk_client, source_path, destination_path)

    assert metadata["path"] == destination_path
    assert metadata["name"] == destination_path.rsplit("/", maxsplit=1)[1]


def test_move_resource_overwrite_replaces_existing_file(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: overwrite=true replaces an occupied destination."""
    source_path = f"{unique_child(sandbox_path, 'move-overwrite-source')}.txt"
    destination_path = f"{unique_child(sandbox_path, 'move-overwrite-target')}.txt"
    source = upload_test_file(disk_client, source_path, b"new move value")
    destination_before = upload_test_file(
        disk_client,
        destination_path,
        b"old move value",
    )
    assert source["md5"] != destination_before["md5"]

    response = disk_client.move_resource(
        source_path,
        destination_path,
        overwrite=True,
    )
    assert_successful_move(response)
    wait_for_operation(disk_client, response)
    destination_after = assert_source_moved(
        disk_client,
        source_path,
        destination_path,
    )

    assert destination_after["md5"] == source["md5"]
    assert destination_after["size"] == source["size"]


def test_move_without_overwrite_returns_409_and_preserves_both_resources(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: an occupied destination is not replaced by default."""
    source_path = f"{unique_child(sandbox_path, 'move-conflict-source')}.txt"
    destination_path = f"{unique_child(sandbox_path, 'move-conflict-target')}.txt"
    source_before = upload_test_file(disk_client, source_path, b"source")
    destination_before = upload_test_file(
        disk_client,
        destination_path,
        b"destination",
    )

    response = disk_client.move_resource(
        source_path,
        destination_path,
        expected_statuses={409},
    )

    assert_error_response(response, requests.codes.conflict)
    assert disk_client.get_resource(source_path).json()["md5"] == source_before["md5"]
    destination_after = disk_client.get_resource(destination_path).json()
    assert destination_after["md5"] == destination_before["md5"]


def test_move_missing_source_returns_404(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: source must point to an existing resource."""
    source_path = unique_child(sandbox_path, "missing-move-source")
    destination_path = unique_child(sandbox_path, "missing-move-result")

    response = disk_client.move_resource(
        source_path,
        destination_path,
        expected_statuses={404},
    )

    payload = assert_error_response(response, requests.codes.not_found)
    assert payload["error"] == "DiskNotFoundError"


def test_move_to_missing_parent_is_rejected(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: the destination's direct parent must exist."""
    source_path = unique_child(sandbox_path, "move-parent-source")
    missing_parent = unique_child(sandbox_path, "move-missing-parent")
    destination_path = f"{missing_parent}/result"
    disk_client.create_folder(source_path)

    response = disk_client.move_resource(
        source_path,
        destination_path,
        expected_statuses={409},
    )

    payload = assert_error_response(response, requests.codes.conflict)
    assert payload["error"] == "DiskPathDoesntExistsError"
    assert disk_client.get_resource(source_path).status_code == requests.codes.ok


def test_move_without_required_from_returns_400(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: omitting the required from parameter is rejected."""
    destination_path = unique_child(sandbox_path, "move-without-source")

    response = disk_client.move_resource(
        None,
        destination_path,
        expected_statuses={400},
    )

    payload = assert_error_response(response, requests.codes.bad_request)
    assert payload["error"] == "FieldValidationError"


def test_move_without_required_path_returns_400(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: omitting the required destination path is rejected."""
    source_path = unique_child(sandbox_path, "move-without-path")
    disk_client.create_folder(source_path)

    response = disk_client.move_resource(
        source_path,
        None,
        expected_statuses={400},
    )

    payload = assert_error_response(response, requests.codes.bad_request)
    assert payload["error"] == "FieldValidationError"
    assert disk_client.get_resource(source_path).status_code == requests.codes.ok


def test_move_folder_inside_itself_returns_409_and_preserves_source(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: a folder cannot be moved into its own subtree."""
    source_path = unique_child(sandbox_path, "move-into-itself")
    nested_path = f"{source_path}/nested"
    destination_path = f"{nested_path}/result"
    disk_client.create_folder(source_path)
    disk_client.create_folder(nested_path)

    response = disk_client.move_resource(
        source_path,
        destination_path,
        expected_statuses={409},
    )

    payload = assert_error_response(response, requests.codes.conflict)
    assert payload["error"] == "DiskPathDoesntExistsError"
    assert disk_client.get_resource(source_path).status_code == requests.codes.ok
    assert disk_client.get_resource(nested_path).status_code == requests.codes.ok


def test_move_with_invalid_token_returns_401_and_changes_nothing(
    disk_client: YandexDiskClient,
    unauthorized_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: invalid OAuth credentials cannot move a resource."""
    source_path = unique_child(sandbox_path, "unauthorized-move")
    destination_path = unique_child(sandbox_path, "unauthorized-move-result")
    disk_client.create_folder(source_path)

    response = unauthorized_disk_client.move_resource(
        source_path,
        destination_path,
        expected_statuses={401},
    )

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"
    assert disk_client.get_resource(source_path).status_code == requests.codes.ok
    missing = disk_client.get_resource(destination_path, expected_statuses={404})
    assert missing.status_code == requests.codes.not_found
