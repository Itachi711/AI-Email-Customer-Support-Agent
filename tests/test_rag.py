from dataclasses import replace

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.runnables import RunnableLambda

from src.agents import Agents
from src.config import PROJECT_ROOT, Settings
from src.rag import build_index, load_chunks, load_retriever


def test_rag_pipeline_with_fake_retriever_and_llm():
    calls = []
    chunks = load_chunks()

    def retrieve(query):
        calls.append(query)
        return chunks[:3]

    model = FakeListChatModel(responses=["The Pro plan is $49/month."])
    agents = Agents(Settings(), llm=model, retriever=RunnableLambda(retrieve))
    assert (
        agents.generate_rag_answer.invoke("What is the Pro plan price?")
        == "The Pro plan is $49/month."
    )
    assert calls == ["What is the Pro plan price?"]


def test_chroma_build_reopen_query_and_repeat_without_duplicates(tmp_path):
    settings = Settings(vector_db_path=tmp_path / "new-index")
    fake = DeterministicFakeEmbedding(size=32)
    store = build_index(settings, embeddings=fake)
    chunks = load_chunks()
    assert len(store.get()["ids"]) == len(chunks) > 3
    assert max(len(chunk.page_content) for chunk in chunks) <= 300
    retriever = load_retriever(settings, embeddings=fake)
    assert retriever.search_kwargs == {"k": 3}
    assert len(retriever.invoke("pricing")) == 3
    again = build_index(settings, embeddings=fake)
    assert again.get()["ids"] == store.get()["ids"]
    with pytest.raises(ValueError, match="mismatch"):
        load_retriever(replace(settings, embedding_model="different-model"), embeddings=fake)
    with pytest.raises(ValueError, match="mismatch"):
        build_index(replace(settings, chroma_collection="different_collection"), embeddings=fake)


def test_legacy_index_rejected_before_chroma_is_opened():
    with pytest.raises(ValueError, match="protected"):
        build_index(Settings(vector_db_path=PROJECT_ROOT / "db"))
    with pytest.raises(ValueError, match="protected"):
        load_retriever(Settings(vector_db_path=PROJECT_ROOT / "db" / "new"))


def test_unknown_index_is_preserved(tmp_path):
    path = tmp_path / "unknown"
    path.mkdir()
    marker = path / "original.txt"
    marker.write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="compatible M1 index"):
        build_index(Settings(vector_db_path=path))
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_missing_index_does_not_create_directory(tmp_path):
    path = tmp_path / "not-built"
    with pytest.raises(ValueError, match="create_index.py"):
        load_retriever(Settings(vector_db_path=path))
    assert not path.exists()
