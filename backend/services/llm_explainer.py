"""LLM explanation generator using LangChain."""

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.config import settings


class LLMExplainer:
    """Generate simple-language tax explanations."""

    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=settings.openai_api_key,
            temperature=0.2,
        )

    def generate_tax_explanation(self, payload: dict) -> str:
        """Generate human-readable tax explanation from computed values."""
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "Explain Indian tax outcomes in plain language for salaried users. "
                    "Be concise and practical.",
                ),
                (
                    "human",
                    "Given this tax payload, explain total tax, why this amount applies, "
                    "and 2-3 practical deduction tips. Payload: {payload}",
                ),
            ]
        )

        chain = prompt | self.llm
        response = chain.invoke({"payload": payload})
        return (response.content or "").strip()


llm_explainer = LLMExplainer()
