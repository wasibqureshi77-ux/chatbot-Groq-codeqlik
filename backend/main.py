from fastapi import FastAPI, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from bson import ObjectId
import os
import shutil

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


class SettingsUpdate(BaseModel):
    company_name: str
    company_description: str
    contact_email: str
    contact_phone: str
    chatbot_greeting: str
    fallback_message: str
    support_email: str
    support_phone: str


class ManualSourceCreate(BaseModel):
    title: str
    category: str
    content: str


class ManualSourceUpdate(BaseModel):
    title: str = None
    category: str = None
    content: str = None
    enabled: bool = None


class DatabaseConnectionRequest(BaseModel):
    connection_name: str
    db_type: str
    connection_string: str
    db_name: str
    target_collection: str
    category: str = "Company Information"


class WebsiteSourceRequest(BaseModel):
    url: str
    category: str = "Company Information"


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

@app.post("/api/chat")
def chat(req: ChatRequest):
    return send_message(
        user_input=req.message,
        thread_id=req.thread_id
    )


@app.get("/api/settings")
def get_settings():
    return get_chatbot_settings()


# DASHBOARD ENDPOINT

@app.get("/api/admin/dashboard")
def get_dashboard():
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

@app.put("/api/admin/settings")
def update_settings(payload: SettingsUpdate):
    return update_chatbot_settings(payload.dict())


# CHATS PAGE

@app.get("/api/admin/chats")
def get_chats_summaries(q: str = None, intent: str = None):
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
def get_thread_chats(thread_id: str):
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
def get_leads(q: str = None, status: str = None):
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
def update_lead_status(id: str, payload: StatusUpdate):
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
def get_support_tickets(q: str = None, status: str = None, priority: str = None):
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
def update_support_status(id: str, payload: SupportStatusUpdate):
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
def get_hiring_candidates(q: str = None, status: str = None):
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
def update_hiring_status(id: str, payload: StatusUpdate):
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
def get_knowledge_sources(q: str = None, type: str = None):
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
def create_manual_source(payload: ManualSourceCreate):
    source_doc = {
        "title": payload.title,
        "type": "manual",
        "category": payload.category,
        "content": payload.content,
        "enabled": True,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    res = sources_collection.insert_one(source_doc)
    source_id = str(res.inserted_id)

    from rag.source_manager import process_and_chunk_source
    num_chunks = process_and_chunk_source(source_id, payload.title, "manual", payload.content)

    sources_collection.update_one(
        {"_id": ObjectId(source_id)},
        {"$set": {"num_chunks": num_chunks}}
    )

    source_doc["_id"] = source_id
    source_doc["num_chunks"] = num_chunks
    return clean_mongo_doc(source_doc)


@app.put("/api/admin/knowledge/{id}")
def update_knowledge_source(id: str, payload: ManualSourceUpdate):
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

    sources_collection.update_one({"_id": ObjectId(id)}, {"$set": update_fields})

    # If content changed for a manual source, re-chunk
    if payload.content is not None and current.get("type") == "manual":
        from rag.source_manager import process_and_chunk_source
        num_chunks = process_and_chunk_source(
            id,
            payload.title or current.get("title"),
            "manual",
            payload.content
        )
        sources_collection.update_one(
            {"_id": ObjectId(id)},
            {"$set": {"num_chunks": num_chunks}}
        )

    updated = sources_collection.find_one({"_id": ObjectId(id)})
    return clean_mongo_doc(updated)


@app.delete("/api/admin/knowledge/{id}")
def delete_knowledge_source(id: str):
    from rag.source_manager import delete_source_data
    delete_source_data(id)
    return {"message": "Source deleted successfully"}


@app.post("/api/admin/knowledge/upload")
def upload_knowledge_file(
    file: UploadFile = File(...),
    category: str = Form("Company Information")
):
    os.makedirs("./temp_uploads", exist_ok=True)
    temp_path = f"./temp_uploads/{file.filename}"
    with open(temp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        from rag.loader import load_any_file
        doc = load_any_file(temp_path)

        source_doc = {
            "title": file.filename,
            "type": "document",
            "category": category,
            "content": doc.content[:1000] + "... [Parsed Document File]",
            "enabled": True,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        res = sources_collection.insert_one(source_doc)
        source_id = str(res.inserted_id)

        from rag.source_manager import process_and_chunk_source
        num_chunks = process_and_chunk_source(source_id, file.filename, doc.metadata.get("source_type", "document"), doc.content)

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
def create_database_source(payload: DatabaseConnectionRequest):
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
        target_collection=payload.target_collection
    )

    sources_collection.update_one(
        {"_id": ObjectId(source_id)},
        {"$set": {"num_chunks": num_chunks}}
    )

    source_doc["_id"] = source_id
    source_doc["num_chunks"] = num_chunks
    return clean_mongo_doc(source_doc)


@app.post("/api/admin/sources/website")
def create_website_source(payload: WebsiteSourceRequest):
    source_doc = {
        "title": payload.url,
        "type": "website",
        "category": payload.category,
        "url": payload.url,
        "enabled": True,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    res = sources_collection.insert_one(source_doc)
    source_id = str(res.inserted_id)

    from rag.source_manager import process_website_source
    num_chunks = process_website_source(
        source_id=source_id,
        url=payload.url
    )

    sources_collection.update_one(
        {"_id": ObjectId(source_id)},
        {"$set": {"num_chunks": num_chunks}}
    )

    source_doc["_id"] = source_id
    source_doc["num_chunks"] = num_chunks
    return clean_mongo_doc(source_doc)


@app.put("/api/admin/knowledge/{id}/enable")
def enable_knowledge_source(id: str):
    sources_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"enabled": True, "updated_at": datetime.utcnow().isoformat()}}
    )
    doc = sources_collection.find_one({"_id": ObjectId(id)})
    return clean_mongo_doc(doc)


@app.put("/api/admin/knowledge/{id}/disable")
def disable_knowledge_source(id: str):
    sources_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"enabled": False, "updated_at": datetime.utcnow().isoformat()}}
    )
    doc = sources_collection.find_one({"_id": ObjectId(id)})
    return clean_mongo_doc(doc)


@app.post("/api/admin/knowledge/{id}/reindex")
def reindex_knowledge_source(id: str):
    current = sources_collection.find_one({"_id": ObjectId(id)})
    if not current:
        raise HTTPException(status_code=404, detail="Source not found")

    from rag.source_manager import process_and_chunk_source, process_database_source, process_website_source

    num_chunks = 0
    t = current.get("type", "manual")
    if t == "manual":
        num_chunks = process_and_chunk_source(id, current.get("title"), "manual", current.get("content"))
    elif t.startswith("db_") or t == "database":
        num_chunks = process_database_source(
            id,
            current.get("title"),
            current.get("connection_string"),
            current.get("db_type"),
            current.get("db_name"),
            current.get("target_collection")
        )
    elif t == "website":
        num_chunks = process_website_source(id, current.get("url"))
        # Document re-indexes current parsed content
        title = current.get("title", "")
        ext = os.path.splitext(title)[1].lower().replace(".", "") or "txt"
        num_chunks = process_and_chunk_source(id, title, ext, current.get("content"))

    sources_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": {"num_chunks": num_chunks, "updated_at": datetime.utcnow().isoformat()}}
    )

    updated = sources_collection.find_one({"_id": ObjectId(id)})
    return clean_mongo_doc(updated)


@app.get("/api/admin/knowledge/sync-status")
def get_knowledge_sync_status():
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