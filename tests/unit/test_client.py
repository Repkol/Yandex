"""Unit tests for request construction and error handling."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from yandex_disk_api import YandexDiskApiError, YandexDiskClient

TOKEN = "test-token"
BASE_URL = "https://example.test/v1/disk"


def make_response(
    status_code: int,
    payload: str = "{}",
    *,
    content_type: str = "application/json",
) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = payload.encode()
    response.headers["Content-Type"] = content_type
    return response


@pytest.fixture
def session() -> Mock:
    mocked_session = Mock(spec=requests.Session)
    mocked_session.headers = {}
    return mocked_session


@pytest.fixture
def client(session: Mock) -> YandexDiskClient:
    return YandexDiskClient(TOKEN, base_url=BASE_URL, session=session)


def test_client_sets_safe_default_headers(session: Mock) -> None:
    YandexDiskClient(TOKEN, base_url=BASE_URL, session=session)

    assert session.headers == {
        "Authorization": "OAuth test-token",
        "Accept": "application/json",
        "User-Agent": "yandex-disk-api-tests/1.0",
    }


def test_public_client_omits_authorization_header(session: Mock) -> None:
    YandexDiskClient(None, base_url=BASE_URL, session=session)

    assert session.headers == {
        "Accept": "application/json",
        "User-Agent": "yandex-disk-api-tests/1.0",
    }


def test_get_disk_info_sends_get(client: YandexDiskClient, session: Mock) -> None:
    session.request.return_value = make_response(200, '{"total_space": 10}')

    response = client.get_disk_info()

    assert response.json()["total_space"] == 10
    session.request.assert_called_once_with(
        "GET",
        BASE_URL,
        timeout=15.0,
    )


def test_get_retries_transient_service_error(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.side_effect = [
        make_response(503),
        make_response(200, '{"total_space": 10}'),
    ]

    with patch("yandex_disk_api.client.time.sleep") as sleep:
        response = client.get_disk_info()

    assert response.status_code == requests.codes.ok
    assert session.request.call_count == 2
    sleep.assert_called_once_with(0.5)


def test_create_folder_sends_put(client: YandexDiskClient, session: Mock) -> None:
    session.request.return_value = make_response(201)

    client.create_folder("disk:/api-tests/new", fields="href,method")

    session.request.assert_called_once_with(
        "PUT",
        f"{BASE_URL}/resources",
        timeout=15.0,
        params={
            "path": "disk:/api-tests/new",
            "fields": "href,method",
        },
    )


def test_update_resource_sends_patch_with_json_body(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(200)
    body = {"custom_properties": {"status": "ready"}}

    client.update_resource(
        "disk:/api-tests/resource",
        body,
        fields="path,custom_properties",
    )

    session.request.assert_called_once_with(
        "PATCH",
        f"{BASE_URL}/resources",
        timeout=15.0,
        params={
            "path": "disk:/api-tests/resource",
            "fields": "path,custom_properties",
        },
        json=body,
    )


def test_update_resource_can_send_unsupported_content_type_for_negative_case(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(415)

    client.update_resource(
        "disk:/api-tests/resource",
        "{}",
        content_type="text/plain",
        expected_statuses={415},
    )

    session.request.assert_called_once_with(
        "PATCH",
        f"{BASE_URL}/resources",
        timeout=15.0,
        params={"path": "disk:/api-tests/resource"},
        data="{}",
        headers={"Content-Type": "text/plain"},
    )


def test_get_resource_sends_optional_query_parameters(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(200)

    client.get_resource(
        "disk:/folder",
        fields="name,type",
        limit=10,
        offset=2,
        preview_crop=True,
        preview_size="S",
        sort="-modified",
    )

    session.request.assert_called_once_with(
        "GET",
        f"{BASE_URL}/resources",
        timeout=15.0,
        params={
            "path": "disk:/folder",
            "fields": "name,type",
            "limit": 10,
            "offset": 2,
            "preview_crop": "true",
            "preview_size": "S",
            "sort": "-modified",
        },
    )


def test_list_files_sends_all_query_parameters(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(200)

    client.list_files(
        fields="limit,items.name",
        limit=10,
        media_type="image",
        offset=2,
        preview_crop=True,
        preview_size="S",
        sort="-modified",
    )

    session.request.assert_called_once_with(
        "GET",
        f"{BASE_URL}/resources/files",
        timeout=15.0,
        params={
            "fields": "limit,items.name",
            "limit": 10,
            "media_type": "image",
            "offset": 2,
            "preview_crop": "true",
            "preview_size": "S",
            "sort": "-modified",
        },
    )


def test_list_last_uploaded_sends_all_query_parameters(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(200)

    client.list_last_uploaded(
        fields="limit,items.name",
        limit=5,
        media_type="video",
        preview_crop=False,
        preview_size="M",
    )

    session.request.assert_called_once_with(
        "GET",
        f"{BASE_URL}/resources/last-uploaded",
        timeout=15.0,
        params={
            "fields": "limit,items.name",
            "limit": 5,
            "media_type": "video",
            "preview_crop": "false",
            "preview_size": "M",
        },
    )


def test_list_public_resources_sends_all_query_parameters(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(200)

    client.list_public_resources(
        fields="limit,items.name",
        limit=5,
        offset=2,
        preview_crop=True,
        preview_size="S",
        resource_type="file",
    )

    session.request.assert_called_once_with(
        "GET",
        f"{BASE_URL}/resources/public",
        timeout=15.0,
        params={
            "fields": "limit,items.name",
            "limit": 5,
            "offset": 2,
            "preview_crop": "true",
            "preview_size": "S",
            "type": "file",
        },
    )


def test_get_public_resource_sends_all_query_parameters(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(200)

    client.get_public_resource(
        "public-key",
        fields="name,_embedded.items.name",
        limit=5,
        offset=2,
        path="/nested",
        preview_crop=True,
        preview_size="S",
        sort="-name",
    )

    session.request.assert_called_once_with(
        "GET",
        f"{BASE_URL}/public/resources",
        timeout=15.0,
        params={
            "public_key": "public-key",
            "fields": "name,_embedded.items.name",
            "limit": 5,
            "offset": 2,
            "path": "/nested",
            "preview_crop": "true",
            "preview_size": "S",
            "sort": "-name",
        },
    )


def test_get_public_download_link_sends_get(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(200)

    client.get_public_download_link(
        "public-key",
        fields="href,method",
        path="/nested/file.txt",
    )

    session.request.assert_called_once_with(
        "GET",
        f"{BASE_URL}/public/resources/download",
        timeout=15.0,
        params={
            "public_key": "public-key",
            "fields": "href,method",
            "path": "/nested/file.txt",
        },
    )


def test_update_public_settings_sends_patch(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(200)
    body = {"available_until": 0}

    client.update_public_settings(
        "disk:/shared",
        body,
        fields="available_until",
    )

    session.request.assert_called_once_with(
        "PATCH",
        f"{BASE_URL}/public/resources/public-settings",
        timeout=15.0,
        params={
            "path": "disk:/shared",
            "fields": "available_until",
        },
        json=body,
    )


def test_update_public_settings_can_send_unsupported_content_type(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(415)

    client.update_public_settings(
        "disk:/shared",
        "not-json",
        content_type="text/plain",
        expected_statuses={415},
    )

    session.request.assert_called_once_with(
        "PATCH",
        f"{BASE_URL}/public/resources/public-settings",
        timeout=15.0,
        params={"path": "disk:/shared"},
        data="not-json",
        headers={"Content-Type": "text/plain"},
    )


def test_save_public_resource_to_disk_sends_all_parameters(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(202)

    client.save_public_resource_to_disk(
        "public-key",
        fields="href,method",
        force_async=True,
        name="saved.txt",
        path="/nested/source.txt",
        save_path="disk:/api-tests/destination",
    )

    session.request.assert_called_once_with(
        "POST",
        f"{BASE_URL}/public/resources/save-to-disk",
        timeout=15.0,
        params={
            "public_key": "public-key",
            "fields": "href,method",
            "force_async": "true",
            "name": "saved.txt",
            "path": "/nested/source.txt",
            "save_path": "disk:/api-tests/destination",
        },
    )


def test_copy_resource_sends_post(client: YandexDiskClient, session: Mock) -> None:
    session.request.return_value = make_response(201)

    client.copy_resource(
        "disk:/source",
        "disk:/copy",
        fields="href,method",
        force_async=True,
        overwrite=True,
    )

    session.request.assert_called_once_with(
        "POST",
        f"{BASE_URL}/resources/copy",
        timeout=15.0,
        params={
            "path": "disk:/copy",
            "fields": "href,method",
            "force_async": "true",
            "overwrite": "true",
            "from": "disk:/source",
        },
    )


def test_move_resource_sends_post(client: YandexDiskClient, session: Mock) -> None:
    session.request.return_value = make_response(202)

    client.move_resource(
        "disk:/source",
        "disk:/destination",
        fields="href,method",
        force_async=True,
        overwrite=True,
    )

    session.request.assert_called_once_with(
        "POST",
        f"{BASE_URL}/resources/move",
        timeout=15.0,
        params={
            "path": "disk:/destination",
            "fields": "href,method",
            "force_async": "true",
            "overwrite": "true",
            "from": "disk:/source",
        },
    )


def test_get_download_link_sends_get(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(200)

    client.get_download_link(
        "disk:/fixture.txt",
        fields="href,method",
    )

    session.request.assert_called_once_with(
        "GET",
        f"{BASE_URL}/resources/download",
        timeout=15.0,
        params={
            "path": "disk:/fixture.txt",
            "fields": "href,method",
        },
    )


@pytest.mark.parametrize(
    ("method_name", "endpoint"),
    [
        ("publish_resource", "/resources/publish"),
        ("unpublish_resource", "/resources/unpublish"),
    ],
)
def test_publication_methods_send_put(
    client: YandexDiskClient,
    session: Mock,
    method_name: str,
    endpoint: str,
) -> None:
    session.request.return_value = make_response(200)

    method = getattr(client, method_name)
    method("disk:/public-resource", fields="href,method")

    session.request.assert_called_once_with(
        "PUT",
        f"{BASE_URL}{endpoint}",
        timeout=15.0,
        params={
            "path": "disk:/public-resource",
            "fields": "href,method",
        },
    )


def test_publish_resource_sends_settings_and_address_access(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(200)
    body = {"public_settings": {"read_only": True}}

    client.publish_resource(
        "disk:/public-resource",
        allow_address_access=True,
        fields="href,method",
        body=body,
    )

    session.request.assert_called_once_with(
        "PUT",
        f"{BASE_URL}/resources/publish",
        timeout=15.0,
        params={
            "path": "disk:/public-resource",
            "allow_address_access": "true",
            "fields": "href,method",
        },
        json=body,
    )


def test_publish_resource_can_send_unsupported_content_type(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(415)

    client.publish_resource(
        "disk:/public-resource",
        body="not-json",
        content_type="text/plain",
        expected_statuses={415},
    )

    session.request.assert_called_once_with(
        "PUT",
        f"{BASE_URL}/resources/publish",
        timeout=15.0,
        params={"path": "disk:/public-resource"},
        data="not-json",
        headers={"Content-Type": "text/plain"},
    )


def test_get_upload_link_sends_all_query_parameters(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(200)

    client.get_upload_link(
        "disk:/upload.txt",
        fields="href,method",
        overwrite=True,
    )

    session.request.assert_called_once_with(
        "GET",
        f"{BASE_URL}/resources/upload",
        timeout=15.0,
        params={
            "path": "disk:/upload.txt",
            "fields": "href,method",
            "overwrite": "true",
        },
    )


def test_upload_resource_from_url_sends_post(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(202)

    client.upload_resource_from_url(
        "disk:/remote.txt",
        "https://example.test/source.txt",
        disable_redirects=True,
        fields="href,method",
    )

    session.request.assert_called_once_with(
        "POST",
        f"{BASE_URL}/resources/upload",
        timeout=15.0,
        params={
            "path": "disk:/remote.txt",
            "url": "https://example.test/source.txt",
            "disable_redirects": "true",
            "fields": "href,method",
        },
    )


def test_delete_resource_sends_delete(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(204, "")

    client.delete_resource(
        "disk:/obsolete",
        fields="href,method",
        force_async=True,
        md5="abc",
        permanently=True,
    )

    session.request.assert_called_once_with(
        "DELETE",
        f"{BASE_URL}/resources",
        timeout=15.0,
        params={
            "path": "disk:/obsolete",
            "fields": "href,method",
            "force_async": "true",
            "md5": "abc",
            "permanently": "true",
        },
    )


def test_delete_resource_omits_optional_parameters_by_default(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(204, "")

    client.delete_resource("disk:/to-trash")

    session.request.assert_called_once_with(
        "DELETE",
        f"{BASE_URL}/resources",
        timeout=15.0,
        params={"path": "disk:/to-trash"},
    )


def test_get_trash_resource_sends_all_parameters(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(200)

    client.get_trash_resource(
        "trash:/removed",
        fields="path,name",
        limit=10,
        offset=20,
        preview_crop=True,
        preview_size="M",
        sort="-deleted",
    )

    session.request.assert_called_once_with(
        "GET",
        f"{BASE_URL}/trash/resources",
        timeout=15.0,
        params={
            "path": "trash:/removed",
            "fields": "path,name",
            "limit": 10,
            "offset": 20,
            "preview_crop": "true",
            "preview_size": "M",
            "sort": "-deleted",
        },
    )


def test_get_trash_root_omits_path(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(200)

    client.get_trash_resource()

    session.request.assert_called_once_with(
        "GET",
        f"{BASE_URL}/trash/resources",
        timeout=15.0,
        params={},
    )


def test_delete_trash_resource_sends_all_parameters(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(202)

    client.delete_trash_resource(
        "trash:/removed",
        fields="href,method",
        force_async=True,
    )

    session.request.assert_called_once_with(
        "DELETE",
        f"{BASE_URL}/trash/resources",
        timeout=15.0,
        params={
            "path": "trash:/removed",
            "fields": "href,method",
            "force_async": "true",
        },
    )


def test_delete_trash_root_omits_path_without_live_request(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    """The destructive whole-Trash request is covered without calling the API."""
    session.request.return_value = make_response(204, "")

    client.delete_trash_resource()

    session.request.assert_called_once_with(
        "DELETE",
        f"{BASE_URL}/trash/resources",
        timeout=15.0,
        params={},
    )


def test_unexpected_status_raises_readable_error(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(
        401,
        '{"error": "UnauthorizedError", "message": "Unauthorized"}',
    )

    with pytest.raises(YandexDiskApiError) as error:
        client.get_disk_info()

    assert error.value.status_code == 401
    assert "UnauthorizedError" in str(error.value)
    assert TOKEN not in str(error.value)


def test_empty_token_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        YandexDiskClient("  ")
