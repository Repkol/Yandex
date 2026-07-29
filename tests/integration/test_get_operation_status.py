"""Cases for GET /v1/disk/operations/{operation_id}."""

from __future__ import annotations

import time
from collections.abc import Iterator
from urllib.parse import unquote, urlparse

import pytest
import requests

from yandex_disk_api import YandexDiskClient

from .conftest import (
    assert_error_response,
    unique_child,
    wait_for_resource_state,
)

pytestmark = pytest.mark.integration


def operation_id_from_href(href: str) -> str:
    """Extract and decode the final operation ID path segment."""
    path = urlparse(href).path.rstrip("/")
    operation_id = unquote(path.rsplit("/", maxsplit=1)[1])
    assert operation_id
    return operation_id


def wait_for_operation_status(
    client: YandexDiskClient,
    operation_id: str,
    *,
    expected_terminal: str,
    timeout: float = 120.0,
) -> tuple[dict[str, object], set[str]]:
    """Poll the endpoint under test and return terminal payload and seen states."""
    deadline = time.monotonic() + timeout
    seen = set()
    while time.monotonic() < deadline:
        response = client.get_operation_status(operation_id)
        assert response.status_code == requests.codes.ok
        assert response.headers["Content-Type"].startswith("application/json")
        payload = response.json()
        assert set(payload) == {"status"}
        status = str(payload["status"])
        seen.add(status)
        assert status in {"in-progress", "success", "failed"}
        if status in {"success", "failed"}:
            assert status == expected_terminal
            return payload, seen
        time.sleep(0.25)

    pytest.fail(
        f"Operation {operation_id!r} did not reach {expected_terminal!r} "
        f"in {timeout} seconds"
    )


@pytest.fixture(scope="module")
def successful_operation(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> Iterator[dict[str, str]]:
    """Start one successful asynchronous copy reused by read-only cases."""
    source_path = unique_child(sandbox_path, "operation-source")
    destination_path = unique_child(sandbox_path, "operation-result")
    disk_client.create_folder(source_path)
    disk_client.create_folder(f"{source_path}/nested")

    response = disk_client.copy_resource(
        source_path,
        destination_path,
        force_async=True,
    )
    assert response.status_code == requests.codes.accepted
    href = str(response.json()["href"])
    yield {
        "destination_path": destination_path,
        "href": href,
        "operation_id": operation_id_from_href(href),
    }


@pytest.fixture(scope="module")
def failed_operation(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> dict[str, str]:
    """Start one import that deterministically fails DNS resolution."""
    destination_path = f"{unique_child(sandbox_path, 'operation-failed')}.txt"
    response = disk_client.upload_resource_from_url(
        destination_path,
        "https://operation-status-test.invalid/missing.txt",
    )
    assert response.status_code == requests.codes.accepted
    href = str(response.json()["href"])
    return {
        "destination_path": destination_path,
        "href": href,
        "operation_id": operation_id_from_href(href),
    }


def test_get_operation_status_happy_path_reaches_success(
    disk_client: YandexDiskClient,
    successful_operation: dict[str, str],
) -> None:
    """Happy Path: an asynchronous copy reaches success."""
    payload, seen = wait_for_operation_status(
        disk_client,
        successful_operation["operation_id"],
        expected_terminal="success",
    )

    assert payload == {"status": "success"}
    assert seen <= {"in-progress", "success"}
    wait_for_resource_state(
        disk_client,
        successful_operation["destination_path"],
        exists=True,
        timeout=60.0,
    )


def test_get_operation_status_fields_limits_response(
    disk_client: YandexDiskClient,
    successful_operation: dict[str, str],
) -> None:
    """Positive: fields=status retains the operation status."""
    response = disk_client.get_operation_status(
        successful_operation["operation_id"],
        fields="status",
    )

    assert response.status_code == requests.codes.ok
    assert response.json() == {"status": "success"}


def test_get_operation_status_ignores_unknown_fields(
    disk_client: YandexDiskClient,
    successful_operation: dict[str, str],
) -> None:
    """Edge: an unknown fields value is ignored for this compact response."""
    response = disk_client.get_operation_status(
        successful_operation["operation_id"],
        fields="unknown_field",
    )

    assert response.status_code == requests.codes.ok
    assert response.json() == {"status": "success"}


def test_get_operation_by_id_matches_full_href(
    disk_client: YandexDiskClient,
    successful_operation: dict[str, str],
) -> None:
    """Positive: operation ID and returned href address the same state."""
    by_id = disk_client.get_operation_status(
        successful_operation["operation_id"],
    ).json()
    by_href = disk_client.get_operation(successful_operation["href"]).json()

    assert by_id == by_href == {"status": "success"}


def test_completed_operation_status_is_stable(
    disk_client: YandexDiskClient,
    successful_operation: dict[str, str],
) -> None:
    """Edge: repeated reads of a completed operation remain successful."""
    first = disk_client.get_operation_status(
        successful_operation["operation_id"],
    ).json()
    second = disk_client.get_operation_status(
        successful_operation["operation_id"],
    ).json()

    assert first == second == {"status": "success"}


def test_get_failed_operation_status(
    disk_client: YandexDiskClient,
    failed_operation: dict[str, str],
) -> None:
    """Edge: an accepted import can terminate with status=failed."""
    payload, seen = wait_for_operation_status(
        disk_client,
        failed_operation["operation_id"],
        expected_terminal="failed",
    )

    assert payload == {"status": "failed"}
    assert seen <= {"in-progress", "failed"}
    response = disk_client.get_resource(
        failed_operation["destination_path"],
        expected_statuses={404},
    )
    assert response.status_code == requests.codes.not_found


def test_get_unknown_operation_returns_404(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: an unknown well-formed operation ID is not found."""
    response = disk_client.get_operation_status(
        "00000000-0000-0000-0000-000000000000",
        expected_statuses={404},
    )

    assert_error_response(response, requests.codes.not_found)


@pytest.mark.parametrize("operation_id", [None, ""])
def test_get_operation_without_id_returns_operation_collection(
    disk_client: YandexDiskClient,
    operation_id: str | None,
) -> None:
    """Edge: an absent ID resolves to the undocumented collection route."""
    response = disk_client.get_operation_status(operation_id)

    assert response.status_code == requests.codes.ok
    payload = response.json()
    assert set(payload) == {"items"}
    assert isinstance(payload["items"], list)


def test_get_operation_id_with_path_characters_is_encoded(
    disk_client: YandexDiskClient,
) -> None:
    """Negative edge: slashes and spaces stay inside one encoded ID segment."""
    response = disk_client.get_operation_status(
        "unknown/id with space",
        expected_statuses={400, 404},
    )

    assert response.status_code in {
        requests.codes.bad_request,
        requests.codes.not_found,
    }
    assert_error_response(response, response.status_code)


def test_get_operation_with_invalid_token_returns_401(
    unauthorized_disk_client: YandexDiskClient,
    successful_operation: dict[str, str],
) -> None:
    """Negative: operation status requires valid OAuth credentials."""
    response = unauthorized_disk_client.get_operation_status(
        successful_operation["operation_id"],
        expected_statuses={401},
    )

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"
