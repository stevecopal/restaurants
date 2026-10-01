"""Inscription, vérification OTP, connexion, profil, déconnexion (API mobile)."""

from __future__ import annotations

import pytest
from django.core import mail
from rest_framework.test import APIClient

from restaurants.users.models import RegistrationOtp
from restaurants.users.models import User

PASSWORD = "MotDePasseSolide123!"

REGISTER_URL = "/api/v1/auth/register/"
VERIFY_URL = "/api/v1/auth/verify-otp/"
LOGIN_URL = "/api/v1/auth/login/"
PROFILE_URL = "/api/v1/profile/"
LOGOUT_URL = "/api/v1/auth/logout/"


@pytest.fixture(autouse=True)
def _no_brevo(settings):
    settings.USE_BREVO = False


def register(client: APIClient, **overrides) -> object:
    payload = {
        "first_name": "Mobile",
        "last_name": "Client",
        "email": "mobile@example.com",
        "phone": "+237691111111",
        "password": PASSWORD,
        "confirm_password": PASSWORD,
    }
    payload.update(overrides)
    return client.post(REGISTER_URL, payload, format="json")


@pytest.mark.django_db
def test_register_sends_otp_and_does_not_create_the_user_yet(anonymous_client):
    response = register(anonymous_client)

    assert response.status_code == 201
    assert response.data["detail"] == "OTP envoyé par email."
    assert not User.objects.filter(email="mobile@example.com").exists()

    otp = RegistrationOtp.objects.get(email="mobile@example.com", purpose="register")
    assert otp.otp_code
    assert len(mail.outbox) == 1
    assert otp.otp_code in mail.outbox[0].body


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "expected_key"),
    [
        ({"email": "pas-un-email"}, "email"),
        ({"phone": ""}, "phone"),
        ({"password": ""}, "password"),
        ({"confirm_password": "AutreMotDePasse123!"}, "confirm_password"),
        ({"email": ""}, "email"),
    ],
)
def test_register_rejects_invalid_payloads(anonymous_client, overrides, expected_key):
    response = register(anonymous_client, **overrides)

    assert response.status_code == 400
    assert expected_key in response.data


@pytest.mark.django_db
def test_register_rejects_duplicate_email(anonymous_client, client_user):
    response = register(anonymous_client, email=client_user.email)

    assert response.status_code == 400
    assert "email" in response.data
    assert not RegistrationOtp.objects.filter(email=client_user.email).exists()


@pytest.mark.django_db
def test_register_rejects_duplicate_phone(anonymous_client, client_user):
    response = register(anonymous_client, phone=client_user.phone)

    assert response.status_code == 400
    assert "phone" in response.data


@pytest.mark.django_db
def test_verify_otp_rejects_a_wrong_code(anonymous_client):
    register(anonymous_client)
    otp = RegistrationOtp.objects.get(email="mobile@example.com", purpose="register")

    response = anonymous_client.post(
        VERIFY_URL,
        {
            "email": "mobile@example.com",
            "otp": "000000" if otp.otp_code != "000000" else "999999",
        },
        format="json",
    )

    assert response.status_code == 400
    assert not User.objects.filter(email="mobile@example.com").exists()


@pytest.mark.django_db
def test_verify_otp_creates_the_client_and_returns_tokens(anonymous_client):
    register(anonymous_client)
    otp = RegistrationOtp.objects.get(email="mobile@example.com", purpose="register")

    response = anonymous_client.post(
        VERIFY_URL,
        {"email": "mobile@example.com", "otp": otp.otp_code},
        format="json",
    )

    assert response.status_code == 201
    assert "access" in response.data
    assert "refresh" in response.data
    assert response.data["user"]["email"] == "mobile@example.com"

    user = User.objects.get(email="mobile@example.com")
    assert user.client_profile is not None

    # Le jeton retourné donne accès au profil.
    profile = anonymous_client.get(
        PROFILE_URL,
        HTTP_AUTHORIZATION=f"Bearer {response.data['access']}",
    )
    assert profile.status_code == 200
    assert profile.data["email"] == "mobile@example.com"


@pytest.mark.django_db
def test_login_returns_tokens_and_rejects_bad_credentials(client_user):
    client = APIClient()

    success = client.post(
        LOGIN_URL,
        {"email": client_user.email, "password": PASSWORD},
        format="json",
    )
    assert success.status_code == 200
    assert "access" in success.data
    assert success.data["user"]["email"] == client_user.email

    bad_password = client.post(
        LOGIN_URL,
        {"email": client_user.email, "password": "MauvaisMotDePasse1!"},
        format="json",
    )
    assert bad_password.status_code == 400

    unknown_email = client.post(
        LOGIN_URL,
        {"email": "inconnu@example.com", "password": PASSWORD},
        format="json",
    )
    assert unknown_email.status_code == 400


@pytest.mark.django_db
def test_profile_requires_authentication_and_can_be_updated(jwt_client, client_user):
    anonymous = APIClient()

    assert anonymous.get(PROFILE_URL).status_code == 401
    assert anonymous.patch(PROFILE_URL, {"first_name": "Hack"}).status_code == 401

    read = jwt_client.get(PROFILE_URL)
    assert read.status_code == 200
    assert read.data["first_name"] == "Client"

    update = jwt_client.patch(PROFILE_URL, {"first_name": "Nouveau"}, format="json")
    assert update.status_code == 200
    assert update.data["first_name"] == "Nouveau"
    assert User.objects.get(pk=client_user.pk).first_name == "Nouveau"


@pytest.mark.django_db
def test_logout_requires_a_token(jwt_client):
    assert APIClient().post(LOGOUT_URL).status_code == 401
    assert jwt_client.post(LOGOUT_URL).status_code == 204
