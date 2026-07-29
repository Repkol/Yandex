"""HTTP client for the endpoints exercised by the test project."""

from __future__ import annotations

import time
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
        token: str | None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
        session: requests.Session | None = None,
    ) -> None:
        if token is not None and not token.strip():
            raise ValueError("OAuth token must not be empty")

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        headers = {
            "Accept": "application/json",
            "User-Agent": "yandex-disk-api-tests/1.0",
        }
        if token is not None:
            headers["Authorization"] = f"OAuth {token}"
        self.session.headers.update(headers)

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
        transient_statuses = {429, 500, 503}
        for attempt in range(3):
            response = self.session.request(
                method,
                url,
                timeout=self.timeout,
                **kwargs,
            )
            if response.status_code in expected_statuses:
                return response
            should_retry = (
                method.upper() == "GET"
                and response.status_code in transient_statuses
                and attempt < 2
            )
            if not should_retry:
                break
            time.sleep(0.5 * (2**attempt))

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

    def list_files(
        self,
        *,
        fields: str | None = None,
        limit: int | str | None = None,
        media_type: str | None = None,
        offset: int | str | None = None,
        preview_crop: bool | None = None,
        preview_size: str | None = None,
        sort: str | None = None,
        expected_statuses: Collection[int] = (200,),
    ) -> requests.Response:
        """GET the flat list of files on Disk."""
        return self._request(
            "GET",
            "/resources/files",
            expected_statuses=expected_statuses,
            params=_query_params(
                fields=fields,
                limit=limit,
                media_type=media_type,
                offset=offset,
                preview_crop=preview_crop,
                preview_size=preview_size,
                sort=sort,
            ),
        )

    def list_last_uploaded(
        self,
        *,
        fields: str | None = None,
        limit: int | str | None = None,
        media_type: str | None = None,
        preview_crop: bool | None = None,
        preview_size: str | None = None,
        expected_statuses: Collection[int] = (200,),
    ) -> requests.Response:
        """GET files ordered from newest to oldest upload."""
        return self._request(
            "GET",
            "/resources/last-uploaded",
            expected_statuses=expected_statuses,
            params=_query_params(
                fields=fields,
                limit=limit,
                media_type=media_type,
                preview_crop=preview_crop,
                preview_size=preview_size,
            ),
        )

    def list_public_resources(
        self,
        *,
        fields: str | None = None,
        limit: int | str | None = None,
        offset: int | str | None = None,
        preview_crop: bool | None = None,
        preview_size: str | None = None,
        resource_type: str | None = None,
        expected_statuses: Collection[int] = (200,),
    ) -> requests.Response:
        """GET resources that have a public link."""
        params = _query_params(
            fields=fields,
            limit=limit,
            offset=offset,
            preview_crop=preview_crop,
            preview_size=preview_size,
        )
        if resource_type is not None:
            params["type"] = resource_type

        return self._request(
            "GET",
            "/resources/public",
            expected_statuses=expected_statuses,
            params=params,
        )

    def get_public_resource(
        self,
        public_key: str | None,
        *,
        fields: str | None = None,
        limit: int | str | None = None,
        offset: int | str | None = None,
        path: str | None = None,
        preview_crop: bool | None = None,
        preview_size: str | None = None,
        sort: str | None = None,
        expected_statuses: Collection[int] = (200,),
    ) -> requests.Response:
        """GET public metadata using a public key or public URL."""
        return self._request(
            "GET",
            "/public/resources",
            expected_statuses=expected_statuses,
            params=_query_params(
                public_key=public_key,
                fields=fields,
                limit=limit,
                offset=offset,
                path=path,
                preview_crop=preview_crop,
                preview_size=preview_size,
                sort=sort,
            ),
        )

    def get_public_download_link(
        self,
        public_key: str | None,
        *,
        fields: str | None = None,
        path: str | None = None,
        expected_statuses: Collection[int] = (200,),
    ) -> requests.Response:
        """GET a direct download link for a public resource."""
        return self._request(
            "GET",
            "/public/resources/download",
            expected_statuses=expected_statuses,
            params=_query_params(
                public_key=public_key,
                fields=fields,
                path=path,
            ),
        )

    def create_folder(
        self,
        path: str | None,
        *,
        fields: str | None = None,
        expected_statuses: Collection[int] = (201,),
    ) -> requests.Response:
        """PUT a new directory at ``path``."""
        return self._request(
            "PUT",
            "/resources",
            expected_statuses=expected_statuses,
            params=_query_params(path=path, fields=fields),
        )

    def update_resource(
        self,
        path: str | None,
        body: object,
        *,
        fields: str | None = None,
        content_type: str = "application/json",
        expected_statuses: Collection[int] = (200,),
    ) -> requests.Response:
        """PATCH user-defined resource properties."""
        request_body: dict[str, object]
        if content_type == "application/json":
            request_body = {"json": body}
        else:
            request_body = {
                "data": body,
                "headers": {"Content-Type": content_type},
            }

        return self._request(
            "PATCH",
            "/resources",
            expected_statuses=expected_statuses,
            params=_query_params(path=path, fields=fields),
            **request_body,
        )

    def copy_resource(
        self,
        source_path: str | None,
        destination_path: str | None,
        *,
        fields: str | None = None,
        force_async: bool | None = None,
        overwrite: bool | None = None,
        expected_statuses: Collection[int] = (201, 202),
    ) -> requests.Response:
        """POST a request to copy a file or directory."""
        params = _query_params(
            path=destination_path,
            fields=fields,
            force_async=force_async,
            overwrite=overwrite,
        )
        if source_path is not None:
            params["from"] = source_path

        return self._request(
            "POST",
            "/resources/copy",
            expected_statuses=expected_statuses,
            params=params,
        )

    def move_resource(
        self,
        source_path: str | None,
        destination_path: str | None,
        *,
        fields: str | None = None,
        force_async: bool | None = None,
        overwrite: bool | None = None,
        expected_statuses: Collection[int] = (201, 202),
    ) -> requests.Response:
        """POST a request to move a file or directory."""
        params = _query_params(
            path=destination_path,
            fields=fields,
            force_async=force_async,
            overwrite=overwrite,
        )
        if source_path is not None:
            params["from"] = source_path

        return self._request(
            "POST",
            "/resources/move",
            expected_statuses=expected_statuses,
            params=params,
        )

    def get_download_link(
        self,
        path: str | None,
        *,
        fields: str | None = None,
        expected_statuses: Collection[int] = (200,),
    ) -> requests.Response:
        """GET a temporary direct download link for a file."""
        return self._request(
            "GET",
            "/resources/download",
            expected_statuses=expected_statuses,
            params=_query_params(path=path, fields=fields),
        )

    def publish_resource(
        self,
        path: str | None,
        *,
        allow_address_access: bool | None = None,
        fields: str | None = None,
        body: object | None = None,
        content_type: str = "application/json",
        expected_statuses: Collection[int] = (200,),
    ) -> requests.Response:
        """PUT a public link and optional public settings on a resource."""
        request_body: dict[str, object] = {}
        if body is not None:
            if content_type == "application/json":
                request_body["json"] = body
            else:
                request_body.update(
                    {
                        "data": body,
                        "headers": {"Content-Type": content_type},
                    }
                )

        return self._request(
            "PUT",
            "/resources/publish",
            expected_statuses=expected_statuses,
            params=_query_params(
                path=path,
                allow_address_access=allow_address_access,
                fields=fields,
            ),
            **request_body,
        )

    def unpublish_resource(
        self,
        path: str | None,
        *,
        fields: str | None = None,
        expected_statuses: Collection[int] = (200,),
    ) -> requests.Response:
        """PUT removal of a public link from one test resource."""
        return self._request(
            "PUT",
            "/resources/unpublish",
            expected_statuses=expected_statuses,
            params=_query_params(path=path, fields=fields),
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
        path: str | None,
        *,
        fields: str | None = None,
        overwrite: bool | None = None,
        expected_statuses: Collection[int] = (200,),
    ) -> requests.Response:
        """GET a temporary URL used to upload local file content."""
        return self._request(
            "GET",
            "/resources/upload",
            expected_statuses=expected_statuses,
            params=_query_params(
                path=path,
                fields=fields,
                overwrite=overwrite,
            ),
        )

    def upload_resource_from_url(
        self,
        path: str | None,
        source_url: str | None,
        *,
        disable_redirects: bool | None = None,
        fields: str | None = None,
        expected_statuses: Collection[int] = (202,),
    ) -> requests.Response:
        """POST an asynchronous import from an external URL."""
        return self._request(
            "POST",
            "/resources/upload",
            expected_statuses=expected_statuses,
            params=_query_params(
                path=path,
                url=source_url,
                disable_redirects=disable_redirects,
                fields=fields,
            ),
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
