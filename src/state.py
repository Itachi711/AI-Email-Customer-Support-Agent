"""Typed graph state and a fresh state factory for each inbox run."""

from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from .structure_outputs import EmailCategory


class Email(BaseModel):
    id: str = Field(..., description="Unique identifier of the email")
    threadId: str = Field(..., description="Thread identifier of the email")
    messageId: str = Field(..., description="Message identifier of the email")
    references: str = Field(..., description="References of the email")
    sender: str = Field(..., description="Email address of the sender")
    subject: str = Field(..., description="Subject line of the email")
    body: str = Field(..., description="Body content of the email")


class GraphState(TypedDict, total=False):
    """Nodes return partial updates; initial_state supplies the full starting state."""

    emails: list[Email]
    current_email: Email | None
    email_category: EmailCategory | None
    generated_email: str
    rag_queries: list[str]
    retrieved_documents: str
    writer_messages: Annotated[list[BaseMessage], add_messages]
    sendable: bool
    trials: int


def initial_state() -> GraphState:
    """Return independent mutable containers for a new workflow invocation."""
    return {
        "emails": [],
        "current_email": None,
        "email_category": None,
        "generated_email": "",
        "rag_queries": [],
        "retrieved_documents": "",
        "writer_messages": [],
        "sendable": False,
        "trials": 0,
    }
