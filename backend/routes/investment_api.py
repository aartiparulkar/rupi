from fastapi import APIRouter
from pydantic import BaseModel
from services.investment import InvestmentAdvisor
from services.rag_llm import generate_advice

router = APIRouter()

# ✅ SAME VARIABLE NAMES (IMPORTANT)
class InvestmentRequest(BaseModel):
    age: int
    income: float
    expenses: float
    savings: float
    risk: str
    horizon: str
    existing: str


@router.post("/investment")
def get_investment_plan(data: InvestmentRequest):

    profile = data.dict()

    advisor = InvestmentAdvisor(profile)
    result = advisor.run()

    # 🚨 HANDLE emergency case
    if result.get("status") == "unsafe":
        return {
            "analysis": result,
            "ai_response": result["advice"]
        }

    # 🔥 RAG + LLM
    ai_response = generate_advice(result)

    return {
        "analysis": result,
        "ai_response": ai_response
    }