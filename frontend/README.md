# RuPi — Your Every Rupee Counts

AI-powered personal finance platform with multi-agent architecture for tax automation, investment management, and document security.

## Run Locally

1. Start FastAPI backend from repository root:

```bash
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

2. Serve this frontend folder with any static server (example with Python):

```bash
cd frontend
python -m http.server 5500
```

3. Open:

- Frontend: `http://localhost:5500`
- FastAPI: `http://localhost:8000`

## API Base URL

Auth/profile pages default to `http://localhost:8000` and can be overridden by setting `window.RUPI_API_BASE`.

## Notes

- Legacy Node/Express backend has been removed from this folder.
- API endpoints are now served by FastAPI.
