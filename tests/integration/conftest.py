"""Fixtures for live Yandex.Disk API tests."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from uuid import uuid4

import pytest
import requests

from yandex_disk_api import YandexDiskClient


@pytest.fixture(scope="session")
def disk_client() -> Iterator[YandexDiskClient]:
    token = os.getenv("YANDEX_DISK_TOKEN")
    if not token:
        pytest.skip("YANDEX_DISK_TOKEN is not set")

    with YandexDiskClient(token) as client:
        yield client


@pytest.fixture(scope="session")
def sandbox_path(disk_client: YandexDiskClient) -> Iterator[str]:
    path = f"disk:/api-autotests-{uuid4().hex}"
    disk_client.create_folder(path)

    try:
        yield path
    finally:
        response = disk_client.get_resource(path, expected_statuses={200, 404})
        if response.status_code == 200:
            deletion = disk_client.delete_resource(path, permanently=True)
            wait_for_operation(disk_client, deletion)


def unique_child(parent: str, prefix: str) -> str:
    """Return a collision-resistant child path inside the test sandbox."""
    return f"{parent}/{prefix}-{uuid4().hex}"


def wait_for_operation(
    client: YandexDiskClient,
    response: requests.Response,
    *,
    timeout: float = 15.0,
) -> None:
    """Wait when a resource-changing endpoint returns HTTP 202."""
    if response.status_code != 202:
        return

    operation_url = response.json()["href"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        operation = client.get_operation(operation_url).json()
        if operation["status"] == "success":
            return
        if operation["status"] == "failed":
            pytest.fail(f"Yandex.Disk operation failed: {operation}")
        time.sleep(0.25)

    pytest.fail(f"Yandex.Disk operation did not finish in {timeout} seconds")


def wait_for_resource_state(
    client: YandexDiskClient,
    path: str,
    *,
    exists: bool,
    timeout: float = 15.0,
) -> None:
    """Poll resource metadata until it appears or disappears."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get_resource(path, expected_statuses={200, 404})
        if (response.status_code == 200) is exists:
            return
        time.sleep(0.25)

    expected = "appear" if exists else "disappear"
    pytest.fail(f"Resource {path!r} did not {expected} in {timeout} seconds")
