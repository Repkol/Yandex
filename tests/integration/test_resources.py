"""End-to-end checks against the live Yandex.Disk REST API."""

from __future__ import annotations

import pytest
import requests

from yandex_disk_api import YandexDiskClient

from .conftest import unique_child, wait_for_operation, wait_for_resource_state

pytestmark = pytest.mark.integration


def test_get_disk_info(disk_client: YandexDiskClient) -> None:
    """GET /v1/disk returns consistent capacity information."""
    response = disk_client.get_disk_info()
    payload = response.json()

    assert response.status_code == requests.codes.ok
    assert isinstance(payload["total_space"], int)
    assert isinstance(payload["used_space"], int)
    assert 0 <= payload["used_space"] <= payload["total_space"]


def test_put_creates_folder(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """PUT /v1/disk/resources creates a directory."""
    folder_path = unique_child(sandbox_path, "put")

    response = disk_client.create_folder(folder_path)
    metadata = disk_client.get_resource(folder_path).json()

    assert response.status_code == requests.codes.created
    assert response.json()["method"] == "GET"
    assert metadata["path"] == folder_path
    assert metadata["type"] == "dir"


def test_post_copies_folder(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """POST /v1/disk/resources/copy copies a directory."""
    source_path = unique_child(sandbox_path, "source")
    destination_path = unique_child(sandbox_path, "copy")
    disk_client.create_folder(source_path)

    response = disk_client.copy_resource(source_path, destination_path)
    wait_for_operation(disk_client, response)
    wait_for_resource_state(disk_client, destination_path, exists=True)
    metadata = disk_client.get_resource(destination_path).json()

    assert response.status_code in {
        requests.codes.created,
        requests.codes.accepted,
    }
    assert metadata["path"] == destination_path
    assert metadata["type"] == "dir"


def test_delete_removes_folder_permanently(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """DELETE /v1/disk/resources removes a directory."""
    folder_path = unique_child(sandbox_path, "delete")
    disk_client.create_folder(folder_path)

    response = disk_client.delete_resource(folder_path, permanently=True)
    wait_for_operation(disk_client, response)
    wait_for_resource_state(disk_client, folder_path, exists=False)
    missing = disk_client.get_resource(folder_path, expected_statuses={404})

    assert response.status_code in {
        requests.codes.accepted,
        requests.codes.no_content,
    }
    assert missing.status_code == requests.codes.not_found
