"""Gmail helpers used by the draft-only workflow.

Authentication is lazy so importing or compiling the graph never starts OAuth.
Tests pass an API-shaped fake through ``service`` and do not contact Gmail.
"""

import base64
import re
import uuid
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr
from html import escape
from typing import Any

from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.config import Settings, get_settings

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class GmailToolsClass:
    def __init__(self, settings: Settings | None = None, service: Any = None):
        self.settings = settings if settings is not None else get_settings()
        self._service = service

    @property
    def service(self):
        """Connect only when an explicit Gmail operation needs the service."""
        if self._service is None:
            self._service = self._get_gmail_service()
        return self._service

    def fetch_unanswered_emails(self, max_results=50):
        """Return one recent message per thread, excluding drafts and self-mail.

        Preserve the baseline's last-eight-hours heuristic. This is not a full
        conversation-level check that a customer message is still unanswered.
        Gmail errors propagate rather than masquerading as an empty inbox.
        """
        if not self.settings.my_email:
            raise ValueError(
                "Set MY_EMAIL to the authenticated Gmail address before fetching mail."
            )
        recent_emails = self.fetch_recent_emails(max_results)
        if not recent_emails:
            return []

        threads_with_drafts = {draft["threadId"] for draft in self.fetch_draft_replies()}
        seen_threads = set()
        unanswered_emails = []
        for email in recent_emails:
            thread_id = email["threadId"]
            if thread_id in seen_threads or thread_id in threads_with_drafts:
                continue
            seen_threads.add(thread_id)
            email_info = self._get_email_info(email["id"])
            if not self._should_skip_email(email_info):
                unanswered_emails.append(email_info)
        return unanswered_emails

    def fetch_recent_emails(self, max_results=50):
        # Preserve the source query: all mail from the last eight hours, up to 50.
        now = datetime.now()
        delay = now - timedelta(hours=8)
        query = f"after:{int(delay.timestamp())} before:{int(now.timestamp())}"
        results = (
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        return results.get("messages", [])

    def fetch_draft_replies(self):
        """Read every draft page so existing replies are not accidentally duplicated."""
        draft_list = []
        page_token = None
        while True:
            params = {"userId": "me"}
            if page_token:
                params["pageToken"] = page_token
            response = self.service.users().drafts().list(**params).execute()
            for draft in response.get("drafts", []):
                draft_list.append(
                    {
                        "draft_id": draft["id"],
                        "threadId": draft["message"]["threadId"],
                        "id": draft["message"]["id"],
                    }
                )
            page_token = response.get("nextPageToken")
            if not page_token:
                return draft_list

    def create_draft_reply(self, initial_email, reply_text):
        """Create a draft only; failures must be visible to the caller."""
        message = self._create_reply_message(initial_email, reply_text)
        return (
            self.service.users().drafts().create(userId="me", body={"message": message}).execute()
        )

    def send_reply(self, initial_email, reply_text):
        """Legacy explicit-send helper; the workflow never routes here."""
        message = self._create_reply_message(initial_email, reply_text, send=True)
        return self.service.users().messages().send(userId="me", body=message).execute()

    def _create_reply_message(self, email, reply_text, send=False):
        message = self._create_html_email_message(
            recipient=email.sender, subject=email.subject, reply_text=reply_text
        )
        if email.messageId:
            message["In-Reply-To"] = email.messageId
            references = (email.references or "").split()
            if email.messageId not in references:
                references.append(email.messageId)
            message["References"] = " ".join(references)
        if send:
            message["Message-ID"] = f"<{uuid.uuid4()}@gmail.com>"
        return {
            "raw": base64.urlsafe_b64encode(message.as_bytes()).decode("ascii"),
            "threadId": email.threadId,
        }

    def _get_gmail_service(self):
        credentials_path = self.settings.gmail_credentials_path
        token_path = self.settings.gmail_token_path
        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not credentials_path.is_file():
                    raise FileNotFoundError(
                        "Gmail OAuth credentials are unavailable. Configure "
                        f"GMAIL_CREDENTIALS_PATH (currently {credentials_path})."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
                creds = flow.run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json(), encoding="utf-8")
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def _should_skip_email(self, email_info):
        # Compare addresses, not substrings in display names or other mailboxes.
        sender = parseaddr(email_info["sender"])[1].casefold()
        own_address = parseaddr(self.settings.my_email)[1].casefold()
        return bool(own_address) and sender == own_address

    def _get_email_info(self, msg_id):
        message = (
            self.service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        )
        payload = message.get("payload", {})
        headers = {header["name"].lower(): header["value"] for header in payload.get("headers", [])}
        return {
            "id": msg_id,
            "threadId": message["threadId"],
            # RFC Message-ID is distinct from the Gmail message resource ID.
            "messageId": headers.get("message-id", ""),
            "references": headers.get("references", ""),
            "sender": headers.get("from", "Unknown"),
            "subject": headers.get("subject", "No Subject"),
            "body": self._get_email_body(payload),
        }

    def _get_email_body(self, payload):
        """Extract nested MIME bodies, preferring plain text over HTML alternatives."""
        plain_parts = []
        html_parts = []

        def extract(part):
            if part.get("filename"):
                return
            data = part.get("body", {}).get("data", "")
            if data:
                # Gmail uses base64url; tolerate responses without trailing padding.
                decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
                content = decoded.decode("utf-8", errors="replace")
                if part.get("mimeType") == "text/html":
                    html_parts.append(content)
                elif part.get("mimeType", "text/plain") == "text/plain":
                    plain_parts.append(content)
            for child in part.get("parts", []):
                extract(child)

        extract(payload)
        if plain_parts:
            body = plain_parts[0]
        elif html_parts:
            body = self._extract_main_content_from_html(html_parts[0])
        else:
            body = ""
        return self._clean_body_text(body)

    def _extract_main_content_from_html(self, html_content):
        soup = BeautifulSoup(html_content, "html.parser")
        for tag in soup(["script", "style", "head", "meta", "title"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)

    def _clean_body_text(self, text):
        return re.sub(r"\s+", " ", text).strip()

    def _create_html_email_message(self, recipient, subject, reply_text):
        """Format generated prose as UTF-8 plain text and escaped HTML alternatives."""
        message = MIMEMultipart("alternative")
        message["To"] = recipient
        message["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        plain_text = reply_text.replace("\\n", "\n")
        html_text = escape(plain_text).replace("\n", "<br>")
        message.attach(MIMEText(plain_text, "plain", "utf-8"))
        message.attach(
            MIMEText(f"<!DOCTYPE html><html><body>{html_text}</body></html>", "html", "utf-8")
        )
        return message
