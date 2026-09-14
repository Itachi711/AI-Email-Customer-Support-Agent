"""Gmail regression tests: every API/OAuth boundary is fake or blocked."""

import base64
from email import message_from_bytes
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from src.tools.GmailTools import GmailToolsClass


@pytest.fixture
def gmail_settings(tmp_path):
    return SimpleNamespace(
        gmail_credentials_path=tmp_path / "credentials.json",
        gmail_token_path=tmp_path / "token.json",
        my_email="support@example.com",
    )


@pytest.fixture
def gmail(gmail_settings):
    return GmailToolsClass(settings=gmail_settings, service=MagicMock())


@pytest.fixture
def initial_email():
    return SimpleNamespace(
        id="gmail-resource-id",
        threadId="thread-1",
        messageId="<original@example.com>",
        references="<ancestor@example.com>",
        sender="Customer <customer@example.com>",
        subject="Product question",
    )


def encoded(text):
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def raw_message(body):
    return message_from_bytes(base64.urlsafe_b64decode(body["raw"]))


def test_constructor_and_mime_building_do_not_start_oauth(
    monkeypatch, gmail_settings, initial_email
):
    connection = MagicMock(side_effect=AssertionError("OAuth must remain lazy"))
    monkeypatch.setattr(GmailToolsClass, "_get_gmail_service", connection)
    client = GmailToolsClass(settings=gmail_settings)
    client._create_reply_message(initial_email, "Thank you")
    connection.assert_not_called()


def test_lazy_service_is_built_once(monkeypatch, gmail_settings):
    fake_service = MagicMock()
    connection = MagicMock(return_value=fake_service)
    monkeypatch.setattr(GmailToolsClass, "_get_gmail_service", connection)
    client = GmailToolsClass(settings=gmail_settings)
    assert client.service is fake_service
    assert client.service is fake_service
    connection.assert_called_once_with()


def test_missing_credentials_has_actionable_error_without_creating_files(gmail_settings):
    client = GmailToolsClass(settings=gmail_settings)
    with pytest.raises(FileNotFoundError, match="GMAIL_CREDENTIALS_PATH"):
        client._get_gmail_service()
    assert not gmail_settings.gmail_credentials_path.exists()
    assert not gmail_settings.gmail_token_path.exists()


def test_recent_query_preserves_eight_hours_and_limit(gmail):
    listing = gmail.service.users().messages().list
    listing.return_value.execute.return_value = {"messages": [{"id": "m1", "threadId": "t1"}]}
    assert gmail.fetch_recent_emails() == [{"id": "m1", "threadId": "t1"}]
    arguments = listing.call_args.kwargs
    assert arguments["userId"] == "me"
    assert arguments["maxResults"] == 50
    after, before = arguments["q"].split()
    assert int(before.removeprefix("before:")) - int(after.removeprefix("after:")) == 8 * 3600
    assert "in:inbox" not in arguments["q"]


def test_draft_listing_follows_every_page(gmail):
    listing = gmail.service.users().drafts().list
    listing.return_value.execute.side_effect = [
        {
            "drafts": [{"id": "d1", "message": {"id": "m1", "threadId": "t1"}}],
            "nextPageToken": "p2",
        },
        {"drafts": [{"id": "d2", "message": {"id": "m2", "threadId": "t2"}}]},
    ]
    assert gmail.fetch_draft_replies() == [
        {"draft_id": "d1", "id": "m1", "threadId": "t1"},
        {"draft_id": "d2", "id": "m2", "threadId": "t2"},
    ]
    assert listing.call_args_list == [call(userId="me"), call(userId="me", pageToken="p2")]


def test_dedup_skips_existing_drafts_and_self_mail(gmail, monkeypatch):
    monkeypatch.setattr(
        gmail,
        "fetch_recent_emails",
        lambda _: [
            {"id": "new", "threadId": "t-new"},
            {"id": "older", "threadId": "t-new"},
            {"id": "drafted", "threadId": "t-draft"},
            {"id": "own", "threadId": "t-own"},
        ],
    )
    monkeypatch.setattr(gmail, "fetch_draft_replies", lambda: [{"threadId": "t-draft"}])
    details = MagicMock(
        side_effect=[
            {"id": "new", "sender": "customer@example.com"},
            {"id": "own", "sender": "Support <SUPPORT@example.com>"},
        ]
    )
    monkeypatch.setattr(gmail, "_get_email_info", details)
    assert gmail.fetch_unanswered_emails() == [{"id": "new", "sender": "customer@example.com"}]
    assert details.call_args_list == [call("new"), call("own")]


def test_self_mail_filter_compares_addresses_not_substrings(gmail):
    assert gmail._should_skip_email({"sender": "Support <SUPPORT@example.com>"})
    assert not gmail._should_skip_email({"sender": "Other <other-support@example.com>"})
    assert not gmail._should_skip_email({"sender": '"support@example.com" <customer@example.com>'})


def test_missing_my_email_fails_before_gmail_access(gmail):
    gmail.settings.my_email = ""
    with pytest.raises(ValueError, match="MY_EMAIL"):
        gmail.fetch_unanswered_emails()
    gmail.service.users.assert_not_called()


def test_empty_recent_mail_does_not_list_drafts(gmail, monkeypatch):
    monkeypatch.setattr(gmail, "fetch_recent_emails", lambda _: [])
    assert gmail.fetch_unanswered_emails() == []
    gmail.service.users().drafts.assert_not_called()


@pytest.mark.parametrize("operation", ["fetch_recent_emails", "fetch_draft_replies"])
def test_read_errors_propagate_instead_of_returning_empty_inbox(gmail, operation):
    gmail.service.users().messages().list.return_value.execute.side_effect = RuntimeError(
        "read failed"
    )
    gmail.service.users().drafts().list.return_value.execute.side_effect = RuntimeError(
        "read failed"
    )
    with pytest.raises(RuntimeError, match="read failed"):
        getattr(gmail, operation)()


def test_draft_list_failure_prevents_processing_mail(gmail, monkeypatch):
    monkeypatch.setattr(gmail, "fetch_recent_emails", lambda _: [{"id": "m1", "threadId": "t1"}])
    gmail.service.users().drafts().list.return_value.execute.side_effect = RuntimeError(
        "read failed"
    )
    with pytest.raises(RuntimeError, match="read failed"):
        gmail.fetch_unanswered_emails()
    gmail.service.users().messages().get.assert_not_called()


def test_get_email_info_keeps_gmail_and_rfc_message_ids_distinct(gmail):
    gmail.service.users().messages().get.return_value.execute.return_value = {
        "threadId": "thread-1",
        "payload": {
            "headers": [
                {"name": "Message-ID", "value": "<rfc-id@example.com>"},
                {"name": "REFERENCES", "value": "<ancestor@example.com>"},
                {"name": "From", "value": "customer@example.com"},
                {"name": "Subject", "value": "Product"},
            ],
            "mimeType": "text/plain",
            "body": {"data": encoded("Hello\nworld")},
        },
    }
    result = gmail._get_email_info("gmail-resource-id")
    assert result["id"] == "gmail-resource-id"
    assert result["messageId"] == "<rfc-id@example.com>"
    assert result["references"] == "<ancestor@example.com>"
    assert result["threadId"] == "thread-1"
    assert result["body"] == "Hello world"


def test_missing_optional_rfc_headers_are_empty_strings(gmail):
    gmail.service.users().messages().get.return_value.execute.return_value = {"threadId": "t1"}
    result = gmail._get_email_info("m1")
    assert result["messageId"] == ""
    assert result["references"] == ""
    assert result["body"] == ""


def test_multipart_body_prefers_plain_even_when_html_comes_first(gmail):
    payload = {
        "parts": [
            {"mimeType": "text/html", "body": {"data": encoded("<p>HTML alternative</p>")}},
            {
                "mimeType": "multipart/mixed",
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "filename": "attachment.txt",
                        "body": {"data": encoded("Attachment")},
                    },
                    {"mimeType": "text/plain", "body": {"data": encoded("Plain\nbody 中文")}},
                ],
            },
        ]
    }
    assert gmail._get_email_body(payload) == "Plain body 中文"


def test_html_body_extracts_visible_text(gmail):
    payload = {
        "mimeType": "text/html",
        "body": {
            "data": encoded(
                "<head><title>Hidden</title></head><p>Hello</p><p>world</p><script>hidden</script>"
            )
        },
    }
    assert gmail._get_email_body(payload) == "Hello world"


def test_draft_api_preserves_threading_and_never_sends(gmail, initial_email):
    creation = gmail.service.users().drafts().create
    creation.return_value.execute.return_value = {
        "id": "fake-draft",
        "message": {"threadId": "thread-1"},
    }
    draft = gmail.create_draft_reply(initial_email, "Thanks <customer>\n中文")
    assert draft["id"] == "fake-draft"
    arguments = creation.call_args.kwargs
    assert arguments["userId"] == "me"
    body = arguments["body"]["message"]
    assert body["threadId"] == "thread-1"
    message = raw_message(body)
    assert message["In-Reply-To"] == "<original@example.com>"
    assert message["References"] == "<ancestor@example.com> <original@example.com>"
    assert message["Subject"] == "Re: Product question"
    assert message["To"] == "Customer <customer@example.com>"
    plain, html = message.get_payload()
    assert plain.get_payload(decode=True).decode("utf-8") == "Thanks <customer>\n中文"
    assert "&lt;customer&gt;<br>中文" in html.get_payload(decode=True).decode("utf-8")
    gmail.service.users().messages().send.assert_not_called()
    gmail.service.users().drafts().send.assert_not_called()


def test_reply_does_not_duplicate_references_or_subject_prefix(gmail, initial_email):
    initial_email.references += " <original@example.com>"
    initial_email.subject = "re: Product question"
    message = raw_message(gmail._create_reply_message(initial_email, "Thanks"))
    assert message["References"].count("<original@example.com>") == 1
    assert message["Subject"] == "re: Product question"


def test_missing_message_id_never_uses_gmail_id_as_rfc_header(gmail, initial_email):
    initial_email.messageId = ""
    message = raw_message(gmail._create_reply_message(initial_email, "Thanks"))
    assert message["In-Reply-To"] is None
    assert message["References"] is None


def test_draft_create_failure_is_visible(gmail, initial_email):
    gmail.service.users().drafts().create.return_value.execute.side_effect = RuntimeError(
        "draft failed"
    )
    with pytest.raises(RuntimeError, match="draft failed"):
        gmail.create_draft_reply(initial_email, "Thanks")
    gmail.service.users().messages().send.assert_not_called()


def test_legacy_send_helper_only_calls_injected_fake(gmail, initial_email):
    sending = gmail.service.users().messages().send
    sending.return_value.execute.return_value = {"id": "fake-sent-id"}
    assert gmail.send_reply(initial_email, "Thanks") == {"id": "fake-sent-id"}
    body = sending.call_args.kwargs["body"]
    assert body["threadId"] == initial_email.threadId
    assert raw_message(body)["Message-ID"]
    gmail.service.users().drafts().create.assert_not_called()
