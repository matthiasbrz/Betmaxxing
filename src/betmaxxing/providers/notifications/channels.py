"""Telegram, e-mail and SMS adapters.

All three refuse to send unless notifications are explicitly enabled *and* the
channel is fully configured. SMS stays behind the same interface but is not
wired to a vendor in V1 because it costs money per message — enabling it is a
deliberate, documented act, never a default.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

import httpx

from betmaxxing.config import Settings
from betmaxxing.domain.enums import ProviderHealth
from betmaxxing.domain.models import ProviderStatus

TELEGRAM_API = "https://api.telegram.org"


class TelegramNotifier:
    name = "telegram"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def _configured(self) -> bool:
        return bool(self._settings.telegram_bot_token and self._settings.telegram_chat_id)

    def health(self) -> ProviderStatus:
        if not self._configured:
            return ProviderStatus(
                name=self.name,
                kind="notification",
                health=ProviderHealth.NOT_CONFIGURED,
                detail="BETMAXXING_TELEGRAM_BOT_TOKEN / _CHAT_ID absents.",
            )
        return ProviderStatus(
            name=self.name,
            kind="notification",
            health=ProviderHealth.OK
            if self._settings.notifications_enabled
            else ProviderHealth.NOT_CONFIGURED,
            detail="Prêt."
            if self._settings.notifications_enabled
            else "Notifications désactivées.",
        )

    def send(self, subject: str, body: str) -> bool:
        if not self._settings.notifications_enabled or not self._configured:
            return False
        url = f"{TELEGRAM_API}/bot{self._settings.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self._settings.telegram_chat_id,
            "text": f"*{subject}*\n\n{body}",
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        response = httpx.post(url, json=payload, timeout=self._settings.provider_timeout_seconds)
        return response.status_code == 200


class EmailNotifier:
    name = "email"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def _configured(self) -> bool:
        s = self._settings
        return bool(s.smtp_host and s.email_from and s.email_to)

    def health(self) -> ProviderStatus:
        if not self._configured:
            return ProviderStatus(
                name=self.name,
                kind="notification",
                health=ProviderHealth.NOT_CONFIGURED,
                detail="Configuration SMTP incomplète.",
            )
        return ProviderStatus(
            name=self.name,
            kind="notification",
            health=ProviderHealth.OK
            if self._settings.notifications_enabled
            else ProviderHealth.NOT_CONFIGURED,
            detail="Prêt."
            if self._settings.notifications_enabled
            else "Notifications désactivées.",
        )

    def send(self, subject: str, body: str) -> bool:
        if not self._settings.notifications_enabled or not self._configured:
            return False
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self._settings.email_from
        message["To"] = self._settings.email_to
        message.set_content(body)
        with smtplib.SMTP(
            self._settings.smtp_host,
            self._settings.smtp_port,
            timeout=self._settings.provider_timeout_seconds,
        ) as smtp:
            smtp.starttls()
            if self._settings.smtp_username:
                smtp.login(self._settings.smtp_username, self._settings.smtp_password)
            smtp.send_message(message)
        return True


class SmsNotifier:
    """Interface placeholder. Deliberately never sends in V1 (per-message cost)."""

    name = "sms"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def health(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            kind="notification",
            health=ProviderHealth.NOT_CONFIGURED,
            detail=(
                "SMS non câblé en V1 : coût par message. L'interface existe pour "
                "brancher un fournisseur explicitement choisi."
            ),
        )

    def send(self, subject: str, body: str) -> bool:
        del subject, body
        return False
