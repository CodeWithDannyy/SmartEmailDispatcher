from dispatcher.reply_codes import describe_reply, summarise_result
from dispatcher.session import SMTPReply, SendResult


def test_describe_reply_covers_common_codes():
    assert describe_reply(SMTPReply("RCPT TO", 250, "2.1.5 OK")) == "Accepted."
    assert "temporarily" in describe_reply(SMTPReply("RCPT TO", 450, "4.2.0 Busy"))
    assert "does not exist" in describe_reply(SMTPReply("RCPT TO", 550, "5.1.1 Unknown"))
    assert "too large" in describe_reply(SMTPReply("DATA", 552, "5.3.4 Too big"))
    assert "full" in describe_reply(SMTPReply("RCPT TO", 550, "5.2.2 Mailbox full"))


def test_summarise_result_lists_refused_recipients():
    result = SendResult(
        sender="sender@example.com",
        accepted=["ok@example.com", "also-ok@example.com"],
        refused={
            "bad@example.com": SMTPReply("RCPT TO", 550, "5.1.1 Unknown user"),
        },
        replies=[SMTPReply("DATA", 250, "2.0.0 Queued")],
        size_bytes=123,
    )
    summary = summarise_result(result)
    assert "Sent to 2 of 3 recipients." in summary
    assert "Not delivered to bad@example.com" in summary
    assert "(550)" in summary
