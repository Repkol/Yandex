"""Cases for POST /v1/disk/public/resources/save-to-disk."""

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
    wait_for_operation,
    wait_for_public_resource_state,
    wait_for_resource_state,
)

pytestmark = pytest.mark.integration


def assert_save_link(
    response: requests.Response,
    *,
    expected_fields: set[str] | None = None,
) -> dict[str, object]:
    """Assert either documented synchronous or asynchronous save Link."""
    assert response.status_code in {
        requests.codes.created,
        requests.codes.accepted,
    }
    assert response.headers["Content-Type"].startswith("application/json")
    payload = response.json()
    if expected_fields is not None:
        assert set(payload) == expected_fields
    assert payload["method"] == "GET"
    assert str(payload["href"]).startswith("https://")
    return payload


def wait_until_public(
    client: YandexDiskClient,
    private: dict[str, object],
    *,
    path: str | None = None,
) -> str:
    """Wait for public indexing and return the key."""
    public_key = str(private["public_key"])
    wait_for_public_resource_state(
        client,
        public_key,
        path=path,
        present=True,
    )
    return public_key


@pytest.fixture(scope="module")
def published_save_file(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> Iterator[dict[str, object]]:
    """Publish one immutable file reused by save-to-disk scenarios."""
    path = f"{unique_child(sandbox_path, 'shared-save-source')}.txt"
    metadata = upload_test_file(disk_client, path, b"shared public file")

    with temporarily_published_resource(disk_client, path) as private:
        wait_until_public(public_disk_client, private)
        yield {**private, "source_path": path, "source_metadata": metadata}


@pytest.fixture(scope="module")
def published_save_folder(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> Iterator[dict[str, object]]:
    """Publish one immutable folder reused by folder/path scenarios."""
    path = unique_child(sandbox_path, "shared-save-folder")
    nested_public_path = "/nested/source.txt"
    disk_client.create_folder(path)
    disk_client.create_folder(f"{path}/nested")
    nested = upload_test_file(
        disk_client,
        f"{path}{nested_public_path}",
        b"shared nested public file",
    )

    with temporarily_published_resource(disk_client, path) as private:
        wait_until_public(
            public_disk_client,
            private,
            path=nested_public_path,
        )
        yield {
            **private,
            "source_path": path,
            "nested_metadata": nested,
            "nested_public_path": nested_public_path,
        }


def test_save_public_file_happy_path(
    disk_client: YandexDiskClient,
    sandbox_path: str,
    published_save_file: dict[str, object],
) -> None:
    """Happy Path: save a public file into an explicit sandbox folder."""
    destination_folder = unique_child(sandbox_path, "save-target")
    saved_path = f"{destination_folder}/saved.txt"
    disk_client.create_folder(destination_folder)

    response = disk_client.save_public_resource_to_disk(
        str(published_save_file["public_key"]),
        name="saved.txt",
        save_path=destination_folder,
    )

    assert_save_link(response)
    wait_for_operation(disk_client, response, timeout=60.0)
    wait_for_resource_state(disk_client, saved_path, exists=True, timeout=60.0)
    saved = disk_client.get_resource(saved_path).json()
    source = published_save_file["source_metadata"]
    assert isinstance(source, dict)
    assert saved["md5"] == source["md5"]
    assert saved["size"] == source["size"]


def test_save_public_folder_preserves_nested_content(
    disk_client: YandexDiskClient,
    sandbox_path: str,
    published_save_folder: dict[str, object],
) -> None:
    """Positive: saving a public folder recursively copies its content."""
    destination_folder = unique_child(sandbox_path, "save-folder-target")
    saved_path = f"{destination_folder}/saved-folder"
    disk_client.create_folder(destination_folder)

    response = disk_client.save_public_resource_to_disk(
        str(published_save_folder["public_key"]),
        name="saved-folder",
        save_path=destination_folder,
    )

    assert_save_link(response)
    wait_for_operation(disk_client, response, timeout=60.0)
    nested_path = f"{saved_path}/nested/source.txt"
    wait_for_resource_state(disk_client, nested_path, exists=True, timeout=60.0)
    original = published_save_folder["nested_metadata"]
    assert isinstance(original, dict)
    assert disk_client.get_resource(nested_path).json()["md5"] == original["md5"]


def test_save_public_resource_accepts_public_url(
    disk_client: YandexDiskClient,
    sandbox_path: str,
    published_save_file: dict[str, object],
) -> None:
    """Positive: public_url can be used instead of public_key."""
    destination_folder = unique_child(sandbox_path, "save-url-target")
    saved_path = f"{destination_folder}/from-url.txt"
    disk_client.create_folder(destination_folder)

    response = disk_client.save_public_resource_to_disk(
        str(published_save_file["public_url"]),
        name="from-url.txt",
        save_path=destination_folder,
    )

    assert_save_link(response)
    wait_for_operation(disk_client, response, timeout=60.0)
    wait_for_resource_state(disk_client, saved_path, exists=True, timeout=60.0)


def test_save_nested_file_from_public_folder(
    disk_client: YandexDiskClient,
    sandbox_path: str,
    published_save_folder: dict[str, object],
) -> None:
    """Positive: path selects one nested file from a public folder."""
    destination_folder = unique_child(sandbox_path, "save-nested-target")
    saved_path = f"{destination_folder}/selected.txt"
    disk_client.create_folder(destination_folder)

    response = disk_client.save_public_resource_to_disk(
        str(published_save_folder["public_key"]),
        path=str(published_save_folder["nested_public_path"]),
        force_async=True,
        name="selected.txt",
        save_path=destination_folder,
    )

    assert response.status_code == requests.codes.accepted
    assert_save_link(response)
    wait_for_operation(disk_client, response, timeout=60.0)
    wait_for_resource_state(disk_client, saved_path, exists=True, timeout=60.0)
    source = published_save_folder["nested_metadata"]
    assert isinstance(source, dict)
    assert disk_client.get_resource(saved_path).json()["md5"] == source["md5"]


def test_save_public_resource_force_async_returns_202(
    disk_client: YandexDiskClient,
    sandbox_path: str,
    published_save_file: dict[str, object],
) -> None:
    """Positive: force_async=true returns and completes an operation."""
    destination_folder = unique_child(sandbox_path, "save-async-target")
    saved_path = f"{destination_folder}/async.txt"
    disk_client.create_folder(destination_folder)

    response = disk_client.save_public_resource_to_disk(
        str(published_save_file["public_key"]),
        force_async=True,
        name="async.txt",
        save_path=destination_folder,
    )

    assert response.status_code == requests.codes.accepted
    assert_save_link(response)
    wait_for_operation(disk_client, response, timeout=60.0)
    wait_for_resource_state(disk_client, saved_path, exists=True, timeout=60.0)


def test_save_public_resource_fields_limits_link(
    disk_client: YandexDiskClient,
    sandbox_path: str,
    published_save_file: dict[str, object],
) -> None:
    """Positive: fields limits Link attributes without breaking the save."""
    destination_folder = unique_child(sandbox_path, "save-fields-target")
    saved_path = f"{destination_folder}/fields.txt"
    disk_client.create_folder(destination_folder)

    response = disk_client.save_public_resource_to_disk(
        str(published_save_file["public_key"]),
        fields="href,method",
        name="fields.txt",
        save_path=destination_folder,
    )

    assert_save_link(response, expected_fields={"href", "method"})
    wait_for_operation(disk_client, response, timeout=60.0)
    wait_for_resource_state(disk_client, saved_path, exists=True, timeout=60.0)


def test_save_public_resource_supports_unicode_paths_and_name(
    disk_client: YandexDiskClient,
    sandbox_path: str,
    published_save_file: dict[str, object],
) -> None:
    """Edge case: Unicode destination folder and name are preserved."""
    destination_folder = unique_child(sandbox_path, "папка назначения")
    saved_name = "копия юникод.txt"
    saved_path = f"{destination_folder}/{saved_name}"
    disk_client.create_folder(destination_folder)

    response = disk_client.save_public_resource_to_disk(
        str(published_save_file["public_key"]),
        name=saved_name,
        save_path=destination_folder,
    )

    assert_save_link(response)
    wait_for_operation(disk_client, response, timeout=60.0)
    wait_for_resource_state(disk_client, saved_path, exists=True, timeout=60.0)
    assert disk_client.get_resource(saved_path).json()["name"] == saved_name


def test_save_public_resource_uses_original_name_when_name_omitted(
    disk_client: YandexDiskClient,
    sandbox_path: str,
    published_save_file: dict[str, object],
) -> None:
    """Edge case: omitted name preserves the source filename."""
    source_path = str(published_save_file["source_path"])
    source_name = source_path.rsplit("/", maxsplit=1)[1]
    destination_folder = unique_child(sandbox_path, "save-original-target")
    saved_path = f"{destination_folder}/{source_name}"
    disk_client.create_folder(destination_folder)

    response = disk_client.save_public_resource_to_disk(
        str(published_save_file["public_key"]),
        save_path=destination_folder,
    )

    assert_save_link(response)
    wait_for_operation(disk_client, response, timeout=60.0)
    wait_for_resource_state(disk_client, saved_path, exists=True, timeout=60.0)


def test_save_public_resource_existing_destination_is_auto_renamed(
    disk_client: YandexDiskClient,
    sandbox_path: str,
    published_save_file: dict[str, object],
) -> None:
    """Edge: an occupied name is preserved and the saved copy is renamed."""
    destination_folder = unique_child(sandbox_path, "save-conflict-target")
    saved_path = f"{destination_folder}/occupied.txt"
    renamed_path = f"{destination_folder}/occupied (1).txt"
    disk_client.create_folder(destination_folder)
    before = upload_test_file(disk_client, saved_path, b"keep destination")

    response = disk_client.save_public_resource_to_disk(
        str(published_save_file["public_key"]),
        name="occupied.txt",
        save_path=destination_folder,
    )

    assert_save_link(response)
    wait_for_operation(disk_client, response, timeout=60.0)
    wait_for_resource_state(disk_client, renamed_path, exists=True, timeout=60.0)
    after = disk_client.get_resource(saved_path).json()
    source = published_save_file["source_metadata"]
    assert isinstance(source, dict)
    assert after["md5"] == before["md5"]
    assert disk_client.get_resource(renamed_path).json()["md5"] == source["md5"]


def test_save_public_resource_without_key_returns_400(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: public_key is a required parameter."""
    destination_folder = unique_child(sandbox_path, "save-no-key-target")
    disk_client.create_folder(destination_folder)

    response = disk_client.save_public_resource_to_disk(
        None,
        save_path=destination_folder,
        expected_statuses={400},
    )

    assert_error_response(response, requests.codes.bad_request)


def test_save_public_resource_empty_key_returns_400(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: an explicitly empty public key is invalid."""
    destination_folder = unique_child(sandbox_path, "save-empty-key-target")
    disk_client.create_folder(destination_folder)

    response = disk_client.save_public_resource_to_disk(
        "",
        save_path=destination_folder,
        expected_statuses={400},
    )

    assert_error_response(response, requests.codes.bad_request)


def test_save_public_resource_unknown_key_returns_404(
    disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: a well-formed but unknown key cannot be saved."""
    destination_folder = unique_child(sandbox_path, "save-unknown-key-target")
    disk_client.create_folder(destination_folder)

    response = disk_client.save_public_resource_to_disk(
        "not-a-public-key",
        save_path=destination_folder,
        expected_statuses={404},
    )

    payload = assert_error_response(response, requests.codes.not_found)
    assert payload["error"] == "DiskNotFoundError"


def test_save_missing_nested_public_path_returns_404(
    disk_client: YandexDiskClient,
    sandbox_path: str,
    published_save_folder: dict[str, object],
) -> None:
    """Negative: path must exist inside the public folder."""
    destination_folder = unique_child(sandbox_path, "save-missing-target")
    disk_client.create_folder(destination_folder)

    response = disk_client.save_public_resource_to_disk(
        str(published_save_folder["public_key"]),
        path="/missing.txt",
        save_path=destination_folder,
        expected_statuses={404},
    )

    assert_error_response(response, requests.codes.not_found)


def test_save_public_resource_to_missing_destination_folder_is_rejected(
    disk_client: YandexDiskClient,
    sandbox_path: str,
    published_save_file: dict[str, object],
) -> None:
    """Negative: save_path must point to an existing folder."""
    missing_folder = unique_child(sandbox_path, "save-missing-destination")

    response = disk_client.save_public_resource_to_disk(
        str(published_save_file["public_key"]),
        save_path=missing_folder,
        expected_statuses={404, 409},
    )

    assert response.status_code in {
        requests.codes.not_found,
        requests.codes.conflict,
    }
    assert_error_response(response, response.status_code)


def test_save_public_resource_with_invalid_token_returns_401(
    unauthorized_disk_client: YandexDiskClient,
    sandbox_path: str,
    disk_client: YandexDiskClient,
    published_save_file: dict[str, object],
) -> None:
    """Negative: save-to-disk requires valid OAuth credentials."""
    destination_folder = unique_child(sandbox_path, "save-unauthorized-target")
    disk_client.create_folder(destination_folder)

    response = unauthorized_disk_client.save_public_resource_to_disk(
        str(published_save_file["public_key"]),
        save_path=destination_folder,
        expected_statuses={401},
    )

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"
