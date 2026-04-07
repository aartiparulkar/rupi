"""FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_current_user_from_header
from app.schemas import ChatMessageRequest, CreateChatSessionRequest, UpdateProfileRequest
from models.database import User, get_db, init_db
from routes.admin import router as admin_router
from routes.auth import router as auth_router
from routes.calculations import router as calculations_router
from routes.docs import router as docs_router
from routes.documents import router as documents_router
from scheduler import start_scheduler, stop_scheduler
from services.auth_service import AuthService
from services.auth_utils import AuthUtils
from services.chat_service import ChatService

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown lifecycle."""
    logger.info("Starting Tax Agent Application...")
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")

    start_scheduler()
    logger.info("Application startup complete")

    yield

    logger.info("Shutting down Tax Agent Application...")
    stop_scheduler()
    logger.info("Application shutdown complete")


app = FastAPI(
    title="Tax Agent API",
    description="API for calculating tax on government-extracted rules",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Router-based structure
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(calculations_router)
app.include_router(docs_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "environment": settings.environment,
        "debug": settings.debug,
    }


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "Tax Agent API - RuPi",
        "version": "0.2.0",
        "status": "Tax Agent with Router-based structure",
        "endpoints": {
            "health": "/health",
            "admin": "/admin/*",
            "documents": "/api/user/documents/*",
            "calculations": ["/api/calculate-tax", "/api/deduction-suggestions", "/api/tax-rules"],
            "user": ["/api/user/profile"],
            "chat": ["/api/chat/session", "/api/chat/history"],
        },
    }


@app.get("/api/user/profile")
async def get_user_profile(current_user: User = Depends(get_current_user_from_header)):
    """Get user profile."""
    return {"user": AuthService.serialize_user(current_user)}


@app.put("/api/user/profile")
async def update_user_profile(
    request: UpdateProfileRequest,
    current_user: User = Depends(get_current_user_from_header),
    db: Session = Depends(get_db),
):
    """Update user profile."""
    try:
        profile_updates = request.dict(exclude_unset=True)

        incoming_profile_data = profile_updates.get("profile_data") or {}
        merged_profile_data = dict(current_user.profile_data or {})

        camel_case_mappings = {
            "dob": "dob",
            "gender": "gender",
            "profession": "profession",
            "pan": "pan",
            "incomeRange": "incomeRange",
            "taxRegime": "taxRegime",
            "riskAppetite": "riskAppetite",
            "goals": "goals",
            "phone": "phone",
            "city": "city",
            "state": "state",
            "address": "address",
            "profileComplete": "profileComplete",
            "mfaEnabled": "mfaEnabled",
            "loginNotifications": "loginNotifications",
            "authProvider": "authProvider",
        }

        for camel_key, data_key in camel_case_mappings.items():
            if camel_key in profile_updates:
                merged_profile_data[data_key] = profile_updates[camel_key]

        merged_profile_data.update(incoming_profile_data)

        if "firstName" in profile_updates:
            profile_updates["first_name"] = profile_updates.pop("firstName")
        if "lastName" in profile_updates:
            profile_updates["last_name"] = profile_updates.pop("lastName")

        profile_updates["profile_data"] = merged_profile_data
        user, error = AuthService.update_user_profile(current_user.user_id, profile_updates, db)
        if error:
            raise HTTPException(status_code=400, detail=error)

        return {
            "user": AuthService.serialize_user(user),
            "message": "Profile updated successfully.",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating profile: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Profile update failed") from e


@app.post("/api/chat/session")
async def create_chat_session(
    request: CreateChatSessionRequest,
    current_user: User = Depends(get_current_user_from_header),
    db: Session = Depends(get_db),
):
    """Create a new chat session."""
    try:
        requested_agent = request.agent_type or request.agent
        if requested_agent == "investment":
            requested_agent = "invest"

        if requested_agent not in ["tax", "invest", "security"]:
            raise HTTPException(status_code=400, detail="Invalid agent_type. Must be 'tax', 'invest', or 'security'")

        session = ChatService.create_session(user_id=current_user.user_id, agent_type=requested_agent, db=db)

        if request.initial_message:
            ChatService.append_message(
                session_id=session.session_id,
                role="user",
                content=request.initial_message,
                db=db,
            )
            ai_response = ChatService.generate_ai_response(
                user_message=request.initial_message,
                session_context={"agent_type": requested_agent, "user_id": current_user.user_id},
                db=db,
            )
            ChatService.append_message(
                session_id=session.session_id,
                role="assistant",
                content=ai_response,
                db=db,
            )

        updated_session = ChatService.get_session(session.session_id, current_user.user_id, db)
        payload = {
            "session_id": updated_session.session_id,
            "agent_type": updated_session.agent_type,
            "messages": updated_session.messages or [],
            "preview": updated_session.preview,
            "created_at": updated_session.created_at.isoformat(),
        }
        return {"session": payload, **payload}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating chat session: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create chat session") from e


@app.post("/api/chat/session/{session_id}/message")
async def send_chat_message(
    session_id: str,
    request: ChatMessageRequest,
    current_user: User = Depends(get_current_user_from_header),
    db: Session = Depends(get_db),
):
    """Send a message to a chat session."""
    try:
        session = ChatService.get_session(session_id, current_user.user_id, db)
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")

        ChatService.append_message(session_id=session_id, role=request.role, content=request.content, db=db)

        if request.role == "user":
            ai_response = ChatService.generate_ai_response(
                user_message=request.content,
                session_context={
                    "agent_type": session.agent_type,
                    "user_id": current_user.user_id,
                    "session_id": session_id,
                },
                db=db,
            )
            ChatService.append_message(session_id=session_id, role="assistant", content=ai_response, db=db)

        updated_session = ChatService.get_session(session_id, current_user.user_id, db)
        return {
            "session_id": updated_session.session_id,
            "agent_type": updated_session.agent_type,
            "messages": updated_session.messages or [],
            "preview": updated_session.preview,
            "created_at": updated_session.created_at.isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending chat message: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to send message") from e


@app.get("/api/chat/history")
async def get_chat_history(
    agent_type: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    current_user: User = Depends(get_current_user_from_header),
    db: Session = Depends(get_db),
):
    """Get chat session history for the current user."""
    try:
        from models.database import ChatSession

        query = db.query(ChatSession).filter(ChatSession.user_id == current_user.user_id)
        if agent_type:
            query = query.filter(ChatSession.agent_type == agent_type)

        total = query.count()
        sessions = query.order_by(ChatSession.created_at.desc()).offset(offset).limit(limit).all()

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "sessions": [
                {
                    "session_id": s.session_id,
                    "agent_type": s.agent_type,
                    "preview": s.preview,
                    "message_count": len(s.messages) if s.messages else 0,
                    "created_at": s.created_at.isoformat(),
                    "updated_at": s.updated_at.isoformat(),
                }
                for s in sessions
            ],
        }
    except Exception as e:
        logger.error(f"Error retrieving chat history: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve chat history") from e


@app.get("/api/chat/session/{session_id}")
async def get_chat_session(
    session_id: str,
    current_user: User = Depends(get_current_user_from_header),
    db: Session = Depends(get_db),
):
    """Get a specific chat session with all messages."""
    try:
        session = ChatService.get_session(session_id, current_user.user_id, db)
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")

        return {
            "session_id": session.session_id,
            "agent_type": session.agent_type,
            "messages": session.messages or [],
            "preview": session.preview,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving chat session: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve chat session") from e


@app.put("/api/chat/session/{session_id}")
async def update_chat_session(
    session_id: str,
    request: dict,
    current_user: User = Depends(get_current_user_from_header),
    db: Session = Depends(get_db),
):
    """Compatibility endpoint for frontend chat session updates."""
    try:
        session = ChatService.get_session(session_id, current_user.user_id, db)
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")

        from models.database import ChatMessage, ChatSession

        messages = request.get("messages", [])
        preview = request.get("preview")

        db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            if content:
                ChatService.append_message(session_id=session_id, role=role, content=content, db=db)

        if preview is not None:
            persisted_session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
            if persisted_session:
                persisted_session.preview = preview
                db.commit()

        updated_session = ChatService.get_session(session_id, current_user.user_id, db)
        return {
            "session": {
                "_id": updated_session.session_id,
                "agent": "investment" if updated_session.agent_type == "invest" else updated_session.agent_type,
                "messages": updated_session.messages or [],
                "preview": updated_session.preview,
                "updatedAt": updated_session.updated_at.isoformat(),
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating chat session: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update chat session") from e


@app.delete("/api/chat/session/{session_id}")
async def delete_chat_session(
    session_id: str,
    current_user: User = Depends(get_current_user_from_header),
    db: Session = Depends(get_db),
):
    """Delete a chat session."""
    try:
        from models.database import ChatSession

        session = db.query(ChatSession).filter(
            ChatSession.session_id == session_id,
            ChatSession.user_id == current_user.user_id,
        ).first()
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")

        db.delete(session)
        db.commit()
        return {"message": "Chat session deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting chat session: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete chat session") from e


@app.post("/api/tax-agent/chat")
async def tax_agent_chat(
    request: dict,
    authorization: str = Header(None),
    db: Session = Depends(get_db),
):
    """Tax-only conversational endpoint with structured interactive prompts."""
    try:
        message = request.get("message", "")
        context = request.get("context") or {}
        profile = dict(context.get("profile") or {})
        is_registered = False

        if authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1]
            payload = AuthUtils.verify_token(token)
            if payload:
                user_id = payload.get("user_id") or payload.get("sub") or payload.get("id")
                if user_id:
                    user = AuthService.get_user_by_id(user_id, db)
                    if user and isinstance(user.profile_data, dict):
                        is_registered = True
                        tax_profile = user.profile_data.get("tax_profile") or {}
                        profile = {**tax_profile, **profile}
                    elif user:
                        is_registered = True

        context["profile"] = profile
        context["is_registered"] = is_registered
        context["db"] = db
        return ChatService.generate_tax_assistant_response(message=message, context=context)
    except Exception as e:
        logger.error(f"Error in tax-agent chat: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to process tax chat") from e


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
