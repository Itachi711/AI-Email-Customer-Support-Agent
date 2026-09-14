"""Run one Gmail polling pass, or explicit side-effect-free compatibility checks."""

import argparse

from src.agents import Agents
from src.config import get_settings
from src.graph import Workflow
from src.state import initial_state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Compile graph offline without Gmail")
    mode.add_argument(
        "--openai-smoke", action="store_true", help="One live structured-output call; no Gmail"
    )
    args = parser.parse_args()
    if args.check:
        Workflow()
        print("PASS: imports and StateGraph compile (no external services)")
        return
    settings = get_settings()
    if args.openai_smoke:
        if not settings.openai_api_key.strip():
            print("NOT RUN - OPENAI_API_KEY unavailable")
            return
        result = Agents(settings).categorize_email.invoke(
            {"email": "Hello, what are the pricing options for your product?"}
        )
        print(f"PASS: OpenAI structured output: {result.category.value}")
        return
    settings.require_openai_key()
    workflow = Workflow()
    print("Starting workflow (one polling pass; approved replies become Gmail drafts)...")
    for output in workflow.app.stream(initial_state(), {"recursion_limit": 100}):
        for key in output:
            print(f"Finished running: {key}")


if __name__ == "__main__":
    main()
