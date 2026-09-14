import importlib
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.graph import Workflow
from src.nodes import Nodes
from src.state import initial_state

pytestmark = pytest.mark.filterwarnings("error::langgraph.warnings.LangGraphDeprecationWarning")


@pytest.fixture
def fake_workflow():
    calls = []

    def fetch():
        calls.append("fetch")
        return []

    nodes = Nodes(agents=object(), gmail_tools=SimpleNamespace(fetch_unanswered_emails=fetch))
    return Workflow(nodes=nodes).app, calls


def test_core_imports_without_key_or_credentials():
    for name in (
        "src.config",
        "src.state",
        "src.structure_outputs",
        "src.prompts",
        "src.agents",
        "src.rag",
        "src.tools.GmailTools",
        "src.nodes",
        "src.graph",
        "main",
        "create_index",
        "deploy_api",
    ):
        importlib.import_module(name)
    assert Workflow().app is not None


def test_langserve_schema_and_invoke_use_fake_gmail(fake_workflow):
    from deploy_api import create_app

    graph, calls = fake_workflow
    app = create_app(graph)
    with TestClient(app) as client:
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/input_schema").status_code == 200
        assert client.get("/output_schema").status_code == 200
        # LangServe also applies with_config() here; it must stay on the binding
        # rather than invoking LangGraph's deprecated config_schema API.
        config_schema = client.get("/config_schema")
        assert config_schema.status_code == 200
        assert config_schema.json()["type"] == "object"
        result = client.post("/invoke", json={"input": initial_state()})
    assert result.status_code == 200, result.text
    assert result.json()["output"]["emails"] == []
    assert calls == ["fetch"]


@pytest.mark.parametrize("endpoint", ["/stream", "/stream_events"])
def test_langserve_sse_streams_fake_graph_to_completion(fake_workflow, endpoint):
    from deploy_api import create_app

    graph, calls = fake_workflow
    with TestClient(create_app(graph)) as client:
        with client.stream("POST", endpoint, json={"input": initial_state()}) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            lines = list(response.iter_lines())

    assert "event: end" in lines
    assert "event: error" not in lines
    payloads = [
        json.loads(line.removeprefix("data: ")) for line in lines if line.startswith("data: ")
    ]
    if endpoint == "/stream":
        assert any(payload.get("load_inbox_emails") == {"emails": []} for payload in payloads)
    else:
        assert any(
            payload.get("event") == "on_chain_end"
            and payload.get("data", {}).get("output", {}).get("emails") == []
            for payload in payloads
        )
    assert calls == ["fetch"]
