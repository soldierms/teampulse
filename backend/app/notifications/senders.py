import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.config import Settings
from app.notifications.base import Message

log = logging.getLogger(__name__)


class ConsoleNotifier:
    """Default in local dev — prints the digest instead of sending it."""

    name = "console"

    def send(self, message: Message) -> None:
        log.info(
            "digest to %s\nsubject: %s\n%s",
            ", ".join(message.recipients) or "(no recipients)",
            message.subject,
            message.text_body,
        )


class SmtpNotifier:
    name = "smtp"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, message: Message) -> None:
        if not message.recipients:
            return
        email = EmailMessage()
        email["Subject"] = message.subject
        email["From"] = self._settings.digest_from_email
        email["To"] = ", ".join(message.recipients)
        email.set_content(message.text_body)
        if message.html_body:
            email.add_alternative(message.html_body, subtype="html")

        with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port) as server:
            server.starttls()
            if self._settings.smtp_username:
                server.login(self._settings.smtp_username, self._settings.smtp_password)
            server.send_message(email)


class ResendNotifier:
    name = "resend"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, message: Message) -> None:
        if not message.recipients:
            return
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {self._settings.resend_api_key}"},
            json={
                "from": self._settings.digest_from_email,
                "to": message.recipients,
                "subject": message.subject,
                "text": message.text_body,
                "html": message.html_body or message.text_body,
            },
            timeout=20.0,
        )
        response.raise_for_status()


class SlackNotifier:
    name = "slack"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, message: Message) -> None:
        response = httpx.post(
            self._settings.slack_webhook_url,
            json={"text": f"*{message.subject}*\n{message.text_body}"},
            timeout=20.0,
        )
        response.raise_for_status()


_NOTIFIERS = {
    "console": lambda s: ConsoleNotifier(),
    "smtp": SmtpNotifier,
    "resend": ResendNotifier,
    "slack": SlackNotifier,
}


def get_notifier(
    settings: Settings,
) -> "ConsoleNotifier | SmtpNotifier | ResendNotifier | SlackNotifier":
    factory = _NOTIFIERS.get(settings.notifier)
    if factory is None:
        log.warning("unknown NOTIFIER '%s', falling back to console", settings.notifier)
        return ConsoleNotifier()
    return factory(settings)
