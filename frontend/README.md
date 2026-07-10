# Frontend README

This is the frontend for the chatbot system. It is built with React and Vite.

The frontend contains:

- Website home page
- Chatbot page
- Admin login page
- Admin dashboard
- Chat, leads, support, hiring, meetings, and knowledge management UI

## Main Frontend Files

```text
frontend/
  index.html
  package.json
  vite.config.js
  src/
    main.jsx
    App.jsx
    App.css
    api.js
    components/
      ProtectedRoute.jsx
    pages/
      home.jsx
      Chatbot.jsx
      AdminLogin.jsx
      Admin.jsx
  dist/
```

## Setup

### 1. Go to frontend folder

```bash
cd frontend
```

### 2. Install packages

```bash
npm install
```

### 3. Run frontend

```bash
npm run dev
```

Frontend URL:

```text
http://localhost:5173
```

## Backend Requirement

The frontend calls backend APIs. Start backend first:

```bash
cd backend
uvicorn main:app --reload
```

Backend should run on:

```text
http://127.0.0.1:8000
```

## Vite Proxy

The file `vite.config.js` sends API calls to backend:

```text
/api  -> http://127.0.0.1:8000
/dist -> http://127.0.0.1:8000
```

This means frontend can call `/api/chat`, and Vite will forward it to backend during development.

## Pages

### `home.jsx`

Simple home page.

### `Chatbot.jsx`

Main chatbot page.

It supports:

- Text messages
- Bot replies
- Fixed option buttons
- Dynamic field collection
- Meeting booking options

### `AdminLogin.jsx`

Admin login page.

It sends login request to:

```text
POST /api/admin/login
```

The returned token is saved in session storage.

### `Admin.jsx`

Main admin panel.

It includes:

- Dashboard
- Chat history
- Leads
- Support tickets
- Hiring candidates
- Meetings
- Knowledge base
- Settings
- LLM usage analytics

### `ProtectedRoute.jsx`

Protects admin pages. If token is missing, user is sent to login page.

## API Helper

`src/api.js` stores API helper code used by frontend.

Admin requests include the token:

```text
Authorization: Bearer <token>
```

## Chatbot Flow in Frontend

Simple flow:

1. User types a message.
2. Frontend sends request to backend.
3. Backend returns reply, intent, profile, and fixed options.
4. Frontend shows bot reply.
5. If fixed options exist, frontend shows clickable buttons inside the bot message.

Text chat API:

```text
POST /api/chat
```

## Admin Panel Data

Admin panel uses these backend APIs:

```text
GET /api/admin/dashboard
GET /api/admin/chats
GET /api/admin/leads
GET /api/admin/support
GET /api/admin/hiring
GET /api/admin/meetings
GET /api/admin/knowledge
GET /api/admin/analytics/llm-usage/summary
```

## Build for Production

```bash
npm run build
```

Output folder:

```text
frontend/dist
```

## Preview Production Build

```bash
npm run preview
```

## Styling

Main styling is in:

```text
src/App.css
```

Some components also use inline styles.

## Common Problems

### Frontend opens but chatbot does not reply

Check backend is running:

```text
http://127.0.0.1:8000
```

### Admin login fails

Check:

- Admin user exists in backend database
- Backend is running
- Token is not expired
- Correct username and password are used

### API request blocked by CORS

Add frontend origin in backend `.env`:

```env
ALLOWED_ORIGINS=http://localhost:5173
```

### Changes not visible

Restart Vite:

```bash
npm run dev
```

Or rebuild:

```bash
npm run build
```
