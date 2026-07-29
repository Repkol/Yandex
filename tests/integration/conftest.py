"""Fixtures for live Yandex.Disk API tests."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
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
def public_disk_client() -> Iterator[YandexDiskClient]:
    """Client without an Authorization header for public API checks."""
    with YandexDiskClient(None) as client:
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
            wait_for_operation(disk_client, deletion, timeout=180.0)
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
    for attempt in range(3):
        upload_url = client.get_upload_link(path, overwrite=True).json()["href"]
        try:
            upload = requests.put(
                upload_url,
                data=content,
                timeout=client.timeout,
            )
            break
        except requests.exceptions.ConnectTimeout:
            if attempt == 2:
                raise
            time.sleep(0.5 * (2**attempt))

    assert upload.status_code == requests.codes.created
    return client.get_resource(path).json()


def wait_for_operation(
    client: YandexDiskClient,
    response: requests.Response,
    *,
    timeout: float = 15.0,
) -> None:
    """Wait when a resource-changing endpoint returns HTTP 202."""
    operation = wait_for_operation_result(client, response, timeout=timeout)
    if operation is None:
        return
    if operation["status"] == "failed":
        pytest.fail(f"Yandex.Disk operation failed: {operation}")


def wait_for_operation_result(
    client: YandexDiskClient,
    response: requests.Response,
    *,
    timeout: float = 15.0,
) -> dict[str, object] | None:
    """Return the terminal payload for an asynchronous operation."""
    if response.status_code != 202:
        return None

    operation_url = response.json()["href"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        operation = client.get_operation(operation_url).json()
        if operation["status"] in {"success", "failed"}:
            return operation
        time.sleep(0.25)

    pytest.fail(f"Yandex.Disk operation did not finish in {timeout} seconds")


def wait_for_resource_state(
    client: YandexDiskClient,
    path: str,
    *,
    exists: bool,
    timeout: float = 60.0,
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


def wait_for_publication_state(
    client: YandexDiskClient,
    path: str,
    *,
    published: bool,
    timeout: float = 180.0,
) -> dict[str, object]:
    """Poll metadata until a test resource gains or loses its public link."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        metadata = client.get_resource(
            path,
            fields="path,public_key,public_url",
        ).json()
        has_public_link = bool(
            metadata.get("public_key") and metadata.get("public_url")
        )
        if has_public_link is published:
            return metadata
        time.sleep(0.25)

    state = "become public" if published else "become private"
    pytest.fail(f"Resource {path!r} did not {state} in {timeout} seconds")


@contextmanager
def temporarily_published_resource(
    client: YandexDiskClient,
    path: str,
    *,
    allow_address_access: bool | None = None,
    publish_body: object | None = None,
    skip_if_unavailable: bool = False,
) -> Iterator[dict[str, object]]:
    """Publish one test resource and always revoke its public link."""
    transient_statuses = {429, 500, 503}
    for attempt in range(3):
        response = client.publish_resource(
            path,
            allow_address_access=allow_address_access,
            body=publish_body,
            expected_statuses={200, *transient_statuses},
        )
        if response.status_code == requests.codes.ok:
            break
        if attempt < 2:
            time.sleep(0.5 * (2**attempt))
    else:
        pytest.fail(
            "Test resource publication failed after retries: "
            f"HTTP {response.status_code} {response.text[:500]}"
        )

    try:
        metadata = wait_for_publication_state(
            client,
            path,
            published=True,
            timeout=180.0,
        )
    except pytest.fail.Exception:
        if not skip_if_unavailable:
            raise
        client.unpublish_resource(path, expected_statuses={200, 404})
        pytest.skip("A public link could not be prepared for this capability test")

    try:
        yield metadata
    finally:
        response = client.unpublish_resource(path, expected_statuses={200, 404})
        if response.status_code == requests.codes.ok:
            wait_for_publication_state(client, path, published=False)


def wait_for_public_resource_state(
    client: YandexDiskClient,
    public_key: str,
    *,
    present: bool,
    path: str | None = None,
    timeout: float = 60.0,
) -> dict[str, object] | None:
    """Poll the unauthenticated public endpoint until availability changes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get_public_resource(
            public_key,
            path=path,
            expected_statuses={200, 404},
        )
        if response.status_code == requests.codes.ok and present:
            return response.json()
        if response.status_code == requests.codes.not_found and not present:
            return None
        time.sleep(0.25)

    state = "become public" if present else "become unavailable"
    pytest.fail(f"Public resource {public_key!r} did not {state} in {timeout} seconds")


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
