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
