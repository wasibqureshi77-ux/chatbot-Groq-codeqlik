# AI Chatbot, Voicebot, and Admin Panel

This project is a complete business chatbot system. It has:

- A chatbot for website visitors
- Voice input and voice reply support
- Admin panel for chats, leads, support tickets, hiring, meetings, and knowledge sources
- MongoDB database storage
- RAG knowledge base support
- Meeting booking flow with fixed options and booked-slot protection

The project has two main parts:

- `backend`: FastAPI server, chatbot logic, database, voice service, admin APIs
- `frontend`: React app for chatbot page and admin panel

## Documentation Files

There are three README files:

- `README.md`: complete project overview
- `backend/README.md`: backend setup and backend explanation
- `frontend/README.md`: frontend setup and frontend explanation

## Project Structure

```text
chatbot-openai-voicebot/
  backend/
    main.py
    chatbot_graph.py
    database.py
    voice_service.py
    requirements.txt
    rag/
    services/
    dist/
  frontend/
    src/
    package.json
    vite.config.js
  tests/
  README.md
```

## Main Features

### Chatbot

The chatbot can answer company questions and collect user details for:

- Client leads
- Customer support
- Hiring/application requests
- Meeting booking

### Voicebot

The user can record audio. The backend converts audio to WAV, transcribes it, sends it through the chatbot, then generates a voice reply.

### Admin Panel

The admin panel shows:

- Dashboard numbers
- Chat history
- Leads
- Support tickets
- Hiring candidates
- Meetings
- Knowledge sources
- LLM usage analytics

### Knowledge Base

Admin can add knowledge from:

- Manual text
- Uploaded files
- Website content
- Database sources

The chatbot can use this content while answering.

## Quick Start

### 1. Backend

Open a terminal:

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

Backend runs on:

```text
http://127.0.0.1:8000
```

### 2. Frontend

Open another terminal:

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on:

```text
http://localhost:5173
```

## Environment Variables

Create `backend/.env` and add values like:

```env
API_KEY_1=your_llm_api_key
API_KEY_2=optional_backup_llm_api_key
GROQ_API_KEY=optional_preferred_groq_key_for_voice_stt
GROQ_STT_MODEL=whisper-large-v3-turbo
MONGO_URI=your_mongodb_connection_string
MONGO_DB=company_chatbot
JWT_SECRET=change_this_secret
ALLOWED_ORIGINS=http://localhost:5173
CHAT_RATE_LIMIT_PER_MIN=15

SMTP_ENABLED=false
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@example.com
SMTP_PASSWORD=your_app_password
MAIL_FROM=no-reply@example.com
ADMIN_NOTIFY_EMAIL=admin@example.com
```

Do not commit real API keys, database passwords, or email passwords.

## Common URLs

```text
GET  /                         Backend health check
POST /api/chat                 Chatbot message API
POST /api/voice/process        Voicebot API
GET  /api/public/settings      Public chatbot/widget settings
POST /api/admin/login          Admin login
GET  /api/admin/dashboard      Admin dashboard data
GET  /api/admin/chats          Chat list
GET  /api/admin/leads          Lead list
GET  /api/admin/meetings       Meeting list
```

## Build Frontend

```bash
cd frontend
npm run build
```

This creates production files inside `frontend/dist`.

## Embedded Widget

The backend also serves widget files from:

```text
backend/dist
```

A website can load the widget script and call `CodeQlikChat.init(...)`.

## Important Notes

- Run backend before frontend, because frontend API calls proxy to `http://127.0.0.1:8000`.
- MongoDB must be reachable for chats, leads, support, meetings, and settings.
- Voice STT uses Groq `whisper-large-v3-turbo` when a Groq key is configured, with local fallback.
- Voice conversion works best when `ffmpeg` is installed.
- The backend also has PyAV fallback for audio conversion.
- Meeting booking slots are protected so the same active slot cannot be booked twice.

## More Details

Read these files:

- `backend/README.md`
- `frontend/README.md`
