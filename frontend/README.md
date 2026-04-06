# RuPi — Your Every Rupee Counts

AI-powered personal finance platform with multi-agent architecture for tax automation, investment management, and document security.

---

## 🚀 Quick Start with Docker (Recommended for Demo)

For final-year project evaluations and team demonstrations, Docker provides the most stable environment.

### 1. Clone the Repository
```bash
git clone https://github.com/your-org/rupi-ui.git
cd rupi-ui/rupi
```

### 2. Configure Environment
```bash
cp .env.example .env
# Open .env and set JWT_SECRET and SESSION_SECRET to secure random strings
```

### 3. Start Infrastructure
```bash
# Starts the backend, frontend, and MongoDB services securely
docker compose up -d

# To launch with Mongo Express GUI (for examiners/reviewers)
docker compose --profile dev up -d
```

| Service | Access URL |
|---|---|
| RuPi Dashboard | `http://localhost:5000` |
| Mongo Express GUI | `http://localhost:8081` (Credentials: `admin` / `rupi2026`) |
| MongoDB Internal | `mongodb://localhost:27017` |

To stop the environment after your demo:
```bash
docker compose down      # Stops gracefully (data persists)
docker compose down -v   # Stops and wipes the database clean
```

---

## 💻 Local Development (No Docker)

If you are running the project directly on your machine without Docker for active development:

### 1. Install Dependencies
Make sure you have Node.js (v18+) installed.
```bash
npm install
```

### 2. Configure Environment variables
```bash
cp .env.example .env
```
Ensure your locally running MongoDB instance URL is provided:
`MONGODB_URI=mongodb://localhost:27017/rupi`

### 3. Start the Development Server
```bash
npm run dev
```
The server will boot up and be accessible at `http://localhost:5000`.

*Note: Since this is a vanilla HTML/CSS/JS frontend served by an Express backend, there is no separate frontend build step. The frontend assets are served statically from the root directories.*

---

## 🗄️ Team Shared Database

**Option A — MongoDB Atlas (best for remote teams)**
1. Create free cluster at mongodb.com/atlas
2. Get connection string, update `.env` for each team member:
   ```
   MONGODB_URI=mongodb+srv://<user>:<pass>@cluster0.xxxxx.mongodb.net/rupi
   ```

**Option B — Docker on one machine**
One person runs `docker compose up`, others point `MONGODB_URI` to their IP.

---

## Google OAuth Setup

To enable Google Sign-In:

1. Go to https://console.cloud.google.com
2. Create or select a project
3. Navigate to **APIs & Services → Credentials**
4. Click **Create Credentials → OAuth 2.0 Client ID**
5. Application type: **Web application**
6. Add Authorized JavaScript origins: `http://localhost:5000`
7. Add Authorized redirect URIs: `http://localhost:5000/api/auth/google/callback`
8. Copy the **Client ID** and **Client Secret**
9. Add them to your `.env` file:
```env
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret
```

10. Also paste the Client ID into the Google SDK script in `login.html` and `signup.html`:
```js
client_id: 'YOUR_CLIENT_ID_HERE'
```

## Demo OTP Flow

During a demo, when a user registers or logs in:

1. The server terminal will print the OTP like this:
```
   🔐 OTP for user@example.com: 847291  (valid 5 minutes)
```
2. Type that code into the OTP input box on screen
3. Click Verify & Continue

No email gateway or SMS service is required.

---

## API Reference

### Auth
| Method | Endpoint | Body / Notes |
|---|---|---|
| POST | `/api/auth/register` | `{firstName, lastName, email, password}` |
| POST | `/api/auth/login` | `{email, password}` |
| GET | `/api/auth/google` | Starts OAuth flow |
| GET | `/api/auth/me` | JWT required |
| DELETE | `/api/auth/delete` | JWT required |

### User (JWT required)
| Method | Endpoint | Notes |
|---|---|---|
| GET | `/api/user/profile` | Full profile |
| PUT | `/api/user/profile` | Update any profile fields |
| POST | `/api/user/documents` | Multipart file upload |
| GET | `/api/user/documents` | List documents |
| DELETE | `/api/user/documents/:id` | Delete document |

### Chat (JWT required)
| Method | Endpoint | Notes |
|---|---|---|
| GET | `/api/chat/history` | All sessions |
| POST | `/api/chat/session` | New session `{agent, messages, preview}` |
| PUT | `/api/chat/session/:id` | Append messages |
| DELETE | `/api/chat/session/:id` | Delete session |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | HTML / CSS / JS |
| Backend | Node.js + Express |
| Database | MongoDB + Mongoose |
| Auth | JWT + Passport (Google OAuth 2.0) |
| File uploads | Multer |
| Containerisation | Docker + Docker Compose |
| DB GUI | Mongo Express |

---

## Team
Vibhasha Nagvekar · Aarti Parulkar · Zaineb Patel · Sakshi Patil

*Your every rupee counts.*
