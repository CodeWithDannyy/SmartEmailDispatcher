from __future__ import annotations

import mimetypes
import os
import re
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate, getaddresses, make_msgid
from typing import List

from .errors import ConfigError


@dataclass
class Draft:
    sender: str
    to: str
    cc: str = ""
    subject: str = ""
    body: str = ""
    attachments: List[str] = field(default_factory=list)


def validate_address(address: str) -> bool:
    if not address or address != address.strip() or any(ch.isspace() for ch in address):
        return False
    if address.count("@") != 1:
        return False
    local, domain = address.rsplit("@", 1)
    if not local or not domain or len(address) > 254:
        return False
    if local.startswith(".") or local.endswith(".") or ".." in local:
        return False
    if domain.startswith(".") or domain.endswith(".") or ".." in domain:
        return False
    return bool(
        re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
        and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+", domain)
    )


def parse_address_list(text: str, field_name: str = "to") -> List[str]:
    if not text or not text.strip():
        return []

    parts = [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]
    parsed = [getaddresses([part]) for part in parts]
    addresses = [address for entries in parsed for _, address in entries]
    invalid = [
        part for part, entries in zip(parts, parsed)
        if len(entries) != 1 or not entries[0][1] or not validate_address(entries[0][1])
    ]
    if invalid:
        raise ConfigError(
            f"Invalid address(es) in {field_name}: {', '.join(invalid)}",
            field=field_name,
        )
    return addresses


def attach_file(message: EmailMessage, path: str) -> None:
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except (OSError, TypeError) as exc:
        raise ConfigError(
            f"Could not read attachment: {path}",
            field="attachments",
        ) from exc
    if not data:
        raise ConfigError(f"Attachment is empty: {path}", field="attachments")

    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    maintype, subtype = content_type.split("/", 1)
    message.add_attachment(
        data,
        maintype=maintype,
        subtype=subtype,
        filename=os.path.basename(path),
    )


def build_message(draft: Draft) -> EmailMessage:
    to = parse_address_list(draft.to, "to")
    if not to:
        raise ConfigError("Enter at least one recipient.", field="to")
    cc = parse_address_list(draft.cc, "cc")

    message = EmailMessage(policy=SMTP)
    message["From"] = draft.sender
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    message["Subject"] = draft.subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    message.set_content(draft.body)
    for path in draft.attachments:
        attach_file(message, path)
    return message
