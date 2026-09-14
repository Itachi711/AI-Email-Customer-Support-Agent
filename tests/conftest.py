"""Offline regression suite: no real keys, OAuth browser, Gmail, or network."""

import os
import socket
import threading

import pytest

# Also protect test collection/imports when the caller has a live .env or tracing setup.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["ANONYMIZED_TELEMETRY"] = "False"
for name in ("OPENAI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY", "LANGSMITH_API_KEY"):
    os.environ.pop(name, None)


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("External network/OAuth is forbidden in M1 offline tests")

    # Windows asyncio builds its wakeup pipe using loopback socketpair().
    # Allow only that internal construction, never arbitrary loopback requests.
    local = threading.local()
    original_connect = socket.socket.connect
    original_socketpair = socket.socketpair

    def guarded_connect(sock, address):
        if getattr(local, "making_socketpair", False) and address[0] in ("127.0.0.1", "::1"):
            return original_connect(sock, address)
        return blocked()

    def internal_socketpair(*args, **kwargs):
        local.making_socketpair = True
        try:
            return original_socketpair(*args, **kwargs)
        finally:
            local.making_socketpair = False

    monkeypatch.setattr(socket, "socketpair", internal_socketpair)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    from google_auth_oauthlib.flow import InstalledAppFlow

    monkeypatch.setattr(InstalledAppFlow, "run_local_server", blocked)
