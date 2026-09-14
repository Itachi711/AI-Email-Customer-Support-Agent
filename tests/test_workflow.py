"""Offline regression tests for the original inbox -> draft StateGraph."""

from copy import deepcopy
from itertools import count
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.message import add_messages
from pydantic import ValidationError

from src.graph import Workflow
from src.nodes import Nodes
from src.state import Email, initial_state
from src.structure_outputs import (
    CategorizeEmailOutput,
    EmailCategory,
    ProofReaderOutput,
    RAGQueriesOutput,
    WriterOutput,
)


def make_email(identifier="one"):
    return Email(
        id=identifier,
        threadId=f"thread-{identifier}",
        messageId=f"<{identifier}@example.test>",
        references="",
        sender="customer@example.test",
        subject=f"Subject {identifier}",
        body=f"Question {identifier}",
    )


def fake_nodes(emails=(), category="customer_feedback", verdicts=(True,)):
    """Only these test doubles may load or create Gmail messages in this module."""
    drafts = count(1)
    agents = SimpleNamespace(
        categorize_email=Mock(),
        design_rag_queries=Mock(),
        generate_rag_answer=Mock(),
        email_writer=Mock(),
        email_proofreader=Mock(),
    )
    agents.categorize_email.invoke.return_value = CategorizeEmailOutput(category=category)
    agents.design_rag_queries.invoke.return_value = RAGQueriesOutput(queries=["What is included?"])
    agents.generate_rag_answer.invoke.return_value = "Included product information."
    agents.email_writer.invoke.side_effect = lambda _: WriterOutput(email=f"Draft body {next(drafts)}")
    agents.email_proofreader.invoke.side_effect = [
        ProofReaderOutput(feedback=f"Review {i}", send=value)
        for i, value in enumerate(verdicts, start=1)
    ]
    gmail = Mock(spec=["fetch_unanswered_emails", "create_draft_reply", "send_reply"])
    gmail.fetch_unanswered_emails.return_value = [email.model_dump() for email in emails]
    return Nodes(agents=agents, gmail_tools=gmail), agents, gmail


def run_workflow(nodes):
    return Workflow(nodes=nodes).app.invoke(initial_state(), {"recursion_limit": 100})


def test_initial_state_has_independent_mutable_containers():
    first, second = initial_state(), initial_state()
    first["emails"].append(make_email())
    first["writer_messages"].append(AIMessage(content="old draft"))
    first["rag_queries"].append("old question")
    assert second["emails"] == second["writer_messages"] == second["rag_queries"] == []


def test_default_workflow_compiles_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    graph = Workflow().app.get_graph()
    assert {
        "load_inbox_emails", "is_email_inbox_empty", "categorize_email",
        "construct_rag_queries", "retrieve_from_rag", "email_writer",
        "email_proofreader", "send_email", "skip_unrelated_email",
    } <= graph.nodes.keys()


def test_empty_inbox_does_not_invoke_agents_or_create_drafts():
    nodes, agents, gmail = fake_nodes()
    result = run_workflow(nodes)
    assert result == initial_state()
    agents.categorize_email.invoke.assert_not_called()
    agents.email_writer.invoke.assert_not_called()
    gmail.create_draft_reply.assert_not_called()
    gmail.send_reply.assert_not_called()


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("product_enquiry", "product related"),
        ("customer_complaint", "not product related"),
        ("customer_feedback", "not product related"),
        ("unrelated", "unrelated"),
    ],
)
def test_category_router_is_pure(category, expected):
    nodes, _, _ = fake_nodes()
    state = {**initial_state(), "email_category": category, "emails": [make_email()]}
    before = deepcopy(state)
    assert nodes.route_email_based_on_category(state) == expected
    assert state == before


def test_category_router_rejects_unknown_category():
    nodes, _, _ = fake_nodes()
    with pytest.raises(ValueError, match="EmailCategory"):
        nodes.route_email_based_on_category({"email_category": "unknown"})


@pytest.mark.parametrize(("emails", "expected"), [([], "empty"), ([make_email()], "process")])
def test_inbox_router_and_check_node_do_not_mutate_state(emails, expected):
    nodes, _, _ = fake_nodes()
    state = {**initial_state(), "emails": emails, "writer_messages": [AIMessage(content="history")]}
    before = deepcopy(state)
    assert nodes.check_new_emails(state) == expected
    assert nodes.is_email_inbox_empty(state) == {}
    assert state == before


@pytest.mark.parametrize(
    ("sendable", "trials", "expected"),
    [(True, 1, "send"), (True, 3, "send"), (False, 1, "rewrite"), (False, 2, "rewrite"), (False, 3, "stop")],
)
def test_retry_router_is_pure(sendable, trials, expected):
    nodes, _, _ = fake_nodes()
    state = {
        **initial_state(), "emails": [make_email()], "sendable": sendable, "trials": trials,
        "writer_messages": [AIMessage(content="draft")],
    }
    before = deepcopy(state)
    assert nodes.must_rewrite(state) == expected
    assert state == before


def test_writer_and_proofreader_emit_only_typed_message_deltas():
    nodes, agents, _ = fake_nodes(verdicts=(False,))
    prior = [AIMessage(content="earlier draft", id="draft"), HumanMessage(content="revise", id="review")]
    state = {
        **initial_state(), "current_email": make_email(), "email_category": EmailCategory.customer_feedback,
        "trials": 1, "writer_messages": prior,
    }
    before = deepcopy(state)
    written = nodes.write_draft_email(state)
    assert state == before
    assert written["trials"] == 2
    assert len(written["writer_messages"]) == 1
    assert isinstance(written["writer_messages"][0], AIMessage)
    assert agents.email_writer.invoke.call_args.args[0]["history"] == prior
    merged = {**state, **written, "writer_messages": add_messages(prior, written["writer_messages"])}
    before_review = deepcopy(merged)
    reviewed = nodes.verify_generated_email(merged)
    assert merged == before_review
    assert len(reviewed["writer_messages"]) == 1
    assert isinstance(reviewed["writer_messages"][0], HumanMessage)
    assert len(add_messages(merged["writer_messages"], reviewed["writer_messages"])) == 4


@pytest.mark.parametrize("category", ["customer_feedback", "customer_complaint"])
def test_non_product_path_creates_one_draft_without_rag(category):
    email = make_email()
    nodes, agents, gmail = fake_nodes([email], category=category)
    assert run_workflow(nodes) == initial_state()
    agents.design_rag_queries.invoke.assert_not_called()
    agents.generate_rag_answer.invoke.assert_not_called()
    gmail.create_draft_reply.assert_called_once_with(email, "Draft body 1")
    gmail.send_reply.assert_not_called()


def test_product_path_preserves_per_query_retrieval_and_writer_context():
    email = make_email()
    nodes, agents, gmail = fake_nodes([email], category="product_enquiry")
    queries = ["What is included?", "What does it cost?", "How is it delivered?"]
    agents.design_rag_queries.invoke.return_value = RAGQueriesOutput(queries=queries)
    assert run_workflow(nodes) == initial_state()
    assert [call.args[0] for call in agents.generate_rag_answer.invoke.call_args_list] == queries
    writer_input = agents.email_writer.invoke.call_args.args[0]
    assert writer_input["history"] == []
    assert "# **EMAIL CATEGORY:** product_enquiry" in writer_input["email_information"]
    for query in queries:
        assert f"{query}\nIncluded product information.\n\n" in writer_input["email_information"]
    gmail.create_draft_reply.assert_called_once_with(email, "Draft body 1")
    gmail.send_reply.assert_not_called()


def test_unrelated_email_is_skipped_without_writer_or_gmail_draft():
    nodes, agents, gmail = fake_nodes([make_email()], category="unrelated")
    assert run_workflow(nodes) == initial_state()
    agents.email_writer.invoke.assert_not_called()
    agents.email_proofreader.invoke.assert_not_called()
    gmail.create_draft_reply.assert_not_called()
    gmail.send_reply.assert_not_called()


@pytest.mark.parametrize(("verdicts", "draft_count"), [((False, False, True), 1), ((False, False, False), 0)])
def test_three_attempt_limit_and_history_without_duplication(verdicts, draft_count):
    nodes, agents, gmail = fake_nodes([make_email()], verdicts=verdicts)
    assert run_workflow(nodes) == initial_state()
    assert agents.email_writer.invoke.call_count == 3
    assert agents.email_proofreader.invoke.call_count == 3
    histories = [call.args[0]["history"] for call in agents.email_writer.invoke.call_args_list]
    assert [len(history) for history in histories] == [0, 2, 4]
    assert [message.type for message in histories[-1]] == ["ai", "human", "ai", "human"]
    assert "Draft 1" in histories[-1][0].content
    assert "Draft 2" in histories[-1][2].content
    assert gmail.create_draft_reply.call_count == draft_count
    if draft_count:
        assert gmail.create_draft_reply.call_args.args[1] == "Draft body 3"
    gmail.send_reply.assert_not_called()


def test_exhausted_email_continues_to_next_email_with_fresh_history_and_retry_budget():
    next_email, exhausted = make_email("next"), make_email("exhausted")
    nodes, agents, gmail = fake_nodes([next_email, exhausted], verdicts=(False, False, False, True))
    assert run_workflow(nodes) == initial_state()
    assert [call.args[0]["email"] for call in agents.categorize_email.invoke.call_args_list] == [
        exhausted.body, next_email.body,
    ]
    histories = [call.args[0]["history"] for call in agents.email_writer.invoke.call_args_list]
    assert [len(history) for history in histories] == [0, 2, 4, 0]
    gmail.create_draft_reply.assert_called_once_with(next_email, "Draft body 4")
    gmail.send_reply.assert_not_called()


def test_product_context_does_not_leak_to_the_next_feedback_email():
    feedback, product = make_email("feedback"), make_email("product")
    nodes, agents, gmail = fake_nodes([feedback, product], verdicts=(True, True))
    agents.categorize_email.invoke.side_effect = [
        CategorizeEmailOutput(category="product_enquiry"),
        CategorizeEmailOutput(category="customer_feedback"),
    ]
    assert run_workflow(nodes) == initial_state()
    first, second = [call.args[0] for call in agents.email_writer.invoke.call_args_list]
    assert "Included product information." in first["email_information"]
    assert "Included product information." not in second["email_information"]
    assert second["email_information"].endswith("# **INFORMATION:**\n")
    assert second["history"] == []
    assert [call.args[0] for call in gmail.create_draft_reply.call_args_list] == [product, feedback]
    gmail.send_reply.assert_not_called()


def test_draft_failure_does_not_mutate_or_remove_current_email():
    nodes, _, gmail = fake_nodes()
    email = make_email()
    state = {
        **initial_state(), "emails": [email], "current_email": email,
        "generated_email": "ready", "writer_messages": [AIMessage(content="ready")],
    }
    before = deepcopy(state)
    gmail.create_draft_reply.side_effect = RuntimeError("fake draft failure")
    with pytest.raises(RuntimeError, match="fake draft failure"):
        nodes.create_draft_response(state)
    assert state == before
    gmail.send_reply.assert_not_called()


def test_invalid_model_output_fails_clearly_before_gmail_effects():
    nodes, agents, gmail = fake_nodes([make_email()])
    agents.categorize_email.invoke.return_value = {"category": "unsupported"}
    with pytest.raises(ValidationError, match="category"):
        run_workflow(nodes)
    agents.email_writer.invoke.assert_not_called()
    gmail.create_draft_reply.assert_not_called()
    gmail.send_reply.assert_not_called()
