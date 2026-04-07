# Tax Agent Backend - Phase 1

## Overview

This is Phase 1 of the Tax Agent implementation. It focuses on project setup, database configuration, and automated document fetching from indiabudget.gov.in.

## Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app
│   └── config.py               # Configuration settings
├── models/
│   ├── __init__.py
│   └── database.py             # SQLAlchemy models
├── services/
│   ├── __init__.py
│   └── document_fetcher.py     # Document fetching service
├── config/
│   └── government_sources.json # Government document URLs
├── scheduler.py                # APScheduler configuration
├── requirements.txt            # Python dependencies
├── .env.example               # Environment variables template
└── README.md                  # This file
```

## Setup Instructions

### 1. Create Virtual Environment

```bash
cd backend
python -m venv venv

# Activate (Windows)
venv\Scripts\activate
# Or (Linux/Mac)
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your database URL and API keys
```

### 4. Setup Database

PostgreSQL must be installed and running.

```sql
-- Create database
CREATE DATABASE tax_agent_db;

-- Create user (optional)
CREATE USER tax_user WITH PASSWORD 'tax_password';
ALTER ROLE tax_user SET client_encoding TO 'utf8';
ALTER ROLE tax_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE tax_user SET default_transaction_deferrable TO off;
ALTER ROLE tax_user SET default_timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE tax_agent_db TO tax_user;
```

### 5. Initialize Database Tables

```bash
python -c "from models.database import init_db; init_db()"
```

### 6. Run the Application

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Application will be available at: http://localhost:8000

## API Endpoints

### Health Check
- **GET** `/health` - Health status of the application

### Admin Endpoints (Testing)
- **POST** `/admin/fetch-documents?fiscal_year=2024-25` - Manually trigger document fetch
- **GET** `/admin/database-status` - Check database connection and table counts
- **POST** `/admin/extract-rules?fiscal_year=2024-25` - Extract tax rules from documents using LLM

## Configuration

### Environment Variables

Edit `.env` file:

```env
# Database
DATABASE_URL=your_db_url_here

# Anthropic API (for Phase 2)
ANTHROPIC_API_KEY=your_api_key_here

# Document storage
DOCUMENTS_STORAGE_PATH=./tax-docs
TEMP_UPLOAD_PATH=./temp_uploads

# Scheduler
SCHEDULER_TIMEZONE=Asia/Kolkata
```

### Government Sources

Edit `config/government_sources.json` to configure:
- Primary source URLs for memorandum, finance bill, budget highlights
- Fallback sources
- Fetch configuration (timeout, retries, file size validation)

## Document Fetching

### Automatic Scheduling

The system automatically fetches documents on **February 1st at 08:00 AM IST** for the new fiscal year.

### Manual Trigger

For testing, manually fetch documents:

```bash
curl -X POST "http://localhost:8000/admin/fetch-documents?fiscal_year=2024-25"
```

### Document Structure

Downloaded documents are stored in:

```
tax-docs/
├── 2024-25/
│   ├── memo_20260229_140530.pdf
│   ├── Finance_Bill_20260229_140545.pdf
│   └── bh1_20260229_140600.pdf
├── 2025-26/
│   └── ...
└── 2026-27/
    └── ...
```

Each file is timestamped to preserve versions.

## Database Tables

### TaxRules
Stores extracted tax rules from government documents

### UserCalculations
Stores user tax calculation history

### DocumentUpload
Logs uploaded user documents (Form 16, salary slips)

### RuleCache
Metadata about rule extraction status

### DocumentFetchLog
Log of all document fetching attempts

## Logging

Logs are output to console with configurable level (INFO, DEBUG, ERROR, etc.)

Configure in `.env`:
```env
LOG_LEVEL=INFO
```

## Troubleshooting

### Database Connection Error

Ensure PostgreSQL is running and DATABASE_URL is correct:

```bash
psql postgresql://tax_user:tax_password@localhost:5432/tax_agent_db
```

### Document Fetch Failing

- Check internet connection
- Verify URLs in `config/government_sources.json`
- Check logs for specific error messages
- Manually test URLs in browser:
  - https://www.indiabudget.gov.in/budget2024-25/doc/memo.pdf
  - https://www.indiabudget.gov.in/budget2024-25/doc/Finance_Bill.pdf
  - https://www.indiabudget.gov.in/doc/bh1.pdf

### APScheduler Not Running

Check that scheduler started in application logs. If needed, restart the application.

## Next Steps

Phase 2 will focus on:
- PDF processing and text extraction
- LLM-powered tax rule extraction using Claude API
- Rule storage and caching in database

Phase 3 will implement:
- User document upload and parsing
- Tax calculation engine
- API endpoints for tax calculations
