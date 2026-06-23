from fastapi import FastAPI, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect, Request, Depends, status
from fastapi.security import OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
from bson import ObjectId
import os
import shutil
import logging
import time
import threading
from collections import defaultdict
from jose import jwt, JWTError
import bcrypt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/admin/login")

JWT_SECRET = os.getenv("JWT_SECRET", "supersecretkey_for_jwt_auth_12345")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Check if hash is valid bcrypt hash, else fail
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt

def require_admin(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        # Confirm the user still exists in the DB
        from database import get_admin_user
        if get_admin_user(username) is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return username

class LoginRequest(BaseModel):
    username: str
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    new_username: str = None  # optional: rename the admin at the same time


# Setup logger
logger = logging.getLogger("backend_main")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[Backend] %(levelname)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

class RateLimiter:
    def __init__(self, requests_per_minute: int = 15):
        self.requests_per_minute = requests_per_minute
        self.requests = defaultdict(list)
        self.lock = threading.Lock()

    def is_rate_limited(self, key: str) -> bool:
        now = time.time()
        with self.lock:
            self.requests[key] = [t for t in self.requests[key] if now - t < 60]
            if len(self.requests[key]) >= self.requests_per_minute:
                return True
            self.requests[key].append(now)
            return False

# Initialize rate limiter from environment variable
chat_rate_limit = int(os.getenv("CHAT_RATE_LIMIT_PER_MIN", "15"))
rate_limiter = RateLimiter(chat_rate_limit)

from chatbot_graph import send_message
from database import (
    chats_collection,
    leads_collection,
    support_collection,
    hiring_collection,
    knowledge_sources_collection,
    knowledge_chunks_collection,
    settings_collection,
    get_chatbot_settings,
    update_chatbot_settings,
    DEFAULT_SETTINGS,
    serialize_doc,
    serialize_many,
    get_profile_value,
    extract_display_name,
    format_chat_summary,
    format_thread_messages,
    format_lead,
    format_support_ticket,
    format_hiring_candidate
)
# Local aliases for compatibility
sources_collection = knowledge_sources_collection
chunks_collection = knowledge_chunks_collection

from realtime import manager
import asyncio

app = FastAPI(title="Enterprise AI Support Platform API")

from pathlib import Path
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
WIDGET_DIST_DIR = BASE_DIR / "dist"

app.mount("/dist", StaticFiles(directory=str(WIDGET_DIST_DIR)), name="dist")

@app.on_event("startup")
async def startup_event():
    manager.loop = asyncio.get_running_loop()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    thread_id: str


from typing import List, Optional

class SettingsUpdate(BaseModel):
    # Support both snake_case and camelCase in update payload
    company_name: Optional[str] = None
    company_description: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    chatbot_greeting: Optional[str] = None
    fallback_message: Optional[str] = None
    support_email: Optional[str] = None
    support_phone: Optional[str] = None

    companyName: Optional[str] = None
    companyDescription: Optional[str] = None
    fallbackMessage: Optional[str] = None
    generalEmail: Optional[str] = None
    generalPhone: Optional[str] = None
    supportEmail: Optional[str] = None
    supportPhone: Optional[str] = None

    title: Optional[str] = None
    subtitle: Optional[str] = None
    welcomeMessage: Optional[str] = None
    placeholder: Optional[str] = None
    primaryColor: Optional[str] = None
    theme: Optional[str] = None
    position: Optional[str] = None
    width: Optional[str] = None
    height: Optional[str] = None
    logoUrl: Optional[str] = None
    botAvatar: Optional[str] = None
    launcherIcon: Optional[str] = None
    launcherText: Optional[str] = None
    showNewChat: Optional[bool] = None
    footerText: Optional[str] = None
    suggestions: Optional[List[str]] = None
    storage: Optional[str] = None



class ManualSourceCreate(BaseModel):
    title: str
    category: str
    content: str
    intent_scope: str = None
    topic: str = None
    service: str = None
    tags: str = None


class ManualSourceUpdate(BaseModel):
    title: str = None
    category: str = None
    content: str = None
    enabled: bool = None
    intent_scope: str = None
    topic: str = None
    service: str = None
    tags: str = None


class DatabaseConnectionRequest(BaseModel):
    connection_name: str
    db_type: str
    connection_string: str
    db_name: str
    target_collection: str
    category: str = "Company Information"
    intent_scope: str = None
    topic: str = None
    service: str = None
    tags: str = None


class WebsiteSourceRequest(BaseModel):
    url: str
    category: str = "Company Information"
    intent_scope: str = None
    topic: str = None
    service: str = None
    tags: str = None


class StatusUpdate(BaseModel):
    status: str


class SupportStatusUpdate(BaseModel):
    status: str = None
    priority: str = None


def clean_mongo_doc(doc):
    if doc:
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
    return doc


@app.get("/")
def home():
    return {
        "message": "Enterprise AI Support Platform API is running"
    }


# REAL-TIME BROADCAST websocket ENDPOINT

@app.websocket("/ws/admin")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Maintain active connection
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


# CHATBOT API

@app.post("/api/admin/login")
def login_admin(request: LoginRequest):
    from database import get_admin_user
    admin_user = get_admin_user(request.username)
    if admin_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not verify_password(request.password, admin_user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=JWT_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": request.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/api/admin/change-password")
def change_admin_password(
    payload: ChangePasswordRequest,
    admin: str = Depends(require_admin)
):
    from database import get_admin_user, upsert_admin_user
    import bcrypt

    # Fetch current record
    admin_user = get_admin_user(admin)
    if admin_user is None:
        raise HTTPException(status_code=404, detail="Admin user not found in database")

    # Verify current password
    if not verify_password(payload.current_password, admin_user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect"
        )

    # Validate new password
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")

    new_username = (payload.new_username or "").strip() or admin
    new_hash = bcrypt.hashpw(
        payload.new_password.encode("utf-8"), bcrypt.gensalt(rounds=12)
    ).decode("utf-8")

    # If renaming, delete old record first then insert new one
    if new_username != admin:
        from database import admin_users_collection
        admin_users_collection.delete_one({"username": admin})

    upsert_admin_user(new_username, new_hash)
    return {"message": f"Password updated successfully for '{new_username}'"}


@app.post("/api/chat")
def chat(req: ChatRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"

    # Rate limiting check
    if rate_limiter.is_rate_limited(client_ip):
        timestamp = datetime.utcnow().isoformat()
        logger.warning(
            f"Rate limit exceeded: IP={client_ip}, thread_id={req.thread_id}, timestamp={timestamp}, endpoint=/api/chat"
        )
        return {
            "response": "Something went wrong. Please try again later.",
            "success": False,
            "reply": "Something went wrong. Please try again later."
        }

    # Exception Handling for Chatbot logic
    try:
        return send_message(
            user_input=req.message,
            thread_id=req.thread_id
        )
    except Exception as e:
        logger.exception(f"Unhandled error in chat endpoint: IP={client_ip}, thread_id={req.thread_id}")
        return {
            "response": "Something went wrong. Please try again later.",
            "success": False,
            "reply": "Something went wrong. Please try again later."
        }


@app.get("/api/settings")
def get_settings(admin: str = Depends(require_admin)):
    return get_chatbot_settings()


@app.get("/api/public/settings")
def get_public_settings():
    settings = get_chatbot_settings()
    safe_keys = [
        "companyName", "companyDescription", "fallbackMessage",
        "generalEmail", "generalPhone", "supportEmail", "supportPhone",
        "title", "subtitle", "welcomeMessage", "placeholder", "primaryColor",
        "theme", "position", "width", "height", "logoUrl", "botAvatar",
        "launcherIcon", "launcherText", "showNewChat", "footerText",
        "suggestions", "storage"
    ]
    # Build safe settings dictionary
    return {k: settings.get(k, DEFAULT_SETTINGS.get(k)) for k in safe_keys}



# DASHBOARD ENDPOINT

@app.get("/api/admin/dashboard")
def get_dashboard(admin: str = Depends(require_admin)):
    total_chats = chats_collection.count_documents({})
    # Count unique threads
    unique_threads = len(chats_collection.distinct("thread_id"))
    total_leads = leads_collection.count_documents({})
    total_support = support_collection.count_documents({})
    total_hiring = hiring_collection.count_documents({})
    total_sources = knowledge_sources_collection.count_documents({})
    active_sources = knowledge_sources_collection.count_documents({"enabled": True})
    disabled_sources = knowledge_sources_collection.count_documents({"enabled": False})

    # Timeline feed compilation
    recent_chats_docs = list(chats_collection.find().sort("created_at", -1).limit(4))
    recent_leads_docs = list(leads_collection.find().sort("updated_at", -1).limit(4))
    recent_support_docs = list(support_collection.find().sort("updated_at", -1).limit(4))
    recent_hiring_docs = list(hiring_collection.find().sort("updated_at", -1).limit(4))

    recent_activity = []
    for c in recent_chats_docs:
        recent_activity.append({
            "type": "chat",
            "title": f"Chat activity on: {c.get('thread_id')}",
            "description": c.get("user_message", "")[:60],
            "timestamp": c.get("created_at")
        })
    for l in recent_leads_docs:
        p = l.get("profile", {})
        recent_activity.append({
            "type": "lead",
            "title": f"Lead qualified: {p.get('name', 'Unknown')}",
            "description": f"Budget: {p.get('budget', 'N/A')} | Project: {p.get('project_type', 'N/A')}",
            "timestamp": l.get("updated_at")
        })
    for s in recent_support_docs:
        p = s.get("profile", {})
        recent_activity.append({
            "type": "support",
            "title": f"Ticket raised: {p.get('name', 'Unknown')}",
            "description": f"Issue: {p.get('issue_type', 'N/A')} - {p.get('issue_details', '')[:50]}",
            "timestamp": s.get("updated_at")
        })
    for h in recent_hiring_docs:
        p = h.get("profile", {})
        recent_activity.append({
            "type": "hiring",
            "title": f"Applicant submission: {p.get('name', 'Unknown')}",
            "description": f"Role: {p.get('role', 'N/A')} | Experience: {p.get('experience', 'N/A')}",
            "timestamp": h.get("updated_at")
        })

    recent_activity.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    recent_activity = recent_activity[:8]

    # Group intents
    pipeline = [
        {"$group": {"_id": "$intent", "count": {"$sum": 1}}}
    ]
    intent_data = list(chats_collection.aggregate(pipeline))
    intent_breakdown = {item["_id"] or "unknown": item["count"] for item in intent_data}

    return {
        "total_chats": total_chats,
        "total_threads": unique_threads,
        "total_leads": total_leads,
        "total_support_tickets": total_support,
        "total_hiring_candidates": total_hiring,
        "total_knowledge_sources": total_sources,
        "total_active_knowledge_sources": active_sources,
        "total_disabled_knowledge_sources": disabled_sources,
        "recent_chats": [format_chat_summary(c) for c in recent_chats_docs],
        "recent_leads": [format_lead(l) for l in recent_leads_docs],
        "recent_support_tickets": [format_support_ticket(s) for s in recent_support_docs],
        "recent_hiring_candidates": [format_hiring_candidate(h) for h in recent_hiring_docs],
        
        # Compatibility structure
        "counters": {
            "chats": total_chats,
            "threads": unique_threads,
            "leads": total_leads,
            "support": total_support,
            "hiring": total_hiring,
            "knowledge": total_sources,
            "active_sources": active_sources,
            "disabled_sources": disabled_sources
        },
        "recent_activity": recent_activity,
        "intent_breakdown": intent_breakdown
    }


# SETTINGS

import re

@app.put("/api/settings")
def update_settings(payload: SettingsUpdate, admin: str = Depends(require_admin)):
    data = payload.dict(exclude_unset=True)
    
    # Validation checks
    if "theme" in data and data["theme"] not in ["light", "dark"]:
        raise HTTPException(status_code=400, detail="theme must be 'light' or 'dark'")
    if "position" in data and data["position"] not in ["bottom-right", "bottom-left"]:
        raise HTTPException(status_code=400, detail="position must be 'bottom-right' or 'bottom-left'")
    if "storage" in data and data["storage"] not in ["local", "session"]:
        raise HTTPException(status_code=400, detail="storage must be 'local' or 'session'")
    if "primaryColor" in data:
        if not re.match(r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$", data["primaryColor"]):
            raise HTTPException(status_code=400, detail="primaryColor must be a valid hex color like #ff7e21")
    if "showNewChat" in data and not isinstance(data["showNewChat"], bool):
        raise HTTPException(status_code=400, detail="showNewChat must be a boolean")
    if "suggestions" in data:
        if not isinstance(data["suggestions"], list) or not all(isinstance(x, str) for x in data["suggestions"]):
            raise HTTPException(status_code=400, detail="suggestions must be an array of strings")
            
    return update_chatbot_settings(data)



# CHATS PAGE

@app.get("/api/admin/chats")
def get_chats_summaries(q: str = None, intent: str = None, admin: str = Depends(require_admin)):
    match_stage = {}
    if q:
        match_stage["$or"] = [
            {"thread_id": {"$regex": q, "$options": "i"}},
            {"user_message": {"$regex": q, "$options": "i"}},
            {"bot_message": {"$regex": q, "$options": "i"}},
            {"profile_snapshot.name": {"$regex": q, "$options": "i"}}
        ]
    if intent:
        match_stage["intent"] = intent

    pipeline = []
    if match_stage:
        pipeline.append({"$match": match_stage})

    pipeline.extend([
        {"$sort": {"created_at": 1}},
        {"$group": {
            "_id": "$thread_id",
            "thread_id": {"$first": "$thread_id"},
            "user_name": {"$last": "$profile_snapshot.name"},
            "last_message": {"$last": "$user_message"},
            "intent": {"$last": "$intent"},
            "timestamp": {"$last": "$created_at"},
            "total_messages": {"$sum": 1},
            "profile_snapshot": {"$last": "$profile_snapshot"}
        }},
        {"$sort": {"timestamp": -1}}
    ])

    grouped = list(chats_collection.aggregate(pipeline))
    return [format_chat_summary(t) for t in grouped]


@app.get("/api/admin/chats/{thread_id}")
def get_thread_chats(thread_id: str, admin: str = Depends(require_admin)):
    docs = list(chats_collection.find({"thread_id": thread_id}).sort("created_at", 1))
    if not docs:
        return {
            "thread_id": thread_id,
            "name": "Anonymous User",
            "profile": {},
            "messages": []
        }
    latest_doc = docs[-1]
    profile = latest_doc.get("profile_snapshot") or {}
    name = extract_display_name(profile)
    return {
        "thread_id": thread_id,
        "name": name,
        "profile": profile,
        "messages": format_thread_messages(docs)
    }


# LEADS PAGE

@app.get("/api/admin/leads")
def get_leads(q: str = None, status: str = None, admin: str = Depends(require_admin)):
    query = {}
    if q:
        query["$or"] = [
            {"profile.name": {"$regex": q, "$options": "i"}},
            {"profile.company": {"$regex": q, "$options": "i"}},
            {"profile.project_type": {"$regex": q, "$options": "i"}},
            {"thread_id": {"$regex": q, "$options": "i"}}
        ]
    if status:
        query["status"] = status

    docs = list(leads_collection.find(query).sort("updated_at", -1))
    return [format_lead(d) for d in docs]


@app.put("/api/admin/leads/{id}/status")
def update_lead_status(id: str, payload: StatusUpdate, admin: str = Depends(require_admin)):
    leads_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": payload.status, "updated_at": datetime.utcnow().isoformat()}}
    )
    doc = leads_collection.find_one({"_id": ObjectId(id)})
    
    # Broadcast lead updated event
    from database import broadcast_event
    broadcast_event("lead_created_or_updated", clean_mongo_doc(doc))
    
    return format_lead(doc)


# SUPPORT TICKETS PAGE

@app.get("/api/admin/support")
def get_support_tickets(q: str = None, status: str = None, priority: str = None, admin: str = Depends(require_admin)):
    query = {}
    if q:
        query["$or"] = [
            {"profile.name": {"$regex": q, "$options": "i"}},
            {"profile.issue_details": {"$regex": q, "$options": "i"}},
            {"thread_id": {"$regex": q, "$options": "i"}}
        ]
    if status:
        query["status"] = status
    if priority:
        query["priority"] = priority

    docs = list(support_collection.find(query).sort("updated_at", -1))
    return [format_support_ticket(d) for d in docs]


@app.put("/api/admin/support/{id}/status")
def update_support_status(id: str, payload: SupportStatusUpdate, admin: str = Depends(require_admin)):
    update_fields = {"updated_at": datetime.utcnow().isoformat()}
    if payload.status is not None:
        update_fields["status"] = payload.status
    if payload.priority is not None:
        update_fields["priority"] = payload.priority

    support_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": update_fields}
    )
    doc = support_collection.find_one({"_id": ObjectId(id)})
    
    # Broadcast ticket updated event
    from database import broadcast_event
    broadcast_event("support_created_or_updated", clean_mongo_doc(doc))
    
    return format_support_ticket(doc)


# HIRING CANDIDATES PAGE

@app.get("/api/admin/hiring")
def get_hiring_candidates(q: str = None, status: str = None, admin: str = Depends(require_admin)):
    query = {}
    if q:
        query["$or"] = [
            {"profile.name": {"$regex": q, "$options": "i"}},
            {"profile.role": {"$regex": q, "$options": "i"}},
            {"profile.skills": {"$regex": q, "$options": "i"}},
            {"thread_id": {"$regex": q, "$options": "i"}}
        ]
    if status:
        query["status"] = status

    docs = list(hiring_collection.find(query).sort("updated_at", -1))
    return [format_hiring_candidate(d) for d in docs]


@app.put("/api/admin/hiring/{id}/status")
def update_hiring_status(id: str, payload: StatusUpdate, admin: str = Depends(require_admin)):
    hiring_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"status": payload.status, "updated_at": datetime.utcnow().isoformat()}}
    )
    doc = hiring_collection.find_one({"_id": ObjectId(id)})
    
    # Broadcast hiring updated event
    from database import broadcast_event
    broadcast_event("hiring_created_or_updated", clean_mongo_doc(doc))
    
    return format_hiring_candidate(doc)


# KNOWLEDGE BASE SOURCES CRUD

@app.get("/api/admin/knowledge")
def get_knowledge_sources(q: str = None, type: str = None, admin: str = Depends(require_admin)):
    query = {}
    if q:
        query["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"category": {"$regex": q, "$options": "i"}},
            {"content": {"$regex": q, "$options": "i"}}
        ]
    if type:
        query["type"] = type

    docs = list(sources_collection.find(query).sort("updated_at", -1))
    return [clean_mongo_doc(d) for d in docs]


@app.post("/api/admin/knowledge")
def create_manual_source(payload: ManualSourceCreate, admin: str = Depends(require_admin)):
    source_doc = {
        "title": payload.title,
        "type": "manual",
        "category": payload.category,
        "content": payload.content,
        "enabled": True,
        "intent_scope": payload.intent_scope,
        "topic": payload.topic,
        "service": payload.service,
        "tags": [t.strip() for t in payload.tags.split(",") if t.strip()] if payload.tags else [],
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    res = sources_collection.insert_one(source_doc)
    source_id = str(res.inserted_id)

    from rag.source_manager import process_and_chunk_source
    num_chunks = process_and_chunk_source(
        source_id, payload.title, "manual", payload.content,
        intent_scope=payload.intent_scope,
        topic=payload.topic,
        service=payload.service,
        tags=[t.strip() for t in payload.tags.split(",") if t.strip()] if payload.tags else None
    )

    sources_collection.update_one(
        {"_id": ObjectId(source_id)},
        {"$set": {"num_chunks": num_chunks}}
    )

    source_doc["_id"] = source_id
    source_doc["num_chunks"] = num_chunks
    return clean_mongo_doc(source_doc)


@app.put("/api/admin/knowledge/{id}")
def update_knowledge_source(id: str, payload: ManualSourceUpdate, admin: str = Depends(require_admin)):
    current = sources_collection.find_one({"_id": ObjectId(id)})
    if not current:
        raise HTTPException(status_code=404, detail="Source not found")

    update_fields = {"updated_at": datetime.utcnow().isoformat()}
    if payload.title is not None:
        update_fields["title"] = payload.title
    if payload.category is not None:
        update_fields["category"] = payload.category
    if payload.content is not None:
        update_fields["content"] = payload.content
    if payload.intent_scope is not None:
        update_fields["intent_scope"] = payload.intent_scope
    if payload.topic is not None:
        update_fields["topic"] = payload.topic
    if payload.service is not None:
        update_fields["service"] = payload.service
    if payload.tags is not None:
        update_fields["tags"] = [t.strip() for t in payload.tags.split(",") if t.strip()] if payload.tags else []

    sources_collection.update_one({"_id": ObjectId(id)}, {"$set": update_fields})

    # If content changed for a manual source, re-chunk
    if payload.content is not None and current.get("type") == "manual":
        from rag.source_manager import process_and_chunk_source
        intent_scope = payload.intent_scope if payload.intent_scope is not None else current.get("intent_scope")
        topic = payload.topic if payload.topic is not None else current.get("topic")
        service = payload.service if payload.service is not None else current.get("service")
        tags = [t.strip() for t in payload.tags.split(",") if t.strip()] if payload.tags is not None else current.get("tags")

        num_chunks = process_and_chunk_source(
            id,
            payload.title or current.get("title"),
            "manual",
            payload.content,
            intent_scope=intent_scope,
            topic=topic,
            service=service,
            tags=tags
        )
        sources_collection.update_one(
            {"_id": ObjectId(id)},
            {"$set": {"num_chunks": num_chunks}}
        )

    updated = sources_collection.find_one({"_id": ObjectId(id)})
    return clean_mongo_doc(updated)


@app.delete("/api/admin/knowledge/{id}")
def delete_knowledge_source(id: str, admin: str = Depends(require_admin)):
    from rag.source_manager import delete_source_data
    delete_source_data(id)
    return {"message": "Source deleted successfully"}


@app.post("/api/admin/knowledge/upload")
def upload_knowledge_file(
    admin: str = Depends(require_admin),
    file: UploadFile = File(...),
    category: str = Form("Company Information"),
    intent_scope: str = Form(None),
    topic: str = Form(None),
    service: str = Form(None),
    tags: str = Form(None)
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".csv", ".json", ".md", ".xlsx"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension '{ext}'. Only .pdf, .docx, .txt, .csv, .json, .md, .xlsx are allowed."
        )

    # Validate file size
    max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "20"))
    # Seek to end to get size
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)

    if size > max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds the limit of {max_upload_mb}MB."
        )

    os.makedirs("./temp_uploads", exist_ok=True)
    temp_path = f"./temp_uploads/{file.filename}"
    with open(temp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        from rag.loader import load_any_file
        doc = load_any_file(temp_path)

        tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        source_doc = {
            "title": file.filename,
            "type": "document",
            "category": category,
            "content": doc.content[:1000] + "... [Parsed Document File]",
            "full_content": doc.content,
            "enabled": True,
            "intent_scope": intent_scope,
            "topic": topic,
            "service": service,
            "tags": tags_list,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        res = sources_collection.insert_one(source_doc)
        source_id = str(res.inserted_id)

        from rag.source_manager import process_and_chunk_source
        num_chunks = process_and_chunk_source(
            source_id,
            file.filename,
            doc.metadata.get("source_type", "document"),
            doc.content,
            intent_scope=intent_scope,
            topic=topic,
            service=service,
            tags=tags_list
        )

        sources_collection.update_one(
            {"_id": ObjectId(source_id)},
            {"$set": {"num_chunks": num_chunks}}
        )

        source_doc["_id"] = source_id
        source_doc["num_chunks"] = num_chunks
        return clean_mongo_doc(source_doc)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.post("/api/admin/sources/database")
def create_database_source(payload: DatabaseConnectionRequest, admin: str = Depends(require_admin)):
    tags_list = [t.strip() for t in payload.tags.split(",") if t.strip()] if payload.tags else []

    source_doc = {
        "title": payload.connection_name,
        "type": "database",
        "category": payload.category,
        "connection_name": payload.connection_name,
        "db_type": payload.db_type,
        "connection_string": payload.connection_string,
        "db_name": payload.db_name,
        "target_collection": payload.target_collection,
        "enabled": True,
        "intent_scope": payload.intent_scope,
        "topic": payload.topic,
        "service": payload.service,
        "tags": tags_list,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    res = sources_collection.insert_one(source_doc)
    source_id = str(res.inserted_id)

    from rag.source_manager import process_database_source
    num_chunks = process_database_source(
        source_id=source_id,
        conn_name=payload.connection_name,
        conn_string=payload.connection_string,
        db_type=payload.db_type,
        db_name=payload.db_name,
        target_collection=payload.target_collection,
        intent_scope=payload.intent_scope,
        topic=payload.topic,
        service=payload.service,
        tags=tags_list
    )

    sources_collection.update_one(
        {"_id": ObjectId(source_id)},
        {"$set": {"num_chunks": num_chunks}}
    )

    source_doc["_id"] = source_id
    source_doc["num_chunks"] = num_chunks
    return clean_mongo_doc(source_doc)


@app.post("/api/admin/sources/website")
def create_website_source(payload: WebsiteSourceRequest, admin: str = Depends(require_admin)):
    tags_list = [t.strip() for t in payload.tags.split(",") if t.strip()] if payload.tags else []

    source_doc = {
        "title": payload.url,
        "type": "website",
        "category": payload.category,
        "url": payload.url,
        "enabled": True,
        "intent_scope": payload.intent_scope,
        "topic": payload.topic,
        "service": payload.service,
        "tags": tags_list,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    res = sources_collection.insert_one(source_doc)
    source_id = str(res.inserted_id)

    from rag.source_manager import process_website_source
    num_chunks = process_website_source(
        source_id=source_id,
        url=payload.url,
        intent_scope=payload.intent_scope,
        topic=payload.topic,
        service=payload.service,
        tags=tags_list
    )

    sources_collection.update_one(
        {"_id": ObjectId(source_id)},
        {"$set": {"num_chunks": num_chunks}}
    )

    source_doc["_id"] = source_id
    source_doc["num_chunks"] = num_chunks
    return clean_mongo_doc(source_doc)


@app.put("/api/admin/knowledge/{id}/enable")
def enable_knowledge_source(id: str, admin: str = Depends(require_admin)):
    sources_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"enabled": True, "updated_at": datetime.utcnow().isoformat()}}
    )
    doc = sources_collection.find_one({"_id": ObjectId(id)})
    return clean_mongo_doc(doc)


@app.put("/api/admin/knowledge/{id}/disable")
def disable_knowledge_source(id: str, admin: str = Depends(require_admin)):
    sources_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"enabled": False, "updated_at": datetime.utcnow().isoformat()}}
    )
    doc = sources_collection.find_one({"_id": ObjectId(id)})
    return clean_mongo_doc(doc)


@app.post("/api/admin/knowledge/{id}/reindex")
def reindex_knowledge_source(id: str, admin: str = Depends(require_admin)):
    current = sources_collection.find_one({"_id": ObjectId(id)})
    if not current:
        raise HTTPException(status_code=404, detail="Source not found")

    from rag.source_manager import process_and_chunk_source, process_database_source, process_website_source

    intent_scope = current.get("intent_scope")
    topic = current.get("topic")
    service = current.get("service")
    tags = current.get("tags")

    num_chunks = 0
    t = current.get("type", "manual")
    if t == "manual":
        num_chunks = process_and_chunk_source(
            id, current.get("title"), "manual", current.get("content"),
            intent_scope=intent_scope, topic=topic, service=service, tags=tags
        )
    elif t.startswith("db_") or t == "database":
        num_chunks = process_database_source(
            id,
            current.get("title"),
            current.get("connection_string"),
            current.get("db_type"),
            current.get("db_name"),
            current.get("target_collection"),
            intent_scope=intent_scope,
            topic=topic,
            service=service,
            tags=tags
        )
    elif t == "website":
        num_chunks = process_website_source(
            id, current.get("url"),
            intent_scope=intent_scope, topic=topic, service=service, tags=tags
        )
    elif t == "document":
        title = current.get("title", "")
        ext = os.path.splitext(title)[1].lower().replace(".", "") or "txt"
        content_to_use = current.get("full_content") or current.get("content")
        num_chunks = process_and_chunk_source(
            id, title, ext, content_to_use,
            intent_scope=intent_scope, topic=topic, service=service, tags=tags
        )

    sources_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"num_chunks": num_chunks, "updated_at": datetime.utcnow().isoformat()}}
    )

    updated = sources_collection.find_one({"_id": ObjectId(id)})
    return clean_mongo_doc(updated)


@app.get("/api/admin/knowledge/sync-status")
def get_knowledge_sync_status(admin: str = Depends(require_admin)):
    total_sources = sources_collection.count_documents({})
    active_sources = sources_collection.count_documents({"enabled": True})
    disabled_sources = sources_collection.count_documents({"enabled": False})
    total_chunks = chunks_collection.count_documents({})

    last_doc = list(sources_collection.find().sort("updated_at", -1).limit(1))
    last_updated = last_doc[0].get("updated_at", "N/A") if last_doc else "N/A"

    return {
        "total_sources": total_sources,
        "active_sources": active_sources,
        "disabled_sources": disabled_sources,
        "total_chunks": total_chunks,
        "last_updated": last_updated
    }