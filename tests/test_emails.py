"""Livraison des emails : l'API Brevo (HTTPS) doit être utilisée, pas le SMTP.

Sur Render Free, le SMTP sortant est bloqué : l'envoi passe donc par
l'API HTTPS de Brevo via django-anymail, dès qu'une clé est configurée.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest
import requests
from django.core import mail

from restaurants.users.utils.emails import EmailUtil

BREVO_API_KEY = "xkeysib-test-key"
BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


class FakeBrevoResponse:
    """Réponse 200 minimale de l'API Brevo."""

    status_code = 200

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.content = json.dumps(payload).encode()

    def json(self) -> dict:
        return self._payload


@pytest.fixture(autouse=True)
def _reset_email_singleton(monkeypatch) -> None:
    """Le singleton EmailUtil est réinitialisé autour de chaque test."""
    monkeypatch.setattr(EmailUtil, "_instance", None)
    monkeypatch.setattr(EmailUtil, "_initialized", False)


@pytest.fixture
def email_util(settings) -> EmailUtil:
    """EmailUtil configuré avec une clé API Brevo (comme en production)."""
    settings.BREVO_API_KEY = BREVO_API_KEY
    return EmailUtil()


def test_a_brevo_key_switches_emailing_to_the_https_api(email_util):
    assert email_util.use_brevo is True
    assert email_util.brevo_api_key == BREVO_API_KEY


def test_the_api_key_is_read_from_the_anymail_settings(settings):
    """Configuration production : la clé vit dans settings.ANYMAIL."""
    settings.BREVO_API_KEY = ""
    settings.ANYMAIL = {"BREVO_API_KEY": "xkeysib-from-anymail"}

    util = EmailUtil()

    assert util.use_brevo is True
    assert util.brevo_api_key == "xkeysib-from-anymail"


def test_without_an_api_key_the_django_backend_is_used(
    settings,
    client_user,
    monkeypatch,
):
    settings.BREVO_API_KEY = ""
    request = mock.Mock()
    monkeypatch.setattr(requests.Session, "request", request)

    util = EmailUtil()
    sent = util.send_otp_verification(client_user, "654321", "register")

    assert util.use_brevo is False
    assert sent is True
    assert request.call_count == 0
    assert len(mail.outbox) == 1
    assert "654321" in mail.outbox[0].body


def test_the_otp_email_goes_through_the_brevo_https_api(
    email_util,
    client_user,
    monkeypatch,
):
    request = mock.Mock(return_value=FakeBrevoResponse({"messageId": "msg-1"}))
    monkeypatch.setattr(requests.Session, "request", request)

    sent = email_util.send_otp_verification(client_user, "123456", "register")

    assert sent is True
    assert request.call_count == 1

    params = request.call_args.kwargs
    assert params["method"] == "POST"
    assert params["url"] == BREVO_SEND_URL
    assert params["headers"]["api-key"] == BREVO_API_KEY

    payload = json.loads(params["data"])
    assert payload["subject"].endswith("Votre code de vérification")
    assert [recipient["email"] for recipient in payload["bcc"]] == [client_user.email]
    assert "123456" in payload["htmlContent"]


def test_the_api_key_is_also_read_from_the_environment(settings, monkeypatch):
    """Variable posée directement sur Render, même si les settings ne la voient pas."""
    settings.BREVO_API_KEY = ""
    monkeypatch.setenv("BREVO_API_KEY", "xkeysib-from-os-environ")

    util = EmailUtil()
    util._refresh_brevo_config()

    assert util.use_brevo is True
    assert util.brevo_api_key == "xkeysib-from-os-environ"


def test_a_key_added_after_boot_is_used_on_the_next_send(
    settings,
    client_user,
    monkeypatch,
):
    """Ajouter BREVO_API_KEY pendant la vie du process suffit (pas de reboot)."""
    settings.BREVO_API_KEY = ""
    util = EmailUtil()
    assert util.use_brevo is False

    request = mock.Mock(return_value=FakeBrevoResponse({"messageId": "msg-2"}))
    monkeypatch.setattr(requests.Session, "request", request)
    settings.BREVO_API_KEY = BREVO_API_KEY

    assert util.send_otp_verification(client_user, "112233", "register")
    assert request.call_count == 1


def test_on_render_without_a_key_smtp_is_not_even_tried(
    settings,
    client_user,
    monkeypatch,
):
    """Sur Render, le SMTP est bloqué : on échoue vite avec un message clair."""
    settings.BREVO_API_KEY = ""
    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    monkeypatch.setenv("RENDER", "true")

    http_request = mock.Mock()
    monkeypatch.setattr(requests.Session, "request", http_request)
    smtp_send = mock.Mock()
    monkeypatch.setattr(
        "django.core.mail.backends.smtp.EmailBackend.send_messages",
        smtp_send,
    )

    util = EmailUtil()
    sent = util.send_otp_verification(client_user, "999999", "register")

    assert util.use_brevo is False
    assert sent is False
    assert http_request.call_count == 0
    assert smtp_send.call_count == 0
    assert len(mail.outbox) == 0


def test_a_brevo_failure_is_logged_but_never_raised(
    email_util,
    client_user,
    monkeypatch,
):
    request = mock.Mock(side_effect=requests.ConnectionError("reseau coupe"))
    monkeypatch.setattr(requests.Session, "request", request)

    assert email_util.send_otp_verification(client_user, "123456", "register") is False
