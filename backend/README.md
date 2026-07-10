# Backend README

This is the backend for the AI chatbot system. It is built with FastAPI.

The backend handles:

- Chatbot API
- Admin APIs
- MongoDB database
- Chat and lead saving
- Meeting booking
- RAG knowledge base
- Email notifications
- LLM usage logging

## Main Backend Files

```text
backend/
  main.py                  FastAPI app and API routes
  chatbot_graph.py         Chatbot flow, field collection, LLM response logic
  database.py              MongoDB collections and save helpers
  llm_client.py            LLM client with API key failover and usage logging
  widget_suggestions.py    Dynamic widget suggestion generation
  email_body_generator.py  Email content generation
  mail_service.py          Mail sending helpers
  admin.py                 Admin user setup helper
  requirements.txt         Python dependencies
  rag/                     Knowledge base loading, chunking, retrieval
  services/                Extra backend services
  dist/                    Widget JavaScript served by backend
  temp_uploads/            Temporary uploaded files
```

## Setup

### 1. Go to backend folder

```bash
cd backend
```

### 2. Create virtual environment

Windows:

```bash
python -m venv venv
venv\Scripts\activate
```

macOS/Linux:

```bash
python -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create `.env`

Create this file:

```text
backend/.env
```

Example:

```env
API_KEY_1=your_llm_api_key
API_KEY_2=optional_backup_llm_api_key
MONGO_URI=your_mongodb_connection_string
MONGO_DB=company_chatbot

JWT_SECRET=change_this_secret
JWT_EXPIRE_MINUTES=1440
ALLOWED_ORIGINS=http://localhost:5173
CHAT_RATE_LIMIT_PER_MIN=15

SMTP_ENABLED=false
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@example.com
SMTP_PASSWORD=your_app_password
MAIL_FROM=no-reply@example.com
ADMIN_NOTIFY_EMAIL=admin@example.com

LANGCHAIN_API_KEY=optional_langsmith_key
LANGCHAIN_PROJECT=company_chatbot
```

Keep real secrets private.

## Run Backend

From the `backend` folder:

```bash
uvicorn main:app --reload
```

Backend URL:

```text
http://127.0.0.1:8000
```

Health check:

```text
http://127.0.0.1:8000/
```

## Admin User

The backend has an `admin.py` helper. Use it to create or update admin login data.

Example:

```bash
python admin.py
```

If the file supports arguments in your local version, use:

```bash
python admin.py --help
```

## Important API Routes

### Public/chat routes

```text
GET  /                         Health check
POST /api/chat                 Send text message to chatbot
POST /api/widget/suggestions   Get dynamic widget suggestions
GET  /api/public/settings      Public chatbot settings
GET  /api/settings             Settings
PUT  /api/settings             Update settings
```

### Admin routes

```text
POST   /api/admin/login
POST   /api/admin/change-password
GET    /api/admin/dashboard
GET    /api/admin/chats
GET    /api/admin/chats/{thread_id}
GET    /api/admin/leads
PUT    /api/admin/leads/{id}/status
GET    /api/admin/support
PUT    /api/admin/support/{id}/status
GET    /api/admin/hiring
PUT    /api/admin/hiring/{id}/status
GET    /api/admin/meetings
PUT    /api/admin/meetings/{meeting_id}/status
GET    /api/admin/knowledge
POST   /api/admin/knowledge
PUT    /api/admin/knowledge/{id}
DELETE /api/admin/knowledge/{id}
POST   /api/admin/knowledge/upload
POST   /api/admin/sources/database
POST   /api/admin/sources/website
PUT    /api/admin/knowledge/{id}/enable
PUT    /api/admin/knowledge/{id}/disable
POST   /api/admin/knowledge/{id}/reindex
GET    /api/admin/knowledge/sync-status
```

### Analytics routes

```text
GET /api/admin/analytics/llm-usage/summary
GET /api/admin/analytics/llm-usage/by-model
GET /api/admin/analytics/llm-usage/daily
GET /api/admin/analytics/llm-usage/recent
```

## How Chatbot Works

The main chatbot logic is in:

```text
chatbot_graph.py
```

It does these steps:

1. Reads the latest user message.
2. Detects intent.
3. Starts or continues the correct collection flow.
4. Extracts data from the user message.
5. Saves completed data to MongoDB.
6. Uses RAG if company knowledge is needed.
7. Generates a response using the LLM.

Supported flows:

- `client_lead`
- `customer_support`
- `hiring_support`
- `meeting_booking`
- `company_info`
- `general_chat`
- `unrelated_query`

## Field Collection

The chatbot collects required fields one by one.

Example for meeting booking:

```text
name
email
phone
company
work_details
meeting_mode
date
time_slot
```

The wording of field questions can be generated dynamically by the LLM, while the backend still controls the correct field order.

## Meeting Booking Logic

Meeting booking saves data in the `meetings` collection.

Important behavior:

- Fixed options are used for meeting mode and time slot.
- Already booked active slots are hidden.
- Same active date and time slot cannot be booked twice.
- Cancelled, completed, and reschedule-needed meetings can free the slot.

## RAG Knowledge Base

RAG files are in:

```text
backend/rag/
```

Simple explanation:

- Loader reads source content.
- Chunker splits content into smaller pieces.
- Embeddings convert chunks into searchable vectors.
- Retriever finds the best matching chunks for a user question.
- Chatbot uses those chunks to answer better.

## Database Collections

MongoDB collections used by the backend include:

```text
chats
client_leads
support_tickets
hiring_candidates
meetings
knowledge_sources
knowledge_chunks
chatbot_settings
admin_users
llm_usage_logs
```

## Email

Email settings come from `.env`.

Set:

```env
SMTP_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@example.com
SMTP_PASSWORD=your_app_password
ADMIN_NOTIFY_EMAIL=admin@example.com
```

Set `SMTP_ENABLED=false` if you do not want email sending.

## Useful Commands

Run backend:

```bash
uvicorn main:app --reload
```

Run backend on a specific port:

```bash
uvicorn main:app --reload --port 8000
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Troubleshooting

### API key missing

Check `.env`:

```env
API_KEY_1=your_llm_api_key
```

### MongoDB connection issue

Check:

```env
MONGO_URI=your_mongodb_connection_string
MONGO_DB=company_chatbot
```

Also make sure your IP is allowed in MongoDB Atlas.

### Frontend cannot call backend

Make sure backend runs on:

```text
http://127.0.0.1:8000
```

Also check `ALLOWED_ORIGINS`.

### Python not found

Install Python and make sure it is available in terminal:

```bash
python --version
```
