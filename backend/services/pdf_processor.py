"""PDF text extraction service

Extracts text from PDF documents using PyPDF2 and optionally refines output with LLM.
"""

import logging
from typing import Dict, Optional

import PyPDF2
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class PDFProcessor:
    """Process PDFs to extract text for tax rule extraction."""

    def __init__(self):
        self._llm_client: Optional[ChatOpenAI] = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=settings.openai_api_key,
            temperature=0,
        )

    def extract_text(self, pdf_path: str, use_llm_cleanup: bool = True) -> str:
        """
        Extract text from PDF file

        Args:
            pdf_path: Path to PDF file
            use_llm_cleanup: Whether to use LLM to clean extracted text

        Returns:
            Extracted text from PDF
        """
        logger.info(f"Extracting text from: {pdf_path}")

        try:
            text = self._extract_with_pypdf2(pdf_path)

            if not text.strip():
                logger.warning(f"No text extracted from {pdf_path}")
                return ""

            if use_llm_cleanup and self._llm_client:
                text = self._cleanup_text_with_llm(text)

            logger.info(f"Successfully extracted {len(text)} characters from PDF")
            return text

        except Exception as e:
            logger.error(f"Error extracting text from PDF: {str(e)}", exc_info=True)
            raise

    def _extract_with_pypdf2(self, pdf_path: str) -> str:
        """Extract text using PyPDF2 (for searchable PDFs)"""
        text = ""
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                num_pages = len(pdf_reader.pages)
                logger.info(f"PDF has {num_pages} pages")
                
                for page_num, page in enumerate(pdf_reader.pages, 1):
                    page_text = page.extract_text()
                    text += page_text + "\n"
                    logger.debug(f"Extracted {len(page_text)} chars from page {page_num}")

            return text
        except Exception as e:
            logger.warning(f"PyPDF2 extraction failed: {str(e)}")
            return ""

    def _cleanup_text_with_llm(self, text: str) -> str:
        """Use LLM to normalize noisy PDF text without changing factual values."""
        try:
            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "human",
                        "Clean the following PDF-extracted text for readability. "
                        "Preserve all numbers, tax sections, rupee values, and rates exactly. "
                        "Return only cleaned plain text with no markdown.\n\n{text}",
                    )
                ]
            )
            chain = prompt | self._llm_client
            response = chain.invoke({"text": text[:12000]})

            cleaned = (response.content or "").strip()
            return cleaned or text
        except Exception as e:
            logger.warning(f"LLM text cleanup failed, using raw extraction: {str(e)}")
            return text

    def extract_text_by_section(self, pdf_path: str, 
                                page_range: Optional[tuple] = None) -> Dict[int, str]:
        """
        Extract text page by page for granular processing
        
        Args:
            pdf_path: Path to PDF file
            page_range: Tuple of (start_page, end_page) to extract (1-indexed, inclusive)
        
        Returns:
            Dictionary mapping page number to extracted text
        """
        pages_text = {}
        
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                num_pages = len(pdf_reader.pages)
                
                start = (page_range[0] - 1) if page_range else 0
                end = min(page_range[1], num_pages) if page_range else num_pages
                
                logger.info(f"Extracting pages {start + 1} to {end} from PDF")
                
                for page_num in range(start, end):
                    page = pdf_reader.pages[page_num]
                    text = page.extract_text()
                    pages_text[page_num + 1] = text
                
                return pages_text

        except Exception as e:
            logger.error(f"Error extracting pages from PDF: {str(e)}", exc_info=True)
            return {}

    def validate_pdf(self, pdf_path: str) -> bool:
        """
        Validate that file is a valid PDF
        
        Args:
            pdf_path: Path to file
        
        Returns:
            True if valid PDF, False otherwise
        """
        try:
            with open(pdf_path, 'rb') as file:
                PyPDF2.PdfReader(file)
            return True
        except Exception as e:
            logger.warning(f"Invalid PDF file: {str(e)}")
            return False


# Singleton instance
pdf_processor = PDFProcessor()
