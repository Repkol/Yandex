"""End-to-end checks against the live Yandex.Disk REST API."""

from __future__ import annotations

import pytest
import requests

from yandex_disk_api import YandexDiskClient

pytestmark = pytest.mark.integration


def test_get_disk_info(disk_client: YandexDiskClient) -> None:
    """GET /v1/disk returns consistent capacity information."""
    response = disk_client.get_disk_info()
    payload = response.json()

    assert response.status_code == requests.codes.ok
    assert isinstance(payload["total_space"], int)
    assert isinstance(payload["used_space"], int)
    assert 0 <= payload["used_space"] <= payload["total_space"]
