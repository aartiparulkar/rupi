# RuPi — Your Every Rupee Counts

AI-powered personal finance platform with multi-agent architecture for tax automation, investment management, and document security.

## Run Locally

1. python -m venv venv


2. venv\Scripts\activate

3. Start FastAPI backend from repository root:

```bash
uvicorn backend.app.main:app --reload
```

4. Serve this frontend folder with any static server (example with Python):

```bash
cd frontend
python -m http.server 5500
```

5. Open:

- Frontend: `http://localhost:5500`
- FastAPI: `http://localhost:8000`

## API Base URL

Auth/profile pages default to `http://localhost:8000` and can be overridden by setting `window.RUPI_API_BASE`.


The `backend/services/chat_service.py` has dummy functions generate_investment_agent_response and generate_security_agent_response. Edit them according to their own logic.