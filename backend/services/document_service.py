"""Document management service for user uploads."""

import logging
from datetime import datetime
from pathlib import Path
import uuid
from sqlalchemy.orm import Session
from models.database import DocumentUpload
from services.document_parser import document_parser
from services.storage_service import StorageService

logger = logging.getLogger(__name__)


class DocumentService:
    """Service for managing user document uploads and processing"""
    
    @staticmethod
    def save_uploaded_file(file_content: bytes, filename: str, user_id: str, upload_path: str) -> tuple[str, str]:
        """
        Save uploaded file to disk
        
        Args:
            file_content: File bytes
            filename: Original filename
            user_id: User ID
            upload_path: Base upload path
        
        Returns:
            Tuple of (file_path, error_message or None)
        """
        try:
            # Create user-specific directory
            user_dir = Path(upload_path) / user_id
            user_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate unique filename
            file_ext = Path(filename).suffix
            unique_filename = f"{uuid.uuid4()}{file_ext}"
            file_path = user_dir / unique_filename
            
            # Save file
            with open(file_path, 'wb') as f:
                f.write(file_content)
            
            logger.info(f"File saved: {file_path}")
            return str(file_path), None
            
        except Exception as e:
            logger.error(f"Error saving file: {str(e)}", exc_info=True)
            return None, f"File save failed: {str(e)}"
    
    @staticmethod
    def create_document_record(
        user_id: str,
        filename: str,
        document_type: str,
        file_path: str,
        db: Session
    ) -> tuple[DocumentUpload, str]:
        """
        Create document upload record in database
        
        Args:
            user_id: User ID
            filename: Original filename
            document_type: Type of document (form_16, salary_slip, etc.)
            file_path: Path to saved file
            db: Database session
        
        Returns:
            Tuple of (DocumentUpload object or None, error message or None)
        """
        try:
            upload_id = str(uuid.uuid4())
            
            doc = DocumentUpload(
                upload_id=upload_id,
                user_id=user_id,
                filename=filename,
                document_type=document_type,
                file_path=file_path,
                extraction_status="pending"
            )
            
            db.add(doc)
            db.commit()
            db.refresh(doc)
            
            logger.info(f"Document record created: {upload_id}")
            return doc, None
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating document record: {str(e)}", exc_info=True)
            return None, f"Database error: {str(e)}"
    
    @staticmethod
    def process_document(file_content: bytes, document_upload: DocumentUpload, db: Session) -> tuple[dict, str]:
        """
        Process uploaded document (extract text)
        
        Args:
            file_content: Raw uploaded file content
            document_upload: DocumentUpload database object
            db: Database session
        
        Returns:
            Tuple of (extracted_data dict or None, error message or None)
        """
        try:
            extracted_tax_data, parse_error, classified_type, sanitized_preview, identity_fields = document_parser.extract_from_bytes(
                file_content=file_content,
                filename=document_upload.filename,
                document_type=document_upload.document_type,
            )

            if parse_error:
                raise ValueError(parse_error)

            extracted_data = {
                "classified_document_type": classified_type,
                "tax_data": extracted_tax_data,
                "sanitized_text_preview": sanitized_preview,
                "itr_profile": identity_fields,
                "extraction_method": "classified+sanitized+llm_regex",
                "extraction_date": datetime.now().isoformat(),
            }

            document_upload.document_type = classified_type
            
            # Update document record
            document_upload.extraction_status = "success"
            document_upload.extracted_data = extracted_data
            db.commit()
            
            logger.info(f"Document processed successfully: {document_upload.upload_id}")
            return extracted_data, None
            
        except Exception as e:
            # Mark as failed
            document_upload.extraction_status = "failed"
            document_upload.error_message = str(e)
            db.commit()
            
            logger.error(f"Error processing document: {str(e)}", exc_info=True)
            return None, f"Processing failed: {str(e)}"
    
    @staticmethod
    def get_user_documents(user_id: str, db: Session) -> list[DocumentUpload]:
        """Get all documents for a user"""
        return db.query(DocumentUpload).filter_by(user_id=user_id).order_by(DocumentUpload.created_at.desc()).all()
    
    @staticmethod
    def get_document_by_id(upload_id: str, db: Session) -> DocumentUpload:
        """Get document by upload ID"""
        return db.query(DocumentUpload).filter_by(upload_id=upload_id).first()
    
    @staticmethod
    def delete_document(upload_id: str, user_id: str, db: Session) -> tuple[bool, str]:
        """
        Delete document and associated file
        
        Args:
            upload_id: Upload ID
            user_id: User ID (for verification)
            db: Database session
        
        Returns:
            Tuple of (Success boolean, error message or None)
        """
        try:
            doc = db.query(DocumentUpload).filter_by(upload_id=upload_id, user_id=user_id).first()
            if not doc:
                return False, "Document not found"
            
            # Delete cloud file from Supabase bucket
            if doc.file_path:
                StorageService.delete_from_supabase(doc.file_path)
                logger.info(f"Cloud file deleted: {doc.file_path}")
            
            # Delete record
            db.delete(doc)
            db.commit()
            
            logger.info(f"Document deleted: {upload_id}")
            return True, None
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error deleting document: {str(e)}", exc_info=True)
            return False, f"Deletion failed: {str(e)}"
