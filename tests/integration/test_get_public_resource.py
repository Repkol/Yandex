"""Positive, negative and edge cases for GET /v1/disk/public/resources."""

from __future__ import annotations

import pytest
import requests

from yandex_disk_api import YandexDiskClient

from .conftest import (
    assert_error_response,
    temporarily_published_resource,
    unique_child,
    upload_test_file,
    wait_for_public_resource_state,
    wait_for_publication_state,
)

pytestmark = pytest.mark.integration


def test_get_public_folder_happy_path_without_oauth(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Happy Path: public folder metadata is available without OAuth."""
    folder_path = unique_child(sandbox_path, "public-metadata-happy")
    disk_client.create_folder(folder_path)
    disk_client.create_folder(f"{folder_path}/nested")

    with temporarily_published_resource(disk_client, folder_path) as private:
        public_key = str(private["public_key"])
        metadata = wait_for_public_resource_state(
            public_disk_client,
            public_key,
            present=True,
        )

        assert metadata is not None
        assert metadata["name"] == folder_path.rsplit("/", maxsplit=1)[1]
        assert metadata["type"] == "dir"
        assert metadata["public_key"] == public_key
        assert metadata["_embedded"]["total"] == 1
        assert metadata["_embedded"]["public_key"] == public_key
        assert metadata["_embedded"]["items"][0]["name"] == "nested"


def test_get_public_resource_accepts_public_url(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: public_url can be used instead of public_key."""
    file_path = f"{unique_child(sandbox_path, 'public-url-metadata')}.txt"
    original = upload_test_file(disk_client, file_path, b"public URL metadata")

    with temporarily_published_resource(disk_client, file_path) as private:
        response = public_disk_client.get_public_resource(
            str(private["public_url"]),
        )
        metadata = response.json()

        assert response.status_code == requests.codes.ok
        assert metadata["type"] == "file"
        assert metadata["md5"] == original["md5"]
        assert metadata["size"] == original["size"]


def test_get_public_file_returns_exact_metadata(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: public file metadata keeps hashes and size."""
    file_path = f"{unique_child(sandbox_path, 'public-file-metadata')}.txt"
    original = upload_test_file(disk_client, file_path, b"exact public metadata")

    with temporarily_published_resource(disk_client, file_path) as private:
        metadata = wait_for_public_resource_state(
            public_disk_client,
            str(private["public_key"]),
            present=True,
        )

        assert metadata is not None
        assert metadata["type"] == "file"
        assert metadata["md5"] == original["md5"]
        assert metadata["sha256"] == original["sha256"]
        assert metadata["size"] == original["size"]


def test_get_public_resource_fields_limits_response(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: fields limits root and nested resource attributes."""
    folder_path = unique_child(sandbox_path, "public-metadata-fields")
    disk_client.create_folder(folder_path)
    disk_client.create_folder(f"{folder_path}/child")

    with temporarily_published_resource(disk_client, folder_path) as private:
        wait_for_public_resource_state(
            public_disk_client,
            str(private["public_key"]),
            present=True,
        )
        response = public_disk_client.get_public_resource(
            str(private["public_key"]),
            fields="name,type,_embedded.total,_embedded.items.name",
        )
        payload = response.json()

        assert set(payload) == {"name", "type", "_embedded"}
        assert set(payload["_embedded"]) == {"total", "items", "public_key"}
        assert payload["_embedded"]["items"] == [{"name": "child"}]
        assert payload["_embedded"]["public_key"] == private["public_key"]


def test_get_nested_file_from_public_folder(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: path selects a nested resource in a public folder."""
    folder_path = unique_child(sandbox_path, "public-nested-metadata")
    file_path = f"{folder_path}/nested/file.txt"
    disk_client.create_folder(folder_path)
    disk_client.create_folder(f"{folder_path}/nested")
    original = upload_test_file(disk_client, file_path, b"nested public file")

    with temporarily_published_resource(disk_client, folder_path) as private:
        metadata = wait_for_public_resource_state(
            public_disk_client,
            str(private["public_key"]),
            path="/nested/file.txt",
            present=True,
        )

        assert metadata is not None
        assert metadata["path"] == "/nested/file.txt"
        assert metadata["name"] == "file.txt"
        assert metadata["md5"] == original["md5"]


def test_get_public_folder_pagination(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive boundary: limit and offset split public folder children."""
    folder_path = unique_child(sandbox_path, "public-metadata-pages")
    disk_client.create_folder(folder_path)
    for index in range(4):
        disk_client.create_folder(f"{folder_path}/item-{index}")

    with temporarily_published_resource(disk_client, folder_path) as private:
        public_key = str(private["public_key"])
        wait_for_public_resource_state(
            public_disk_client,
            public_key,
            present=True,
        )
        first = public_disk_client.get_public_resource(
            public_key,
            limit=2,
            offset=0,
            sort="name",
        ).json()["_embedded"]
        second = public_disk_client.get_public_resource(
            public_key,
            limit=2,
            offset=2,
            sort="name",
        ).json()["_embedded"]
        first_names = {item["name"] for item in first["items"]}
        second_names = {item["name"] for item in second["items"]}

        assert first["total"] == second["total"] == 4
        assert first["limit"] == second["limit"] == 2
        assert first["offset"] == 0
        assert second["offset"] == 2
        assert first_names.isdisjoint(second_names)


def test_get_public_folder_sorts_children_by_name(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Positive: sort=name orders nested public resources."""
    folder_path = unique_child(sandbox_path, "public-metadata-sort")
    disk_client.create_folder(folder_path)
    expected_names = ["alpha", "middle", "zeta"]
    for name in reversed(expected_names):
        disk_client.create_folder(f"{folder_path}/{name}")

    with temporarily_published_resource(disk_client, folder_path) as private:
        public_key = str(private["public_key"])
        wait_for_public_resource_state(
            public_disk_client,
            public_key,
            present=True,
        )
        response = public_disk_client.get_public_resource(
            public_key,
            limit=100,
            sort="name",
        )
        names = [item["name"] for item in response.json()["_embedded"]["items"]]

        assert names == expected_names


def test_get_public_resource_supports_unicode_path(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: Unicode nested paths are returned intact."""
    folder_path = unique_child(sandbox_path, "public-unicode-root")
    nested_path = f"{folder_path}/юникод имя"
    disk_client.create_folder(folder_path)
    disk_client.create_folder(nested_path)

    with temporarily_published_resource(disk_client, folder_path) as private:
        metadata = wait_for_public_resource_state(
            public_disk_client,
            str(private["public_key"]),
            path="/юникод имя",
            present=True,
        )

        assert metadata is not None
        assert metadata["path"] == "/юникод имя"
        assert metadata["name"] == "юникод имя"


def test_get_public_folder_large_offset_returns_empty_page(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Edge case: an offset beyond total returns an empty items list."""
    folder_path = unique_child(sandbox_path, "public-large-offset")
    disk_client.create_folder(folder_path)

    with temporarily_published_resource(disk_client, folder_path) as private:
        public_key = str(private["public_key"])
        wait_for_public_resource_state(
            public_disk_client,
            public_key,
            present=True,
        )
        embedded = public_disk_client.get_public_resource(
            public_key,
            limit=1,
            offset=1_000_000,
        ).json()["_embedded"]

        assert embedded["offset"] == 1_000_000
        assert embedded["items"] == []


@pytest.mark.parametrize("parameter", ["limit", "offset"])
def test_get_public_resource_rejects_non_numeric_pagination(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
    parameter: str,
) -> None:
    """Negative: limit and offset must be numeric."""
    folder_path = unique_child(sandbox_path, f"public-invalid-{parameter}")
    disk_client.create_folder(folder_path)

    with temporarily_published_resource(disk_client, folder_path) as private:
        kwargs = {
            parameter: "not-a-number",
            "expected_statuses": {400},
        }
        response = public_disk_client.get_public_resource(
            str(private["public_key"]),
            **kwargs,
        )

        assert_error_response(response, requests.codes.bad_request)


def test_get_public_resource_without_key_returns_400(
    public_disk_client: YandexDiskClient,
) -> None:
    """Negative: public_key is required even without OAuth."""
    response = public_disk_client.get_public_resource(
        None,
        expected_statuses={400},
    )

    assert_error_response(response, requests.codes.bad_request)


def test_get_public_resource_rejects_malformed_key(
    public_disk_client: YandexDiskClient,
) -> None:
    """Negative: an explicitly empty public key is invalid."""
    response = public_disk_client.get_public_resource(
        "",
        expected_statuses={400},
    )

    assert_error_response(response, requests.codes.bad_request)


def test_get_public_resource_unknown_key_returns_404(
    public_disk_client: YandexDiskClient,
) -> None:
    """Negative: a well-formed but unknown key does not resolve."""
    response = public_disk_client.get_public_resource(
        "not-a-public-key",
        expected_statuses={404},
    )

    payload = assert_error_response(response, requests.codes.not_found)
    assert payload["error"] == "DiskNotFoundError"


def test_get_missing_path_in_public_folder_returns_404(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative: path must exist inside the published folder."""
    folder_path = unique_child(sandbox_path, "public-missing-path")
    disk_client.create_folder(folder_path)

    with temporarily_published_resource(disk_client, folder_path) as private:
        wait_for_public_resource_state(
            public_disk_client,
            str(private["public_key"]),
            present=True,
        )
        response = public_disk_client.get_public_resource(
            str(private["public_key"]),
            path="/missing.txt",
            expected_statuses={404},
        )

        assert_error_response(response, requests.codes.not_found)


def test_revoked_public_key_returns_404(
    disk_client: YandexDiskClient,
    public_disk_client: YandexDiskClient,
    sandbox_path: str,
) -> None:
    """Negative edge: an unpublished key no longer resolves metadata."""
    folder_path = unique_child(sandbox_path, "public-revoked-key")
    disk_client.create_folder(folder_path)
    disk_client.publish_resource(folder_path)
    private = wait_for_publication_state(
        disk_client,
        folder_path,
        published=True,
    )
    public_key = str(private["public_key"])
    wait_for_public_resource_state(
        public_disk_client,
        public_key,
        present=True,
    )

    disk_client.unpublish_resource(folder_path)
    wait_for_publication_state(disk_client, folder_path, published=False)

    assert (
        wait_for_public_resource_state(
            public_disk_client,
            public_key,
            present=False,
        )
        is None
    )
