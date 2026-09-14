"""Dense retrieval with a separate, explicitly identified OpenAI index."""

import hashlib
import json
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import PROJECT_ROOT, Settings, get_settings

DOCUMENT_PATH = PROJECT_ROOT / "data" / "agency.txt"
CHUNK_SIZE = 300
CHUNK_OVERLAP = 50
MANIFEST_NAME = "m1-index.json"


def load_chunks(source: Path = DOCUMENT_PATH) -> list[Document]:
    # Same text document and splitter as before; explicit UTF-8 works on Windows.
    documents = [
        Document(page_content=source.read_text(encoding="utf-8"), metadata={"source": str(source)})
    ]
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    ).split_documents(documents)


def create_embeddings(settings: Settings) -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.require_openai_key(),
    )


def _check_path(settings: Settings) -> None:
    legacy = (PROJECT_ROOT / "db").resolve()
    if settings.vector_db_path == legacy or settings.vector_db_path.is_relative_to(legacy):
        raise ValueError("Legacy db/ is protected. Set VECTOR_DB_PATH to a new directory.")


def _identity(settings: Settings) -> dict:
    return {
        "format": 1,
        "provider": "openai",
        "embedding_model": settings.embedding_model,
        "collection": settings.chroma_collection,
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
    }


def _read_manifest(settings: Settings) -> dict:
    _check_path(settings)
    manifest = settings.vector_db_path / MANIFEST_NAME
    if not manifest.is_file():
        raise ValueError(
            "No compatible M1 index. Run python create_index.py in a new VECTOR_DB_PATH."
        )
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if any(data.get(key) != value for key, value in _identity(settings).items()):
        raise ValueError("Index configuration mismatch. Build a new index in a new VECTOR_DB_PATH.")
    return data


def build_index(settings: Settings | None = None, *, embeddings=None) -> Chroma:
    settings = settings if settings is not None else get_settings()
    _check_path(settings)
    chunks = load_chunks()
    identity = _identity(settings) | {
        "source": "data/agency.txt",
        "source_sha256": hashlib.sha256(DOCUMENT_PATH.read_bytes()).hexdigest(),
        "chunk_count": len(chunks),
    }
    path = settings.vector_db_path
    existing = path.exists() and any(path.iterdir())
    if existing:
        if _read_manifest(settings) != identity:
            raise ValueError(
                "Source/index changed. Rebuild into a new VECTOR_DB_PATH; old data is preserved."
            )
    embedding_function = embeddings if embeddings is not None else create_embeddings(settings)
    store = Chroma(
        collection_name=settings.chroma_collection,
        persist_directory=str(path),
        embedding_function=embedding_function,
        create_collection_if_not_exists=not existing,
    )
    if existing:
        if len(store.get()["ids"]) != len(chunks):
            raise ValueError("Index is incomplete. Build in a new VECTOR_DB_PATH.")
        return store
    ids = [f"agency-{identity['source_sha256']}-{i}" for i in range(len(chunks))]
    store.add_documents(chunks, ids=ids)
    (path / MANIFEST_NAME).write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    return store


def load_retriever(settings: Settings | None = None, *, embeddings=None):
    settings = settings if settings is not None else get_settings()
    manifest = _read_manifest(settings)
    embedding_function = embeddings if embeddings is not None else create_embeddings(settings)
    store = Chroma(
        collection_name=settings.chroma_collection,
        persist_directory=str(settings.vector_db_path),
        embedding_function=embedding_function,
        create_collection_if_not_exists=False,
    )
    if len(store.get()["ids"]) != manifest["chunk_count"]:
        raise ValueError("Index is incomplete. Build in a new VECTOR_DB_PATH.")
    return store.as_retriever(
        search_type="similarity", search_kwargs={"k": settings.retrieval_top_k}
    )
