"""Project-local settings; reading configuration never contacts external services."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = field(default="", repr=False)
    chat_model: str = "gpt-5.6-luna"
    embedding_model: str = "text-embedding-3-small"
    chat_temperature: float | None = None
    vector_db_path: Path = PROJECT_ROOT / "db_openai_m1"
    chroma_collection: str = "email_support_openai_m1"
    retrieval_top_k: int = 3
    gmail_credentials_path: Path = PROJECT_ROOT / "credentials.json"
    gmail_token_path: Path = PROJECT_ROOT / "token.json"
    my_email: str = ""

    def __post_init__(self):
        if self.retrieval_top_k < 1:
            raise ValueError("RETRIEVAL_TOP_K must be a positive integer")
        if not self.chat_model or not self.embedding_model or not self.chroma_collection:
            raise ValueError("Model names and CHROMA_COLLECTION must not be empty")
        for name in ("vector_db_path", "gmail_credentials_path", "gmail_token_path"):
            object.__setattr__(self, name, _project_path(str(getattr(self, name))))

    def require_openai_key(self) -> str:
        if not self.openai_api_key.strip():
            raise ValueError(
                "OPENAI_API_KEY is required for live OpenAI operations; set it in .env"
            )
        return self.openai_api_key


def get_settings() -> Settings:
    # Existing process variables win; never change an existing .env file.
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    temperature = os.getenv("OPENAI_CHAT_TEMPERATURE", "").strip()
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        chat_model=os.getenv("OPENAI_CHAT_MODEL", "gpt-5.6-luna"),
        embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        chat_temperature=float(temperature) if temperature else None,
        vector_db_path=_project_path(os.getenv("VECTOR_DB_PATH", "db_openai_m1")),
        chroma_collection=os.getenv("CHROMA_COLLECTION", "email_support_openai_m1"),
        retrieval_top_k=int(os.getenv("RETRIEVAL_TOP_K", "3")),
        gmail_credentials_path=_project_path(
            os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
        ),
        gmail_token_path=_project_path(os.getenv("GMAIL_TOKEN_PATH", "token.json")),
        my_email=os.getenv("MY_EMAIL", "").strip(),
    )
