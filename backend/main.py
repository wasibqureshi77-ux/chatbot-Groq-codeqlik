from fastapi import FastAPI, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect, Request, Depends, status
from fastapi.security import OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
import os
import re
import shutil
import logging
import time
import threading
from collections import defaultdict
from jose import jwt, JWTError
import bcrypt
from widget_suggestions import WidgetSuggestionRequest, generate_widget_suggestions

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
    meetings_collection,
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
    format_hiring_candidate,
    now_iso,
    build_meeting_slot_key,
    is_meeting_slot_available,
    is_meeting_status_active,
    normalize_booking_date,
    normalize_booking_slot
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
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

from fastapi.responses import FileResponse

@app.get("/dist/widget.js")
def get_widget_js():
    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0"
    }
    return FileResponse(path=str(WIDGET_DIST_DIR / "widget.js"), headers=headers, media_type="application/javascript")

app.mount("/dist", StaticFiles(directory=str(WIDGET_DIST_DIR)), name="dist")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

@app.on_event("startup")
async def startup_event():
    manager.loop = asyncio.get_running_loop()

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex="https?://.*",
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
    logoUrlLight: Optional[str] = None
    logoUrlDark: Optional[str] = None
    botAvatar: Optional[str] = None
    launcherIcon: Optional[str] = None
    launcherSize: Optional[float] = None
    launcherText: Optional[str] = None
    showLauncherGreeting: Optional[bool] = None
    launcherGreeting: Optional[str] = None
    launcherGreetingColor: Optional[str] = None
    launcherGreetingFontSize: Optional[float] = None
    launcherGreetingBgStart: Optional[str] = None
    launcherGreetingBgEnd: Optional[str] = None
    launcherGreetingWidth: Optional[float] = None
    launcherGreetingBorderRadius: Optional[float] = None
    launcherGreetingOffsetX: Optional[float] = None
    launcherGreetingOffsetY: Optional[float] = None
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
    full_content: str = None
    enabled: bool = None
    intent_scope: str = None
    topic: str = None
    service: str = None
    tags: str = None
    url: str = None
    connection_name: str = None
    db_type: str = None
    connection_string: str = None
    db_name: str = None
    target_collection: str = None


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


@app.post("/api/widget/suggestions")
def get_widget_suggestions(req: WidgetSuggestionRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if rate_limiter.is_rate_limited(client_ip):
        return {"suggestions": []}
    try:
        from llm_client import thread_id_var, node_name_var
        if req.thread_id:
            thread_id_var.set(req.thread_id)
        else:
            thread_id_var.set("suggestions_api")
        node_name_var.set("suggestions")
        
        suggestions = generate_widget_suggestions(req)
        return {"suggestions": suggestions}
    except Exception as e:
        logger.error(f"Error generating suggestions: {e}")
        return {"suggestions": []}


@app.get("/api/settings")
def get_settings(admin: str = Depends(require_admin)):
    return get_chatbot_settings()


from fastapi import Response

@app.get("/api/public/settings")
def get_public_settings(response: Response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    settings = get_chatbot_settings()
    safe_keys = [
        "companyName", "companyDescription", "fallbackMessage",
        "generalEmail", "generalPhone", "supportEmail", "supportPhone",
        "title", "subtitle", "welcomeMessage", "placeholder", "primaryColor",
        "theme", "position", "width", "height", "logoUrl", "logoUrlLight", "logoUrlDark", "botAvatar",
        "launcherIcon", "launcherSize", "launcherText", "showLauncherGreeting", "launcherGreeting", "launcherGreetingColor", "launcherGreetingFontSize",
        "launcherGreetingBgStart", "launcherGreetingBgEnd", "launcherGreetingWidth", "launcherGreetingBorderRadius",
        "launcherGreetingOffsetX", "launcherGreetingOffsetY", "showNewChat", "footerText",
        "suggestions", "storage"
    ]
    # Build safe settings dictionary
    return {k: settings.get(k, DEFAULT_SETTINGS.get(k)) for k in safe_keys}



# AI USAGE ANALYTICS ENDPOINTS

def build_usage_filter(start_date: Optional[str] = None, end_date: Optional[str] = None, model: Optional[str] = None) -> dict:
    query = {}
    if start_date or end_date:
        query["timestamp"] = {}
        if start_date:
            try:
                query["timestamp"]["$gte"] = parse_usage_datetime(start_date, end_of_day=False)
            except Exception:
                pass
        if end_date:
            try:
                query["timestamp"]["$lte"] = parse_usage_datetime(end_date, end_of_day=True)
            except Exception:
                pass
    if model:
        query["model"] = model
    return query


def parse_usage_datetime(value: str, end_of_day: bool = False) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Empty date")

    normalized = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if len(raw) == 10 and re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        if end_of_day:
            parsed = parsed + timedelta(days=1) - timedelta(microseconds=1)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _usage_number(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _usage_tokens(row: dict, key: str) -> int:
    return int(_usage_number(row.get(key)))


def _usage_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    from llm_client import calculate_cost
    return calculate_cost(model or "", input_tokens, output_tokens)


def _usage_rates(model: str) -> dict:
    from llm_client import get_model_cost_rates
    cost_model, rates = get_model_cost_rates(model or "")
    return {
        "cost_model": cost_model,
        "input_cost_per_million": rates["input_cost_per_million"],
        "output_cost_per_million": rates["output_cost_per_million"],
        "pricing_note": rates.get("pricing_note", "token"),
    }

@app.get("/api/admin/analytics/llm-usage/summary")
def get_llm_usage_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    model: Optional[str] = None,
    admin: str = Depends(require_admin)
):
    from database import llm_usage_logs_collection
    query = build_usage_filter(start_date, end_date, model)
    
    pipeline = [
        {"$match": query},
        {
            "$group": {
                "_id": "$model",
                "total_requests": {"$sum": 1},
                "total_input_tokens": {"$sum": {"$ifNull": ["$input_tokens", 0]}},
                "total_output_tokens": {"$sum": {"$ifNull": ["$output_tokens", 0]}},
                "latency_sum": {"$sum": {"$ifNull": ["$latency", 0]}},
            }
        }
    ]
    
    result = list(llm_usage_logs_collection.aggregate(pipeline))
    
    summary = {
        "total_requests": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_tokens": 0,
        "total_cost": 0.0,
        "avg_latency": 0.0,
    }

    latency_sum = 0.0
    for row in result:
        model_name = row.get("_id") or "unknown"
        input_tokens = _usage_tokens(row, "total_input_tokens")
        output_tokens = _usage_tokens(row, "total_output_tokens")
        total_requests = int(row.get("total_requests") or 0)
        calculated_cost = _usage_cost(model_name, input_tokens, output_tokens)
            
        summary["total_requests"] += total_requests
        summary["total_input_tokens"] += input_tokens
        summary["total_output_tokens"] += output_tokens
        summary["total_tokens"] += input_tokens + output_tokens
        summary["total_cost"] += calculated_cost
        latency_sum += _usage_number(row.get("latency_sum"))

    avg_tokens = 0
    if summary["total_requests"] > 0:
        avg_tokens = round(summary["total_tokens"] / summary["total_requests"], 1)

    summary["avg_tokens_per_request"] = avg_tokens
    summary["estimated_monthly_cost"] = round(summary["total_cost"] * 30, 4)
    summary["total_cost"] = round(summary["total_cost"], 6)
    summary["avg_latency"] = round(latency_sum / summary["total_requests"], 3) if summary["total_requests"] else 0.0
    
    return summary

@app.get("/api/admin/analytics/llm-usage/by-model")
def get_llm_usage_by_model(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    model: Optional[str] = None,
    admin: str = Depends(require_admin)
):
    from database import llm_usage_logs_collection
    query = build_usage_filter(start_date, end_date, model)
    
    pipeline = [
        {"$match": query},
        {
            "$group": {
                "_id": "$model",
                "total_requests": {"$sum": 1},
                "input_tokens": {"$sum": {"$ifNull": ["$input_tokens", 0]}},
                "output_tokens": {"$sum": {"$ifNull": ["$output_tokens", 0]}},
            }
        },
        {"$sort": {"input_tokens": -1}}
    ]
    
    result = list(llm_usage_logs_collection.aggregate(pipeline))
    formatted = []
    for r in result:
        model_name = r["_id"] or "Unknown"
        input_tokens = _usage_tokens(r, "input_tokens")
        output_tokens = _usage_tokens(r, "output_tokens")
        rates = _usage_rates(model_name)
        total_cost = _usage_cost(model_name, input_tokens, output_tokens)
            
        formatted.append({
            "model": model_name,
            **rates,
            "total_requests": r["total_requests"],
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "total_cost": round(total_cost, 6)
        })
    formatted.sort(key=lambda row: row["total_tokens"], reverse=True)
    return formatted

@app.get("/api/admin/analytics/llm-usage/daily")
def get_llm_usage_daily(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    model: Optional[str] = None,
    admin: str = Depends(require_admin)
):
    from database import llm_usage_logs_collection
    query = build_usage_filter(start_date, end_date, model)
    
    pipeline = [
        {"$match": query},
        {
            "$group": {
                "_id": {
                    "date": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$timestamp"
                        }
                    },
                    "model": "$model"
                },
                "total_requests": {"$sum": 1},
                "input_tokens": {"$sum": {"$ifNull": ["$input_tokens", 0]}},
                "output_tokens": {"$sum": {"$ifNull": ["$output_tokens", 0]}},
            }
        },
        {"$sort": {"_id": 1}}
    ]
    
    result = list(llm_usage_logs_collection.aggregate(pipeline))
    daily = {}
    for r in result:
        day = r["_id"].get("date")
        model_name = r["_id"].get("model") or "unknown"
        input_tokens = _usage_tokens(r, "input_tokens")
        output_tokens = _usage_tokens(r, "output_tokens")
        total_cost = _usage_cost(model_name, input_tokens, output_tokens)
            
        item = daily.setdefault(day, {
            "date": day,
            "total_requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
        })
        item["total_requests"] += int(r.get("total_requests") or 0)
        item["input_tokens"] += input_tokens
        item["output_tokens"] += output_tokens
        item["total_tokens"] += input_tokens + output_tokens
        item["total_cost"] += total_cost
    formatted = []
    for item in sorted(daily.values(), key=lambda row: row["date"]):
        item["total_cost"] = round(item["total_cost"], 6)
        formatted.append(item)
    return formatted

@app.get("/api/admin/analytics/llm-usage/recent")
def get_llm_usage_recent(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    model: Optional[str] = None,
    limit: int = 50,
    admin: str = Depends(require_admin)
):
    from database import llm_usage_logs_collection, chats_collection
    query = build_usage_filter(start_date, end_date, model)
    
    # Exclude dynamic suggestions and unknown/suggestions_api threads
    query["node"] = {"$ne": "suggestions"}
    query["thread_id"] = {"$nin": ["suggestions_api", "unknown"]}
    
    pipeline = [
        {"$match": query},
        {
            "$group": {
                "_id": {
                    "thread_id": "$thread_id",
                    "model": "$model",
                },
                "total_requests": {"$sum": 1},
                "input_tokens": {"$sum": {"$ifNull": ["$input_tokens", 0]}},
                "output_tokens": {"$sum": {"$ifNull": ["$output_tokens", 0]}},
                "last_active": {"$max": "$timestamp"}
            }
        },
        {"$sort": {"last_active": -1}},
    ]
    
    result = list(llm_usage_logs_collection.aggregate(pipeline))
    combined_threads = {}
    for r in result:
        thread_id = (r.get("_id") or {}).get("thread_id") or "unknown"
        model_name = (r.get("_id") or {}).get("model") or "unknown"
        input_tokens = _usage_tokens(r, "input_tokens")
        output_tokens = _usage_tokens(r, "output_tokens")
        total_cost = _usage_cost(model_name, input_tokens, output_tokens)
            
        item = combined_threads.setdefault(thread_id, {
            "thread_id": thread_id,
            "total_requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "last_active": r.get("last_active"),
        })
        item["total_requests"] += int(r.get("total_requests") or 0)
        item["input_tokens"] += input_tokens
        item["output_tokens"] += output_tokens
        item["total_tokens"] += input_tokens + output_tokens
        item["total_cost"] += total_cost
        last_active = r.get("last_active")
        if last_active and (not item.get("last_active") or last_active > item["last_active"]):
            item["last_active"] = last_active

    def _timestamp_sort_value(row: dict) -> float:
        value = row.get("last_active")
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.timestamp()
        return 0.0

    result = sorted(combined_threads.values(), key=_timestamp_sort_value, reverse=True)[:limit]
    
    # Fetch thread display names from chats_collection
    thread_ids = [r["thread_id"] for r in result if r.get("thread_id")]
    thread_names = {}
    if thread_ids:
        docs = list(chats_collection.find({"thread_id": {"$in": thread_ids}}))
        for d in docs:
            tid = d.get("thread_id")
            ps = d.get("profile_snapshot") or {}
            name = ps.get("name") or ps.get("user_name")
            if not name:
                prof = d.get("profile") or {}
                name = prof.get("name") or prof.get("user_name")
            if name:
                thread_names[tid] = name
    
    formatted = []
    for r in result:
        ts = r.get("last_active")
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            timestamp_str = ts.isoformat()
        else:
            timestamp_str = ts
            
        tid = r.get("thread_id") or "unknown"
        display_name = thread_names.get(tid) or tid
            
        formatted.append({
            "thread_id": tid,
            "display_name": display_name,
            "total_requests": r["total_requests"],
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "total_tokens": r["input_tokens"] + r["output_tokens"],
            "total_cost": round(r["total_cost"], 6),
            "timestamp": timestamp_str
        })
    return formatted


@app.get("/api/admin/analytics/llm-usage/model-rates")
def get_llm_usage_model_rates(admin: str = Depends(require_admin)):
    from llm_client import get_model_pricing_catalog
    return get_model_pricing_catalog()


# DASHBOARD ENDPOINT

@app.get("/api/admin/dashboard")
def get_dashboard(admin: str = Depends(require_admin)):
    total_chats = chats_collection.count_documents({})
    # Count unique threads
    unique_threads = len(chats_collection.distinct("thread_id"))
    total_leads = leads_collection.count_documents({})
    total_support = support_collection.count_documents({})
    total_hiring = hiring_collection.count_documents({})
    total_meetings = meetings_collection.count_documents({})
    total_sources = knowledge_sources_collection.count_documents({})
    active_sources = knowledge_sources_collection.count_documents({"enabled": True})
    disabled_sources = knowledge_sources_collection.count_documents({"enabled": False})

    # Timeline feed compilation
    recent_chats_docs = list(chats_collection.find().sort("created_at", -1).limit(4))
    recent_leads_docs = list(leads_collection.find().sort("updated_at", -1).limit(4))
    recent_support_docs = list(support_collection.find().sort("updated_at", -1).limit(4))
    recent_hiring_docs = list(hiring_collection.find().sort("updated_at", -1).limit(4))
    recent_meetings_docs = list(meetings_collection.find().sort("updated_at", -1).limit(4))

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
    for m in recent_meetings_docs:
        p = m.get("profile", {})
        recent_activity.append({
            "type": "meeting",
            "title": f"Meeting booked: {p.get('name', 'Unknown')}",
            "description": f"{p.get('meeting_mode', 'N/A')} | {p.get('date', 'N/A')} at {p.get('time_slot', 'N/A')}",
            "timestamp": m.get("updated_at")
        })

    recent_activity.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    recent_activity = recent_activity[:8]

    # Group intents
    intent_breakdown = {}
    for doc in chats_collection.find({}, {"intent": 1}):
        intent = doc.get("intent") or "unknown"
        intent_breakdown[intent] = intent_breakdown.get(intent, 0) + 1

    return {
        "total_chats": total_chats,
        "total_threads": unique_threads,
        "total_leads": total_leads,
        "total_support_tickets": total_support,
        "total_hiring_candidates": total_hiring,
        "total_booked_meetings": total_meetings,
        "total_knowledge_sources": total_sources,
        "total_active_knowledge_sources": active_sources,
        "total_disabled_knowledge_sources": disabled_sources,
        "recent_chats": [format_chat_summary(c) for c in recent_chats_docs],
        "recent_leads": [format_lead(l) for l in recent_leads_docs],
        "recent_support_tickets": [format_support_ticket(s) for s in recent_support_docs],
        "recent_hiring_candidates": [format_hiring_candidate(h) for h in recent_hiring_docs],
        "recent_meetings": serialize_many(recent_meetings_docs),
        
        # Compatibility structure
        "counters": {
            "chats": total_chats,
            "threads": unique_threads,
            "leads": total_leads,
            "support": total_support,
            "hiring": total_hiring,
            "meetings": total_meetings,
            "knowledge": total_sources,
            "active_sources": active_sources,
            "disabled_sources": disabled_sources
        },
        "recent_activity": recent_activity,
        "intent_breakdown": intent_breakdown
    }


# SETTINGS

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
IMAGE_EXTENSION_BY_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}


def save_uploaded_image(file: UploadFile, prefix: str) -> dict:
    ext = os.path.splitext(file.filename or "")[1].lower()
    content_type = (file.content_type or "").lower().split(";")[0].strip()

    if ext and ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only image uploads are allowed")
    if not ext:
        ext = IMAGE_EXTENSION_BY_TYPE.get(content_type, "")
    if not ext or (content_type and not content_type.startswith("image/")):
        raise HTTPException(status_code=400, detail="Only image uploads are allowed")

    safe_prefix = re.sub(r"[^a-zA-Z0-9_-]", "", prefix) or "image"
    filename = f"{safe_prefix}_{int(time.time() * 1000)}{ext or '.png'}"
    filepath = UPLOAD_DIR / filename
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"url": f"/uploads/{filename}"}


@app.post("/api/admin/settings/upload-logo")
def upload_logo(file: UploadFile = File(...), admin: str = Depends(require_admin)):
    return save_uploaded_image(file, "logo")


@app.post("/api/admin/settings/upload-launcher-icon")
def upload_launcher_icon(file: UploadFile = File(...), admin: str = Depends(require_admin)):
    return save_uploaded_image(file, "launcher_icon")

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
    for color_key in ["launcherGreetingColor", "launcherGreetingBgStart", "launcherGreetingBgEnd"]:
        if data.get(color_key):
            if not re.match(r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$", data[color_key]):
                raise HTTPException(status_code=400, detail=f"{color_key} must be a valid hex color like #ff7e21")
    numeric_ranges = {
        "launcherSize": (44, 96),
        "launcherGreetingFontSize": (7, 18),
        "launcherGreetingWidth": (72, 180),
        "launcherGreetingBorderRadius": (6, 40),
        "launcherGreetingOffsetX": (0, 180),
        "launcherGreetingOffsetY": (24, 140),
    }
    for numeric_key, (min_value, max_value) in numeric_ranges.items():
        if numeric_key in data:
            value = data[numeric_key]
            if value is None or value < min_value or value > max_value:
                raise HTTPException(status_code=400, detail=f"{numeric_key} must be between {min_value} and {max_value}")
    if "showNewChat" in data and not isinstance(data["showNewChat"], bool):
        raise HTTPException(status_code=400, detail="showNewChat must be a boolean")
    if "showLauncherGreeting" in data and not isinstance(data["showLauncherGreeting"], bool):
        raise HTTPException(status_code=400, detail="showLauncherGreeting must be a boolean")
    if "suggestions" in data:
        if not isinstance(data["suggestions"], list) or not all(isinstance(x, str) for x in data["suggestions"]):
            raise HTTPException(status_code=400, detail="suggestions must be an array of strings")
            
    return update_chatbot_settings(data)



# MEETINGS PAGE

@app.get("/api/admin/meetings")
def get_meetings(admin: str = Depends(require_admin)):
    docs = list(meetings_collection.find().sort("updated_at", -1))
    return serialize_many(docs)

@app.put("/api/admin/meetings/{meeting_id}/status")
def update_meeting_status(meeting_id: str, payload: dict, admin: str = Depends(require_admin)):
    status = payload.get("status")
    if not status:
        raise HTTPException(status_code=400, detail="Status is required")
    
    query = {}
    try:
        query["_id"] = ObjectId(meeting_id)
    except Exception:
        query["thread_id"] = meeting_id

    current = meetings_collection.find_one(query)
    if not current:
        raise HTTPException(status_code=404, detail="Meeting not found")

    profile = current.get("profile") or {}
    slot = normalize_booking_slot(profile.get("time_slot"))
    date_value = profile.get("date")
    slot_key = build_meeting_slot_key(date_value, slot)
    slot_active = bool(slot_key and is_meeting_status_active(status))

    if slot_active and not is_meeting_slot_available(date_value, slot, thread_id=current.get("thread_id")):
        raise HTTPException(status_code=409, detail="This date and time slot is already booked")

    update_fields = {
        "profile.status": status,
        "profile.slot_active": slot_active,
        "updated_at": now_iso(),
    }
    if slot:
        update_fields["profile.time_slot"] = slot
    date_key = normalize_booking_date(date_value)
    if date_key:
        update_fields["profile.date_key"] = date_key
    if slot_key:
        update_fields["profile.slot_key"] = slot_key

    try:
        result = meetings_collection.update_one(query, {"$set": update_fields})
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="This date and time slot is already booked")
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Meeting not found")

    from database import broadcast_event
    updated = meetings_collection.find_one(query)
    if updated:
        updated = serialize_doc(updated)
        broadcast_event("meeting_created_or_updated", updated)
        return updated

    return {"success": True}



# CHATS PAGE

@app.get("/api/admin/chats")
def get_chats_summaries(q: str = None, intent: str = None, admin: str = Depends(require_admin)):
    query = {}
    if intent:
        query["intent"] = intent

    docs = list(chats_collection.find(query).sort("created_at", 1))
    
    grouped = {}
    for doc in docs:
        thread_id = doc.get("thread_id")
        if not thread_id:
            continue
            
        if thread_id not in grouped:
            grouped[thread_id] = {
                "thread_id": thread_id,
                "user_name": None,
                "last_message": None,
                "intent": None,
                "timestamp": None,
                "total_messages": 0,
                "profile_snapshot": {},
                "user_messages": [],
                "bot_messages": []
            }
        
        g = grouped[thread_id]
        g["total_messages"] += 1
        
        profile_snap = doc.get("profile_snapshot") or {}
        g["user_name"] = profile_snap.get("name") or g["user_name"]
        g["last_message"] = doc.get("user_message") or g["last_message"]
        g["intent"] = doc.get("intent") or g["intent"]
        g["timestamp"] = doc.get("created_at") or g["timestamp"]
        g["profile_snapshot"] = profile_snap
        
        if doc.get("user_message"):
            g["user_messages"].append(doc["user_message"])
        if doc.get("bot_message"):
            g["bot_messages"].append(doc["bot_message"])

    # Pre-fetch all profiles to resolve N+1 query overhead.
    leads_by_thread = {l["thread_id"]: l["profile"] for l in leads_collection.find({"thread_id": {"$exists": True}}) if "profile" in l}
    support_by_thread = {s["thread_id"]: s["profile"] for s in support_collection.find({"thread_id": {"$exists": True}}) if "profile" in s}
    hiring_by_thread = {h["thread_id"]: h["profile"] for h in hiring_collection.find({"thread_id": {"$exists": True}}) if "profile" in h}
    meetings_by_thread = {m["thread_id"]: m["profile"] for m in meetings_collection.find({"thread_id": {"$exists": True}}) if "profile" in m}

    results = []
    for thread_id, g in grouped.items():
        merged_profile = dict(g["profile_snapshot"] or {})
        
        if thread_id in leads_by_thread:
            merged_profile.update(leads_by_thread[thread_id])
        if thread_id in support_by_thread:
            merged_profile.update(support_by_thread[thread_id])
        if thread_id in hiring_by_thread:
            merged_profile.update(hiring_by_thread[thread_id])
        if thread_id in meetings_by_thread:
            merged_profile.update(meetings_by_thread[thread_id])
                    
        user_name = merged_profile.get("name") or g["user_name"] or "Anonymous User"
        g["profile_snapshot"] = merged_profile
        g["user_name"] = user_name
        
        if q:
            q_lower = q.lower()
            match_q = (
                q_lower in thread_id.lower() or
                any(q_lower in msg.lower() for msg in g["user_messages"]) or
                any(q_lower in msg.lower() for msg in g["bot_messages"]) or
                q_lower in user_name.lower()
            )
            if not match_q:
                continue
                
        g.pop("user_messages", None)
        g.pop("bot_messages", None)
        
        results.append(format_chat_summary(g))
        
    results.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    return results


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
    profile = dict(latest_doc.get("profile_snapshot") or {})
    
    # Merge actual profile from completed collections.
    lead_doc = leads_collection.find_one({"thread_id": thread_id})
    if lead_doc and "profile" in lead_doc:
        profile.update(lead_doc["profile"])
    support_doc = support_collection.find_one({"thread_id": thread_id})
    if support_doc and "profile" in support_doc:
        profile.update(support_doc["profile"])
    hiring_doc = hiring_collection.find_one({"thread_id": thread_id})
    if hiring_doc and "profile" in hiring_doc:
        profile.update(hiring_doc["profile"])
    meeting_doc = meetings_collection.find_one({"thread_id": thread_id})
    if meeting_doc and "profile" in meeting_doc:
        profile.update(meeting_doc["profile"])
                
    name = profile.get("name") or extract_display_name(profile)
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
    if payload.url is not None:
        update_fields["url"] = payload.url
    if payload.connection_name is not None:
        update_fields["connection_name"] = payload.connection_name
    if payload.db_type is not None:
        update_fields["db_type"] = payload.db_type
    if payload.connection_string is not None:
        update_fields["connection_string"] = payload.connection_string
    if payload.db_name is not None:
        update_fields["db_name"] = payload.db_name
    if payload.target_collection is not None:
        update_fields["target_collection"] = payload.target_collection
    if payload.full_content is not None:
        update_fields["full_content"] = payload.full_content

    sources_collection.update_one({"_id": ObjectId(id)}, {"$set": update_fields})

    from rag.source_manager import process_and_chunk_source, process_database_source, process_website_source

    current_updated = sources_collection.find_one({"_id": ObjectId(id)})
    source_type = current_updated.get("type", "manual")
    intent_scope = current_updated.get("intent_scope")
    topic = current_updated.get("topic")
    service = current_updated.get("service")
    tags = current_updated.get("tags")

    num_chunks = None
    if source_type == "manual":
        content = current_updated.get("content", "")
        num_chunks = process_and_chunk_source(
            id,
            current_updated.get("title"),
            "manual",
            content,
            intent_scope=intent_scope,
            topic=topic,
            service=service,
            tags=tags
        )
    elif source_type == "document":
        title = current_updated.get("title", "")
        ext = os.path.splitext(title)[1].lower().replace(".", "") or "txt"
        content_to_use = current_updated.get("full_content") or current_updated.get("content") or ""
        num_chunks = process_and_chunk_source(
            id,
            title,
            ext,
            content_to_use,
            intent_scope=intent_scope,
            topic=topic,
            service=service,
            tags=tags
        )
    elif source_type == "database" or source_type.startswith("db_"):
        num_chunks = process_database_source(
            source_id=id,
            conn_name=current_updated.get("connection_name") or current_updated.get("title"),
            conn_string=current_updated.get("connection_string"),
            db_type=current_updated.get("db_type"),
            db_name=current_updated.get("db_name"),
            target_collection=current_updated.get("target_collection"),
            intent_scope=intent_scope,
            topic=topic,
            service=service,
            tags=tags
        )
    elif source_type == "website":
        website_content = current_updated.get("content")
        if website_content:
            num_chunks = process_and_chunk_source(
                id,
                current_updated.get("url"),
                "website",
                website_content,
                intent_scope=intent_scope,
                topic=topic,
                service=service,
                tags=tags
            )
        else:
            num_chunks = process_website_source(
                id,
                current_updated.get("url"),
                intent_scope=intent_scope,
                topic=topic,
                service=service,
                tags=tags
            )

    if num_chunks is not None:
        sources_collection.update_one(
            {"_id": ObjectId(id)},
            {"$set": {"num_chunks": num_chunks, "updated_at": datetime.utcnow().isoformat()}}
        )
    else:
        sources_collection.update_one(
            {"_id": ObjectId(id)},
            {"$set": {"updated_at": datetime.utcnow().isoformat()}}
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

    from rag.source_manager import process_website_source, build_website_content
    formatted_content = build_website_content(payload.url)

    source_doc = {
        "title": payload.url,
        "type": "website",
        "category": payload.category,
        "url": payload.url,
        "content": formatted_content,
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
