from __future__ import annotations

import re

from .session import SendResult, SMTPReply


def describe_reply(reply: SMTPReply) -> str:
    enhanced = re.match(r"\s*([245]\.\d+\.\d+)", reply.message)
    enhanced_descriptions = {
        "4.2.0": "Mailbox is temporarily unavailable - try again later.",
        "4.3.1": "The mail system is temporarily unavailable - try again later.",
        "5.1.1": "Mailbox does not exist or is unavailable.",
        "5.2.2": "The recipient's mailbox is full.",
        "5.3.4": "Message too large for the server.",
        "5.7.1": "Rejected by the server's policy or spam filter.",
    }
    if enhanced and enhanced.group(1) in enhanced_descriptions:
        return enhanced_descriptions[enhanced.group(1)]

    exact = {
        220: "Service ready.",
        221: "Service closing transmission channel.",
        235: "Authentication successful.",
        250: "Accepted.",
        251: "Accepted; the server will forward it.",
        354: "Continue sending the message.",
        421: "Server is shutting down or busy - try again later.",
        450: "Mailbox is temporarily unavailable - try again later.",
        451: "Temporary server error - try again later.",
        452: "Insufficient server storage - try again later.",
        550: "Mailbox does not exist or is unavailable.",
        551: "Mailbox is not local; the server may provide a forwarding address.",
        552: "Message too large for the server.",
        553: "Address not allowed or badly formatted.",
        554: "Rejected by the server's policy or spam filter.",
    }
    if reply.code in exact:
        return exact[reply.code]
    if 200 <= reply.code < 300:
        return "Accepted by the server."
    if 300 <= reply.code < 400:
        return "The server requests more information."
    if 400 <= reply.code < 500:
        return "Temporary failure - try again later."
    if 500 <= reply.code < 600:
        return "Permanent failure - the server rejected the request."
    return "Unknown server response."


def summarise_result(result: SendResult) -> str:
    total = len(result.accepted) + len(result.refused)
    lines = [f"Sent to {len(result.accepted)} of {total} recipients."]
    for address, reply in result.refused.items():
        lines.append(
            f"Not delivered to {address}: {describe_reply(reply)} ({reply.code})."
        )
    return "\n".join(lines)
