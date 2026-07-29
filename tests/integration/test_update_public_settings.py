"""Cases for PATCH /v1/disk/public/resources/public-settings."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import requests

from yandex_disk_api import YandexDiskClient

from .conftest import (
    assert_error_response,
    temporarily_published_resource,
    unique_child,
    upload_test_file,
    wait_for_public_resource_state,
)

pytestmark = pytest.mark.integration


def assert_empty_success(response: requests.Response) -> None:
    """Assert the documented successful response without a model."""
    assert response.status_code == requests.codes.ok
    assert response.content in {b"", b"{}"}


def update_settings_or_skip(
    client: YandexDiskClient,
    path: str,
    body: object,
    *,
    fields: str | None = None,
) -> requests.Response:
    """Skip positive checks when the account lacks extended public settings."""
    response = client.update_public_settings(
        path,
        body,
        fields=fields,
        expected_statuses={200, 404},
    )
    if response.status_code == requests.codes.not_found:
        payload = assert_error_response(response, requests.codes.not_found)
        assert payload["error"] == "DiskNotFoundError"
        pytest.skip("Extended public settings are unavailable for this account")
    return response


@pytest.fixture(scope="module")
def published_settings_folder(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> Iterator[dict[str, object]]:
    """Publish one Unicode folder reused by settings scenarios."""
    path = unique_child(sandbox_path, "настройки юникод")
    disk_client.create_folder(path)

    with temporarily_published_resource(
        disk_client,
        path,
        allow_address_access=True,
        publish_body={"public_settings": {"read_only": True}},
    ) as private:
        yield {**private, "source_path": path}


@pytest.fixture(scope="module")
def published_settings_file(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> Iterator[dict[str, object]]:
    """Publish one immutable file reused by the file scenario."""
    path = f"{unique_child(sandbox_path, 'public-settings-file')}.txt"
    metadata = upload_test_file(disk_client, path, b"settings file")

    with temporarily_published_resource(
        disk_client,
        path,
        skip_if_unavailable=True,
    ) as private:
        yield {**private, "source_path": path, "source_metadata": metadata}


def test_update_public_settings_happy_path_for_folder(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    published_settings_folder: dict[str, object],
) -> None:
    """Happy Path: update safe settings of a published folder."""
    response = update_settings_or_skip(
        disk_client,
        str(published_settings_folder["source_path"]),
        {"available_until": 2_000_000_000},
    )

    assert_empty_success(response)
    public = wait_for_public_resource_state(
        public_disk_client,
        str(published_settings_folder["public_key"]),
        present=True,
    )
    assert public is not None
    assert public["type"] == "dir"


def test_update_public_settings_for_file(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    published_settings_file: dict[str, object],
) -> None:
    """Positive: the endpoint accepts an owned public file."""
    response = update_settings_or_skip(
        disk_client,
        str(published_settings_file["source_path"]),
        {"available_until": 0},
    )

    assert_empty_success(response)
    public = wait_for_public_resource_state(
        public_disk_client,
        str(published_settings_file["public_key"]),
        present=True,
    )
    original = published_settings_file["source_metadata"]
    assert public is not None
    assert isinstance(original, dict)
    assert public["md5"] == original["md5"]


def test_update_public_settings_accepts_fields(
    disk_client: YandexDiskClient,
    published_settings_folder: dict[str, object],
) -> None:
    """Positive: fields is accepted for the empty success response."""
    response = update_settings_or_skip(
        disk_client,
        str(published_settings_folder["source_path"]),
        {"available_until": 0},
        fields="available_until",
    )

    assert_empty_success(response)


def test_update_public_settings_supports_unicode_path(
    disk_client: YandexDiskClient,
    published_settings_folder: dict[str, object],
) -> None:
    """Edge case: Unicode and spaces in path are encoded correctly."""
    response = update_settings_or_skip(
        disk_client,
        str(published_settings_folder["source_path"]),
        {"available_until": 0},
    )

    assert_empty_success(response)


def test_update_public_settings_empty_object_returns_400(
    disk_client: YandexDiskClient,
    published_settings_folder: dict[str, object],
) -> None:
    """Negative edge: at least one documented setting is required."""
    response = disk_client.update_public_settings(
        str(published_settings_folder["source_path"]),
        {},
        expected_statuses={400},
    )

    payload = assert_error_response(response, requests.codes.bad_request)
    assert payload["error"] == "FieldOneRequiredValidationError"


def test_update_public_settings_is_idempotent(
    disk_client: YandexDiskClient,
    published_settings_folder: dict[str, object],
) -> None:
    """Edge case: applying the same settings twice remains successful."""
    folder_path = str(published_settings_folder["source_path"])
    first = update_settings_or_skip(
        disk_client,
        folder_path,
        {"available_until": 0},
    )
    second = disk_client.update_public_settings(
        folder_path,
        {"available_until": 0},
    )

    assert_empty_success(first)
    assert_empty_success(second)


def test_update_public_settings_without_body_returns_400(
    disk_client: YandexDiskClient,
    published_settings_folder: dict[str, object],
) -> None:
    """Negative: body is required by the endpoint contract."""
    response = disk_client.update_public_settings(
        str(published_settings_folder["source_path"]),
        body=None,
        expected_statuses={400},
    )

    assert_error_response(response, requests.codes.bad_request)


def test_update_public_settings_without_path_returns_400(
    disk_client: YandexDiskClient,
) -> None:
    """Negative: path is a required query parameter."""
    response = disk_client.update_public_settings(
        None,
        {"available_until": 0},
        expected_statuses={400},
    )

    payload = assert_error_response(response, requests.codes.bad_request)
    assert payload["error"] == "FieldValidationError"


def test_update_public_settings_missing_resource_returns_404(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: the resource path must exist."""
    missing_path = unique_child(sandbox_path, "missing-public-settings")

    response = disk_client.update_public_settings(
        missing_path,
        {"available_until": 0},
        expected_statuses={404},
    )

    payload = assert_error_response(response, requests.codes.not_found)
    assert payload["error"] == "DiskNotFoundError"


def test_update_public_settings_private_resource_is_rejected(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: settings cannot be changed before publication."""
    folder_path = unique_child(sandbox_path, "private-public-settings")
    disk_client.create_folder(folder_path)

    response = disk_client.update_public_settings(
        folder_path,
        {"available_until": 0},
        expected_statuses={400, 404},
    )

    assert response.status_code in {
        requests.codes.bad_request,
        requests.codes.not_found,
    }
    assert_error_response(response, response.status_code)


@pytest.mark.parametrize(
    "body",
    [
        "not-an-object",
        {"available_until": "not-a-timestamp"},
    ],
)
def test_update_public_settings_rejects_invalid_json_shape(
    disk_client: YandexDiskClient,
    published_settings_folder: dict[str, object],
    body: object,
) -> None:
    """Negative: settings must match the documented JSON schema."""
    response = disk_client.update_public_settings(
        str(published_settings_folder["source_path"]),
        body,
        expected_statuses={400},
    )

    assert_error_response(response, requests.codes.bad_request)


def test_update_public_settings_rejects_unsupported_content_type(
    disk_client: YandexDiskClient,
    published_settings_folder: dict[str, object],
) -> None:
    """Negative: a non-JSON body is rejected with HTTP 415."""
    response = disk_client.update_public_settings(
        str(published_settings_folder["source_path"]),
        "not-json",
        content_type="text/plain",
        expected_statuses={415},
    )

    assert_error_response(
        response,
        requests.codes.unsupported_media_type,
    )


def test_update_public_settings_with_invalid_token_returns_401(
    unauthorized_disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    published_settings_folder: dict[str, object],
) -> None:
    """Negative: invalid OAuth credentials cannot update settings."""
    response = unauthorized_disk_client.update_public_settings(
        str(published_settings_folder["source_path"]),
        {"available_until": 0},
        expected_statuses={401},
    )

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"
    assert (
        wait_for_public_resource_state(
            public_disk_client,
            str(published_settings_folder["public_key"]),
            present=True,
        )
        is not None
    )
