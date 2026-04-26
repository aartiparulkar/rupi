"""Chat session management service"""

import logging
import uuid
import json
import re
from datetime import datetime, date
from typing import Optional, List, Dict, Tuple, Any
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.config import settings, government_sources
from models.database import ChatSession, ChatMessage, Form16Extraction
from services.tax_calculator import TaxCalculator
from services.tax_slab_loader import TaxSlabLoader

logger = logging.getLogger(__name__)


class ChatService:
    """Service for managing chat sessions with AI agents"""

    _tax_reply_llm = None

    TAX_KEYWORDS = {
        "tax", "itr", "deduction", "80c", "80d", "hra", "regime", "income", "salary",
        "form 16", "rebate", "section", "nps", "ppf", "elss", "cess", "capital gain",
        "exemption", "tds", "advance tax", "return",
    }

    EXPLANATION_KEYWORDS = {
        "how did", "how do", "calculated", "calculate", "breakdown", "explain",
        "working", "logic", "why",
    }

    SAVING_ADVICE_KEYWORDS = {
        "save tax", "reduce tax", "where can i save", "how can i save",
        "tax saving", "save more", "deduction options",
    }

    @staticmethod
    def _make_json_safe(value: Any) -> Any:
        """Convert nested state objects into JSON-serializable values."""
        if isinstance(value, dict):
            return {k: ChatService._make_json_safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [ChatService._make_json_safe(v) for v in value]
        if isinstance(value, tuple):
            return [ChatService._make_json_safe(v) for v in value]
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if hasattr(value, "as_tuple"):
            return float(value)
        return value


    @staticmethod
    def _build_tax_knowledge_context(profile: Dict[str, Any]) -> str:
        fiscal_year = profile.get("fiscal_year") or "2026-27"
        slabs = TaxSlabLoader.load_slabs() or {}
        tax_slab_data = slabs.get("fiscal_years", {}).get(fiscal_year) or {}
        government_sources_block = government_sources or {}

        knowledge = {
            "focus": "strictly salaried_individuals_only",
            "fiscal_year": fiscal_year,
            "tax_slabs": tax_slab_data,
            "government_sources": government_sources_block,
        }
        return json.dumps(knowledge, ensure_ascii=False, indent=2)

    @staticmethod
    def _get_tax_reply_llm():
        if ChatService._tax_reply_llm is None:
            ChatService._tax_reply_llm = ChatOpenAI(
                model="gpt-4o-mini",
                api_key=settings.openai_api_key,
                temperature=0.2,
            )
        return ChatService._tax_reply_llm

    @staticmethod
    def _extract_first_number(text: str) -> Optional[float]:
        cleaned = (text or "").replace(",", "")
        match = re.search(r"(-?\d+(?:\.\d+)?)", cleaned)
        if not match:
            return None
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_pending_field_value(user_text: str, pending_field: str) -> Optional[float]:
        numeric_value = ChatService._extract_first_number(user_text)
        if numeric_value is not None:
            return numeric_value

        # Fallback extraction via LLM to keep follow-up parsing field-agnostic.
        try:
            llm = ChatService._get_tax_reply_llm()
            prompt = (
                "Extract a numeric value for the requested tax field from the user text. "
                "Return strict JSON only with shape {\"value\": number|null}.\n\n"
                f"Requested field: {pending_field}\n"
                f"User text: {user_text}"
            )
            llm_response = llm.invoke(prompt)
            content = (getattr(llm_response, "content", "") or "").strip()
            parsed = json.loads(content)
            value = parsed.get("value") if isinstance(parsed, dict) else None
            if value is None:
                return None
            return float(value)
        except Exception:
            logger.debug("Could not extract pending value via LLM", exc_info=True)
            return None

    @staticmethod
    def _is_explanation_request(query: str, has_last_calc: bool = False) -> bool:
        lowered = (query or "").lower()
        mentions_tax_result = any(k in lowered for k in ["tax", "regime", "savings", "save", "calculation"])
        mentions_explain = any(k in lowered for k in ChatService.EXPLANATION_KEYWORDS) or any(
            k in lowered for k in ["more depth", "more detail", "deeper", "break it down"]
        )
        if has_last_calc and mentions_explain:
            return True
        return mentions_tax_result and mentions_explain

    @staticmethod
    def _detect_requested_regime(query: str) -> str:
        lowered = (query or "").lower()
        asks_both = any(k in lowered for k in ["both", "compare", "comparison"])
        asks_new = "new regime" in lowered
        asks_old = "old regime" in lowered
        if asks_both or (asks_new and asks_old):
            return "both"
        if asks_new:
            return "new"
        if asks_old:
            return "old"
        return "both"

    @staticmethod
    def _is_tax_saving_advice_request(query: str) -> bool:
        lowered = (query or "").lower()
        return any(k in lowered for k in ChatService.SAVING_ADVICE_KEYWORDS)

    @staticmethod
    def _format_tax_computation_explanation(calc_result: Dict[str, Any]) -> str:
        old_regime = calc_result.get("old_regime") or {}
        new_regime = calc_result.get("new_regime") or {}
        comparison = calc_result.get("comparison") or {}

        def _explain(label: str, data: Dict[str, Any]) -> str:
            taxable = float(data.get("taxable_income") or 0)
            tax_before_cess = float(data.get("tax_on_total_income") or 0)
            cess = float(data.get("health_education_cess") or 0)
            rebate = float(data.get("section_87a_rebate") or 0)
            total = float(data.get("total_tax") or data.get("net_payable_tax") or 0)
            std_ded = float(data.get("standard_deduction") or 0)
            return (
                f"{label}: taxable income ₹{taxable:,.0f}; tax before cess ₹{tax_before_cess:,.0f}; "
                f"health and education cess ₹{cess:,.0f}; rebate ₹{rebate:,.0f}; "
                f"standard deduction used ₹{std_ded:,.0f}; final tax ₹{total:,.0f}."
            )

        if old_regime and new_regime:
            old_total = float(old_regime.get("total_tax") or old_regime.get("net_payable_tax") or 0)
            new_total = float(new_regime.get("total_tax") or new_regime.get("net_payable_tax") or 0)
            recommended = comparison.get("recommended_regime") or ("Old Regime" if old_total <= new_total else "New Regime")
            savings = float(comparison.get("savings") or abs(old_total - new_total))
            return (
                "Here is the detailed computation. "
                + _explain("Old Regime", old_regime)
                + " "
                + _explain("New Regime", new_regime)
                + f" Recommended regime is {recommended} with an estimated difference of ₹{savings:,.0f}."
            )

        if new_regime:
            return "Here is the detailed computation for New Regime. " + _explain("New Regime", new_regime)
        if old_regime:
            return "Here is the detailed computation for Old Regime. " + _explain("Old Regime", old_regime)
        return "I do not have a recent calculation context to explain yet."

    @staticmethod
    def _build_tax_saving_advice(profile: Dict[str, Any]) -> str:
        gross_income = profile.get("gross_total_income") or profile.get("gross_income") or profile.get("gross_salary")
        if gross_income is None:
            return (
                "I can suggest personalized tax-saving options once I know your gross income. "
                "Please share your gross annual income."
            )

        fiscal_year = profile.get("fiscal_year") or TaxCalculator.DEFAULT_FISCAL_YEAR
        comparison = TaxCalculator.compare_regimes(
            gross_income=float(gross_income),
            deductions=0,
            fiscal_year=fiscal_year,
        )

        comparison_data = comparison.get("comparison") or {}
        suggested_regime = comparison_data.get("recommended_regime", "New Regime")
        old_tax = float(comparison_data.get("old_regime_tax") or 0)
        new_tax = float(comparison_data.get("new_regime_tax") or 0)
        delta = abs(old_tax - new_tax)
        return (
            f"Based on current income, the estimated tax is ₹{old_tax:,.0f} in Old Regime and ₹{new_tax:,.0f} in New Regime. "
            f"Current recommendation is {suggested_regime} with an estimated difference of ₹{delta:,.0f}. "
            "To optimize old-regime savings, consider eligible deductions under 80C, 80D, 80GG, and 80TTA/80TTB as applicable."
        )

    @staticmethod
    def _update_session_state(session_id: Optional[str], user_id: Optional[str], db: Optional[Session], new_state: Dict[str, Any]) -> None:
        if not session_id or not user_id or db is None:
            return
        session = db.query(ChatSession).filter(
            ChatSession.session_id == session_id,
            ChatSession.user_id == user_id,
        ).first()
        if not session:
            return
        current = dict(session.session_data or {})
        current.update(new_state)
        session.session_data = ChatService._make_json_safe(current)
        db.commit()
    
    @staticmethod
    def create_session(user_id: str, agent_type: str, db: Session) -> ChatSession:
        """
        Create a new chat session
        
        Args:
            user_id: User ID
            agent_type: Type of agent ('tax', 'investment', 'security')
            db: Database session
        
        Returns:
            ChatSession object
        """
        try:
            session_id = str(uuid.uuid4())
            
            chat_session = ChatSession(
                session_id=session_id,
                user_id=user_id,
                agent_type=agent_type,
                messages_count=0
            )
            
            db.add(chat_session)
            db.commit()
            db.refresh(chat_session)
            
            # Fetch messages for the session
            messages = db.query(ChatMessage).filter_by(session_id=session_id).order_by(ChatMessage.created_at).all()
            chat_session.messages = [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.created_at.isoformat() if msg.created_at else None
                }
                for msg in messages
            ]
            
            logger.info(f"Chat session created: {session_id} for {agent_type} agent")
            return chat_session
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating chat session: {str(e)}", exc_info=True)
            raise
    
    @staticmethod
    def get_session(session_id: str, user_id: str, db: Session) -> Optional[ChatSession]:
        """
        Get a chat session with all messages
        
        Args:
            session_id: Session ID
            user_id: User ID (for ownership verification)
            db: Database session
        
        Returns:
            ChatSession object with messages or None if not found/not owned
        """
        try:
            session = db.query(ChatSession).filter(
                ChatSession.session_id == session_id,
                ChatSession.user_id == user_id
            ).first()
            
            if not session:
                return None
            
            # Fetch messages for the session
            messages = db.query(ChatMessage).filter_by(session_id=session_id).order_by(ChatMessage.created_at).all()
            session.messages = [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.created_at.isoformat() if msg.created_at else None
                }
                for msg in messages
            ]
            
            # Set preview as first message
            if messages:
                session.preview = messages[0].content[:100]
            
            return session
            
        except Exception as e:
            logger.error(f"Error retrieving session: {str(e)}", exc_info=True)
            return None
    
    @staticmethod
    def append_message(session_id: str, role: str, content: str, db: Session) -> bool:
        """
        Add a message to chat session
        
        Args:
            session_id: Session ID
            role: 'user' or 'assistant'
            content: Message content
            db: Database session
        
        Returns:
            True if successful, False otherwise
        """
        try:
            chat_session = db.query(ChatSession).filter_by(session_id=session_id).first()
            if not chat_session:
                logger.error(f"Session {session_id} not found")
                return False
            
            message = ChatMessage(
                session_id=session_id,
                role=role,
                content=content
            )
            
            db.add(message)
            chat_session.messages_count += 1
            chat_session.last_message_at = datetime.utcnow()
            
            # Update preview if this is the first message or currently None
            if not chat_session.preview or chat_session.messages_count == 1:
                chat_session.preview = content[:255] if len(content) > 255 else content
            
            db.commit()
            db.refresh(message)
            
            logger.info(f"Message added to session {session_id}")
            return True
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error adding message: {str(e)}", exc_info=True)
            return False
    
    @staticmethod
    def generate_ai_response(user_message: str, session_context: Dict, db: Session) -> str:
        """
        Generate AI response based on agent type and user message
        
        Args:
            user_message: User's message
            session_context: Context dict with agent_type, user_id, session_id
            db: Database session
        
        Returns:
            AI-generated response string
        """
        try:
            agent_type = session_context.get("agent_type", "tax")
            
            if agent_type == "tax":
                user_id = session_context.get("user_id")
                session_id = session_context.get("session_id")
                history = list(session_context.get("history") or [])
                if session_id and not history:
                    messages = (
                        db.query(ChatMessage)
                        .filter(ChatMessage.session_id == session_id)
                        .order_by(ChatMessage.created_at)
                        .all()
                    )
                    history = [{"role": m.role, "content": m.content} for m in messages]

                persisted_state = {}
                if session_id and user_id:
                    session = db.query(ChatSession).filter(
                        ChatSession.session_id == session_id,
                        ChatSession.user_id == user_id,
                    ).first()
                    if session and isinstance(session.session_data, dict):
                        persisted_state = dict(session.session_data)

                profile = dict(persisted_state.get("profile") or {})
                profile.update(dict(session_context.get("profile") or {}))

                latest_form16_extraction = None
                if user_id and db is not None:
                    latest_form16_extraction = (
                        db.query(Form16Extraction)
                        .filter(Form16Extraction.user_id == user_id)
                        .order_by(Form16Extraction.created_at.desc())
                        .first()
                    )
                if latest_form16_extraction:
                    extracted_tax_profile: Dict[str, Any] = {"form16_provided": True}
                    for column in latest_form16_extraction.__table__.columns:
                        key = column.name
                        value = getattr(latest_form16_extraction, key, None)
                        if value is None:
                            continue
                        extracted_tax_profile[key] = float(value) if hasattr(value, "as_tuple") else value
                    profile = {**extracted_tax_profile, **profile}

                enriched_context = {
                    **session_context,
                    "profile": profile,
                    "form16_extraction": latest_form16_extraction,
                    "history": history,
                    "pending": session_context.get("pending") if session_context.get("pending") is not None else persisted_state.get("pending"),
                    "last_calc_result": session_context.get("last_calc_result") if session_context.get("last_calc_result") is not None else persisted_state.get("last_calc_result"),
                }
                structured = ChatService.generate_tax_assistant_response(user_message, enriched_context)

                response_context = structured.get("context") or {}
                ChatService._update_session_state(
                    session_id=session_id,
                    user_id=user_id,
                    db=db,
                    new_state={
                        "profile": response_context.get("profile") or profile,
                        "pending": response_context.get("pending"),
                        "last_calc_result": response_context.get("last_calc_result"),
                    },
                )
                return structured.get("reply") or "Please share your tax-related question."
            elif agent_type == "invest":
                return ChatService.generate_investment_agent_response(user_message)
            elif agent_type == "security":
                return ChatService.generate_security_agent_response(user_message)
            else:
                return "I'm here to help! What would you like to know?"
                
        except Exception as e:
            logger.error(f"Error generating AI response: {str(e)}", exc_info=True)
            return "I'm having trouble generating a response. Please try again."
    
    @staticmethod
    def get_session_history(session_id: str, db: Session) -> List[ChatMessage]:
        """Get all messages in a session"""
        return db.query(ChatMessage).filter_by(session_id=session_id).order_by(ChatMessage.created_at).all()
    
    @staticmethod
    def get_user_sessions(user_id: str, limit: int = 20, db: Session = None) -> List[ChatSession]:
        """Get all chat sessions for a user"""
        if db is None:
            from models.database import SessionLocal
            db = SessionLocal()
        
        return db.query(ChatSession).filter_by(user_id=user_id).order_by(desc(ChatSession.created_at)).limit(limit).all()
    
    @staticmethod
    def delete_session(session_id: str, user_id: str, db: Session) -> Tuple[bool, Optional[str]]:
        """Delete a chat session"""
        try:
            session = db.query(ChatSession).filter_by(session_id=session_id, user_id=user_id).first()
            if not session:
                return False, "Session not found"
            
            # Delete all messages in session
            db.query(ChatMessage).filter_by(session_id=session_id).delete()
            
            # Delete session
            db.delete(session)
            db.commit()
            
            logger.info(f"Chat session deleted: {session_id}")
            return True, None
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error deleting session: {str(e)}", exc_info=True)
            return False, f"Deletion failed: {str(e)}"
    
    @staticmethod
    def generate_tax_agent_response(user_message: str, context: Optional[Dict] = None, db: Session = None) -> str:
        """Backward-compatible wrapper that now uses the structured tax assistant."""
        structured = ChatService.generate_tax_assistant_response(user_message, context)
        return structured.get("reply") or "Please share your tax-related question."
    
    @staticmethod
    def generate_investment_agent_response(user_message: str) -> str:
        """Generate response for Investment Agent"""
        user_message_lower = user_message.lower()
        
        if any(keyword in user_message_lower for keyword in ["risk", "profile", "conservative", "aggressive"]):
            return "Tell me about your risk tolerance and investment horizon. Are you conservative (low risk), moderate (balanced), or aggressive (high growth)?"
        
        if any(keyword in user_message_lower for keyword in ["mutual", "fund", "etf", "stock"]):
            return "Mutual funds and ETFs offer diversified exposure. Index funds (Nifty 50 ETF) are good for long-term wealth building with low fees."
        
        return "I help with investment planning. Tell me your goals, investment amount, and time horizon!"
    
    @staticmethod
    def generate_security_agent_response(user_message: str) -> str:
        """Generate response for Security Agent"""
        return "I help with financial security planning. Discuss your insurance needs, emergency funds, and risk mitigation strategies."

    @staticmethod
    def generate_tax_assistant_response(message: str, context: Optional[Dict] = None) -> Dict:
        """Generate a tax-only assistant response without interactive controls."""
        ctx = context or {}
        profile = dict(ctx.get("profile") or {})
        history = list(ctx.get("history") or [])[-12:]
        pending = dict(ctx.get("pending") or {}) if isinstance(ctx.get("pending"), dict) else None
        last_calc_result = dict(ctx.get("last_calc_result") or {}) if isinstance(ctx.get("last_calc_result"), dict) else None
        form16_extraction = ctx.get("form16_extraction")
        text = (message or "").strip()
        lowered = text.lower()

        def requires_calculation(query: str) -> bool:
            calc_keywords = {
                "calculate", "calculation", "compute", "estimate", "how much", "amount",
                "claimed", "claim", "liability", "tax payable", "refund", "compare",
                "regime", "save tax", "deduction", "80c", "80d", "tds",
            }
            q = query.lower()
            return any(keyword in q for keyword in calc_keywords)

        if pending and pending.get("field"):
            resolved_value = ChatService._extract_pending_field_value(text, pending.get("field"))
            if resolved_value is not None:
                profile[pending["field"]] = resolved_value
                pending = None

        available_tax_fields = dict(profile or {})
        missing_required_fields = []
        has_income_basis = bool(
            available_tax_fields.get("gross_total_income")
            or available_tax_fields.get("gross_salary")
            or available_tax_fields.get("salary_section_17_1")
            or available_tax_fields.get("perquisites_17_2")
            or available_tax_fields.get("profits_in_lieu_17_3")
            or available_tax_fields.get("income_under_salary")
        )
        if not has_income_basis:
            missing_required_fields.append("gross_total_income")
        has_form16_snapshot = bool(available_tax_fields)
        if has_form16_snapshot:
            profile["form16_provided"] = True

        inferred_income = (
            profile.get("gross_total_income")
            or profile.get("gross_salary")
            or profile.get("income_under_salary")
        )
        if inferred_income is not None and not profile.get("gross_income"):
            profile["gross_income"] = float(inferred_income)

        if ChatService._is_explanation_request(lowered, has_last_calc=bool(last_calc_result)):
            explanation_calc = last_calc_result
            if not explanation_calc and not missing_required_fields:
                requested_regime = ChatService._detect_requested_regime(lowered)
                explanation_calc = TaxCalculator.calculate_tax(
                    form16_extraction=form16_extraction or profile,
                    gross_income=profile.get("gross_income"),
                    deductions=profile.get("deductions_80c") or 0,
                    fiscal_year=profile.get("fiscal_year"),
                    regime=requested_regime,
                )
            if explanation_calc and not explanation_calc.get("error"):
                return {
                    "reply": ChatService._format_tax_computation_explanation(explanation_calc),
                    "is_tax_related": True,
                    "controls": [],
                    "context": {
                        "profile": profile,
                        "history": history,
                        "pending": pending,
                        "last_calc_result": explanation_calc,
                    },
                }

        if ChatService._is_tax_saving_advice_request(lowered):
            return {
                "reply": ChatService._build_tax_saving_advice(profile),
                "is_tax_related": True,
                "controls": [],
                "context": {
                    "profile": profile,
                    "history": history,
                    "pending": pending,
                    "last_calc_result": last_calc_result,
                },
            }

        should_calculate = requires_calculation(lowered) or bool(ctx.get("pending") and not pending)
        if should_calculate:
            requested_regime = ChatService._detect_requested_regime(lowered)
            if missing_required_fields:
                missing_prompts = {
                    field: f"Please provide {field.replace('_', ' ')}."
                    for field in missing_required_fields
                }
                next_field = next(iter(missing_prompts.keys()), None)
                next_prompt = missing_prompts.get(next_field) if next_field else None
                if not has_form16_snapshot:
                    reply = (
                        "I do not see required Form 16 extraction data yet. "
                        "Please upload Form 16 or provide the missing details manually: "
                        + "; ".join(missing_prompts)
                    )
                else:
                    reply = "I need a bit more information before calculating tax: " + "; ".join(missing_prompts)
                return {
                    "reply": reply,
                    "is_tax_related": True,
                    "controls": [],
                    "context": {
                        "profile": profile,
                        "history": history,
                        "pending": (
                            {
                                "field": next_field,
                                "prompt": next_prompt,
                                "reason": "calculation",
                            }
                            if next_field
                            else None
                        ),
                        "last_calc_result": last_calc_result,
                    },
                }

            calc_result = TaxCalculator.calculate_tax(
                form16_extraction=form16_extraction or profile,
                gross_income=profile.get("gross_income"),
                deductions=profile.get("deductions_80c") or 0,
                fiscal_year=profile.get("fiscal_year"),
                regime=requested_regime,
            )

            if calc_result.get("error"):
                prompts = calc_result.get("missing_fields") or []
                reply = calc_result["error"]
                if prompts:
                    reply = reply + " Please share: " + "; ".join(str(p) for p in prompts)
                return {
                    "reply": reply,
                    "is_tax_related": True,
                    "controls": [],
                    "context": {
                        "profile": profile,
                        "history": history,
                        "pending": None,
                        "last_calc_result": last_calc_result,
                    },
                }

            old_regime = calc_result.get("old_regime") or {}
            new_regime = calc_result.get("new_regime") or {}
            comparison = calc_result.get("comparison") or {}
            old_tax = float(old_regime.get("total_tax") or 0)
            new_tax = float(new_regime.get("total_tax") or 0)
            recommended = comparison.get("recommended_regime") or ("Old Regime" if old_tax <= new_tax else "New Regime")
            savings = float(comparison.get("savings") or abs(old_tax - new_tax))

            if requested_regime == "new":
                tax_before_cess = float(new_regime.get("tax_on_total_income") or 0)
                cess = float(new_regime.get("health_education_cess") or 0)
                taxable = float(new_regime.get("taxable_income") or 0)
                reply_text = (
                    f"Here is your New Regime tax estimate. Taxable income: ₹{taxable:,.0f}. "
                    f"Tax before cess: ₹{tax_before_cess:,.0f}. Cess: ₹{cess:,.0f}. "
                    f"Final tax: ₹{new_tax:,.0f}."
                )
            elif requested_regime == "old":
                tax_before_cess = float(old_regime.get("tax_on_total_income") or 0)
                cess = float(old_regime.get("health_education_cess") or 0)
                taxable = float(old_regime.get("taxable_income") or 0)
                reply_text = (
                    f"Here is your Old Regime tax estimate. Taxable income: ₹{taxable:,.0f}. "
                    f"Tax before cess: ₹{tax_before_cess:,.0f}. Cess: ₹{cess:,.0f}. "
                    f"Final tax: ₹{old_tax:,.0f}."
                )
            else:
                reply_text = (
                    f"Here is your tax comparison. Old Regime tax: ₹{old_tax:,.0f}. "
                    f"New Regime tax: ₹{new_tax:,.0f}. "
                    f"Recommended: {recommended}. Estimated difference: ₹{savings:,.0f}."
                )

            return {
                "reply": reply_text,
                "is_tax_related": True,
                "controls": [],
                "context": {
                    "profile": profile,
                    "history": history,
                    "pending": None,
                    "last_calc_result": calc_result,
                },
            }

        try:
            llm = ChatService._get_tax_reply_llm()
            knowledge_context = ChatService._build_tax_knowledge_context(profile)
            safe_profile = ChatService._make_json_safe(profile)
            safe_history = ChatService._make_json_safe(history)
            safe_last_calc = ChatService._make_json_safe(last_calc_result)
            llm_prompt = (
                "You are RuPi assistant. Keep a natural conversational flow across turns. "
                "Use history, profile data, and latest calculation context when answering. "
                "If the user asks whether latest Form16 is available, answer based only on profile/extraction context; do not invent data. "
                "If user asks tax computation details, explain from calculation context if present. "
                "Do not produce markdown tables or JSON; respond with plain text only.\n\n"
                f"Profile data: {json.dumps(safe_profile, ensure_ascii=False)}\n"
                f"Recent history: {json.dumps(safe_history, ensure_ascii=False)}\n"
                f"Last calculation context: {json.dumps(safe_last_calc, ensure_ascii=False)}\n"
                f"Tax knowledge context: {knowledge_context}\n"
                f"User question: {text}"
            )
            llm_response = llm.invoke(llm_prompt)
            llm_text = (getattr(llm_response, "content", "") or "").strip()
            if llm_text:
                return {
                    "reply": llm_text,
                    "is_tax_related": any(k in lowered for k in ChatService.TAX_KEYWORDS),
                    "controls": [],
                    "context": {
                        "profile": profile,
                        "history": history,
                        "pending": pending,
                        "last_calc_result": last_calc_result,
                    },
                }
        except Exception:
            logger.debug("Falling back to default tax reply", exc_info=True)

        return {
            "reply": "I can help with your queries and continue the conversation. Ask anything related to your tax profile or Form 16 context.",
            "is_tax_related": any(k in lowered for k in ChatService.TAX_KEYWORDS),
            "controls": [],
            "context": {
                "profile": profile,
                "history": history,
                "pending": pending,
                "last_calc_result": last_calc_result,
            },
        }
