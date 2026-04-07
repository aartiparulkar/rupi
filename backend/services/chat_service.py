"""Chat session management service"""

import logging
import uuid
import re
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
import PyPDF2
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.config import settings, government_sources
from models.database import ChatSession, ChatMessage, TaxRules
from services.tax_calculator import TaxCalculator
from services.tax_slab_loader import TaxSlabLoader

logger = logging.getLogger(__name__)


class ChatService:
    """Service for managing chat sessions with AI agents"""

    _tax_interactive_chain = None

    TAX_KEYWORDS = {
        "tax", "itr", "deduction", "80c", "80d", "hra", "regime", "income", "salary",
        "form 16", "rebate", "section", "nps", "ppf", "elss", "cess", "capital gain",
        "exemption", "tds", "advance tax", "return",
    }

    YES_TOKENS = {"yes", "y", "haan", "ha", "sure", "ok", "okay"}
    NO_TOKENS = {"no", "n", "nah", "nope"}

    CONTROL_LIBRARY: Dict[str, Dict[str, Any]] = {
        "gross_income_slider": {
            "type": "slider",
            "key": "gross_income",
            "label": "Gross annual income (INR)",
            "min": 300000,
            "max": 5000000,
            "step": 50000,
            "default": 1200000,
        },
        "has_hra_buttons": {
            "type": "buttons",
            "key": "has_hra",
            "label": "Do you claim HRA?",
            "options": [{"label": "Yes", "value": "yes"}, {"label": "No", "value": "no"}],
        },
        "has_80g_buttons": {
            "type": "buttons",
            "key": "has_80g",
            "label": "Any donation deductions under 80G?",
            "options": [{"label": "Yes", "value": "yes"}, {"label": "No", "value": "no"}],
        },
        "has_life_insurance_buttons": {
            "type": "buttons",
            "key": "has_life_insurance",
            "label": "Life insurance premium under Section 80C?",
            "options": [{"label": "Yes", "value": "yes"}, {"label": "No", "value": "no"}],
        },
        "has_other_80c_buttons": {
            "type": "buttons",
            "key": "has_other_80c",
            "label": "Any other Section 80C investments?",
            "options": [{"label": "Yes", "value": "yes"}, {"label": "No", "value": "no"}],
        },
        "form16_uploaded_buttons": {
            "type": "buttons",
            "key": "form16_provided",
            "label": "Form 16 uploaded?",
            "options": [{"label": "Yes, uploaded", "value": "form16_yes"}, {"label": "Not yet", "value": "form16_no"}],
        },
        "upload_form16_now_buttons": {
            "type": "buttons",
            "key": "upload_form16_now",
            "label": "Upload Form 16 now?",
            "options": [{"label": "Yes", "value": "upload_form16_yes"}, {"label": "No", "value": "upload_form16_no"}],
        },
        "form16_upload_progress_buttons": {
            "type": "buttons",
            "key": "form16_upload_progress",
            "label": "After uploading, choose:",
            "options": [{"label": "Uploaded", "value": "form16_done"}, {"label": "Skip for now", "value": "form16_skip"}],
        },
        "hra_exemption_slider": {
            "type": "slider",
            "key": "hra_exemption",
            "label": "Annual HRA exemption (INR)",
            "min": 0,
            "max": 600000,
            "step": 10000,
            "default": 120000,
        },
        "donations_80g_slider": {
            "type": "slider",
            "key": "donations_80g",
            "label": "Total donations under 80G (INR)",
            "min": 0,
            "max": 300000,
            "step": 5000,
            "default": 10000,
        },
        "life_insurance_slider": {
            "type": "slider",
            "key": "life_insurance_premium",
            "label": "Annual life insurance premium (INR)",
            "min": 0,
            "max": 150000,
            "step": 5000,
            "default": 30000,
        },
        "other_80c_slider": {
            "type": "slider",
            "key": "other_80c",
            "label": "Additional 80C amount (INR)",
            "min": 0,
            "max": 150000,
            "step": 5000,
            "default": 20000,
        },
        "deductions_80c_slider": {
            "type": "slider",
            "key": "deductions_80c",
            "label": "Section 80C claimed amount (INR)",
            "min": 0,
            "max": 150000,
            "step": 5000,
            "default": 50000,
        },
    }

    @staticmethod
    def _control(name: str, **overrides: Any) -> Dict[str, Any]:
        base = deepcopy(ChatService.CONTROL_LIBRARY.get(name, {}))
        if not base:
            return {}
        base.update(overrides)
        return base

    @staticmethod
    def _controls(*names: str) -> List[Dict[str, Any]]:
        return [c for c in (ChatService._control(name) for name in names) if c]

    @staticmethod
    def _load_json_file(path: Path) -> Dict[str, Any]:
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as handle:
                    return json.load(handle)
        except Exception:
            logger.debug("Unable to load JSON file: %s", path, exc_info=True)
        return {}

    @staticmethod
    def _latest_memo_excerpt(max_chars: int = 3500) -> str:
        """Extract a short excerpt from the latest memo PDF available on disk."""
        try:
            tax_docs_root = Path(__file__).resolve().parent.parent / "tax-docs"
            candidates = sorted(tax_docs_root.glob("**/memo_*.pdf"), key=lambda path: path.stat().st_mtime, reverse=True)
            if not candidates:
                return ""

            reader = PyPDF2.PdfReader(str(candidates[0]))
            pages = []
            for page in reader.pages[:2]:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    continue
            excerpt = "\n".join(page for page in pages if page).strip()
            return excerpt[:max_chars]
        except Exception:
            logger.debug("Unable to extract memo excerpt", exc_info=True)
            return ""

    @staticmethod
    def _db_rules_excerpt(db: Optional[Session], fiscal_year: Optional[str], limit: int = 8) -> str:
        if db is None:
            return ""
        try:
            query = db.query(TaxRules).order_by(TaxRules.created_at.desc())
            if fiscal_year:
                query = query.filter(TaxRules.fiscal_year == fiscal_year)
            rules = query.limit(limit).all()
            if not rules:
                return ""

            lines = []
            for rule in rules:
                parts = [
                    f"{rule.fiscal_year or 'unknown fiscal year'}",
                    f"{rule.category or 'general'}",
                    f"{rule.regime or 'both'}",
                    (rule.description or "").strip(),
                ]
                if rule.amount is not None:
                    parts.append(f"amount={float(rule.amount):,.0f}")
                if rule.percentage is not None:
                    parts.append(f"rate={float(rule.percentage)}%")
                lines.append(" | ".join(part for part in parts if part))
            return "\n".join(lines)
        except Exception:
            logger.debug("Unable to read DB tax rules", exc_info=True)
            return ""

    @staticmethod
    def _build_tax_knowledge_context(profile: Dict[str, Any], db: Optional[Session]) -> str:
        fiscal_year = profile.get("fiscal_year") or "2026-27"
        config_dir = Path(__file__).resolve().parent.parent / "config"
        slabs = ChatService._load_json_file(config_dir / "tax_slabs.json") or TaxSlabLoader.load_slabs() or {}
        tax_slab_data = slabs.get("fiscal_years", {}).get(fiscal_year) or {}
        government_sources_block = ChatService._load_json_file(config_dir / "government_sources.json") or government_sources or {}
        memo_excerpt = ChatService._latest_memo_excerpt()
        db_rules = ChatService._db_rules_excerpt(db, fiscal_year)

        knowledge = {
            "focus": "strictly salaried_individuals_only",
            "fiscal_year": fiscal_year,
            "tax_slabs": tax_slab_data,
            "government_sources": government_sources_block,
            "memo_excerpt": memo_excerpt,
            "database_rules_excerpt": db_rules,
        }
        return json.dumps(knowledge, ensure_ascii=False, indent=2)

    @staticmethod
    def _get_tax_interactive_chain():
        """LangChain pipeline that can suggest structured interactive controls."""
        if ChatService._tax_interactive_chain is None:
            parser = JsonOutputParser()
            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "You are RuPi Tax Agent for Indian personal income tax for strictly salaried individuals. "
                        "Use the provided tax knowledge context and answer only from those sources when possible. "
                        "If the question is outside salaried personal income tax, politely deny it and redirect back to salaried-tax topics. "
                        "Be warm, patient, and conversational. Start with a brief acknowledgement when appropriate. "
                        "Do not sound blunt, robotic, or overly terse. If missing details are needed, ask one concise follow-up at a time. "
                        "Return JSON only. Prefer interactive controls so the user does not need to type amounts. "
                        "Use only control keys from available_controls. "
                        "If information is complete, return empty control_keys.",
                    ),
                    (
                        "human",
                        "{format_instructions}\n"
                        "User query: {user_query}\n"
                        "Known profile data: {profile_data}\n"
                        "Recent conversation history: {conversation_history}\n"
                        "Current pending state: {pending_state}\n"
                        "Tax knowledge context: {tax_knowledge_context}\n"
                        "Available control keys: {available_controls}\n"
                        "Output schema: {{\"reply\": string, \"control_keys\": string[]}}",
                    ),
                ]
            )
            llm = ChatOpenAI(
                model="gpt-4o-mini",
                api_key=settings.openai_api_key,
                temperature=0.2,
            )
            ChatService._tax_interactive_chain = prompt | llm | parser
        return ChatService._tax_interactive_chain
    
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
                structured = ChatService.generate_tax_assistant_response(user_message, session_context)
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
        """Generate a tax-only assistant response with interactive follow-up controls."""
        ctx = context or {}
        profile = dict(ctx.get("profile") or {})
        is_registered = bool(ctx.get("is_registered") or profile.get("is_registered"))
        history = list(ctx.get("history") or [])[-12:]
        text = (message or "").strip()
        lowered = text.lower()

        def is_tax_related(query: str) -> bool:
            q = query.lower()
            return any(keyword in q for keyword in ChatService.TAX_KEYWORDS)

        def requires_calculation(query: str) -> bool:
            calc_keywords = {
                "calculate", "calculation", "compute", "estimate", "how much", "amount",
                "claimed", "claim", "liability", "tax payable", "refund", "compare",
                "regime", "save tax", "deduction", "80c", "80d", "tds",
            }
            q = query.lower()
            return any(keyword in q for keyword in calc_keywords)

        def asks_form16_80c_amount(query: str) -> bool:
            q = query.lower()
            has_form16_ref = "form 16" in q or "form16" in q
            has_80c_ref = "80c" in q or "section 80c" in q
            asks_amount = any(k in q for k in ["how much", "claimed", "amount", "find", "check"])
            return has_form16_ref and has_80c_ref and asks_amount

        def extract_number(query: str) -> Optional[float]:
            normalized = query.replace(",", "")
            match = re.search(r"(\d+(?:\.\d+)?)", normalized)
            if not match:
                return None
            return float(match.group(1))

        def llm_tax_interactive_reply(user_query: str, profile_data: Dict, conversation_history: List[Dict], pending_state: Optional[str]) -> Dict[str, Any]:
            try:
                chain = ChatService._get_tax_interactive_chain()
                parser = JsonOutputParser()
                payload = chain.invoke(
                    {
                        "format_instructions": parser.get_format_instructions(),
                        "user_query": user_query,
                        "profile_data": profile_data,
                        "conversation_history": conversation_history,
                        "pending_state": pending_state or "none",
                        "tax_knowledge_context": ChatService._build_tax_knowledge_context(profile_data, ctx.get("db")),
                        "available_controls": sorted(ChatService.CONTROL_LIBRARY.keys()),
                    }
                )
                reply = str(payload.get("reply") or "").strip()
                control_keys = [key for key in payload.get("control_keys") or [] if key in ChatService.CONTROL_LIBRARY]
                return {"reply": reply, "controls": ChatService._controls(*control_keys)}
            except Exception:
                return {"reply": "", "controls": []}

        controls: List[Dict] = []

        yes_tokens = ChatService.YES_TOKENS
        no_tokens = ChatService.NO_TOKENS

        if ctx.get("pending") == "ask_hra":
            if lowered in yes_tokens:
                profile["has_hra"] = True
                return {
                    "reply": "Great. Please share your annual HRA exemption amount if you know it.",
                    "is_tax_related": True,
                    "controls": ChatService._controls("hra_exemption_slider"),
                    "context": {"profile": profile, "history": history, "pending": "capture_hra"},
                }
            if lowered in no_tokens:
                profile["has_hra"] = False
                return {
                    "reply": "Noted. Do you claim any deduction under Section 80G (donations)?",
                    "is_tax_related": True,
                    "controls": ChatService._controls("has_80g_buttons"),
                    "context": {"profile": profile, "history": history, "pending": "ask_80g"},
                }

        if ctx.get("pending") == "capture_hra":
            amount = extract_number(lowered)
            if amount is not None:
                profile["house_rent_exemption_10_13a"] = amount
                return {
                    "reply": f"Captured HRA exemption as ₹{amount:,.0f}. Do you also have donation deductions under Section 80G?",
                    "is_tax_related": True,
                    "controls": ChatService._controls("has_80g_buttons"),
                    "context": {"profile": profile, "history": history, "pending": "ask_80g"},
                }

        if ctx.get("pending") == "ask_80g":
            if lowered in yes_tokens:
                profile["has_80g"] = True
                return {
                    "reply": "Please keep your donation receipts ready for ITR filing. Do you know your total donation amount under 80G?",
                    "is_tax_related": True,
                    "controls": ChatService._controls("donations_80g_slider"),
                    "context": {"profile": profile, "history": history, "pending": "capture_80g"},
                }
            if lowered in no_tokens:
                profile["has_80g"] = False
                llm_payload = llm_tax_interactive_reply(
                    "Compare old and new tax regimes based on the collected profile data.",
                    profile,
                    history,
                    None,
                )
                answer = llm_payload.get("reply")
                return {
                    "reply": answer or "Noted. Based on the details so far, I can compare old and new regime for you. Please share your gross annual income if missing.",
                    "is_tax_related": True,
                    "controls": llm_payload.get("controls") or [],
                    "context": {"profile": profile, "history": history, "pending": None},
                }

        if ctx.get("pending") == "capture_80g":
            amount = extract_number(lowered)
            if amount is not None:
                profile["donations_80g"] = amount
                llm_payload = llm_tax_interactive_reply(
                    "Compare old and new tax regimes based on current profile and include 80G implications.",
                    profile,
                    history,
                    None,
                )
                answer = llm_payload.get("reply")
                return {
                    "reply": answer or f"Captured donation deduction as ₹{amount:,.0f}. Keep receipts ready for ITR. I can now compare regimes for you.",
                    "is_tax_related": True,
                    "controls": llm_payload.get("controls") or [],
                    "context": {"profile": profile, "history": history, "pending": None},
                }

        if "yes" == lowered and ctx.get("pending") == "ask_life_insurance":
            profile["has_life_insurance"] = True
            reply = "Great. Approximately how much life insurance premium do you pay annually under Section 80C?"
            controls.append(
                ChatService._control("life_insurance_slider")
            )
            return {
                "reply": reply,
                "is_tax_related": True,
                "controls": controls,
                "context": {"profile": profile, "history": history, "pending": "capture_life_insurance_premium"},
            }

        if "no" == lowered and ctx.get("pending") == "ask_life_insurance":
            profile["has_life_insurance"] = False
            return {
                "reply": "Understood. Do you pay house rent and claim HRA?",
                "is_tax_related": True,
                "controls": ChatService._controls("has_hra_buttons"),
                "context": {"profile": profile, "history": history, "pending": "ask_hra"},
            }

        if ctx.get("pending") == "capture_life_insurance_premium":
            amount = extract_number(lowered)
            if amount is not None:
                profile["life_insurance_premium"] = amount
                return {
                    "reply": f"Captured. I recorded ₹{amount:,.0f} for life insurance premium. Do you also invest in PPF or ELSS?",
                    "is_tax_related": True,
                    "controls": ChatService._controls("has_other_80c_buttons"),
                    "context": {"profile": profile, "history": history, "pending": "ask_other_80c"},
                }

        if ctx.get("pending") == "ask_other_80c":
            if lowered in yes_tokens:
                return {
                    "reply": "Please enter your estimated additional 80C investment amount (PPF/ELSS/etc.).",
                    "is_tax_related": True,
                    "controls": ChatService._controls("other_80c_slider"),
                    "context": {"profile": profile, "history": history, "pending": "capture_other_80c"},
                }
            if lowered in no_tokens:
                return {
                    "reply": "Noted. Do you claim HRA exemption?",
                    "is_tax_related": True,
                    "controls": [
                        {
                            "type": "buttons",
                            "key": "has_hra",
                            "label": "Do you claim HRA?",
                            "options": [{"label": "Yes", "value": "yes"}, {"label": "No", "value": "no"}],
                        }
                    ],
                    "context": {"profile": profile, "history": history, "pending": "ask_hra"},
                }

        if ctx.get("pending") == "capture_other_80c":
            amount = extract_number(lowered)
            if amount is not None:
                profile["deductions_80c"] = (profile.get("life_insurance_premium") or 0) + amount
                return {
                    "reply": f"Captured. Your total 80C estimate is ₹{profile['deductions_80c']:,.0f}. Do you claim HRA exemption?",
                    "is_tax_related": True,
                    "controls": [
                        {
                            "type": "buttons",
                            "key": "has_hra",
                            "label": "Do you claim HRA?",
                            "options": [{"label": "Yes", "value": "yes"}, {"label": "No", "value": "no"}],
                        }
                    ],
                    "context": {"profile": profile, "history": history, "pending": "ask_hra"},
                }

        if ctx.get("pending") == "capture_income":
            amount = extract_number(lowered)
            if amount is not None and amount > 0:
                profile["gross_income"] = amount
                return {
                    "reply": (
                        f"Thanks. I noted your gross annual income as ₹{amount:,.0f}. "
                        "Do you pay life insurance premium under Section 80C?"
                    ),
                    "is_tax_related": True,
                    "controls": ChatService._controls("has_life_insurance_buttons"),
                    "context": {"profile": profile, "history": history, "pending": "ask_life_insurance"},
                }

        if not is_tax_related(lowered) and not ctx.get("pending"):
            return {
                "reply": (
                    "I can only help with tax-related topics. "
                    "Please ask about income tax, deductions (80C/80D), HRA, ITR filing, or regime comparison."
                ),
                "is_tax_related": False,
                "controls": [
                    {
                        "type": "options",
                        "key": "suggested_tax_topics",
                        "label": "Try one of these:",
                        "options": [
                            {"label": "Compare old vs new regime", "value": "compare old vs new regime"},
                            {"label": "How much 80C can I claim?", "value": "how much 80c can i claim"},
                            {"label": "What documents do I need for ITR?", "value": "what documents do i need for itr"},
                        ],
                    }
                ],
                "context": {"profile": profile, "history": history, "pending": None},
            }

        if asks_form16_80c_amount(lowered):
            amount_80c = profile.get("deductions_80c")
            if amount_80c is not None:
                return {
                    "reply": f"Based on your uploaded Form 16, your claimed deduction under Section 80C is ₹{float(amount_80c):,.0f}.",
                    "is_tax_related": True,
                    "controls": [],
                    "context": {"profile": profile, "history": history, "pending": None},
                }
            if not is_registered:
                return {
                    "reply": "I can read Form 16 and compute this. If you are not registered yet, you can either register now or enter your 80C amount manually.",
                    "is_tax_related": True,
                    "controls": [
                        {
                            "type": "buttons",
                            "key": "registration_required",
                            "label": "Choose how to continue:",
                            "options": [
                                {"label": "Register now", "value": "register_now"},
                                {"label": "Enter 80C manually", "value": "enter_80c_manually"},
                            ],
                        }
                    ],
                    "context": {"profile": profile, "history": history, "pending": "ask_80c_manual_without_registration"},
                }
            return {
                "reply": "I can read this from Form 16. I do not see Form 16 data yet. Would you like to upload Form 16 now or enter 80C manually?",
                "is_tax_related": True,
                "controls": [
                    {
                        "type": "buttons",
                        "key": "upload_form16_now",
                        "label": "Choose one:",
                        "options": [
                            {"label": "Yes", "value": "upload_form16_yes"},
                            {"label": "No", "value": "upload_form16_no"},
                            {"label": "Enter 80C manually", "value": "enter_80c_manually"},
                        ],
                    }
                ],
                "context": {"profile": profile, "history": history, "pending": "ask_80c_capture_method"},
            }

        if requires_calculation(lowered) and not ctx.get("pending"):
            if not is_registered:
                return {
                    "reply": "For best accuracy, register/login so I can read your documents. You can also continue by entering values manually in chat.",
                    "is_tax_related": True,
                    "controls": [
                        {
                            "type": "buttons",
                            "key": "registration_required",
                            "label": "Choose how to continue:",
                            "options": [
                                {"label": "Register now", "value": "register_now"},
                                {"label": "Continue with manual inputs", "value": "continue_manual"},
                            ],
                        }
                    ],
                    "context": {"profile": profile, "history": history, "pending": "ask_manual_without_registration"},
                }

            if not profile.get("form16_provided"):
                return {
                    "reply": "For accurate calculation, please upload Form 16 first. Would you like to upload it now?",
                    "is_tax_related": True,
                    "controls": [
                        {
                            "type": "buttons",
                            "key": "upload_form16_now",
                            "label": "Upload Form 16 now?",
                            "options": [
                                {"label": "Yes", "value": "upload_form16_yes"},
                                {"label": "No", "value": "upload_form16_no"},
                            ],
                        }
                    ],
                    "context": {"profile": profile, "history": history, "pending": "ask_upload_form16"},
                }

        needs_income = any(k in lowered for k in ["calculate", "compare", "which regime", "tax liability", "save tax"])
        if needs_income and not profile.get("gross_income"):
            if not profile.get("form16_provided"):
                return {
                    "reply": "Before comparison, have you uploaded Form 16? It helps me ask fewer questions and improves accuracy.",
                    "is_tax_related": True,
                    "controls": ChatService._controls("form16_uploaded_buttons"),
                    "context": {"profile": profile, "history": history, "pending": "ask_form16"},
                }
            return {
                "reply": "I can help with that. Please share your gross annual income first.",
                "is_tax_related": True,
                "controls": ChatService._controls("gross_income_slider"),
                "context": {"profile": profile, "history": history, "pending": "capture_income"},
            }

        if ctx.get("pending") == "ask_form16":
            if lowered in {"form16_yes", "yes"}:
                profile["form16_provided"] = True
                return {
                    "reply": "Perfect. I will use your Form 16 details when available. Please share your gross annual income to start the comparison.",
                    "is_tax_related": True,
                    "controls": ChatService._controls("gross_income_slider"),
                    "context": {"profile": profile, "history": history, "pending": "capture_income"},
                }

        if ctx.get("pending") == "ask_manual_without_registration":
            if lowered in {"continue_manual", "manual", "yes"}:
                return {
                    "reply": "Sure. Let us continue manually. Please share your gross annual income.",
                    "is_tax_related": True,
                    "controls": ChatService._controls("gross_income_slider"),
                    "context": {"profile": profile, "history": history, "pending": "capture_income"},
                }
            if lowered in {"register_now"}:
                return {
                    "reply": "Please register/login, then continue here and I will use your uploaded documents for better accuracy.",
                    "is_tax_related": True,
                    "controls": [],
                    "context": {"profile": profile, "history": history, "pending": None},
                }

        if ctx.get("pending") == "ask_80c_manual_without_registration":
            if lowered in {"enter_80c_manually", "manual", "yes"}:
                return {
                    "reply": "Please enter your total claimed Section 80C amount.",
                    "is_tax_related": True,
                    "controls": ChatService._controls("deductions_80c_slider"),
                    "context": {"profile": profile, "history": history, "pending": "capture_80c_manual"},
                }
            if lowered in {"register_now"}:
                return {
                    "reply": "Please register/login and upload Form 16. Then I can fetch exact 80C directly from your document.",
                    "is_tax_related": True,
                    "controls": [],
                    "context": {"profile": profile, "history": history, "pending": None},
                }

        if ctx.get("pending") == "ask_80c_capture_method":
            if lowered in {"enter_80c_manually", "manual"}:
                return {
                    "reply": "Please enter your total claimed Section 80C amount.",
                    "is_tax_related": True,
                    "controls": [
                        {
                            "type": "slider",
                            "key": "deductions_80c",
                            "label": "Section 80C claimed amount (INR)",
                            "min": 0,
                            "max": 150000,
                            "step": 5000,
                            "default": 50000,
                        }
                    ],
                    "context": {"profile": profile, "history": history, "pending": "capture_80c_manual"},
                }
            if lowered in {"upload_form16_yes", "yes"}:
                return {
                    "reply": "Great. Please upload your Form 16 using the upload section above, then choose 'Uploaded'.",
                    "is_tax_related": True,
                    "controls": [
                        {
                            "type": "buttons",
                            "key": "form16_upload_progress",
                            "label": "After uploading, choose:",
                            "options": [
                                {"label": "Uploaded", "value": "form16_done"},
                                {"label": "Skip for now", "value": "form16_skip"},
                            ],
                        }
                    ],
                    "context": {"profile": profile, "history": history, "pending": "wait_form16_upload"},
                }
            if lowered in {"upload_form16_no", "no"}:
                return {
                    "reply": "No problem. You can enter your 80C amount manually.",
                    "is_tax_related": True,
                    "controls": [
                        {
                            "type": "slider",
                            "key": "deductions_80c",
                            "label": "Section 80C claimed amount (INR)",
                            "min": 0,
                            "max": 150000,
                            "step": 5000,
                            "default": 50000,
                        }
                    ],
                    "context": {"profile": profile, "history": history, "pending": "capture_80c_manual"},
                }

        if ctx.get("pending") == "capture_80c_manual":
            amount = extract_number(lowered)
            if amount is not None and amount >= 0:
                profile["deductions_80c"] = amount
                return {
                    "reply": f"Captured. Your Section 80C claimed amount is recorded as ₹{amount:,.0f}.",
                    "is_tax_related": True,
                    "controls": [],
                    "context": {"profile": profile, "history": history, "pending": None},
                }
            if lowered in {"form16_no", "no"}:
                profile["form16_provided"] = False
                return {
                    "reply": "No problem. Would you like to upload Form 16 now?",
                    "is_tax_related": True,
                    "controls": [
                        {
                            "type": "buttons",
                            "key": "upload_form16_now",
                            "label": "Upload Form 16 now?",
                            "options": [
                                {"label": "Yes", "value": "upload_form16_yes"},
                                {"label": "No", "value": "upload_form16_no"},
                            ],
                        }
                    ],
                    "context": {"profile": profile, "history": history, "pending": "ask_upload_form16"},
                }

        if ctx.get("pending") == "ask_upload_form16":
            if lowered in {"upload_form16_yes", "yes"}:
                return {
                    "reply": "Great. Please upload your Form 16 using the upload section above, then type 'done' once uploaded.",
                    "is_tax_related": True,
                    "controls": [
                        {
                            "type": "buttons",
                            "key": "form16_upload_progress",
                            "label": "After uploading, choose:",
                            "options": [
                                {"label": "Uploaded", "value": "form16_done"},
                                {"label": "Skip for now", "value": "form16_skip"},
                            ],
                        }
                    ],
                    "context": {"profile": profile, "history": history, "pending": "wait_form16_upload"},
                }
            if lowered in {"upload_form16_no", "no"}:
                return {
                    "reply": "Understood. Please keep these ready for ITR later: Form 16, donation receipts (80G), and health insurance premium receipts (80D). Share your gross annual income to continue.",
                    "is_tax_related": True,
                    "controls": [
                        {
                            "type": "slider",
                            "key": "gross_income",
                            "label": "Gross annual income (INR)",
                            "min": 300000,
                            "max": 5000000,
                            "step": 50000,
                            "default": 1200000,
                        }
                    ],
                    "context": {"profile": profile, "history": history, "pending": "capture_income"},
                }

        if ctx.get("pending") == "wait_form16_upload":
            if lowered in {"form16_done", "done", "uploaded", "upload complete"}:
                profile["form16_provided"] = True
                return {
                    "reply": "Perfect. I will factor in your Form 16 details. Please share your gross annual income to continue.",
                    "is_tax_related": True,
                    "controls": [
                        {
                            "type": "slider",
                            "key": "gross_income",
                            "label": "Gross annual income (INR)",
                            "min": 300000,
                            "max": 5000000,
                            "step": 50000,
                            "default": 1200000,
                        }
                    ],
                    "context": {"profile": profile, "history": history, "pending": "capture_income"},
                }
            if lowered in {"form16_skip", "skip", "not now"}:
                profile["form16_provided"] = False
                return {
                    "reply": "No problem. Please share your gross annual income and I will continue without Form 16.",
                    "is_tax_related": True,
                    "controls": [
                        {
                            "type": "slider",
                            "key": "gross_income",
                            "label": "Gross annual income (INR)",
                            "min": 300000,
                            "max": 5000000,
                            "step": 50000,
                            "default": 1200000,
                        }
                    ],
                    "context": {"profile": profile, "history": history, "pending": "capture_income"},
                }

        llm_payload = llm_tax_interactive_reply(text, profile, history, ctx.get("pending"))
        llm_answer = llm_payload.get("reply")
        llm_controls = llm_payload.get("controls") or []
        if llm_answer:
            return {
                "reply": llm_answer,
                "is_tax_related": True,
                "controls": llm_controls,
                "context": {"profile": profile, "history": history, "pending": None},
            }

        return {
            "reply": (
                "Sure. I can help with tax planning, deductions, filing, and regime comparison. "
                "If you want a personalized estimate, share your gross annual income."
            ),
            "is_tax_related": True,
            "controls": [
                {
                    "type": "slider",
                    "key": "gross_income",
                    "label": "Gross annual income (INR)",
                    "min": 300000,
                    "max": 5000000,
                    "step": 50000,
                    "default": 1000000,
                },
                {
                    "type": "buttons",
                    "key": "need_regime_comparison",
                    "label": "Need old vs new regime comparison?",
                    "options": [{"label": "Yes", "value": "compare old vs new regime"}, {"label": "No", "value": "show deductions"}],
                },
            ],
            "context": {"profile": profile, "history": history, "pending": "capture_income"},
        }
