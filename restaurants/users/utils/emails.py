import logging
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.core.mail import get_connection
from django.template.loader import render_to_string

User = get_user_model()

logger = logging.getLogger(__name__)


class EmailUtil:
    """
    Singleton pour l'envoi d'emails via Brevo (Sendinblue) ou Django SMTP.
    Configuration via settings.py.
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not self.__class__._initialized:
            logger.info("## Initializing EmailUtil — Les délices de Mam's ##")

            self.testing = getattr(settings, "TESTING", False)
            self.debug = getattr(settings, "DEBUG", False)
            self.brevo_api_key = self._resolve_brevo_api_key()
            self.use_brevo = bool(self.brevo_api_key) and getattr(
                settings, "USE_BREVO", True,
            )

            logger.info("Testing mode: %s", self.testing)
            logger.info("Debug mode: %s", self.debug)
            logger.info("Using Brevo (API HTTPS): %s", self.use_brevo)

            if not self.use_brevo:
                # Render Free bloque le SMTP sortant : sans clé API, l'envoi
                # échouera en production. On le dit explicitement au démarrage.
                logger.warning(
                    "BREVO_API_KEY absent — repli sur le backend Django %s. "
                    "Sur Render, renseignez BREVO_API_KEY (API HTTPS Brevo).",
                    settings.EMAIL_BACKEND,
                )

            self.__class__._initialized = True

    @staticmethod
    def _resolve_brevo_api_key() -> str:
        """Clé API Brevo : settings.ANYMAIL puis settings.BREVO_API_KEY."""
        anymail_settings = getattr(settings, "ANYMAIL", None) or {}
        return (
            anymail_settings.get("BREVO_API_KEY")
            or getattr(settings, "BREVO_API_KEY", "")
            or ""
        )

    # ═══════════════════════════════════════════════════════════════════════
    # CONFIGURATION & HELPERS
    # ═══════════════════════════════════════════════════════════════════════

    def _get_base_url(self, request: Any = None) -> str:
        """Construit l'URL de base selon l'environnement."""
        base_url = getattr(settings, "BASE_URL", "http://localhost:8000")

        if request:
            protocol = "https" if request.is_secure() else "http"
            host = request.get_host()
            return f"{protocol}://{host}"

        return base_url

    def _get_sender(self, _from: str | None = None) -> str:
        """Résolve l'expéditeur avec fallback sur les settings."""
        default_from = getattr(
            settings,
            "DEFAULT_FROM_EMAIL",
            "noreply@mams.com",
        )
        site_name = getattr(settings, "SITE_NAME", "Les délices de Mam's")

        if _from:
            return _from

        if "<" in default_from and ">" in default_from:
            return default_from

        return f"{site_name} <{default_from}>"

    def _get_active_admin_emails(self) -> list[str]:
        """Retourne les emails des utilisateurs actifs avec le rôle admin."""
        return list(
            User.objects.filter(
                is_active=True,
                is_superuser=True,
            )
            .exclude(email="")
            .order_by("email")
            .values_list("email", flat=True)
            .distinct(),
        )

    def _validate_send_email_params(
        self,
        to: list[str],
        subject: str,
        html_content: str | None,
        text_content: str | None,
        template: str | None,
    ) -> None:
        """Valide les paramètres obligatoires de send_email."""
        if not isinstance(to, list) or not to or any(not e for e in to):
            msg = "Paramètre 'to' invalide : liste d'emails requise"
            raise ValueError(msg)

        if not subject:
            msg = "Le sujet est obligatoire"
            raise ValueError(msg)

        if not html_content and not text_content and not template:
            msg = "Contenu requis : html_content, text_content ou template"
            raise ValueError(msg)

    def _render_template_content(
        self, template: str, subject: str, context: dict | None,
    ) -> str:
        """Rend un template email avec le contexte enrichi (logo, site_name)."""
        render_ctx = context or {}
        render_ctx["subject"] = subject
        render_ctx["site_name"] = getattr(
            settings, "SITE_NAME", "Les délices de Mam's",
        )

        base_url = getattr(settings, "BASE_URL", "http://localhost:8000")
        render_ctx["base_url"] = base_url
        render_ctx["logo_url"] = f"{base_url}/static/images/logo-mams.png"

        return render_to_string(template, render_ctx)

    # ═══════════════════════════════════════════════════════════════════════
    # MÉTHODE PRINCIPALE
    # ═══════════════════════════════════════════════════════════════════════

    def send_email(
        self,
        subject: str,
        to: list[str],
        _from: str | None = None,
        html_content: str | None = None,
        text_content: str | None = None,
        attachments: list[str] | None = None,
        template: str | None = None,
        context: dict | None = None,
    ) -> bool:
        """Méthode universelle d'envoi d'email."""
        self._validate_send_email_params(
            to, subject, html_content, text_content, template,
        )

        if self.debug and not self.testing:
            subject = f"[DEV] {subject}"

        if template:
            html_content = self._render_template_content(template, subject, context)

        if self.testing:
            logger.info(
                "*** TEST EMAIL ***\nTo: %s\nSubject: %s\nFrom: %s\nContent: %s...",
                to,
                subject,
                self._get_sender(_from),
                text_content or html_content[:200] if html_content else "",
            )
            return True

        from_email = self._get_sender(_from)

        if self.use_brevo:
            return self._send_brevo(
                subject=subject,
                to=to,
                from_email=from_email,
                html_content=html_content,
                text_content=text_content,
                attachments=attachments,
            )
        return self._send_django(
            subject=subject,
            to=to,
            from_email=from_email,
            html_content=html_content,
            text_content=text_content,
            attachments=attachments,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # BACKENDS D'ENVOI
    # ═══════════════════════════════════════════════════════════════════════

    def _send_brevo(
        self,
        subject: str,
        to: list[str],
        from_email: str,
        html_content: str | None = None,
        text_content: str | None = None,
        attachments: list[str] | None = None,
    ) -> bool:
        """Envoi via l'API Brevo en HTTPS (django-anymail) — jamais de SMTP."""
        logger.info("## Envoi via Brevo (API HTTPS) ##")

        try:
            email = EmailMessage(
                subject=str(subject),
                body=html_content or text_content or "",
                from_email=from_email,
                to=[],
                bcc=to,
            )
            email.content_subtype = "html" if html_content else "plain"

            if attachments:
                for file_path in attachments:
                    if Path(file_path).exists():
                        email.attach_file(file_path)

            connection = get_connection(
                "anymail.backends.brevo.EmailBackend",
                api_key=self.brevo_api_key,
            )
            sent = connection.send_messages([email])
        except Exception:
            # L'échec du fournisseur d'email ne doit pas casser les vues
            # (inscription, commande, ...) : il est seulement journalisé.
            logger.exception("❌ Échec de l'envoi Brevo (API HTTPS)")
            return False

        logger.info("✅ Email envoyé via Brevo (%s message(s)) : %s", sent, to)
        return bool(sent)

    def _send_django(
        self,
        subject: str,
        to: list[str],
        from_email: str,
        html_content: str | None = None,
        text_content: str | None = None,
        attachments: list[str] | None = None,
    ) -> bool:
        """Envoi via backend email Django (SMTP)."""
        logger.info("## Envoi via Django SMTP ##")

        try:
            body = html_content or text_content or ""
            email = EmailMessage(
                subject=subject,
                body=body,
                from_email=from_email,
                to=[],
                bcc=to,
            )
            email.content_subtype = "html" if html_content else "plain"

            if attachments:
                for file_path in attachments:
                    if Path(file_path).exists():
                        email.attach_file(file_path)

            email.send()
        except Exception:
            # SMTP/Brevo indisponible : on journalise au lieu de casser la
            # requête HTTP (l'inscription ou une commande doivent passer).
            logger.exception("❌ Échec de l'envoi email Django")
            return False
        logger.info("✅ Email envoyé via Django SMTP")
        return True

    # ═══════════════════════════════════════════════════════════════════════
    # SHORTCUTS MÉTIER — LES DÉLICES DE MAM'S
    # ═══════════════════════════════════════════════════════════════════════

    def send_welcome_email(self, user, raw_password: str | None = None) -> bool:
        """Email de bienvenue après inscription."""
        return self.send_email(
            subject="Bienvenue chez Les délices de Mam's !",
            to=[user.email],
            template="emails/users/welcome.html",
            context={
                "user": user,
                "raw_password": raw_password,
                "login_url": f"{self._get_base_url()}/users/login/",
            },
        )

    def send_otp_verification(self, user, otp_code: str, purpose: str) -> bool:
        """Email contenant le code OTP de vérification."""
        return self.send_email(
            subject="Votre code de vérification",
            to=[user.email],
            template="emails/auth/otp_verification.html",
            context={
                "user": user,
                "otp_code": otp_code,
                "purpose": purpose,
                "expiry_minutes": getattr(settings, "OTP_EXPIRY_MINUTES", 10),
            },
        )

    def send_password_reset(self, user, reset_url: str) -> bool:
        """Email de réinitialisation de mot de passe."""
        return self.send_email(
            subject="Réinitialisation de votre mot de passe",
            to=[user.email],
            template="emails/auth/password_reset.html",
            context={
                "user": user,
                "reset_url": reset_url,
                "expiry_hours": 24,
            },
        )

    def send_newsletter_campaign(self, subject: str, html_content: str, recipients: list[str]) -> bool:
        """Envoi d'une campagne de newsletter."""
        if not recipients:
            return True

        return self.send_email(
            subject=subject,
            to=recipients,
            html_content=html_content,
        )

    def send_new_order_admin_notification(self, order) -> bool:
        """Notification aux admins lorsqu'une commande est effectuée."""
        recipients = self._get_active_admin_emails()
        if not recipients:
            logger.info("Aucun admin actif à notifier pour la commande %s", order.id)
            return True

        return self.send_email(
            subject=f"Nouvelle Commande #{order.id} à traiter",
            to=recipients,
            template="emails/orders/admin_new_order.html",
            context={"order": order},
        )

    def send_order_status_update(self, order) -> bool:
        """Notification au client de la mise à jour du statut de sa commande."""
        if not order.client or not order.client.user.email:
            return False

        status_labels = {
            "pending": "en attente de traitement",
            "preparing": "en cours de préparation",
            "ready": "prête",
            "delivering": "en cours de livraison",
            "delivered": "livrée",
            "cancelled": "annulée",
        }
        label = status_labels.get(order.status, "mise à jour")

        return self.send_email(
            subject=f"Votre commande Mam's #{order.id} est {label}",
            to=[order.client.user.email],
            template="emails/orders/status_update.html",
            context={"order": order, "label": label},
        )
