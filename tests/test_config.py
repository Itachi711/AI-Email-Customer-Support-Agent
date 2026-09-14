import pytest

from src.config import PROJECT_ROOT, Settings, get_settings


def test_environment_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "explicit-account-model")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "explicit-embedding-model")
    monkeypatch.setenv("VECTOR_DB_PATH", str(tmp_path / "vectors"))
    monkeypatch.setenv("RETRIEVAL_TOP_K", "3")
    settings = get_settings()
    assert settings.chat_model == "explicit-account-model"
    assert settings.embedding_model == "explicit-embedding-model"
    assert settings.vector_db_path == tmp_path / "vectors"
    assert settings.retrieval_top_k == 3


def test_relative_paths_are_project_relative(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    settings = Settings()
    assert settings.vector_db_path == PROJECT_ROOT / "db_openai_m1"
    assert settings.gmail_credentials_path == PROJECT_ROOT / "credentials.json"


def test_missing_key_is_only_required_for_live_operation():
    settings = Settings()
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        settings.require_openai_key()


def test_settings_repr_redacts_key():
    settings = Settings(openai_api_key="offline-test-value")
    assert "offline-test-value" not in repr(settings)


def test_invalid_top_k_rejected():
    with pytest.raises(ValueError, match="RETRIEVAL_TOP_K"):
        Settings(retrieval_top_k=0)
