"""Exercise real LangChain/OpenAI SDK structured-output parsing via an in-memory HTTP transport."""

import json

import httpx
import pytest
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from src.agents import Agents, create_chat_model
from src.config import Settings
from src.structure_outputs import (
    CategorizeEmailOutput,
    ProofReaderOutput,
    RAGQueriesOutput,
    WriterOutput,
)


def response_body(payload):
    return {
        "id": "resp_offline",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "model": "configured-test-model",
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "output": [
            {
                "id": "msg_offline",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": json.dumps(payload), "annotations": []}
                ],
            }
        ],
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


@pytest.mark.parametrize(
    ("chain_name", "inputs", "payload", "schema"),
    [
        (
            "categorize_email",
            {"email": "Pricing?"},
            {"category": "product_enquiry"},
            CategorizeEmailOutput,
        ),
        (
            "design_rag_queries",
            {"email": "Pricing?"},
            {"queries": ["What is the price?"]},
            RAGQueriesOutput,
        ),
        (
            "email_writer",
            {"email_information": "Customer asks price", "history": []},
            {"email": "Dear Customer, the Pro plan is $49/month."},
            WriterOutput,
        ),
        (
            "email_proofreader",
            {"initial_email": "Pricing?", "generated_email": "$49"},
            {"feedback": "Clear answer", "send": True},
            ProofReaderOutput,
        ),
    ],
)
def test_openai_native_structured_pipelines(chain_name, inputs, payload, schema):
    requests = []

    def handle(request):
        assert request.url.path == "/v1/responses"
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response_body(payload))

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        model = ChatOpenAI(
            model="configured-test-model",
            api_key="test-only",
            use_responses_api=True,
            http_client=client,
            max_retries=0,
        )
        result = getattr(Agents(Settings(), llm=model), chain_name).invoke(inputs)
    assert isinstance(result, schema)
    assert result.model_dump(mode="json") == payload
    assert len(requests) == 1
    assert requests[0]["model"] == "configured-test-model"
    output_format = requests[0]["text"]["format"]
    assert output_format["type"] == "json_schema"
    assert output_format["strict"] is True
    assert output_format["schema"]["additionalProperties"] is False


def test_invalid_native_model_output_reports_schema_error():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=response_body({"category": "invented_category"})
            )
        )
    ) as client:
        model = ChatOpenAI(
            model="configured-test-model",
            api_key="test-only",
            use_responses_api=True,
            http_client=client,
            max_retries=0,
        )
        with pytest.raises(ValidationError, match="category"):
            Agents(Settings(), llm=model).categorize_email.invoke({"email": "hello"})


def test_default_factory_requires_key_but_agents_construction_does_not():
    agents = Agents(Settings())
    assert agents.settings.chat_model == "gpt-5.6-luna"
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        create_chat_model(agents.settings)
