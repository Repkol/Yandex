"""HTTP client for the endpoints exercised by the test project."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

import requests


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
        path: str,
        *,
        expected_statuses: Collection[int] = (200,),
    ) -> requests.Response:
        """GET metadata for a file or directory."""
        return self._request(
            "GET",
            "/resources",
            expected_statuses=expected_statuses,
            params={"path": path},
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
        path: str,
        *,
        permanently: bool = True,
    ) -> requests.Response:
        """DELETE a file or directory."""
        return self._request(
            "DELETE",
            "/resources",
            expected_statuses={202, 204},
            params={
                "path": path,
                "permanently": str(permanently).lower(),
            },
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
