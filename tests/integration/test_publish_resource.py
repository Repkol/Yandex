"""Positive, negative and edge cases for PUT /v1/disk/resources/publish."""

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
    """Assert the documented Link response returned by publication methods."""
    assert response.status_code == requests.codes.ok
    assert response.headers["Content-Type"].startswith("application/json")
    payload = response.json()
    if expected_fields is not None:
        assert set(payload) == expected_fields
    assert str(payload["href"]).startswith("https://")
    return payload


@contextmanager
def publication_cleanup(
    client: YandexDiskClient,
    path: str,
) -> Iterator[None]:
    """Always remove a public link potentially created by a test."""
    try:
        yield
    finally:
        response = client.unpublish_resource(path, expected_statuses={200, 404})
        if response.status_code == requests.codes.ok:
            wait_for_publication_state(client, path, published=False)


def test_publish_folder_happy_path(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: publish an existing private folder."""
    folder_path = unique_child(sandbox_path, "publish-happy")
    disk_client.create_folder(folder_path)

    with publication_cleanup(disk_client, folder_path):
        response = disk_client.publish_resource(folder_path)
        payload = assert_link_response(response)
        metadata = wait_for_publication_state(
            disk_client,
            folder_path,
            published=True,
        )

        assert payload["method"] == "GET"
        assert metadata["path"] == folder_path
        assert str(metadata["public_url"]).startswith("https://")
        assert metadata["public_key"]


def test_publish_file_with_read_only_settings(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: publish a file with an explicit safe JSON body."""
    file_path = f"{unique_child(sandbox_path, 'publish-file')}.txt"
    upload_test_file(disk_client, file_path, b"read-only public fixture")

    with publication_cleanup(disk_client, file_path):
        response = disk_client.publish_resource(
            file_path,
            body={"public_settings": {"read_only": True}},
        )

        assert_link_response(response)
        metadata = wait_for_publication_state(
            disk_client,
            file_path,
            published=True,
        )
        assert metadata["public_key"]


def test_publish_supports_allow_address_access(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: allow_address_access=true is accepted and serialized."""
    folder_path = unique_child(sandbox_path, "publish-address-access")
    disk_client.create_folder(folder_path)

    with publication_cleanup(disk_client, folder_path):
        response = disk_client.publish_resource(
            folder_path,
            allow_address_access=True,
            body={"public_settings": {"read_only": True}},
        )

        assert_link_response(response)
        wait_for_publication_state(disk_client, folder_path, published=True)


def test_publish_fields_limits_link_response(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: fields limits attributes in the returned Link object."""
    folder_path = unique_child(sandbox_path, "publish-fields")
    disk_client.create_folder(folder_path)

    with publication_cleanup(disk_client, folder_path):
        response = disk_client.publish_resource(
            folder_path,
            fields="href,method",
        )

        payload = assert_link_response(
            response,
            expected_fields={"href", "method"},
        )
        assert payload["method"] == "GET"
        wait_for_publication_state(disk_client, folder_path, published=True)


def test_publish_supports_unicode_and_spaces(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: Unicode and spaces in a path are encoded correctly."""
    folder_path = unique_child(sandbox_path, "публичная папка")
    disk_client.create_folder(folder_path)

    with publication_cleanup(disk_client, folder_path):
        response = disk_client.publish_resource(folder_path)

        assert_link_response(response)
        metadata = wait_for_publication_state(
            disk_client,
            folder_path,
            published=True,
        )
        assert metadata["path"] == folder_path


def test_publish_is_idempotent_and_keeps_public_key(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: publishing an already public resource is idempotent."""
    folder_path = unique_child(sandbox_path, "publish-twice")
    disk_client.create_folder(folder_path)

    with publication_cleanup(disk_client, folder_path):
        first = disk_client.publish_resource(folder_path)
        assert_link_response(first)
        before = wait_for_publication_state(
            disk_client,
            folder_path,
            published=True,
        )

        second = disk_client.publish_resource(folder_path)
        assert_link_response(second)
        after = wait_for_publication_state(
            disk_client,
            folder_path,
            published=True,
        )

        assert after["public_key"] == before["public_key"]
        assert after["public_url"] == before["public_url"]


def test_publish_without_body_uses_default_settings(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: live API accepts an omitted body despite the polygon schema."""
    folder_path = unique_child(sandbox_path, "publish-no-body")
    disk_client.create_folder(folder_path)

    with publication_cleanup(disk_client, folder_path):
        response = disk_client.publish_resource(folder_path, body=None)

        assert_link_response(response)
        wait_for_publication_state(disk_client, folder_path, published=True)


def test_publish_without_required_path_returns_400(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: path is a required query parameter."""
    response = disk_client.publish_resource(
        None,
        expected_statuses={400},
    )

    payload = assert_error_response(response, requests.codes.bad_request)
    assert payload["error"] == "FieldValidationError"


def test_publish_missing_resource_returns_404(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: a non-existent resource cannot be published."""
    missing_path = unique_child(sandbox_path, "missing-publish")

    response = disk_client.publish_resource(
        missing_path,
        expected_statuses={404},
    )

    payload = assert_error_response(response, requests.codes.not_found)
    assert payload["error"] == "DiskNotFoundError"


def test_publish_rejects_invalid_public_settings(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: public_settings must be a JSON object."""
    folder_path = unique_child(sandbox_path, "publish-invalid-settings")
    disk_client.create_folder(folder_path)

    with publication_cleanup(disk_client, folder_path):
        response = disk_client.publish_resource(
            folder_path,
            body={"public_settings": "not-an-object"},
            expected_statuses={400},
        )

        assert_error_response(response, requests.codes.bad_request)


def test_publish_rejects_unsupported_content_type(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: a non-JSON body is rejected with HTTP 415."""
    folder_path = unique_child(sandbox_path, "publish-content-type")
    disk_client.create_folder(folder_path)

    with publication_cleanup(disk_client, folder_path):
        response = disk_client.publish_resource(
            folder_path,
            body="not-json",
            content_type="text/plain",
            expected_statuses={415},
        )

        assert_error_response(
            response,
            requests.codes.unsupported_media_type,
        )


def test_publish_with_invalid_token_returns_401_and_remains_private(
    disk_client: YandexDiskClient,
    unauthorized_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: invalid OAuth credentials cannot publish a resource."""
    folder_path = unique_child(sandbox_path, "unauthorized-publish")
    disk_client.create_folder(folder_path)

    response = unauthorized_disk_client.publish_resource(
        folder_path,
        expected_statuses={401},
    )

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"
    metadata = wait_for_publication_state(
        disk_client,
        folder_path,
        published=False,
    )
    assert "public_key" not in metadata
    assert "public_url" not in metadata
