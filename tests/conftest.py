"""Fixtures partagées par les tests HTTP de bout en bout."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from restaurants.users.models import User

PASSWORD = "MotDePasseSolide123!"


@pytest.fixture(autouse=True)
def _media_storage(settings, tmpdir) -> None:
    settings.MEDIA_ROOT = tmpdir.strpath


@pytest.fixture
def client_user(db) -> User:
    return User.objects.create_user(
        email="client@example.com",
        phone="+237690000101",
        first_name="Client",
        last_name="Test",
        password=PASSWORD,
    )


@pytest.fixture
def other_user(db) -> User:
    return User.objects.create_user(
        email="autre@example.com",
        phone="+237690000102",
        first_name="Autre",
        last_name="Client",
        password=PASSWORD,
    )


@pytest.fixture
def admin_user(db) -> User:
    return User.objects.create_superuser(email="admin@example.com", password=PASSWORD)


@pytest.fixture
def anonymous_client() -> APIClient:
    return APIClient()


@pytest.fixture
def auth_client(client_user: User) -> APIClient:
    api_client = APIClient()
    api_client.force_authenticate(client_user)
    return api_client


@pytest.fixture
def jwt_client(client_user: User) -> APIClient:
    """Client authentifié via l'en-tête Bearer (vrai chemin du mobile)."""
    api_client = APIClient()
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(client_user).access_token}",
    )
    return api_client
