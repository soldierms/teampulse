from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class Message:
    subject: str
    text_body: str
    html_body: str | None = None
    recipients: list[str] = field(default_factory=list)


@runtime_checkable
class Notifier(Protocol):
    """One method, so swapping SMTP for Resend, Postmark or Slack is a config
    change rather than a code change."""

    name: str

    def send(self, message: Message) -> None: ...
