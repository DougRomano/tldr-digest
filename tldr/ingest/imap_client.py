"""Yahoo IMAP fetcher for TLDR newsletters.

Run synchronously in a worker — `imap-tools` is sync; the CLI dispatches to it
via `asyncio.to_thread`.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from imap_tools import AND, MailBox

from tldr.config import settings
from tldr.db.models import SourceName

log = logging.getLogger(__name__)


# All TLDR newsletters are sent from one address (dan@tldrnewsletter.com); the
# newsletter is identified by the From *display name*, not the subject (subjects
# are content headlines). Match the full name exactly, case-insensitive —
# "TLDR Dev" is a prefix of "TLDR DevOps", so prefix matching would misroute.
# Newsletters not in this map (TLDR InfoSec/IT/Design/Founders/Data/Fintech/
# Product) are intentionally skipped.
DISPLAY_NAME_MAP: dict[str, SourceName] = {
    "tldr": SourceName.tldr_tech,        # the flagship "TLDR" newsletter
    "tldr ai": SourceName.tldr_ai,
    "tldr devops": SourceName.tldr_devops,
    "tldr dev": SourceName.tldr_dev,
}


def classify_source(from_name: str) -> SourceName | None:
    key = re.sub(r"\s+", " ", (from_name or "").strip().lower())
    return DISPLAY_NAME_MAP.get(key)


@dataclass(slots=True)
class FetchedEmail:
    imap_uid: str
    imap_folder: str
    source: SourceName
    subject: str
    received_at: datetime
    html: str
    text: str


def fetch_recent(since_days: int = 7, folder: str = "INBOX") -> list[FetchedEmail]:
    if not settings.yahoo_app_password:
        raise RuntimeError("YAHOO_APP_PASSWORD is not set in .env")
    since_date = (datetime.now(timezone.utc) - timedelta(days=since_days)).date()
    out: list[FetchedEmail] = []
    with MailBox(settings.yahoo_imap_host, port=settings.yahoo_imap_port).login(
        settings.yahoo_user, settings.yahoo_app_password, initial_folder=folder
    ) as mailbox:
        criteria = AND(date_gte=since_date)
        for msg in mailbox.fetch(criteria, mark_seen=False, bulk=True):
            from_name = msg.from_values.name if msg.from_values else ""
            source = classify_source(from_name)
            if source is None:
                continue
            received_at = msg.date if msg.date else datetime.now(timezone.utc)
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
            out.append(
                FetchedEmail(
                    imap_uid=str(msg.uid),
                    imap_folder=folder,
                    source=source,
                    subject=msg.subject or "",
                    received_at=received_at,
                    html=msg.html or "",
                    text=msg.text or "",
                )
            )
    log.info("imap: fetched %d TLDR emails from last %d days", len(out), since_days)
    return out
