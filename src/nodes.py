"""Workflow nodes with injectable integrations and reducer-safe state updates."""

from colorama import Fore, Style
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from .agents import Agents
from .state import Email, GraphState, initial_state
from .structure_outputs import (
    CategorizeEmailOutput,
    EmailCategory,
    ProofReaderOutput,
    RAGQueriesOutput,
    WriterOutput,
)
from .tools.GmailTools import GmailToolsClass


class Nodes:
    def __init__(self, agents=None, gmail_tools=None):
        self.agents = agents if agents is not None else Agents()
        self.gmail_tools = gmail_tools if gmail_tools is not None else GmailToolsClass()

    def load_new_emails(self, state: GraphState) -> GraphState:
        """Load unanswered Gmail messages without mutating the incoming state."""
        print(Fore.YELLOW + "Loading new emails...\n" + Style.RESET_ALL)
        recent_emails = self.gmail_tools.fetch_unanswered_emails()
        return {"emails": [Email.model_validate(email) for email in recent_emails]}

    def check_new_emails(self, state: GraphState) -> str:
        """Choose the next edge without modifying graph state."""
        return "process" if state.get("emails") else "empty"

    def is_email_inbox_empty(self, state: GraphState) -> GraphState:
        # Returning the full state would reapply add_messages to existing history.
        return {}

    def categorize_email(self, state: GraphState) -> GraphState:
        """Categorize the last queued email, preserving the original inbox order."""
        print(Fore.YELLOW + "Checking email category...\n" + Style.RESET_ALL)
        current_email = state["emails"][-1]
        result = CategorizeEmailOutput.model_validate(
            self.agents.categorize_email.invoke({"email": current_email.body})
        )
        print(Fore.MAGENTA + f"Email category: {result.category.value}" + Style.RESET_ALL)
        return {
            "email_category": result.category,
            "current_email": current_email,
            "generated_email": "",
            "rag_queries": [],
            "retrieved_documents": "",
            "writer_messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
            "sendable": False,
            "trials": 0,
        }

    def route_email_based_on_category(self, state: GraphState) -> str:
        """Route only the four supported categories; malformed state fails clearly."""
        category = EmailCategory(state["email_category"])
        if category == EmailCategory.product_enquiry:
            return "product related"
        if category == EmailCategory.unrelated:
            return "unrelated"
        return "not product related"

    def construct_rag_queries(self, state: GraphState) -> GraphState:
        print(Fore.YELLOW + "Designing RAG query...\n" + Style.RESET_ALL)
        query_result = RAGQueriesOutput.model_validate(
            self.agents.design_rag_queries.invoke({"email": state["current_email"].body})
        )
        return {"rag_queries": query_result.queries}

    def retrieve_from_rag(self, state: GraphState) -> GraphState:
        """Keep the original per-query retrieval and answer concatenation."""
        print(Fore.YELLOW + "Retrieving information from internal knowledge...\n" + Style.RESET_ALL)
        answers = []
        for query in state["rag_queries"]:
            rag_result = self.agents.generate_rag_answer.invoke(query)
            answers.append(f"{query}\n{rag_result}\n\n")
        return {"retrieved_documents": "".join(answers)}

    def write_draft_email(self, state: GraphState) -> GraphState:
        print(Fore.YELLOW + "Writing draft email...\n" + Style.RESET_ALL)
        category = EmailCategory(state["email_category"]).value
        inputs = (
            f'# **EMAIL CATEGORY:** {category}\n\n'
            f'# **EMAIL CONTENT:**\n{state["current_email"].body}\n\n'
            f'# **INFORMATION:**\n{state["retrieved_documents"]}'
        )
        draft_result = WriterOutput.model_validate(
            self.agents.email_writer.invoke({
                "email_information": inputs,
                "history": list(state.get("writer_messages", [])),
            })
        )
        trials = state.get("trials", 0) + 1
        return {
            "generated_email": draft_result.email,
            "trials": trials,
            # add_messages appends this delta exactly once.
            "writer_messages": [AIMessage(content=f"**Draft {trials}:**\n{draft_result.email}")],
        }

    def verify_generated_email(self, state: GraphState) -> GraphState:
        print(Fore.YELLOW + "Verifying generated email...\n" + Style.RESET_ALL)
        review = ProofReaderOutput.model_validate(
            self.agents.email_proofreader.invoke({
                "initial_email": state["current_email"].body,
                "generated_email": state["generated_email"],
            })
        )
        return {
            "sendable": review.send,
            "writer_messages": [HumanMessage(content=f"**Proofreader Feedback:**\n{review.feedback}")],
        }

    def must_rewrite(self, state: GraphState) -> str:
        """Pure routing: allow no more than three total writer attempts per email."""
        if state["sendable"]:
            return "send"
        return "stop" if state["trials"] >= 3 else "rewrite"

    @staticmethod
    def _finish_current_email(state: GraphState) -> GraphState:
        """Remove the completed item and reset all state belonging to that email."""
        return {
            **initial_state(),
            "emails": state["emails"][:-1],
            # An empty list cannot clear a channel using the add_messages reducer.
            "writer_messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
        }

    def create_draft_response(self, state: GraphState) -> GraphState:
        """Create a Gmail draft, then complete this email only if creation succeeds."""
        print(Fore.YELLOW + "Creating draft email...\n" + Style.RESET_ALL)
        self.gmail_tools.create_draft_reply(state["current_email"], state["generated_email"])
        return self._finish_current_email(state)

    def send_email_response(self, state: GraphState) -> GraphState:
        """Preserve the explicit send helper; the graph uses create_draft_response."""
        print(Fore.YELLOW + "Sending email...\n" + Style.RESET_ALL)
        self.gmail_tools.send_reply(state["current_email"], state["generated_email"])
        return self._finish_current_email(state)

    def skip_unrelated_email(self, state: GraphState) -> GraphState:
        print("Skipping unrelated email...\n")
        return self._finish_current_email(state)

    def discard_unsendable_email(self, state: GraphState) -> GraphState:
        """Finish an exhausted email before checking whether another one remains."""
        print(Fore.RED + "Email reached the maximum of three drafts; skipping.\n" + Style.RESET_ALL)
        return self._finish_current_email(state)
