"""Pydantic v2 contracts for the existing structured agent outputs."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class EmailCategory(StrEnum):
    product_enquiry = "product_enquiry"
    customer_complaint = "customer_complaint"
    customer_feedback = "customer_feedback"
    unrelated = "unrelated"


class StructuredOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CategorizeEmailOutput(StructuredOutput):
    category: EmailCategory = Field(
        ...,
        description="The category assigned to the email, indicating its type based on predefined rules.",
    )


NonEmptyQuery = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RAGQueriesOutput(StructuredOutput):
    queries: list[NonEmptyQuery] = Field(
        ...,
        min_length=1,
        max_length=3,
        description="One to three questions representing the customer's intent, based on their email.",
    )


class WriterOutput(StructuredOutput):
    email: str = Field(
        ...,
        min_length=1,
        description="The draft email written in response to the customer's inquiry, adhering to company tone and standards.",
    )


class ProofReaderOutput(StructuredOutput):
    feedback: str = Field(
        ...,
        description="Detailed feedback explaining why the email is or is not sendable.",
    )
    send: bool = Field(
        ...,
        strict=True,
        description="Indicates whether the email is ready to be sent (true) or requires rewriting (false).",
    )
