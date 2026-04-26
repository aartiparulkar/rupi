"""Document routes."""

import logging
import re
from uuid import uuid4
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.dependencies import get_current_user_from_header
from app.schemas import DocumentResponse
from models.database import DocumentUpload, User, get_db
from services.document_parser import document_parser
from services.document_service import DocumentService
from services.storage_service import StorageService
from scripts.populate_itr_xlsm_from_db import populate_itr_xlsm

router = APIRouter(prefix="/api/user/documents", tags=["documents"])
logger = logging.getLogger(__name__)
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _cleanup_generated_files(*paths: Path) -> None:
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            logger.debug("Unable to remove generated file: %s", path, exc_info=True)


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    confirm_override: bool = Form(False),
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

        # Enforce explicit confirmation before replacing an existing Form 16.
        if classified_type == "form_16":
            existing_form16_docs = (
                db.query(DocumentUpload)
                .filter(
                    DocumentUpload.user_id == current_user.user_id,
                    DocumentUpload.document_type == "form_16",
                )
                .order_by(DocumentUpload.created_at.desc())
                .all()
            )

            if existing_form16_docs and not confirm_override:
                latest_doc = existing_form16_docs[0]
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "FORM16_OVERRIDE_REQUIRED",
                        "message": "A Form 16 already exists. Confirm override to replace it.",
                        "existing_upload_id": latest_doc.upload_id,
                        "existing_filename": latest_doc.filename,
                        "existing_count": len(existing_form16_docs),
                    },
                )

            if existing_form16_docs and confirm_override:
                for existing_doc in existing_form16_docs:
                    success, delete_error = DocumentService.delete_document(
                        existing_doc.upload_id,
                        current_user.user_id,
                        db,
                    )
                    if not success:
                        raise HTTPException(
                            status_code=500,
                            detail=f"Unable to replace previous Form 16: {delete_error or 'delete failed'}",
                        )

        try:
            sanitized_bytes = document_parser.sanitize_for_storage(file_content, file.filename)
        except Exception as sanitize_error:
            logger.warning(
                "Falling back to original upload bytes for %s due to sanitize_for_storage error: %s",
                file.filename,
                str(sanitize_error),
                exc_info=True,
            )
            sanitized_bytes = file_content

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

        extracted_payload = {
            "classified_document_type": classified_type,
            "tax_data": extracted_tax_data,
            "sanitized_text_preview": (sanitized_text or "")[:3000],
            "storage_path": cloud_path,
            "itr_profile": identity_fields,
        }
        missing_critical_fields = DocumentService.get_missing_critical_tax_fields(extracted_tax_data)
        if missing_critical_fields:
            doc.extraction_status = "needs_confirmation"
            logger.info(
                "Document %s requires user confirmation for fields: %s",
                doc.upload_id,
                ", ".join(missing_critical_fields),
            )
        else:
            doc.extraction_status = "success"

        _, extraction_error = DocumentService.upsert_form16_extraction(
            upload_id=doc.upload_id,
            user_id=current_user.user_id,
            filename=file.filename,
            document_type=classified_type,
            extracted_data=extracted_payload,
            db=db,
        )
        if extraction_error:
            raise HTTPException(status_code=500, detail=extraction_error)

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
        logger.error("Document upload failed for %s: %s", file.filename if file else "unknown", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Document upload failed: {str(e)}") from e


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


@router.get("/itr/workbook")
async def download_filled_itr_workbook(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user_from_header),
):
    """Generate the filled ITR workbook from the latest Form 16 extraction and return it."""
    template_path = BACKEND_ROOT / "ITR1_AY_25-26_V1.7.xlsm"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="ITR workbook template not found")

    temp_dir = BACKEND_ROOT / "temp_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    safe_user_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(current_user.user_id))
    output_path = temp_dir / f"itr_filled_{safe_user_id}_{uuid4().hex}.xlsm"

    try:
        result = populate_itr_xlsm(
            template_path=template_path,
            output_path=output_path,
            user_id=current_user.user_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to generate ITR workbook for %s: %s", current_user.user_id, str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate ITR workbook: {str(exc)}") from exc

    payload_path = Path(result.get("output_payload") or output_path.with_name(output_path.stem + "_payload.json"))
    background_tasks.add_task(_cleanup_generated_files, output_path, payload_path)

    assessment_year = result.get("assessment_year") or "2025-26"
    filename = f"ITR1_filled_{assessment_year}.xlsm"
    return FileResponse(
        path=str(output_path),
        filename=filename,
        media_type="application/vnd.ms-excel.sheet.macroEnabled.12",
        background=background_tasks,
    )


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
