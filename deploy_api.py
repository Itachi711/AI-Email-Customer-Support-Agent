"""Optional LangServe API. Import/route registration only compiles the lazy workflow."""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.runnables import RunnableBinding
from langserve import add_routes

from src.graph import Workflow


def get_runnable():
    return Workflow().app


def create_app(runnable=None) -> FastAPI:
    app = FastAPI(
        title="Gmail Automation",
        version="1.0",
        description="M1 StateGraph workflow; invoking it can create Gmail drafts.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
    graph = runnable if runnable is not None else get_runnable()
    # LangServe requests a Runnable config schema. A public binding keeps that
    # adapter on LangChain's API and delegates execution/streaming to StateGraph,
    # instead of calling LangGraph's deprecated config_schema compatibility API.
    add_routes(app, RunnableBinding(bound=graph))
    return app


app = create_app()


def main():
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
