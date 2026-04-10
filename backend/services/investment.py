from .rag_llm import generate_advice
class InvestmentAdvisor:

    def __init__(self, profile):
        self.profile = profile
        self.score = 0

    # 📊 Step 1: Calculate financial metrics
    def calculate_metrics(self):
        income = self.profile["income"]
        expenses = self.profile["expenses"]
        savings = self.profile["savings"]

        self.savings_ratio = (income - expenses) / income if income > 0 else 0
        self.emergency_fund_months = savings / expenses if expenses > 0 else 0

    # 🎯 Step 2: Score calculation
    def calculate_score(self):
        age = self.profile["age"]
        risk = self.profile["risk"]
        horizon = self.profile["horizon"]
        existing = self.profile.get("existing", "none")

        # AGE SCORE (Weighted - higher impact)
        if age < 30:
            self.score += 4
        elif age < 35:
            self.score += 3
        elif age < 40:
            self.score += 1
        else:
            self.score -= 2

        # SAVINGS SCORE
        if self.savings_ratio < 0.1:
            self.score -= 2
        elif self.savings_ratio < 0.3:
            self.score += 0
        elif self.savings_ratio < 0.5:
            self.score += 1
        else:
            self.score += 2

        # RISK SCORE
        if risk == "low":
            self.score -= 2
        elif risk == "medium":
            self.score += 0
        else:
            self.score += 2

        # HORIZON SCORE
        if horizon == "short":
            self.score -= 2
        elif horizon == "medium":
            self.score += 0
        else:
            self.score += 2

        # EXISTING INVESTMENT SCORE
        if existing == "none":
            self.score -= 1
        elif existing == "fd":
            self.score += 0
        elif existing == "mutual":
            self.score += 2
        elif existing == "stocks":
            self.score += 3
        else:
            self.score += 1

    # 🚨 Step 3: Emergency fund check
    def emergency_check(self):
        return self.emergency_fund_months < 6

    # 🧠 Step 4: Classification
    def classify(self):
        if self.score <= -2:
            return "Survival", ["Focus on saving", "Avoid risky investments", "Use FD"]
        elif self.score <= 2:
            return "Conservative", ["FD", "Debt funds", "Low risk instruments"]
        elif self.score <= 5:
            return "Balanced", ["Hybrid mutual funds", "Mix equity & debt"]
        elif self.score <= 8:
            return "Growth", ["Equity mutual funds", "Index funds", "SIP"]
        else:
            return "Aggressive", ["Stocks", "Small-cap funds", "Diversified portfolio"]

    # 📌 Step 5: Existing investment logic
    def existing_investment_advice(self):
        existing = self.profile.get("existing", "none")
        if existing == "none":
            return "Start with SIP and build discipline."
        elif existing == "fd":
            return "Shift some funds into mutual funds."
        elif existing == "mutual":
            return "Diversify into equity funds."
        elif existing == "stocks":
            return "Ensure diversification."
        else:
            return "Rebalance your portfolio."

    # 🚀 Step 6: Run full pipeline
    def run(self):
        self.calculate_metrics()

        # if self.emergency_check():
        #     return {
        #         "status": "unsafe",
        #         "advice": "⚠️ Build an emergency fund (6 months expenses) before investing."
        #     }

        self.calculate_score()
        category, advice = self.classify()
        extra = self.existing_investment_advice()

        return {
            "score": self.score,
            "category": category,
            "risk_profile": category,
            "age": self.profile["age"],
            "risk": self.profile["risk"],
            "horizon": self.profile["horizon"],
            "savings_ratio": round(self.savings_ratio, 2),
            "emergency_fund_months": round(self.emergency_fund_months, 1),
            "advice": advice,
            "extra_advice": extra
        }


# 🧠 OPTIONAL: Interactive CLI Agent
def get_user_input():
    print("\n💰 Investment Advisor\n")

    profile = {
        "age": int(input("Enter your age: ")),
        "income": float(input("Monthly income (₹): ")),
        "expenses": float(input("Monthly expenses (₹): ")),
        "savings": float(input("Current savings (₹): ")),
        "risk": input("Risk tolerance (low/medium/high): ").lower(),
        "horizon": input("Investment horizon i.e time period (short/medium/long): ").lower(),
        "existing": input("Existing investments (none/fd/mutual/stocks/mixed): ").lower()
    }

    return profile


if __name__ == "__main__":
    user_profile = get_user_input()

    advisor = InvestmentAdvisor(user_profile)
    result = advisor.run()

    print("\n📊 RESULT:")
    print(f"Score: {result.get('score', '-')}")
    print(f"Category: {result.get('category', '-')}")
    print(f"Savings Ratio: {result.get('savings_ratio', '-')}")
    print(f"Emergency Fund (months): {result.get('emergency_fund_months', '-')}")

    print("\n💡 Advice:")
    for a in result.get("advice", []):
        print(f"- {a}")

    print("\n📌 Extra Advice:")
    print(result.get("extra_advice", ""))
    ai_response = generate_advice(result)   # 🔥 call RAG + LLM
    print(ai_response)