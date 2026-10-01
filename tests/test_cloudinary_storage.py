"""Le stockage Cloudinary doit renvoyer la ``secure_url`` réelle de la ressource."""

from __future__ import annotations

from unittest import mock

import pytest
from cloudinary.exceptions import NotFound
from cloudinary_storage import app_settings
from django.core.cache import cache
from django.core.files.base import ContentFile

from restaurants.core.storage import MISS_TTL
from restaurants.core.storage import SecureUrlCloudinaryStorage

SECURE_URL = (
    "https://res.cloudinary.com/demo/image/upload/v1756291702/media/meals/poulet"
)
PUBLIC_ID = "media/meals/poulet"


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _cloudinary_prefix(monkeypatch):
    """Le préfixe Cloudinary est ``media/`` (dérivé de ``MEDIA_URL`` en prod)."""
    monkeypatch.setattr(app_settings, "PREFIX", "/media/")


@pytest.fixture
def storage():
    return SecureUrlCloudinaryStorage()


def resource_metadata(**overrides):
    resource = {
        "public_id": PUBLIC_ID,
        "secure_url": SECURE_URL,
        "version": 1756291702,
        "format": "jpeg",
        "bytes": 4321,
        "width": 800,
        "height": 600,
        "resource_type": "image",
        "type": "upload",
        "created_at": "2025-08-27T00:00:00Z",
    }
    resource.update(overrides)
    return resource


def test_url_returns_the_real_secure_url_from_cloudinary_metadata(storage):
    with mock.patch(
        "cloudinary.api.resource",
        return_value=resource_metadata(),
    ) as api_resource:
        assert storage.url("media/meals/poulet") == SECURE_URL
        api_resource.assert_called_once_with(
            PUBLIC_ID,
            type="upload",
            resource_type="image",
        )

        # Métadonnées mises en cache : aucun nouvel appel API au rendu suivant.
        assert storage.url("media/meals/poulet") == SECURE_URL
        assert api_resource.call_count == 1


def test_url_strips_the_extension_when_the_resource_is_stored_without_it(storage):
    with mock.patch(
        "cloudinary.api.resource",
        side_effect=[Exception("404 Not Found"), resource_metadata()],
    ) as api_resource:
        assert storage.url("media/meals/poulet.jpeg") == SECURE_URL
        assert [call.args[0] for call in api_resource.call_args_list] == [
            "media/meals/poulet.jpeg",
            "media/meals/poulet",
        ]


def test_a_not_found_is_logged_without_a_traceback(storage, caplog):
    with (
        caplog.at_level("INFO", logger="restaurants.core.storage"),
        mock.patch(
            "cloudinary.api.resource",
            side_effect=NotFound("Error 404 - Resource not found"),
        ),
    ):
        assert storage.url("media/meals/poulet") != ""

    assert caplog.records
    assert all(rec.exc_info is None for rec in caplog.records)
    assert any("ressource absente" in rec.getMessage() for rec in caplog.records)


def test_url_falls_back_to_the_composed_url_when_the_resource_is_missing(storage):
    with mock.patch("cloudinary.api.resource", side_effect=Exception("404 Not Found")):
        url = storage.url("media/meals/eru.jpeg")

    assert url == "https://res.cloudinary.com/demo/image/upload/v1/media/meals/eru.jpeg"


def test_a_miss_is_cached_briefly_and_retried(storage):
    keys = [
        SecureUrlCloudinaryStorage._cache_key("media/meals/eru.jpeg"),
        SecureUrlCloudinaryStorage._cache_key("media/meals/eru"),
    ]
    with mock.patch(
        "cloudinary.api.resource",
        side_effect=Exception("404 Not Found"),
    ) as api_resource:
        storage.url("media/meals/eru.jpeg")
        # L'identifiant avec puis sans extension ont tous deux été interrogés.
        assert api_resource.call_count == 2
        assert [cache.get(key) for key in keys] == ["", ""]
        assert MISS_TTL > 0

        # Tant que l'échec est en cache, l'API n'est pas rappelée.
        storage.url("media/meals/eru.jpeg")
        assert api_resource.call_count == 2

        # Après expiration, Cloudinary est de nouveau interrogé.
        for key in keys:
            cache.delete(key)
        storage.url("media/meals/eru.jpeg")
        assert api_resource.call_count == 4


def test_url_keeps_an_already_complete_url_untouched(storage):
    legacy = "https://res.cloudinary.com/demo/image/upload/v1/media/hero/old.jpg"

    with mock.patch("cloudinary.api.resource") as api_resource:
        assert storage.url(legacy) == legacy
        api_resource.assert_not_called()


def test_url_returns_an_empty_string_without_a_name(storage):
    assert storage.url("") == ""


def test_url_does_not_raise_when_the_sdk_is_not_configured(storage):
    with (
        mock.patch("cloudinary.api.resource", side_effect=Exception("401")),
        mock.patch.object(
            SecureUrlCloudinaryStorage.__mro__[1],
            "url",
            side_effect=ValueError("Must supply cloud_name"),
        ),
    ):
        assert storage.url("media/meals/poulet") == ""


def test_upload_warms_the_cache_with_the_secure_url(storage):
    upload_response = resource_metadata()
    with mock.patch("cloudinary.uploader.upload", return_value=upload_response):
        name = storage._save("meals/poulet.jpeg", ContentFile(b"fake-image-bytes"))

    assert name == PUBLIC_ID

    with mock.patch(
        "cloudinary.api.resource",
        side_effect=Exception("l'API ne doit pas être appelée"),
    ):
        assert storage.url(name) == SECURE_URL
