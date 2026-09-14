"""Build the M1 index explicitly. Importing this module does not create files or call APIs."""

import argparse

from src.agents import Agents
from src.config import get_settings
from src.rag import build_index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-query", help="Optionally run a live RAG query after building")
    args = parser.parse_args()
    settings = get_settings()
    store = build_index(settings)
    print(f"Index ready: {settings.vector_db_path} ({len(store.get()['ids'])} chunks)")
    if args.smoke_query:
        print(Agents(settings).generate_rag_answer.invoke(args.smoke_query))


if __name__ == "__main__":
    main()
