"""The original five LCEL pipelines, initialized only when invoked."""

from functools import cached_property

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder, PromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI

from .config import Settings, get_settings
from .prompts import (
    CATEGORIZE_EMAIL_PROMPT,
    EMAIL_PROOFREADER_PROMPT,
    EMAIL_WRITER_PROMPT,
    GENERATE_RAG_ANSWER_PROMPT,
    GENERATE_RAG_QUERIES_PROMPT,
)
from .structure_outputs import (
    CategorizeEmailOutput,
    ProofReaderOutput,
    RAGQueriesOutput,
    WriterOutput,
)


def create_chat_model(settings: Settings) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.chat_model,
        api_key=settings.require_openai_key(),
        temperature=settings.chat_temperature,
        use_responses_api=True,
        timeout=60,
        max_retries=2,
    )


class Agents:
    def __init__(self, settings: Settings | None = None, *, llm=None, retriever=None):
        self.settings = settings if settings is not None else get_settings()
        self._llm = llm
        self._retriever = retriever

    @cached_property
    def llm(self):
        return self._llm if self._llm is not None else create_chat_model(self.settings)

    def _structured(self, prompt, schema):
        return prompt | self.llm.with_structured_output(schema, method="json_schema", strict=True)

    @cached_property
    def categorize_email(self):
        return self._structured(
            PromptTemplate.from_template(CATEGORIZE_EMAIL_PROMPT), CategorizeEmailOutput
        )

    @cached_property
    def design_rag_queries(self):
        return self._structured(
            PromptTemplate.from_template(GENERATE_RAG_QUERIES_PROMPT), RAGQueriesOutput
        )

    @cached_property
    def generate_rag_answer(self):
        from .rag import load_retriever

        retriever = (
            self._retriever if self._retriever is not None else load_retriever(self.settings)
        )
        # Preserve the original retriever -> prompt -> LLM -> text data flow.
        return (
            {"context": retriever, "question": RunnablePassthrough()}
            | ChatPromptTemplate.from_template(GENERATE_RAG_ANSWER_PROMPT)
            | self.llm
            | StrOutputParser()
        )

    @cached_property
    def email_writer(self):
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", EMAIL_WRITER_PROMPT),
                MessagesPlaceholder("history"),
                ("human", "{email_information}"),
            ]
        )
        return self._structured(prompt, WriterOutput)

    @cached_property
    def email_proofreader(self):
        return self._structured(
            PromptTemplate.from_template(EMAIL_PROOFREADER_PROMPT), ProofReaderOutput
        )
