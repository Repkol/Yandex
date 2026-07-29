"""Positive, negative and edge cases for GET /v1/disk."""

from __future__ import annotations

from datetime import datetime

import pytest
import requests

from yandex_disk_api import YandexDiskClient

from .conftest import assert_error_response

pytestmark = pytest.mark.integration

CORE_FIELDS = {
    "total_space",
    "used_space",
    "trash_size",
    "max_file_size",
    "system_folders",
    "is_paid",
    "revision",
    "user",
}

CAPACITY_FIELDS = {
    "total_space",
    "used_space",
    "trash_size",
    "max_file_size",
    "paid_max_file_size",
    "photounlim_size",
    "disk_size",
    "monthly_traffic_limit",
}


def assert_non_negative_integer(value: object) -> None:
    """Check an API integer without accepting bool, which subclasses int."""
    assert type(value) is int
    assert value >= 0


def assert_iso_datetime(value: object) -> None:
    """Check that a response value is an ISO-8601 timestamp."""
    assert isinstance(value, str)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


def test_get_disk_info_happy_path_returns_consistent_schema(
    disk_client: YandexDiskClient,
) -> None:
    """Happy Path: return account, capacity and system-folder metadata."""
    response = disk_client.get_disk_info()
    payload = response.json()

    assert response.status_code == requests.codes.ok
    assert response.headers["Content-Type"].startswith("application/json")
    assert CORE_FIELDS <= payload.keys()

    for field in CAPACITY_FIELDS & payload.keys():
        assert_non_negative_integer(payload[field])

    assert 0 <= payload["used_space"] <= payload["total_space"]
    assert payload["trash_size"] <= payload["total_space"]
    assert_non_negative_integer(payload["revision"])
    assert isinstance(payload["is_paid"], bool)

    system_folders = payload["system_folders"]
    assert isinstance(system_folders, dict)
    assert isinstance(system_folders["downloads"], str)
    assert system_folders["downloads"].startswith("disk:/")

    user = payload["user"]
    assert isinstance(user, dict)
    assert isinstance(user["uid"], str)
    assert user["uid"]
    assert isinstance(user["login"], str)
    assert user["login"]
    assert isinstance(user["display_name"], str)

    assert_iso_datetime(payload["reg_time"])


def test_get_disk_info_fields_limits_top_level_response(
    disk_client: YandexDiskClient,
) -> None:
    """Positive: fields limits the response to requested top-level values."""
    response = disk_client.get_disk_info(
        fields="total_space,used_space,trash_size,is_paid",
    )

    assert response.status_code == requests.codes.ok
    payload = response.json()
    assert set(payload) == {
        "total_space",
        "used_space",
        "trash_size",
        "is_paid",
    }
    assert 0 <= payload["used_space"] <= payload["total_space"]
    assert payload["trash_size"] <= payload["total_space"]
    assert isinstance(payload["is_paid"], bool)


def test_get_disk_info_fields_supports_nested_attributes(
    disk_client: YandexDiskClient,
) -> None:
    """Positive: fields projects nested user and system-folder attributes."""
    response = disk_client.get_disk_info(
        fields="user.uid,user.login,system_folders.downloads",
    )

    assert response.status_code == requests.codes.ok
    payload = response.json()
    assert set(payload) == {"user", "system_folders"}
    assert set(payload["user"]) == {"uid", "login"}
    assert set(payload["system_folders"]) == {"downloads"}


def test_get_disk_info_accepts_extra_fields(
    disk_client: YandexDiskClient,
) -> None:
    """Positive: extra_fields is accepted without losing the base schema."""
    response = disk_client.get_disk_info(
        extra_fields="disk_size,file_size_limit_upgrades",
    )

    assert response.status_code == requests.codes.ok
    payload = response.json()
    assert CORE_FIELDS <= payload.keys()
    assert_non_negative_integer(payload["disk_size"])
    upgrades = payload["file_size_limit_upgrades"]
    assert isinstance(upgrades, dict)
    for value in upgrades.values():
        assert_non_negative_integer(value)


def test_get_disk_info_repeated_reads_keep_account_identity(
    disk_client: YandexDiskClient,
) -> None:
    """Edge: repeated read-only calls return stable account identity."""
    fields = "user.uid,user.login,total_space"

    first = disk_client.get_disk_info(fields=fields).json()
    second = disk_client.get_disk_info(fields=fields).json()

    assert first == second


def test_get_disk_info_empty_fields_returns_default_response(
    disk_client: YandexDiskClient,
) -> None:
    """Edge: an empty fields value behaves like an omitted projection."""
    response = disk_client.get_disk_info(fields="")

    assert response.status_code == requests.codes.ok
    assert CORE_FIELDS <= response.json().keys()


def test_get_disk_info_unknown_fields_returns_default_response(
    disk_client: YandexDiskClient,
) -> None:
    """Edge: a wholly unknown fields projection is ignored by the live API."""
    response = disk_client.get_disk_info(fields="unknown_field")

    assert response.status_code == requests.codes.ok
    payload = response.json()
    assert CORE_FIELDS <= payload.keys()
    assert "unknown_field" not in payload


def test_get_disk_info_duplicate_fields_are_deduplicated(
    disk_client: YandexDiskClient,
) -> None:
    """Edge: duplicate field names do not duplicate or expand the response."""
    response = disk_client.get_disk_info(
        fields="total_space,total_space,used_space",
    )

    assert response.status_code == requests.codes.ok
    assert set(response.json()) == {"total_space", "used_space"}


def test_get_disk_info_unknown_extra_fields_are_ignored(
    disk_client: YandexDiskClient,
) -> None:
    """Edge: an unknown extra_fields value does not appear in the response."""
    response = disk_client.get_disk_info(extra_fields="unknown_field")

    assert response.status_code == requests.codes.ok
    payload = response.json()
    assert CORE_FIELDS <= payload.keys()
    assert "unknown_field" not in payload


def test_get_disk_info_with_invalid_token_returns_401(
    unauthorized_disk_client: YandexDiskClient,
) -> None:
    """Negative: a malformed OAuth credential is rejected."""
    response = unauthorized_disk_client.get_disk_info(expected_statuses={401})

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"


def test_get_disk_info_without_authorization_returns_401(
    public_disk_client: YandexDiskClient,
) -> None:
    """Negative: this private endpoint cannot be called without OAuth."""
    response = public_disk_client.get_disk_info(expected_statuses={401})

    payload = assert_error_response(response, requests.codes.unauthorized)
    assert payload["error"] == "UnauthorizedError"
