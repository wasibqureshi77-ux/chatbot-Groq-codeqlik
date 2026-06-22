from pymongo import MongoClient
from datetime import datetime
from bson import ObjectId
import asyncio
from config import MONGO_URI, MONGO_DB

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[MONGO_DB]

chats_collection = db["chats"]
leads_collection = db["client_leads"]
support_collection = db["support_tickets"]
hiring_collection = db["hiring_candidates"]
knowledge_sources_collection = db["knowledge_sources"]
knowledge_chunks_collection = db["knowledge_chunks"]
settings_collection = db["chatbot_settings"]
admin_users_collection = db["admin_users"]

# Aliases for compatibility
sources_collection = knowledge_sources_collection
chunks_collection = knowledge_chunks_collection


# Backend serialization and formatting helpers
def serialize_doc(doc):
    if not doc:
        return None
    serialized = dict(doc)
    if "_id" in serialized:
        serialized["id"] = str(serialized["_id"])
        serialized["_id"] = str(serialized["_id"])
    return serialized


def serialize_many(docs):
    return [serialize_doc(d) for d in docs]


def get_profile_value(doc, key, fallback=""):
    profile = doc.get("profile")
    if isinstance(profile, dict) and key in profile:
        val = profile[key]
        return val if val is not None else fallback
    snapshot = doc.get("profile_snapshot")
    if isinstance(snapshot, dict) and key in snapshot:
        val = snapshot[key]
        return val if val is not None else fallback
    if key in doc:
        val = doc[key]
        return val if val is not None else fallback
    return fallback


def extract_display_name(profile):
    if not profile or not isinstance(profile, dict):
        return "Anonymous User"
    return profile.get("name") or "Anonymous User"


def format_chat_summary(doc):
    thread_id = doc.get("thread_id") or doc.get("_id")
    profile = doc.get("profile_snapshot") or doc.get("profile") or {}
    name = doc.get("user_name") or extract_display_name(profile)
    latest_message = doc.get("last_message") or doc.get("user_message") or ""
    latest_intent = doc.get("intent") or ""
    total_messages = doc.get("total_messages") or 1
    last_active = doc.get("timestamp") or doc.get("created_at") or ""
    
    return {
        "thread_id": str(thread_id),
        "name": name,
        "latest_message": latest_message,
        "latest_intent": latest_intent,
        "total_messages": total_messages,
        "last_active": last_active,
        "profile": profile,
        
        # Compatibility keys for older frontend versions
        "user_name": name,
        "last_message": latest_message,
        "intent": latest_intent,
        "timestamp": last_active
    }


def format_thread_messages(docs):
    formatted = []
    for doc in docs:
        formatted.append({
            "user_message": doc.get("user_message", ""),
            "bot_message": doc.get("bot_message", ""),
            "intent": doc.get("intent", ""),
            "created_at": doc.get("created_at", "")
        })
    return formatted


def format_lead(doc):
    return {
        "id": str(doc.get("_id", "")),
        "name": get_profile_value(doc, "name", "N/A"),
        "email_or_phone": get_profile_value(doc, "email_or_phone", "N/A"),
        "company": get_profile_value(doc, "company", "N/A"),
        "project_type": get_profile_value(doc, "project_type", "N/A"),
        "requirements": get_profile_value(doc, "requirements", "N/A"),
        "budget": get_profile_value(doc, "budget", "N/A"),
        "timeline": get_profile_value(doc, "timeline", "N/A"),
        "status": doc.get("status", "New"),
        "created_at": doc.get("created_at", ""),
        "updated_at": doc.get("updated_at", "")
    }


def format_support_ticket(doc):
    return {
        "id": str(doc.get("_id", "")),
        "name": get_profile_value(doc, "name", "N/A"),
        "email_or_phone": get_profile_value(doc, "email_or_phone", "N/A"),
        "issue_type": get_profile_value(doc, "issue_type", "N/A"),
        "issue_details": get_profile_value(doc, "issue_details", "N/A"),
        "urgency": get_profile_value(doc, "urgency", "Medium"),
        "status": doc.get("status", "Open"),
        "created_at": doc.get("created_at", ""),
        "updated_at": doc.get("updated_at", "")
    }


def format_hiring_candidate(doc):
    return {
        "id": str(doc.get("_id", "")),
        "name": get_profile_value(doc, "name", "N/A"),
        "email": get_profile_value(doc, "email", "N/A"),
        "phone": get_profile_value(doc, "phone", "N/A"),
        "role": get_profile_value(doc, "role", "N/A"),
        "experience": get_profile_value(doc, "experience", "N/A"),
        "skills": get_profile_value(doc, "skills", "N/A"),
        "resume_or_portfolio": doc.get("resume_or_portfolio", ""),
        "status": doc.get("status", "Applied"),
        "created_at": doc.get("created_at", ""),
        "updated_at": doc.get("updated_at", "")
    }



# Default settings in case collection is empty
DEFAULT_SETTINGS = {
    # Snake_case fields for existing backend compatibility
    "company_name": "CodeQlik",
    "company_description": "CodeQlik provides software development, AI automation, web apps, mobile apps, CRM systems, SaaS solutions, cloud services, and IT consulting.",
    "contact_email": "info@codeqlik.com",
    "contact_phone": "+91-8949687368",
    "chatbot_greeting": "Hi! How can we help you today?",
    "fallback_message": "I am the official company support assistant and can assist with company services, support requests, project inquiries, hiring, and company-related information.",
    "support_email": "info@codeqlik.com",
    "support_phone": "+91-8949687368",

    # CamelCase fields for public/widget settings
    "companyName": "CodeQlik",
    "companyDescription": "CodeQlik provides software development, AI automation, web apps, mobile apps, CRM systems, SaaS solutions, cloud services, and IT consulting.",
    "fallbackMessage": "I am the official company support assistant and can assist with company services, support requests, project inquiries, hiring, and company-related information.",
    "generalEmail": "info@codeqlik.com",
    "generalPhone": "+91-8949687368",
    "supportEmail": "info@codeqlik.com",
    "supportPhone": "+91-8949687368",

    # UI/Widget fields
    "title": "CodeQlik Assistant",
    "subtitle": "Usually replies instantly",
    "welcomeMessage": "Hi! How can we help you today?",
    "placeholder": "Type your message...",
    "primaryColor": "#ff7e21",
    "theme": "light",
    "position": "bottom-right",
    "width": "480px",
    "height": "680px",
    "logoUrl": "",
    "botAvatar": "CQ",
    "launcherIcon": "💬",
    "launcherText": "",
    "showNewChat": True,
    "footerText": "Powered by CodeQlik",
    "suggestions": [],
    "storage": "local"
}


def now_iso():
    return datetime.utcnow().isoformat()


def broadcast_event(event_type: str, data: dict):
    """Broadcasting utility calling the realtime connection manager task loop."""
    try:
        from realtime import manager
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(manager.broadcast({"type": event_type, "data": data}))
            # Also notify dashboard panel to update counter badges
            loop.create_task(manager.broadcast({"type": "dashboard_updated", "data": {}}))
        else:
            asyncio.run(manager.broadcast({"type": event_type, "data": data}))
            asyncio.run(manager.broadcast({"type": "dashboard_updated", "data": {}}))
    except Exception:
        pass


def get_chatbot_settings():
    settings = settings_collection.find_one({"type": "chatbot_settings"})
    if not settings:
        doc = dict(DEFAULT_SETTINGS)
        doc["type"] = "chatbot_settings"
        doc["created_at"] = now_iso()
        doc["updated_at"] = now_iso()
        settings_collection.insert_one(doc)
        settings = doc
    else:
        # Auto-upgrade settings with missing fields
        missing_updates = {}
        for key, val in DEFAULT_SETTINGS.items():
            if key not in settings:
                missing_updates[key] = val
        if missing_updates:
            settings_collection.update_one({"type": "chatbot_settings"}, {"$set": missing_updates})
            settings.update(missing_updates)

    if "_id" in settings:
        settings["_id"] = str(settings["_id"])
    return settings


def update_chatbot_settings(data: dict):
    settings = get_chatbot_settings()
    
    # Extract keys supporting both naming styles to avoid issues
    c_name = data.get("companyName", data.get("company_name", settings.get("company_name")))
    c_desc = data.get("companyDescription", data.get("company_description", settings.get("company_description")))
    fallback = data.get("fallbackMessage", data.get("fallback_message", settings.get("fallback_message")))
    g_email = data.get("generalEmail", data.get("contact_email", settings.get("contact_email")))
    g_phone = data.get("generalPhone", data.get("contact_phone", settings.get("contact_phone")))
    s_email = data.get("supportEmail", data.get("support_email", settings.get("support_email")))
    s_phone = data.get("supportPhone", data.get("support_phone", settings.get("support_phone")))
    w_msg = data.get("welcomeMessage", data.get("chatbot_greeting", settings.get("chatbot_greeting")))
    
    update_data = {
        # Snake_case keys
        "company_name": c_name,
        "company_description": c_desc,
        "contact_email": g_email,
        "contact_phone": g_phone,
        "chatbot_greeting": w_msg,
        "fallback_message": fallback,
        "support_email": s_email,
        "support_phone": s_phone,

        # CamelCase keys
        "companyName": c_name,
        "companyDescription": c_desc,
        "fallbackMessage": fallback,
        "generalEmail": g_email,
        "generalPhone": g_phone,
        "supportEmail": s_email,
        "supportPhone": s_phone,

        # UI/Widget fields
        "title": data.get("title", settings.get("title")),
        "subtitle": data.get("subtitle", settings.get("subtitle")),
        "welcomeMessage": w_msg,
        "placeholder": data.get("placeholder", settings.get("placeholder")),
        "primaryColor": data.get("primaryColor", settings.get("primaryColor")),
        "theme": data.get("theme", settings.get("theme")),
        "position": data.get("position", settings.get("position")),
        "width": data.get("width", settings.get("width")),
        "height": data.get("height", settings.get("height")),
        "logoUrl": data.get("logoUrl", settings.get("logoUrl", "")),
        "botAvatar": data.get("botAvatar", settings.get("botAvatar")),
        "launcherIcon": data.get("launcherIcon", settings.get("launcherIcon")),
        "launcherText": data.get("launcherText", settings.get("launcherText", "")),
        "showNewChat": data.get("showNewChat", settings.get("showNewChat")),
        "footerText": data.get("footerText", settings.get("footerText")),
        "suggestions": data.get("suggestions", settings.get("suggestions")),
        "storage": data.get("storage", settings.get("storage")),
        "updated_at": now_iso()
    }
    settings_collection.update_one({"type": "chatbot_settings"}, {"$set": update_data})
    
    # Broadcast settings update event
    broadcast_event("settings_updated", update_data)
    
    return get_chatbot_settings()



def save_chat_to_mongo(thread_id, user_message, bot_message, intent, profile):
    created_at = now_iso()
    doc = {
        "thread_id": thread_id,
        "user_message": user_message,
        "bot_message": bot_message,
        "intent": intent,
        "profile_snapshot": profile,
        "created_at": created_at
    }
    chats_collection.insert_one(doc)
    
    # Clean ID for serialization
    doc["_id"] = str(doc["_id"])
    broadcast_event("chat_created", doc)


def save_collection_data(intent, thread_id, profile):
    # Filter profile to only include keys relevant to this specific collection/intent
    allowed_keys = {
        "client_lead": ["name", "email_or_phone", "company", "project_type", "requirements", "budget", "timeline"],
        "customer_support": ["name", "email_or_phone", "issue_type", "issue_details", "urgency"],
        "hiring_support": ["name", "email", "phone", "role", "experience", "skills", "resume_or_portfolio"]
    }.get(intent, [])
    
    filtered_profile = {k: v for k, v in profile.items() if k in allowed_keys}

    document = {
        "thread_id": thread_id,
        "intent": intent,
        "profile": filtered_profile,
        "updated_at": now_iso()
    }

    update = {
        "$set": document,
        "$setOnInsert": {
            "created_at": now_iso()
        }
    }

    if intent == "client_lead":
        leads_collection.update_one({"thread_id": thread_id}, update, upsert=True)
        saved = leads_collection.find_one({"thread_id": thread_id})
        saved["_id"] = str(saved["_id"])
        broadcast_event("lead_created_or_updated", saved)

    elif intent == "customer_support":
        support_collection.update_one({"thread_id": thread_id}, update, upsert=True)
        saved = support_collection.find_one({"thread_id": thread_id})
        saved["_id"] = str(saved["_id"])
        broadcast_event("support_created_or_updated", saved)

    elif intent == "hiring_support":
        hiring_collection.update_one({"thread_id": thread_id}, update, upsert=True)
        saved = hiring_collection.find_one({"thread_id": thread_id})
        saved["_id"] = str(saved["_id"])
        broadcast_event("hiring_created_or_updated", saved)


# Initialize default settings and default knowledge sources + chunks if empty
def initialize_knowledge_sources():
    if sources_collection.count_documents({}) == 0:
        source_doc = {
            "title": "Default CodeQlik Base Info",
            "type": "manual",
            "category": "Company Information",
            "content": "CodeQlik provides custom web development, mobile app development, AI chatbot building (RAG / AI agents), SaaS, CRM dashboard building, and cloud services. Email: info@codeqlik.com. Phone: +91-8949687368. Jaipur, Rajasthan, India.",
            "enabled": True,
            "created_at": now_iso(),
            "updated_at": now_iso()
        }
        res = sources_collection.insert_one(source_doc)
        source_id = str(res.inserted_id)
        
        from rag.chunker import split_text
        text_chunks = split_text(source_doc["content"], chunk_size=800, chunk_overlap=150)
        chunk_docs = []
        for idx, chunk in enumerate(text_chunks):
            chunk_docs.append({
                "source_id": source_id,
                "source_name": source_doc["title"],
                "source_type": source_doc["type"],
                "chunk_index": idx,
                "chunk_text": chunk,
                "upload_date": now_iso()
            })
        if chunk_docs:
            chunks_collection.insert_many(chunk_docs)

initialize_knowledge_sources()
get_chatbot_settings()


# ---------------------------------------------------------------------------
# Admin user helpers (credentials stored in DB, not in .env)
# ---------------------------------------------------------------------------

def get_admin_user(username: str):
    """Return the admin user document for *username*, or None if not found."""
    return admin_users_collection.find_one({"username": username})


def upsert_admin_user(username: str, password_hash: str):
    """Insert or replace the admin user record in the database."""
    admin_users_collection.update_one(
        {"username": username},
        {
            "$set": {
                "username": username,
                "password_hash": password_hash,
                "updated_at": now_iso()
            },
            "$setOnInsert": {"created_at": now_iso()}
        },
        upsert=True
    )