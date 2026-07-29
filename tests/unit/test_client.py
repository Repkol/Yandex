"""Unit tests for request construction and error handling."""

from __future__ import annotations

from unittest.mock import Mock

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


def test_get_disk_info_sends_get(client: YandexDiskClient, session: Mock) -> None:
    session.request.return_value = make_response(200, '{"total_space": 10}')

    response = client.get_disk_info()

    assert response.json()["total_space"] == 10
    session.request.assert_called_once_with(
        "GET",
        BASE_URL,
        timeout=15.0,
    )


def test_create_folder_sends_put(client: YandexDiskClient, session: Mock) -> None:
    session.request.return_value = make_response(201)

    client.create_folder("disk:/api-tests/new")

    session.request.assert_called_once_with(
        "PUT",
        f"{BASE_URL}/resources",
        timeout=15.0,
        params={"path": "disk:/api-tests/new"},
    )


def test_copy_resource_sends_post(client: YandexDiskClient, session: Mock) -> None:
    session.request.return_value = make_response(201)

    client.copy_resource("disk:/source", "disk:/copy")

    session.request.assert_called_once_with(
        "POST",
        f"{BASE_URL}/resources/copy",
        timeout=15.0,
        params={
            "from": "disk:/source",
            "path": "disk:/copy",
            "overwrite": "false",
        },
    )


def test_delete_resource_sends_delete(
    client: YandexDiskClient,
    session: Mock,
) -> None:
    session.request.return_value = make_response(204, "")

    client.delete_resource("disk:/obsolete")

    session.request.assert_called_once_with(
        "DELETE",
        f"{BASE_URL}/resources",
        timeout=15.0,
        params={"path": "disk:/obsolete", "permanently": "true"},
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
