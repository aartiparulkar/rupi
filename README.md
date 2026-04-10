# RuPi - AI-Powered Personal Finance & Tax Agent

A multi-agent platform for tax automation, investment guidance, and financial security analysis. Powered by FastAPI backend and LangChain AI agents.

## 📋 Project Overview

RuPi provides three specialized agents:
- **Tax Agent**: Calculates income tax, suggests deductions, compares regimes
- **Investment Agent**: Provides investment guidance based on financial profile
- **Security Agent**: Offers security best practices and financial protection strategies

Features:
- OTP-based email authentication (Supabase Auth)
- AI-powered tax calculations with regime comparison
- PDF document parsing and rule extraction
- User profile management
- Conversational tax guidance
- RESTful API with JWT tokens


## 🚀 Setup & Installation

### Prerequisites
- Python 3.12+
- Node.js (optional, for frontend development)
- Supabase account (free tier available at https://supabase.com)
- OpenAI API key (for LLM features)

### Step 1: Clone & Navigate

```bash
git clone <repository-url>
cd rupi
```

### Step 2: Backend Setup

#### 2a. Create Python Virtual Environment

```bash
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (Linux/macOS)
source .venv/bin/activate
```

#### 2b. Install Dependencies

```bash
pip install -r requirements.txt
```
pip install -qU  langchain-chroma
pip install -qU  langchain-huggingface
pip install sentence-transformers

#### 2c. Configure Environment

```bash
# Copy template to actual environment file
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# ── Database (Supabase PostgreSQL) ──
DATABASE_URL=postgresql://postgres.PROJECT_ID:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres

# ── Supabase ──
SUPABASE_URL=https://your-project.supabase.co
SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...  # Get from Supabase Settings > API

# ── API Keys ──
OPENAI_API_KEY=sk-proj-xxxxx...  # Get from OpenAI Dashboard

# ── Authentication ──
JWT_SECRET_KEY=your-very-secret-key-min-32-chars-change-in-production
JWT_EXPIRATION_HOURS=24

# ── Application ──
DEBUG=false
ENVIRONMENT=production
LOG_LEVEL=INFO
```

**How to get Supabase credentials:**
1. Sign up at https://supabase.com
2. Create a new project
3. Navigate to **Settings > Database**
4. Copy the **connection string** (or construct from host/port/user/password) → `DATABASE_URL`
5. Navigate to **Settings > API**
6. Copy the **Project URL** → `SUPABASE_URL`
7. Copy the **Service Role Secret** → `SERVICE_ROLE_KEY`
8. Enable **Email OTP** in Authentication > Email

#### 2d. Run Backend

```bash
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Backend runs at: **`http://127.0.0.1:8000`**

### Step 3: Frontend Setup

#### 3a. Serve Frontend (Python)

```bash
# From project root
cd frontend
python -m http.server 5500
```

Frontend runs at: **`http://localhost:5500`**

#### 3b. Configure Frontend API Base (Optional)

By default, frontend points to `http://127.0.0.1:8000`. To override, add before page load:

```javascript
window.RUPI_API_BASE = "http://your-custom-backend:8000";
```

## 📡 API Endpoints

### Authentication Routes (`/api/auth/*`)
- `POST /api/auth/register` - Signup with email, name, password
- `POST /api/auth/login` - Login with email (triggers OTP)
- `POST /api/auth/send-otp` - Resend OTP to email
- `POST /api/auth/verify-otp` - Verify OTP, return JWT token
- `GET /api/auth/me` - Get current user profile (requires JWT)
- `DELETE /api/auth/delete` - Delete account (requires JWT)

### Tax Calculation Routes (`/api/calculations/*`)
- `POST /api/calculations/old-regime` - Calculate old regime tax
- `POST /api/calculations/new-regime` - Calculate new regime tax
- `POST /api/calculations/compare` - Compare both regimes

### Chat Routes (`/api/chat/*`)
- `POST /api/chat/tax` - Send message to tax agent
- `POST /api/chat/investment` - Send message to investment agent
- `POST /api/chat/security` - Send message to security agent

### Document Routes (`/api/documents/*`)
- `POST /api/documents/upload` - Upload tax document (Form 16, etc.)
- `GET /api/documents/list` - List user's documents

## 🔐 Authentication Flow

1. **Signup/Login**: User enters email
2. **OTP Sent**: Backend sends 6-digit code via Supabase Auth email
3. **Verification**: User enters OTP
4. **Token Returned**: Backend returns JWT + user profile
5. **Stored Locally**: Frontend saves token in `localStorage`
6. **API Access**: Include token in header: `Authorization: Bearer <token>`

## ⚙️ Configuration Reference

### Environment Variables

| Variable | Required | Type | Default | Description |
|----------|----------|------|---------|-------------|
| `DATABASE_URL` | Yes | string | - | Supabase PostgreSQL connection string (get from Settings > Database) |
| `SUPABASE_URL` | Yes | string | - | Supabase project URL |
| `SERVICE_ROLE_KEY` | Yes | string | - | Supabase service role key |
| `OPENAI_API_KEY` | Yes | string | - | OpenAI API key |
| `JWT_SECRET_KEY` | Yes | string | - | Signing key (min 32 chars) |
| `DEBUG` | No | bool | false | Enable debug logging |
| `LOG_LEVEL` | No | string | INFO | Logging level |
| `SCHEDULER_TIMEZONE` | No | string | Asia/Kolkata | Timezone for jobs |

### Tax Configuration Files

- **`backend/config/tax_slabs.json`**: Tax brackets, deductions, rates
- **`backend/config/government_sources.json`**: Document source URLs

## ️ Development

### Running Both Backend & Frontend

**Terminal 1: Backend**
```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Terminal 2: Frontend**
```bash
cd frontend
python -m http.server 5500
```

Then open: **`http://localhost:5500`**

### Backend Debugging

Enable debug logging:
```env
DEBUG=true
LOG_LEVEL=DEBUG
```

Check backend logs in the terminal where uvicorn is running.

### Frontend Debugging

Open browser DevTools (F12) and check:
- Network tab for API calls
- Console tab for JavaScript errors
- Application tab for localStorage tokens

## 🐛 Troubleshooting

### OTP Email Not Arriving
1. Check that **Email OTP is enabled** in Supabase > Authentication > Email
2. Verify `SERVICE_ROLE_KEY` is correct in `.env`
3. Check email spam folder
4. Ensure Supabase email provider is configured (free tier uses Supabase's email)

### Backend Connection Error (localhost)
1. Ensure backend is running: `uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000`
2. Check that port 8000 is not in use: `lsof -i :8000` (macOS/Linux)
3. Verify `SUPABASE_URL` and `SERVICE_ROLE_KEY` are set correctly

### Database Connection Error
1. Verify Supabase project is active and not paused
2. Check `DATABASE_URL` is correct (from Supabase Settings > Database)
3. Ensure connection string includes correct password and region

### JWT Token Invalid
1. Ensure `JWT_SECRET_KEY` is set and consistent across restarts
2. Token expires after `JWT_EXPIRATION_HOURS` (default: 24)
3. On logout, browser should clear `localStorage` of `rupi_token`


## 📚 Key Technologies

- **Backend**: FastAPI, SQLAlchemy, LangChain
- **Database**: PostgreSQL (via Supabase)
- **Authentication**: Supabase Auth (OTP via email)
- **AI/LLM**: OpenAI GPT-4o-mini
- **Frontend**: HTML5, Vanilla JavaScript, Bootstrap CSS
- **File Storage**: Supabase Storage

## 🤝 Contributing

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Make changes and commit: `git commit -m "Add feature"`
3. Push to branch: `git push origin feature/your-feature`
4. Create Pull Request with description

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## ❓ Support

For issues and questions:
- Check existing GitHub Issues
- Review logs in backend terminal / browser console
- Verify all environment variables are set
- Ensure Supabase project is properly configured

---
