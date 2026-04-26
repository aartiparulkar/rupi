"""Document management service for user uploads."""

import logging
from datetime import datetime
from pathlib import Path
import uuid
from decimal import Decimal, InvalidOperation
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session
from models.database import DocumentUpload, Form16Extraction
from services.document_parser import document_parser
from services.storage_service import StorageService

logger = logging.getLogger(__name__)


class DocumentService:
    """Service for managing user document uploads and processing"""

    CRITICAL_TAX_FIELDS = (
        "financial_year",
        "gross_total_income",
        "taxable_income",
        "tax_payable",
        "tds",
    )

    @staticmethod
    def get_missing_critical_tax_fields(tax_data: dict) -> list[str]:
        """Return critical tax fields that still need user confirmation/input."""
        payload = tax_data or {}
        missing: list[str] = []
        for field_name in DocumentService.CRITICAL_TAX_FIELDS:
            value = payload.get(field_name)
            if value is None or value == "":
                missing.append(field_name)
        return missing
    
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
    def upsert_form16_extraction(
        upload_id: str,
        user_id: str,
        filename: str,
        document_type: str,
        extracted_data: dict,
        db: Session,
    ) -> tuple[Form16Extraction, str]:
        """Store extraction payload in form_16_extractions table columns."""

        def to_decimal(value):
            if value is None or value == "":
                return None
            try:
                return Decimal(str(value).replace(",", ""))
            except (InvalidOperation, ValueError, TypeError):
                return None

        def to_bool(value):
            if value is None:
                return None
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "1", "yes", "y"}:
                    return True
                if lowered in {"false", "0", "no", "n"}:
                    return False
            return bool(value)

        try:
            try:
                record = db.query(Form16Extraction).filter_by(upload_id=upload_id, user_id=user_id).first()
            except ProgrammingError as lookup_error:
                db.rollback()
                lookup_error_text = str(lookup_error).lower()
                # Guard only the true "relation does not exist" case; let other
                # schema errors (e.g. missing columns) bubble up with full details.
                is_missing_relation = (
                    "relation" in lookup_error_text and
                    "does not exist" in lookup_error_text and
                    ("form_16_extractions" in lookup_error_text or "form16_extractions" in lookup_error_text)
                )
                if not is_missing_relation:
                    raise

                # Backward-compatible fallback: allow upload flow to succeed even if
                # form_16_extractions table is missing in this environment.
                logger.warning(
                    "Skipping form_16_extractions upsert because table is missing. "
                    "Apply DB migrations to enable structured extraction storage."
                )
                return None, None

            if record is None:
                record = Form16Extraction(
                    extraction_id=str(uuid.uuid4()),
                    upload_id=upload_id,
                    user_id=user_id,
                )
                db.add(record)

            tax_data = (extracted_data or {}).get("tax_data") or {}
            itr_profile = (extracted_data or {}).get("itr_profile") or {}

            record.filename = filename
            record.document_type = document_type
            record.classified_document_type = (extracted_data or {}).get("classified_document_type") or document_type
            record.storage_path = (extracted_data or {}).get("storage_path")
            record.sanitized_text_preview = (extracted_data or {}).get("sanitized_text_preview")
            record.extraction_method = (extracted_data or {}).get("extraction_method")

            record.gross_salary = to_decimal(tax_data.get("gross_salary"))
            record.salary_section_17_1 = to_decimal(tax_data.get("salary_section_17_1"))
            record.perquisites_17_2 = to_decimal(tax_data.get("perquisites_17_2"))
            record.profits_in_lieu_17_3 = to_decimal(tax_data.get("profits_in_lieu_17_3"))
            record.basic_salary = to_decimal(tax_data.get("basic_salary"))
            record.hra = to_decimal(tax_data.get("hra"))
            record.lta = to_decimal(tax_data.get("lta"))
            record.travel_concession_exemption = to_decimal(tax_data.get("travel_concession_exemption"))
            record.gratuity_exemption = to_decimal(tax_data.get("gratuity_exemption"))
            record.commuted_pension_exemption = to_decimal(tax_data.get("commuted_pension_exemption"))
            record.leave_encashment_exemption = to_decimal(tax_data.get("leave_encashment_exemption"))
            record.other_section10_exemptions = to_decimal(tax_data.get("other_section10_exemptions"))
            record.total_section10_exemptions = to_decimal(tax_data.get("total_section10_exemptions"))
            record.salary_after_section10_exemptions = to_decimal(tax_data.get("salary_after_section10_exemptions"))
            record.other_allowances = to_decimal(tax_data.get("other_allowances"))
            record.deductions_80c = to_decimal(tax_data.get("deductions_80c"))
            record.deductions_80ccc = to_decimal(tax_data.get("deductions_80ccc"))
            record.deductions_80ccd_1 = to_decimal(tax_data.get("deductions_80ccd_1"))
            record.deductions_80ccd_1b = to_decimal(tax_data.get("deductions_80ccd_1b"))
            record.deductions_80ccd_2 = to_decimal(tax_data.get("deductions_80ccd_2"))
            record.deductions_80d = to_decimal(tax_data.get("deductions_80d"))
            record.deductions_80e = to_decimal(tax_data.get("deductions_80e"))
            record.deductions_other = to_decimal(tax_data.get("deductions_other"))
            record.entertainment_allowance = to_decimal(tax_data.get("entertainment_allowance"))
            record.standard_deduction = to_decimal(tax_data.get("standard_deduction"))
            record.professional_tax = to_decimal(tax_data.get("professional_tax"))
            record.total_section16_deductions = to_decimal(tax_data.get("total_section16_deductions"))
            record.income_under_salary = to_decimal(tax_data.get("income_under_salary"))
            record.house_property_income = to_decimal(tax_data.get("house_property_income"))
            record.other_sources_income = to_decimal(tax_data.get("other_sources_income"))
            record.total_other_income = to_decimal(tax_data.get("total_other_income"))
            record.gross_total_income = to_decimal(tax_data.get("gross_total_income"))
            record.chapter_via_total_deductions = to_decimal(tax_data.get("chapter_via_total_deductions"))
            record.tds = to_decimal(tax_data.get("tds"))
            record.net_salary = to_decimal(tax_data.get("net_salary"))
            record.taxable_income = to_decimal(tax_data.get("taxable_income"))
            record.tax_payable = to_decimal(tax_data.get("tax_payable"))
            record.net_payable_tax = to_decimal(tax_data.get("net_payable_tax"))
            record.surcharge = to_decimal(tax_data.get("surcharge"))
            record.health_education_cess = to_decimal(tax_data.get("health_education_cess"))
            record.relief_89 = to_decimal(tax_data.get("relief_89"))
            record.section_87a_rebate = to_decimal(tax_data.get("section_87a_rebate"))
            record.house_rent_exemption_10_13a = to_decimal(tax_data.get("house_rent_exemption_10_13a"))
            record.donations_80g = to_decimal(tax_data.get("donations_80g"))
            record.other_income = to_decimal(tax_data.get("other_income"))

            record.financial_year = tax_data.get("financial_year")
            record.assessment_year = tax_data.get("assessment_year")
            record.form16_part_a_present = to_bool(tax_data.get("form16_part_a_present"))
            record.form16_part_b_present = to_bool(tax_data.get("form16_part_b_present"))

            record.employee_name = itr_profile.get("employee_name")
            record.employer_name = itr_profile.get("employer_name")
            record.pan = itr_profile.get("pan")
            record.pan_last4 = itr_profile.get("pan_last4")
            record.address = itr_profile.get("address")

            db.commit()
            db.refresh(record)
            return record, None
        except Exception as e:
            db.rollback()
            logger.error(f"Error saving form_16_extractions record: {str(e)}", exc_info=True)
            return None, f"Extraction storage failed: {str(e)}"
    
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
            
            # Update document record status only; extraction payload lives in form_16_extractions.
            document_upload.extraction_status = "success"
            db.commit()

            _, storage_error = DocumentService.upsert_form16_extraction(
                upload_id=document_upload.upload_id,
                user_id=document_upload.user_id,
                filename=document_upload.filename,
                document_type=classified_type,
                extracted_data=extracted_data,
                db=db,
            )
            if storage_error:
                raise ValueError(storage_error)
            
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

            # Cleanup extraction snapshots, but don't block document deletion if this fails.
            try:
                with db.begin_nested():
                    extraction_rows = db.query(Form16Extraction).filter_by(
                        upload_id=upload_id,
                        user_id=user_id,
                    ).all()
                    for extraction_row in extraction_rows:
                        db.delete(extraction_row)
            except Exception as extraction_error:
                logger.warning(
                    "Could not delete form_16_extractions for upload %s and user %s: %s",
                    upload_id,
                    user_id,
                    str(extraction_error),
                    exc_info=True,
                )
            
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
            return False, f"Deletion failed ({type(e).__name__}): {str(e)}"
