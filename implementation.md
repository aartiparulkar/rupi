# Tax Calculation Agent - Implementation Plan

## Project Overview

**Goal:** Build a backend API that fetches government tax documents, extracts tax rules for salaried individuals, processes user financial documents (Form 16, salary slips), calculates taxes, and explains results in simple language using LLM.

**Architecture:** Backend API only (Python/FastAPI)

**Tech Stack:**
- Backend: Python 3.10+, FastAPI
- PDF Processing: Python-pptx + Tesseract OCR + PyPDF2
- LLM: Claude API (Anthropic)
- Database: PostgreSQL
- Scheduling: APScheduler
- Frontend: React (separate codebase)

---

## Requirements Summary

| Requirement | Decision |
|-------------|----------|
| Document Fetching | Automatic from gov portals on Feb 1st each year |
| PDF Processing | Mixed (text + OCR for scanned documents) |
| Tax Scope | India - both Old and New regimes |
| Documents to Fetch | 3 PDFs: Memorandum, Finance Bill, Budget Highlights |
| User Input | Financial documents (Form 16, salary slips) |
| LLM Output | Simple, non-technical explanations for salaried individuals |

---

## Implementation Plan

### Phase 1: Project Setup & Document Fetching Infrastructure

**Objective:** Initialize project, set up scheduled document fetching, store PDFs and extracted rules.

**Tasks:**

1. **Project structure initialization**
   - Create `/backend` directory with Python virtual environment
   - Set up FastAPI project structure: `app/`, `services/`, `models/`, `routes/`, `config/`
   - Initialize requirements.txt with dependencies: fastapi, uvicorn, sqlalchemy, psycopg2, anthropic, requests, beautifulsoup4, selenium, pytesseract, PyPDF2, apscheduler, python-dotenv

2. **Configure environment & database**
   - Create `.env` template with: DATABASE_URL, ANTHROPIC_API_KEY, LOG_LEVEL
   - Initialize PostgreSQL models for: TaxRules, UserCalculations, DocumentUpload, RuleCache
   - Run migrations to create tables

3. **Web scraper for government documents**
   - Primary source: **https://www.indiabudget.gov.in** (official Union Budget website)
   - **Actual document URLs (tested):**
     - **Memorandum:** 
       - `https://www.indiabudget.gov.in/budget{fiscal_year}/doc/memo.pdf` (primary)
       - `https://www.indiabudget.gov.in/doc/memo.pdf` (fallback)
     - **Finance Bill:** 
       - `https://www.indiabudget.gov.in/budget{fiscal_year}/doc/Finance_Bill.pdf` (primary)
       - `https://www.indiabudget.gov.in/doc/Finance_Bill.pdf` (fallback)
     - **Budget Highlights:** 
       - `https://www.indiabudget.gov.in/doc/bh1.pdf` (primary)
       - `https://www.indiabudget.gov.in/budget{fiscal_year}/doc/bh1.pdf` (fallback)
   - Implement scraper with:
     - Direct HTTP GET for known PDF paths (no JavaScript rendering needed)
     - Request headers: User-Agent, Accept-Language to mimic browser requests
     - Error handling for 404s, permission denied, network timeouts
     - Retry logic: exponential backoff for transient failures
   - Implement `download_from_indiabudget(fiscal_year)` function:
     ```python
     # Logic:
     # 1. For each document type (memo, Finance_Bill, bh1):
     #    a. Try primary URL pattern first
     #    b. If 404/error, try fallback URL
     # 2. Validate file > 1MB (non-empty)
     # 3. Verify PDF structure (magic bytes: %PDF)
     # 4. Store with metadata (source URL, download time, file hash)
     # 5. Log success/failure to database
     # Example for FY 2025-26:
     #   memo: https://www.indiabudget.gov.in/budget2025-26/doc/memo.pdf
     #        → fallback: https://www.indiabudget.gov.in/doc/memo.pdf
     ```

4. **APScheduler configuration**
   - Create scheduler task to run Feb 1st annually at 08:00 AM IST
   - Task: Download 3 PDFs, validate file size > 0, store in `tax-docs/{fiscal_year}/`
   - Log all fetch attempts and store metadata in database

5. **PDF storage & versioning**
   - Implement file versioning: rename downloaded PDFs with timestamp
   - Keep original + extracted text versions
   - Store file metadata (source URL, fetch date, file hash) in database
   - Organize in `tax-docs/{fiscal_year}/`:
     - `Memorandum_{FY}_{timestamp}.pdf`
     - `Finance_Bill_{FY}_{timestamp}.pdf`
     - `Budget_Highlights_{FY}_{timestamp}.pdf`
   - Archive previous versions (keep for comparison, rule updates)

**Pre-Phase 1 Validation:**
   - Test scraper against existing 2024-25 & 2025-26 PDFs in `tax-docs/`
   - Verify downloaded files match originals (file hash comparison)
   - Confirm fiscal year URL format: `budget2024-25` (with hyphen), `budget2025-26`, etc.
   - Test both URL patterns (with budget folder and fallback without)
   - Document any variations or blocking for future fiscal years
   - Example: For FY 2025-26, try `/budget2025-26/doc/memo.pdf` first, then `/doc/memo.pdf`

---

### Phase 2: PDF Processing & Rule Extraction

**Objective:** Extract readable text from PDFs and use Claude to identify tax rules applicable to salaried individuals.

**Tasks:**

6. **PDF text extraction pipeline**
   - Create `backend/services/pdf_processor.py`
   - Implement `extract_text_with_ocr()`:
     - Try PyPDF2 for text-based PDFs first (fast)
     - Fall back to Tesseract OCR for scanned images
     - Handle multi-page documents, preserve formatting
   - Test on existing tax-docs PDFs (memo, Finance Bill, budget highlights)

7. **LLM-powered rule extraction**
   - Create `backend/services/llm_extractor.py`
   - Design prompt: "Extract all tax rules applicable to salaried individuals from this document. Include: deductions (80C, 80D, etc.), exemptions, thresholds, rebates, surcharge rules, both Old and New regime rules. Format as structured JSON."
   - Call Claude API with extracted PDF text
   - Parse response to identify: rule ID, description, regime (old/new/both), fiscal year, category (deduction/exemption/rate/surcharge/rebate)

8. **Rule storage & caching**
   - Create database schema for TaxRules table:
     ```
     id, rule_id, description, regime, fiscal_year, category, amount/percentage, 
     source_document, extraction_date, confidence_score
     ```
   - Store extracted rules with year/regime metadata
   - Implement query methods: `get_rules_by_year()`, `get_rules_by_regime()`, `search_rule_by_keyword()`

9. **Fallback manual rule entry**
   - Create admin API endpoint: `POST /admin/rules/manual-entry`
   - Allow override/addition of rules if Claude extraction misses edge cases
   - Log all manual entries for audit trail

---

### Phase 3: User Document Processing & Tax Calculation

**Objective:** Accept user financial documents, extract data, calculate tax under both regimes.

**Tasks:**

10. **API endpoint for document upload**
    - Create `POST /api/documents/upload` endpoint
    - Accept: Form 16 PDF, salary slip images/PDFs
    - Validate file type, size < 10MB
    - Store in temporary location, assign upload_id

11. **Document data extraction**
    - Create `backend/services/document_parser.py`
    - Function `extract_financial_data()`:
      - Use Tesseract OCR on uploaded document
      - Parse structured fields: gross salary, basic, HRA, LTA, deductions (80C, 80D, etc.), taxable income
      - Use Claude API with structured extraction prompt: "Extract these fields from this salary document: gross_salary, basic_salary, HRA, LTA, other_allowances, deductions_80C, deductions_80D, deductions_other, tax_paid_till_date. Return as JSON."
    - Handle multiple documents (Form 16 + salary slips) → merge data

12. **Tax calculation engine**
    - Create `backend/services/tax_calculator.py`
    - Implement `calculate_tax_old_regime(income, deductions, regime_rules)`:
      - Apply standard deduction (if applicable)
      - Calculate taxable income = income - eligible_deductions
      - Apply slab rates: 0%, 5%, 20%, 30% (FY 25-26 slabs)
      - Apply surcharge based on income level
      - Apply health & education cess (4%)
      - Apply §87A rebate if income ≤ ₹5L
      - Return total tax, effective rate, breakdown
    - Implement `calculate_tax_new_regime(income, deductions, regime_rules)`:
      - Apply simplified slabs (no deductions except standard deduction)
      - Calculate tax with new regime rates
      - Apply surcharge, cess
      - Apply §87A rebate
      - Return total tax, effective rate, breakdown
    - Implement `recommended_regime()`:
      - Compare both regimes
      - Return "old" or "new" based on lower tax liability

13. **Calculation history & audit trail**
    - Store calculations in database:
      ```
      id, user_id, uploaded_documents, extracted_data, 
      tax_old_regime, tax_new_regime, recommended_regime, 
      created_at, updated_at
      ```
    - Allow users to retrieve past calculations

---

### Phase 4: LLM-Powered Explanations & API Response

**Objective:** Generate human-readable tax explanations and structure API responses.

**Tasks:**

14. **Explanation generation pipeline**
    - Create `backend/services/llm_explainer.py`
    - Function `generate_tax_explanation()`:
      - Input: calculated_tax, deductions, applicable_rules, regime
      - Prompt Claude: "Explain this tax calculation in simple, non-technical language for a salaried employee. Use analogies, avoid jargon like 'assessee' or 'assessment'. Include: what you owe, why, how to reduce it, filing requirements. Keep under 200 words."
      - Return explanation text

15. **API response structure**
    - Design endpoint: `POST /api/calculate-tax`
    - Request body:
      ```json
      {
        "uploaded_document_ids": ["doc_id_1"],
        "extracted_data": {
          "gross_salary": 1000000,
          "deductions_80C": 150000,
          "deductions_80D": 50000,
          "hra": 400000
        }
      }
      ```
    - Response:
      ```json
      {
        "tax_old_regime": {
          "total_tax": 126000,
          "effective_rate": "12.6%",
          "breakdown": {
            "taxable_income": 1000000,
            "deductions_applied": 200000,
            "slab_tax": 130000,
            "surcharge": 0,
            "cess": 5200,
            "rebate_87A": -9200
          },
          "explanation": "Based on your gross salary of ₹10L and deductions..."
        },
        "tax_new_regime": {
          "total_tax": 109000,
          "effective_rate": "10.9%",
          "breakdown": {...},
          "explanation": "Under the New Regime..."
        },
        "recommended_regime": "new",
        "rules_applied": [
          {"rule_id": "deduction_80C", "description": "Investment in ELSS, PPF, etc."},
          {"rule_id": "surcharge_0", "description": "No surcharge applicable"}
        ],
        "filing_requirements": "You must file ITR-1 if..."
      }
      ```

---

### Phase 5: Deployment & Testing

**Objective:** Validate calculations, error handling, and deploy to staging.

**Tasks:**

16. **Unit tests for tax calculation**
    - Create `backend/tests/test_tax_calculator.py`
    - Test Old Regime:
      - Test case 1: Salary ₹10L, deductions ₹2L → Expected tax ≈ ₹109K
      - Test case 2: Salary ₹5L → Expected tax = ₹0 (§87A rebate applies)
      - Test case 3: Salary ₹50L (surcharge applicable) → Verify surcharge calculation
    - Test New Regime:
      - Same cases under new slabs
    - Test edge cases: negative income, deductions > income, invalid data types

17. **Integration tests**
    - Test PDF fetching: Verify 3 PDFs download, have content
    - Test rule extraction: Parse downloadedPDFs, verify ≥10 rules extracted
    - Test document upload → calculation → explanation end-to-end
    - Test error cases: invalid PDF, missing fields, API rate limit

18. **Error handling & logging**
    - Implement try-catch for: PDF parsing failures, API rate limits, database errors
    - Create fallback rules if Claude extraction fails
    - Structured logging: all API calls, failures, timings
    - Create `/admin/health-check` endpoint for monitoring

19. **Documentation & API spec**
    - Generate OpenAPI/Swagger docs (auto-generated by FastAPI)
    - Document all endpoints: `/upload`, `/calculate-tax`, `/history`, `/admin/*`
    - Create README with setup instructions, example requests

20. **Staging deployment**
    - Deploy to staging environment (AWS EC2 or Docker container)
    - Set up PostgreSQL staging database
    - Configure Anthropic API key in CI/CD secrets
    - Test both regimes against 2024-25 and 2025-26 tax rules

---

## File Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app initialization
│   └── config.py                  # Environment config, source URLs
├── services/
│   ├── pdf_processor.py           # extract_text_with_ocr()
│   ├── document_fetcher.py        # Scrape indiabudget.gov.in, download PDFs
│   ├── llm_extractor.py           # Rule extraction from PDFs
│   ├── document_parser.py         # Parse user financial documents
│   ├── tax_calculator.py          # calculate_tax_old/new_regime()
│   └── llm_explainer.py           # Generate explanations
├── models/
│   ├── database.py                # SQLAlchemy models
│   └── schemas.py                 # Pydantic request/response schemas
├── routes/
│   ├── documents.py               # POST /upload
│   ├── calculations.py            # POST /calculate-tax, GET /history
│   └── admin.py                   # Admin endpoints, manual rule entry
├── config/
│   └── government_sources.json    # URLs for indiabudget.gov.in, fallback sources
├── scheduler.py                   # APScheduler config for Feb 1st fetch
├── tests/
│   ├── test_tax_calculator.py     # Unit tests
│   └── test_integration.py        # Integration tests
├── requirements.txt
├── .env.example
└── README.md
```

### Configuration Example: `config/government_sources.json`

```json
{
  "primary_source": {
    "name": "India Budget Official Portal",
    "base_url": "https://www.indiabudget.gov.in",
    "documents": {
      "memorandum": {
        "url_patterns": [
          "/budget{fiscal_year}/doc/memo.pdf",
          "/doc/memo.pdf"
        ],
        "example_urls": [
          "https://www.indiabudget.gov.in/budget2024-25/doc/memo.pdf",
          "https://www.indiabudget.gov.in/doc/memo.pdf"
        ]
      },
      "finance_bill": {
        "url_patterns": [
          "/budget{fiscal_year}/doc/Finance_Bill.pdf",
          "/doc/Finance_Bill.pdf"
        ],
        "example_urls": [
          "https://www.indiabudget.gov.in/budget2024-25/doc/Finance_Bill.pdf",
          "https://www.indiabudget.gov.in/doc/Finance_Bill.pdf"
        ]
      },
      "budget_highlights": {
        "url_patterns": [
          "/doc/bh1.pdf",
          "/budget{fiscal_year}/doc/bh1.pdf"
        ],
        "example_urls": [
          "https://www.indiabudget.gov.in/doc/bh1.pdf",
          "https://www.indiabudget.gov.in/budget2025-26/doc/bh1.pdf"
        ]
      }
    }
  },
  "fallback_sources": [
    {
      "name": "PRS India",
      "base_url": "https://prsindia.org/budget",
      "type": "parliamentary_research"
    },
    {
      "name": "Ministry of Finance",
      "base_url": "https://finmin.gov.in",
      "type": "government_ministry"
    }
  ],
  "fetch_config": {
    "schedule": "0 8 1 2 *",
    "timezone": "Asia/Kolkata",
    "timeout_seconds": 30,
    "retry_attempts": 3,
    "retry_backoff_seconds": 5,
    "min_file_size_bytes": 1048576,
    "validate_pdf_magic": true
  }
}
```

---

## Database Schema (PostgreSQL)

```sql
-- Tax rules extracted from government documents
CREATE TABLE tax_rules (
  id SERIAL PRIMARY KEY,
  rule_id VARCHAR(100) UNIQUE,
  description TEXT,
  regime VARCHAR(20),  -- 'old', 'new', 'both'
  fiscal_year VARCHAR(10),  -- '2025-26'
  category VARCHAR(50),  -- 'deduction', 'exemption', 'rate', 'surcharge', 'rebate'
  amount DECIMAL(15,2),
  percentage DECIMAL(5,2),
  source_document VARCHAR(50),  -- 'Finance_Bill', 'Memorandum', 'Budget_Highlights'
  extraction_date TIMESTAMP,
  confidence_score DECIMAL(3,2),
  created_at TIMESTAMP DEFAULT NOW()
);

-- User calculations & history
CREATE TABLE user_calculations (
  id SERIAL PRIMARY KEY,
  user_id VARCHAR(100),  -- External user ID
  uploaded_document_ids TEXT[],  -- Array of doc IDs
  extracted_data JSONB,  -- Parsed salary data
  tax_old_regime DECIMAL(15,2),
  tax_new_regime DECIMAL(15,2),
  recommended_regime VARCHAR(10),
  calculation_breakdown JSONB,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP
);

-- Document uploads
CREATE TABLE document_uploads (
  id SERIAL PRIMARY KEY,
  upload_id VARCHAR(100) UNIQUE,
  user_id VARCHAR(100),
  filename VARCHAR(255),
  document_type VARCHAR(50),  -- 'form_16', 'salary_slip'
  file_path VARCHAR(500),
  extraction_status VARCHAR(20),  -- 'pending', 'success', 'failed'
  extracted_data JSONB,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Rule cache for monitoring
CREATE TABLE rule_cache (
  id SERIAL PRIMARY KEY,
  fiscal_year VARCHAR(10),
  last_extraction_date TIMESTAMP,
  total_rules_extracted INT,
  extraction_status VARCHAR(20),  -- 'success', 'partial', 'failed'
  error_message TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| **Claude API over other LLMs** | Strong at simplifying complex tax concepts; excellent context handling for multi-page documents; good pricing |
| **PostgreSQL over MongoDB** | Relational schema fits tax rules hierarchy; better for structured financial data; ACID compliance for audit trail |
| **APScheduler over Celery** | Simpler setup for single scheduled task; no separate message broker needed; easier to debug |
| **Tesseract OCR + PyPDF2** | Open-source; handles both text-based and scanned PDFs; no dependency on paid services |
| **Feb 1st automation** | Aligns with government document release schedule; reduces manual intervention; allows rule cache to update before tax season |
| **API-only architecture** | Flexibility for multiple frontend clients (web, mobile); stateless design scales easily |

---

## Success Criteria

### Document Fetching
- [ ] 3 PDFs download on Feb 1st annually
- [ ] File sizes > 1MB (non-empty)
- [ ] Files stored in `tax-docs/{fiscal_year}` with correct names

### Rule Extraction
- [ ] ≥10 rules extracted per regime from each PDF
- [ ] Rules include: deductions, exemptions, thresholds, surcharge rules
- [ ] Rules match official 2025-26 tax regime (spot-check 5 key rules)

### Tax Calculation
- [ ] Old Regime: Salary ₹10L + deductions ₹2L = tax ₹109K ±5%
- [ ] New Regime: Salary ₹10L = tax ₹92K ±5%
- [ ] §87A rebate: Income ≤₹5L returns ₹0 tax
- [ ] Surcharge: Income ₹50L+ applies surcharge correctly

### Document Processing
- [ ] Upload Form 16 → Extract salary, deductions
- [ ] Calculation matches manual verification ±2%
- [ ] Fallback to manual entry if OCR fails

### LLM Output
- [ ] Explanation < 200 words
- [ ] No jargon ("assessee", "basic salary" explained as "base pay")
- [ ] Includes breakdown, filing requirements, ways to reduce tax

### API
- [ ] All required fields present in response
- [ ] Error handling for invalid PDFs, missing fields
- [ ] Response time < 5 seconds per calculation

---

## Considerations & Open Questions

1. **Government Portal URLs & Scraping Strategy**
   - **Primary source:** https://www.indiabudget.gov.in
   - Official budget portal released annually on Feb 1st
   - Typical document paths:
     - Memorandum: `/budget/{FY}/Memo.pdf` (e.g., `/budget/2025-26/Memo.pdf`)
     - Finance Bill: `/budget/{FY}/Finance_Bill.pdf`
     - Budget Highlights: `/budget/{FY}/Highlights.pdf`
   - **Action needed:** 
     - Confirm exact URL patterns by checking Feb 2025, Feb 2024 releases
     - Test scraper against 2024-25 docs (already in `tax-docs/`)
     - Set up dynamic scraping if paths change year-to-year
   - **Fallback sources:**
     - PRS India (https://prsindia.org/budget)
     - Ministry of Finance (https://finmin.gov.in)
     - Parliament e-books (https://eparlib.nic.in)
   - **Recommendation:** Hardcode primary URL + fallback strategy; update config annually if paths drift

2. **Claude API Cost**
   - Rule extraction: ~1-2 API calls per year (low cost)
   - Per-user explanation: ~1 API call per calculation
   - Estimated cost: $5-20/month for 1000 users
   - Acceptable threshold?

3. **Form 16 Variability**
   - Should accept structured JSON upload for initial MVP?
   - OCR-based parsing as Phase 2?
   - Recommendation: Start with manual JSON; add OCR in Phase 2 after testing calculation engine

4. **Multi-Country Support**
   - India-only for MVP?
   - US/UK tax regimes in future?
   - Current plan: India only; restructure rule extraction for multi-country in Phase 3+

5. **User Authentication**
   - How should users be identified? (email, phone, external ID?)
   - Should we implement auth or assume external system provides user_id?
   - Recommendation: Accept user_id as header/query param; implement full auth in Phase 2

6. **Rule Versioning**
   - Should old rules (2024-25, 2023-24) be queryable?
   - Archive strategy?
   - Recommendation: Keep all historical rules; tag with fiscal_year; query by year

---

## Next Steps

1. **Test URL patterns with existing PDFs** (HIGH PRIORITY)
   - Verify fiscal year format: e.g., "2024-25" (with hyphen, not underscore)
   - Test with existing PDFs in `tax-docs/2024-25/` and `tax-docs/2025-26/`
   - Confirm file size and accessibility for each URL pattern
   - Test fallback URLs if primary returns 404
   - Create scraper test script locally

2. Set up Python/FastAPI project structure
3. Begin Phase 1 implementation (document fetching setup)
4. Validate tax calculation logic against known scenarios
5. Set up CI/CD pipeline for automated testing on Feb 1st
