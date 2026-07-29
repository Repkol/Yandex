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
def unauthorized_disk_client(
    disk_client: YandexDiskClient,
) -> Iterator[YandexDiskClient]:
    """Client with a deliberately invalid token for deterministic 401 checks."""
    with YandexDiskClient("invalid-token-for-negative-api-test") as client:
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
            wait_for_operation(disk_client, deletion, timeout=60.0)
            wait_for_resource_state(
                disk_client,
                path,
                exists=False,
                timeout=60.0,
            )


def unique_child(parent: str, prefix: str) -> str:
    """Return a collision-resistant child path inside the test sandbox."""
    return f"{parent}/{prefix}-{uuid4().hex}"


def assert_error_response(
    response: requests.Response,
    expected_status: int,
) -> dict[str, object]:
    """Assert the common documented error envelope."""
    assert response.status_code == expected_status
    assert response.headers["Content-Type"].startswith("application/json")

    payload = response.json()
    assert isinstance(payload["error"], str)
    assert isinstance(payload["description"], str)
    assert isinstance(payload["message"], str)
    return payload


def upload_test_file(
    client: YandexDiskClient,
    path: str,
    content: bytes,
) -> dict[str, object]:
    """Upload a small fixture file and return its resource metadata."""
    upload_url = client.get_upload_link(path).json()["href"]
    upload = requests.put(upload_url, data=content, timeout=client.timeout)
    assert upload.status_code == requests.codes.created
    return client.get_resource(path).json()


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


def wait_for_trash_resource_state(
    client: YandexDiskClient,
    path: str,
    *,
    exists: bool,
    timeout: float = 15.0,
) -> None:
    """Poll Trash metadata until one test resource appears or disappears."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get_trash_resource(path, expected_statuses={200, 404})
        if (response.status_code == 200) is exists:
            return
        time.sleep(0.25)

    expected = "appear in" if exists else "disappear from"
    pytest.fail(f"Resource {path!r} did not {expected} Trash in {timeout} seconds")


def wait_for_trashed_origin(
    client: YandexDiskClient,
    origin_path: str,
    *,
    timeout: float = 15.0,
) -> dict[str, object]:
    """Find a newly trashed test item by its stable original Disk path."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        offset = 0
        while True:
            response = client.get_trash_resource(
                "trash:/",
                limit=1000,
                offset=offset,
            ).json()
            embedded = response["_embedded"]
            for item in embedded["items"]:
                if item.get("origin_path") == origin_path:
                    return item

            offset += len(embedded["items"])
            if offset >= embedded["total"] or not embedded["items"]:
                break

        time.sleep(0.25)

    pytest.fail(f"Resource with origin_path={origin_path!r} did not appear in Trash")
