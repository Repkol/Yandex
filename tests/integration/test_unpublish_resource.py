"""Positive, negative and edge cases for PUT /v1/disk/resources/unpublish."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import requests

from yandex_disk_api import YandexDiskClient

from .conftest import (
    assert_error_response,
    unique_child,
    upload_test_file,
    wait_for_publication_state,
)

pytestmark = pytest.mark.integration


def assert_link_response(
    response: requests.Response,
    *,
    expected_fields: set[str] | None = None,
) -> dict[str, object]:
    """Assert the documented Link response."""
    assert response.status_code == requests.codes.ok
    assert response.headers["Content-Type"].startswith("application/json")
    payload = response.json()
    if expected_fields is not None:
        assert set(payload) == expected_fields
    assert str(payload["href"]).startswith("https://")
    return payload


@contextmanager
def published_resource(
    client: YandexDiskClient,
    path: str,
) -> Iterator[dict[str, object]]:
    """Publish a resource and guarantee removal of its public link."""
    client.publish_resource(path)
    metadata = wait_for_publication_state(client, path, published=True)
    try:
        yield metadata
    finally:
        response = client.unpublish_resource(path, expected_statuses={200, 404})
        if response.status_code == requests.codes.ok:
            wait_for_publication_state(client, path, published=False)


def test_unpublish_folder_happy_path(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: remove the public link from a published folder."""
    folder_path = unique_child(sandbox_path, "unpublish-happy")
    disk_client.create_folder(folder_path)

    with published_resource(disk_client, folder_path):
        response = disk_client.unpublish_resource(folder_path)
        payload = assert_link_response(response)
        metadata = wait_for_publication_state(
            disk_client,
            folder_path,
            published=False,
        )

        assert payload["method"] == "GET"
        assert metadata["path"] == folder_path
        assert "public_key" not in metadata
        assert "public_url" not in metadata


def test_unpublish_file_keeps_resource_content(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: unpublishing a file keeps its bytes and metadata."""
    file_path = f"{unique_child(sandbox_path, 'unpublish-file')}.txt"
    before = upload_test_file(disk_client, file_path, b"private again")

    with published_resource(disk_client, file_path):
        response = disk_client.unpublish_resource(file_path)
        assert_link_response(response)
        wait_for_publication_state(disk_client, file_path, published=False)
        after = disk_client.get_resource(file_path).json()

        assert after["md5"] == before["md5"]
        assert after["size"] == before["size"]


def test_unpublish_fields_limits_link_response(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: fields limits attributes in the returned Link object."""
    folder_path = unique_child(sandbox_path, "unpublish-fields")
    disk_client.create_folder(folder_path)

    with published_resource(disk_client, folder_path):
        response = disk_client.unpublish_resource(
            folder_path,
            fields="href,method",
        )

        payload = assert_link_response(
            response,
            expected_fields={"href", "method"},
        )
        assert payload["method"] == "GET"
        wait_for_publication_state(disk_client, folder_path, published=False)


def test_unpublish_supports_unicode_and_spaces(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: Unicode and spaces in a path are encoded correctly."""
    folder_path = unique_child(sandbox_path, "снять публикацию")
    disk_client.create_folder(folder_path)

    with published_resource(disk_client, folder_path):
        response = disk_client.unpublish_resource(folder_path)

        assert_link_response(response)
        metadata = wait_for_publication_state(
            disk_client,
            folder_path,
            published=False,
        )
        assert metadata["path"] == folder_path


def test_unpublish_is_idempotent_for_private_resource(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: an existing private resource can be unpublished again."""
    folder_path = unique_child(sandbox_path, "unpublish-private")
    disk_client.create_folder(folder_path)

    response = disk_client.unpublish_resource(folder_path)

    assert_link_response(response)
    wait_for_publication_state(disk_client, folder_path, published=False)


def test_unpublish_twice_keeps_resource_private(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: repeated unpublish requests are idempotent."""
    folder_path = unique_child(sandbox_path, "unpublish-twice")
    disk_client.create_folder(folder_path)

    with published_resource(disk_client, folder_path):
        first = disk_client.unpublish_resource(folder_path)
        assert_link_response(first)
        wait_for_publication_state(disk_client, folder_path, published=False)

        second = disk_client.unpublish_resource(folder_path)
        assert_link_response(second)
        wait_for_publication_state(disk_client, folder_path, published=False)


def test_unpublish_without_required_path_returns_400(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: path is a required query parameter."""
    response = disk_client.unpublish_resource(
        None,
        expected_statuses={400},
    )

    payload = assert_error_response(response, requests.codes.bad_request)
    assert payload["error"] == "FieldValidationError"


def test_unpublish_missing_resource_returns_404(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: a non-existent resource cannot be unpublished."""
    missing_path = unique_child(sandbox_path, "missing-unpublish")

    response = disk_client.unpublish_resource(
        missing_path,
        expected_statuses={404},
    )

    payload = assert_error_response(response, requests.codes.not_found)
    assert payload["error"] == "DiskNotFoundError"


def test_unpublish_with_invalid_token_returns_401_and_keeps_public_link(
    disk_client: YandexDiskClient,
    unauthorized_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: invalid OAuth credentials cannot remove a public link."""
    folder_path = unique_child(sandbox_path, "unauthorized-unpublish")
    disk_client.create_folder(folder_path)

    with published_resource(disk_client, folder_path) as before:
        response = unauthorized_disk_client.unpublish_resource(
            folder_path,
            expected_statuses={401},
        )

        payload = assert_error_response(response, requests.codes.unauthorized)
        assert payload["error"] == "UnauthorizedError"
        after = wait_for_publication_state(
            disk_client,
            folder_path,
            published=True,
        )
        assert after["public_key"] == before["public_key"]
        assert after["public_url"] == before["public_url"]
