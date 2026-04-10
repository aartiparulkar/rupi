import os
from dotenv import load_dotenv

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
# from langchain_anthropic import ChatAnthropic   # optional

load_dotenv()


def generate_advice(result):
    # ==============================
    # LOAD VECTOR DB
    # ==============================
    embedding_model = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-mpnet-base-v2"
    )

    vectorstore = Chroma(
        persist_directory="../chroma_storage_txt",
        embedding_function=embedding_model
    )

    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

    # ==============================
    # RETRIEVE CONTEXT
    # ==============================
    category = result["category"]

    query = f"Investment strategy for {category} investor"

    docs = retriever.invoke(query)

    context = "\n\n".join([doc.page_content for doc in docs])

    # ==============================
    # GEMINI (WORKING VERSION)
    # ==============================
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",   # ✅ stable model
        temperature=0.3
    )

    # ==============================
    # CLAUDE (OPTIONAL)
    # ==============================
    # llm = ChatAnthropic(
    #     model="claude-3-haiku-20240307",
    #     temperature=0.3
    # )

    # ==============================
    # PROMPT
    # ==============================
    # prompt = f"""
    #  You are a financial advisor AI.

    # User Profile:
    # -Age: {result['age']} years
    # -Risk: {result['risk']}
    # -Horizon: {result['horizon']}
    # - Category: {result['category']}
    # - Savings Ratio: {result['savings_ratio']}
    # - Emergency Fund: {result['emergency_fund_months']} months



    # Context:

    # {context}

    # Task:
    # Give a personalized investment strategy.

    # Include:
    # -Include what are the investment meaning , explain them how it has to be done 
    # - Investment allocation
    # - Risk management
    # - Savings plan
    # - Mistakes to avoid
    # - Recommended investment allocation  like SBI, ICICI ,AXIS according to the market trends and the user's profile.
    # -Create it visual appeling like it can be visulaized in a pie chart or bar graph.
    # """



    prompt = f"""
    You are a Indian financial advisor AI.  
Your role is to generate a **clear, structured, and visual investment strategy** using ONLY the retrieved context.  

User Profile:
- Age: {result['age']} years
- Risk Appetite: {result['risk']}
- Investment Horizon: {result['horizon']}
- Category: {result['category']}
- Savings Ratio: {result['savings_ratio']}
- Emergency Fund: {result['emergency_fund_months']} months

Context:
{context}
Advice:{result['advice']}
Extra Advice:{result['extra_advice']}

Task:
Create a **personalized investment strategy** that progresses from **basic to advanced concepts**, ensuring it is understandable for beginners yet insightful for advanced users.  
━━━━━━━━━━━━━━━━━━━━━━━
STRICT OUTPUT RULES (VERY IMPORTANT)
━━━━━━━━━━━━━━━━━━━━━━━
1. DO NOT generate:
   - ASCII diagrams
   - Text-based charts
   - Boxes, lines, or visual drawings
   - Code blocks (```)
2. DO NOT simulate charts visually.
3. KEEP explanation clean and readable.


Include all the below points sequentially :
1. Investment Basics – Explain key terms simply (stocks, bonds, mutual funds, SIPs, etc.).  
2. Investment Allocation – Show recommended distribution across asset classes.  
3. Risk Management – Explain how to balance risk vs. return.  
4. Savings Plan – Suggest monthly savings discipline.  
5. Mistakes to Avoid – Common pitfalls for investors.  
6. Recommended Allocation – Suggest banks/funds (e.g., SBI, ICICI, AXIS) based on market trends and user profile or mentioned in advice {result['advice']} even if the context doesn't have specific information.  
7. Final Allocation Summary :provide ONLY  structured data  

At the END, ALWAYS include a disclaimer: "This advice is generated based on the user's profile and retrieved context. It is for informational purposes only and should not be considered as financial advice. Always consult with a certified financial advisor before making investment decisions."

━━━━━━━━━━━━━━━━━━━━━━━

IMPORTANT:
- Make response human-like and natural.


 
Remember:give a comprehensive strategy that educates and guides the user, leveraging the context effectively while ensuring clarity and actionable advice and the reponse you have curated will be visble to the user so ensure that they shouldn not give any information that tells that it is ai generated.
  """



    response = llm.invoke(prompt)

    return response.content