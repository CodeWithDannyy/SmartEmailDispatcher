from email import policy

import pytest

from dispatcher.errors import ConfigError
from dispatcher.message_builder import (
    Draft,
    attach_file,
    build_message,
    parse_address_list,
    validate_address,
)


@pytest.mark.parametrize(
    "address",
    ["a@example.com", "A User <a.user+tag@example.co.uk>"],
)
def test_validate_address(address):
    bare = address.split("<")[-1].rstrip(">")
    assert validate_address(bare)


@pytest.mark.parametrize("address", ["bad", "a@@example.com", "a@localhost", "a @example.com"])
def test_validate_address_rejects_invalid_values(address):
    assert not validate_address(address)


def test_parse_address_list_accepts_names_and_separators():
    assert parse_address_list("a@example.com; B User <b@example.org>, c@example.net") == [
        "a@example.com",
        "b@example.org",
        "c@example.net",
    ]


def test_parse_address_list_reports_all_invalid_addresses():
    with pytest.raises(ConfigError) as error:
        parse_address_list("good@example.com, bad, also-bad@", "cc")
    assert error.value.field == "cc"
    assert "bad" in error.value.user_message
    assert "also-bad@" in error.value.user_message


def test_build_message_includes_headers_and_attachment(tmp_path):
    attachment = tmp_path / "notes.txt"
    attachment.write_text("hello", encoding="utf-8")
    message = build_message(
        Draft(
            sender="sender@example.com",
            to="A User <a@example.com>",
            cc="copy@example.org",
            subject="A subject",
            body="The body",
            attachments=[str(attachment)],
        )
    )

    assert message.policy is policy.SMTP
    assert message["From"] == "sender@example.com"
    assert message["To"] == "a@example.com"
    assert message["Cc"] == "copy@example.org"
    assert message.get_body().get_content() == "The body\n"
    attachment_part = list(message.iter_attachments())[0]
    assert attachment_part.get_filename() == "notes.txt"
    assert attachment_part.get_content() == "hello"


def test_build_message_requires_recipient():
    with pytest.raises(ConfigError) as error:
        build_message(Draft(sender="sender@example.com", to=""))
    assert error.value.field == "to"


@pytest.mark.parametrize("contents", [b"", None])
def test_attach_file_rejects_empty_file(tmp_path, contents):
    path = tmp_path / "empty.bin"
    path.write_bytes(contents or b"")
    with pytest.raises(ConfigError) as error:
        attach_file(build_message(Draft(sender="s@example.com", to="a@example.com")), str(path))
    assert error.value.field == "attachments"


def test_attach_file_reports_missing_file(tmp_path):
    with pytest.raises(ConfigError) as error:
        attach_file(
            build_message(Draft(sender="s@example.com", to="a@example.com")),
            str(tmp_path / "missing.txt"),
        )
    assert error.value.field == "attachments"
