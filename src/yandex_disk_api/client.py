"""HTTP client for the endpoints exercised by the test project."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

import requests


def _query_params(**values: str | int | bool | None) -> dict[str, str | int]:
    """Drop unset values and serialize booleans as API query parameters."""
    return {
        name: str(value).lower() if isinstance(value, bool) else value
        for name, value in values.items()
        if value is not None
    }


class YandexDiskApiError(RuntimeError):
    """Raised when Yandex.Disk returns an unexpected HTTP status."""

    def __init__(self, method: str, url: str, response: requests.Response) -> None:
        self.method = method
        self.url = url
        self.status_code = response.status_code

        try:
            details = response.json()
        except requests.exceptions.JSONDecodeError:
            details = response.text[:500] or "<empty response>"

        super().__init__(
            f"{method} {url} returned HTTP {response.status_code}: {details}"
        )


class YandexDiskClient:
    """Minimal synchronous client for the Yandex.Disk REST API."""

    DEFAULT_BASE_URL = "https://cloud-api.yandex.net/v1/disk"

    def __init__(
        self,
        token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
        session: requests.Session | None = None,
    ) -> None:
        if not token.strip():
            raise ValueError("OAuth token must not be empty")

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"OAuth {token}",
                "Accept": "application/json",
                "User-Agent": "yandex-disk-api-tests/1.0",
            }
        )

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()

    def __enter__(self) -> YandexDiskClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        expected_statuses: Collection[int],
        **kwargs: Any,
    ) -> requests.Response:
        url = f"{self.base_url}{endpoint}"
        response = self.session.request(
            method,
            url,
            timeout=self.timeout,
            **kwargs,
        )
        if response.status_code not in expected_statuses:
            raise YandexDiskApiError(method, url, response)
        return response

    def get_disk_info(self) -> requests.Response:
        """GET information about the authenticated user's Disk."""
        return self._request("GET", "", expected_statuses={200})

    def get_resource(
        self,
        path: str | None,
        *,
        fields: str | None = None,
        limit: int | str | None = None,
        offset: int | None = None,
        preview_crop: bool | None = None,
        preview_size: str | None = None,
        sort: str | None = None,
        expected_statuses: Collection[int] = (200,),
    ) -> requests.Response:
        """GET metadata for a file or directory."""
        return self._request(
            "GET",
            "/resources",
            expected_statuses=expected_statuses,
            params=_query_params(
                path=path,
                fields=fields,
                limit=limit,
                offset=offset,
                preview_crop=preview_crop,
                preview_size=preview_size,
                sort=sort,
            ),
        )

    def create_folder(self, path: str) -> requests.Response:
        """PUT a new directory at ``path``."""
        return self._request(
            "PUT",
            "/resources",
            expected_statuses={201},
            params={"path": path},
        )

    def copy_resource(
        self,
        source_path: str,
        destination_path: str,
        *,
        overwrite: bool = False,
    ) -> requests.Response:
        """POST a request to copy a file or directory."""
        return self._request(
            "POST",
            "/resources/copy",
            expected_statuses={201, 202},
            params={
                "from": source_path,
                "path": destination_path,
                "overwrite": str(overwrite).lower(),
            },
        )

    def delete_resource(
        self,
        path: str | None,
        *,
        fields: str | None = None,
        force_async: bool | None = None,
        md5: str | None = None,
        permanently: bool | None = None,
        expected_statuses: Collection[int] = (202, 204),
    ) -> requests.Response:
        """DELETE a file or directory."""
        return self._request(
            "DELETE",
            "/resources",
            expected_statuses=expected_statuses,
            params=_query_params(
                path=path,
                fields=fields,
                force_async=force_async,
                md5=md5,
                permanently=permanently,
            ),
        )

    def get_upload_link(
        self,
        path: str,
        *,
        overwrite: bool = True,
    ) -> requests.Response:
        """GET a one-time URL used by test fixtures to upload a file."""
        return self._request(
            "GET",
            "/resources/upload",
            expected_statuses={200},
            params=_query_params(path=path, overwrite=overwrite),
        )

    def get_trash_resource(
        self,
        path: str,
        *,
        limit: int | None = None,
        offset: int | None = None,
        expected_statuses: Collection[int] = (200,),
    ) -> requests.Response:
        """GET metadata for a resource moved to the Trash."""
        return self._request(
            "GET",
            "/trash/resources",
            expected_statuses=expected_statuses,
            params=_query_params(path=path, limit=limit, offset=offset),
        )

    def delete_trash_resource(
        self,
        path: str,
        *,
        force_async: bool = True,
    ) -> requests.Response:
        """Permanently DELETE one test resource from the Trash."""
        return self._request(
            "DELETE",
            "/trash/resources",
            expected_statuses={202, 204},
            params=_query_params(path=path, force_async=force_async),
        )

    def get_operation(
        self,
        operation_url: str,
        *,
        expected_statuses: Collection[int] = (200,),
    ) -> requests.Response:
        """GET the state of an asynchronous operation."""
        response = self.session.request(
            "GET",
            operation_url,
            timeout=self.timeout,
        )
        if response.status_code not in expected_statuses:
            raise YandexDiskApiError("GET", operation_url, response)
        return response
