"""Structured-output validation is independent of provider keys or network access."""

import pytest
from pydantic import ValidationError

from src.structure_outputs import (
    CategorizeEmailOutput,
    EmailCategory,
    ProofReaderOutput,
    RAGQueriesOutput,
    WriterOutput,
)


@pytest.mark.parametrize("category", list(EmailCategory))
def test_original_email_categories_are_valid(category):
    parsed = CategorizeEmailOutput.model_validate({"category": category.value})
    assert parsed.category is category


@pytest.mark.parametrize("category", ["unknown", "", None, 123])
def test_invalid_category_is_rejected(category):
    with pytest.raises(ValidationError, match="category"):
        CategorizeEmailOutput.model_validate({"category": category})


@pytest.mark.parametrize("size", [1, 2, 3])
def test_baseline_query_count_is_one_to_three(size):
    assert len(RAGQueriesOutput(queries=[f"Question {i}?" for i in range(size)]).queries) == size


@pytest.mark.parametrize("queries", [[], ["q"] * 4, [""], ["   "], [123], "question"])
def test_invalid_rag_queries_are_rejected(queries):
    with pytest.raises(ValidationError, match="queries"):
        RAGQueriesOutput.model_validate({"queries": queries})


def test_writer_and_proofreader_construct_without_any_model():
    assert WriterOutput(email="Hello, here is our reply.").email.startswith("Hello")
    assert ProofReaderOutput(feedback="Ready", send=True).send is True
    assert ProofReaderOutput(feedback="Please revise", send=False).send is False


@pytest.mark.parametrize("send", ["false", "true", 0, 1, None])
def test_proofreader_requires_a_boolean_verdict(send):
    with pytest.raises(ValidationError, match="send"):
        ProofReaderOutput.model_validate({"feedback": "Review", "send": send})


@pytest.mark.parametrize("email", ["", 42, None])
def test_invalid_writer_result_is_rejected(email):
    with pytest.raises(ValidationError, match="email"):
        WriterOutput.model_validate({"email": email})


def test_unexpected_structured_fields_are_rejected():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        CategorizeEmailOutput.model_validate({"category": "unrelated", "invented": "field"})


def test_json_schema_retains_enum_query_bounds_and_required_fields():
    schema = RAGQueriesOutput.model_json_schema()
    assert schema["properties"]["queries"]["minItems"] == 1
    assert schema["properties"]["queries"]["maxItems"] == 3
    assert schema["additionalProperties"] is False
    category_schema = CategorizeEmailOutput.model_json_schema()
    assert set(category_schema["$defs"]["EmailCategory"]["enum"]) == {
        "product_enquiry", "customer_complaint", "customer_feedback", "unrelated",
    }
    assert ProofReaderOutput.model_json_schema()["required"] == ["feedback", "send"]
