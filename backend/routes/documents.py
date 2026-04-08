"""Document routes."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.dependencies import get_current_user_from_header
from app.schemas import DocumentResponse
from models.database import DocumentUpload, User, get_db
from services.document_parser import document_parser
from services.document_service import DocumentService
from services.storage_service import StorageService

router = APIRouter(prefix="/api/user/documents", tags=["documents"])


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user_from_header),
    db: Session = Depends(get_db),
):
    """Upload a user document."""
    try:
        allowed_extensions = {".pdf", ".jpg", ".jpeg", ".png"}
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in allowed_extensions:
            raise HTTPException(status_code=400, detail="File type not supported. Use PDF, JPG, or PNG.")

        file_content = await file.read()
        if len(file_content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File size exceeds 10MB limit")

        extracted_tax_data, parse_error, classified_type, sanitized_text, identity_fields = document_parser.extract_from_bytes(
            file_content=file_content,
            filename=file.filename,
        )
        if parse_error:
            raise HTTPException(status_code=400, detail=parse_error)

        sanitized_bytes = document_parser.sanitize_for_storage(file_content, file.filename)
        cloud_path, error = await StorageService.upload_to_supabase(
            sanitized_bytes,
            file.filename,
            current_user.user_id,
            classified_type,
        )
        if error:
            raise HTTPException(status_code=500, detail=f"Cloud Upload Error: {error}")

        doc, db_error = DocumentService.create_document_record(
            current_user.user_id,
            file.filename,
            classified_type,
            cloud_path,
            db,
        )
        if db_error:
            raise HTTPException(status_code=500, detail=db_error)

        doc.extracted_data = {
            "classified_document_type": classified_type,
            "tax_data": extracted_tax_data,
            "sanitized_text_preview": sanitized_text[:3000],
            "storage_path": cloud_path,
            "itr_profile": identity_fields,
        }
        doc.extraction_status = "success"

        # Keep a compact tax profile snapshot for chat follow-ups.
        existing_profile = current_user.profile_data or {}
        tax_profile = dict(existing_profile.get("tax_profile") or {})
        itr_profile = dict(existing_profile.get("itr_profile") or {})
        tax_profile.update(extracted_tax_data or {})
        tax_profile["form16_provided"] = classified_type == "form_16" or tax_profile.get("form16_provided", False)
        existing_profile["tax_profile"] = tax_profile
        if identity_fields:
            itr_profile.update({k: v for k, v in identity_fields.items() if v})
            existing_profile["itr_profile"] = itr_profile
        current_user.profile_data = existing_profile

        db.commit()
        db.refresh(doc)

        return DocumentResponse.from_orm(doc)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal Server Error") from e


@router.get("/{upload_id}/view")
async def view_document(
    upload_id: str,
    current_user: User = Depends(get_current_user_from_header),
    db: Session = Depends(get_db),
):
    """Generate a signed URL for document view."""
    doc = db.query(DocumentUpload).filter_by(upload_id=upload_id, user_id=current_user.user_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")

    url = StorageService.get_temporary_url(doc.file_path)
    return {"signed_url": url}


@router.get("")
async def list_user_documents(
    current_user: User = Depends(get_current_user_from_header),
    db: Session = Depends(get_db),
):
    """Get all documents for current user."""
    try:
        documents = DocumentService.get_user_documents(current_user.user_id, db)
        return [DocumentResponse.from_orm(doc) for doc in documents]
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to list documents") from e


@router.delete("/{upload_id}")
async def delete_user_document(
    upload_id: str,
    current_user: User = Depends(get_current_user_from_header),
    db: Session = Depends(get_db),
):
    """Delete a user document."""
    try:
        success, error = DocumentService.delete_document(upload_id, current_user.user_id, db)
        if error:
            raise HTTPException(status_code=400, detail=error)
        return {"message": "Document deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to delete document") from e
