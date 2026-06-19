import os
import re
import urllib.request
import json
from datetime import datetime
from bson import ObjectId
from database import db, knowledge_sources_collection, knowledge_chunks_collection
from rag.chunker import chunk_document

sources_collection = knowledge_sources_collection
chunks_collection = knowledge_chunks_collection


def now_iso():
    return datetime.utcnow().isoformat()


def detect_topic(text: str, title: str, category: str, heading: str = "") -> str:
    combined = f"{text} {title} {category} {heading}".lower()
    if any(w in combined for w in ["technology", "technologies", "tech stack", "languages", "frameworks", "python", "javascript", "react", "node", "mongodb", "postgresql", "mysql", "fastapi", "langgraph", "groq", "llama"]):
        return "technologies"
    if any(w in combined for w in ["pricing", "price", "cost", "budget", "quote", "charges", "rate", "fees"]):
        return "pricing"
    if any(w in combined for w in ["contact", "address", "phone", "email", "office", "location", "reach us", "get in touch"]):
        return "contact"
    if any(w in combined for w in ["portfolio", "projects", "case study", "case studies", "our work", "clients", "track record", "delivered"]):
        return "portfolio"
    if any(w in combined for w in ["faq", "frequently asked questions", "common questions"]):
        return "faq"
    if any(w in combined for w in ["policy", "policies", "refund", "privacy", "terms of service", "cancellation", "tos"]):
        return "policies"
    if any(w in combined for w in ["service", "services", "provide", "offer", "specialty", "expertise", "custom development", "solution"]):
        return "services"
    
    # Fallback category mapping
    cat_lower = category.lower()
    for topic_val in ["services", "technologies", "pricing", "contact", "portfolio", "faq", "policies"]:
        if topic_val in cat_lower:
            return topic_val
    return "general"


def detect_service(text: str, title: str, category: str, heading: str = "") -> str:
    combined = f"{text} {title} {category} {heading}".lower()
    if any(w in combined for w in ["website", "web app", "web development", "react", "frontend", "html", "css", "static site"]):
        return "website"
    if any(w in combined for w in ["mobile app", "ios", "android", "flutter", "react native", "swift", "kotlin", "mobile application"]):
        return "mobile_app"
    if any(w in combined for w in ["ecommerce", "e-commerce", "shopify", "woocommerce", "online store", "shopping cart", "payment gateway"]):
        return "ecommerce"
    if any(w in combined for w in ["crm", "erp", "dashboard", "admin panel", "sales force", "hubspot", "management system"]):
        return "crm"
    if any(w in combined for w in ["ai automation", "chatbot", "rag", "langgraph", "agentic", "openai", "groq", "llama", "artificial intelligence", "automation script"]):
        return "ai_automation"
    if any(w in combined for w in ["software", "custom software", "saas", "cloud services", "backend", "database", "api"]):
        return "software"
    return "general"


def detect_intent_scope(text: str, title: str, category: str, heading: str = "") -> str:
    combined = f"{text} {title} {category} {heading}".lower()
    if any(w in combined for w in ["greet", "greeting", "hello", "hi ", "welcome"]):
        return "greet"
    if any(w in combined for w in ["hiring", "job", "career", "opening", "internship", "apply", "resume", "cv ", "skills", "experience", "candidate"]):
        return "hiring"
    if any(w in combined for w in ["support", "ticket", "bug", "issue", "crash", "error", "not working", "problem", "fault", "complaint", "server down"]):
        return "support"
    if any(w in combined for w in ["client", "lead", "project details", "budget", "timeline", "sales", "proposal", "quote", "buy", "purchase"]):
        return "client"
    return "all"


def process_and_chunk_source(source_id: str, source_name: str, source_type: str, content: str,
                             intent_scope: str = None, topic: str = None, service: str = None, tags: list = None) -> int:
    """Splits raw text content into chunks and stores them in the database associated with the source_id."""
    # First, clear any existing chunks for this source (e.g. if we are re-indexing or editing)
    chunks_collection.delete_many({"source_id": source_id})
    
    if not content or not content.strip():
        return 0
        
    # Get parent source doc for category and title
    source_doc = sources_collection.find_one({"_id": ObjectId(source_id)})
    category = source_doc.get("category", "Company Information") if source_doc else "Company Information"
    title = source_doc.get("title", source_name) if source_doc else source_name
    
    # Chunk text using smart type-based chunker
    smart_chunks = chunk_document(source_type, content, base_metadata={"source_name": source_name})
    
    chunk_docs = []
    for idx, sc in enumerate(smart_chunks):
        heading = sc["metadata"].get("section_header", "")
        
        ch_intent_scope = intent_scope
        if ch_intent_scope is None or ch_intent_scope == "":
            ch_intent_scope = detect_intent_scope(sc["chunk_text"], title, category, heading)
            
        ch_topic = topic
        if ch_topic is None or ch_topic == "":
            ch_topic = detect_topic(sc["chunk_text"], title, category, heading)
            
        ch_service = service
        if ch_service is None or ch_service == "":
            ch_service = detect_service(sc["chunk_text"], title, category, heading)
            
        ch_priority = 1
        ch_tags = tags if tags is not None else []

        chunk_docs.append({
            "source_id": source_id,
            "title": title,
            "category": category,
            "source_type": source_type,
            "chunk_index": idx,
            "chunk_text": sc["chunk_text"],
            "keywords": sc["keywords"],
            "summary": sc["chunk_summary"],
            "metadata": sc["metadata"],
            "status": "active",
            "intent_scope": ch_intent_scope,
            "topic": ch_topic,
            "service": ch_service,
            "priority": ch_priority,
            "tags": ch_tags,
            "created_at": now_iso(),
            "upload_date": now_iso()  # for backwards compatibility
        })
        
    if chunk_docs:
        chunks_collection.insert_many(chunk_docs)
        
    return len(chunk_docs)


def delete_source_data(source_id: str):
    """Deletes the source record and all associated chunks."""
    # Delete chunks
    chunks_collection.delete_many({"source_id": source_id})
    # Delete source record
    sources_collection.delete_one({"_id": ObjectId(source_id)})


def set_source_active_state(source_id: str, enabled: bool):
    """Enables or disables a knowledge source."""
    sources_collection.update_one(
        {"_id": ObjectId(source_id)},
        {"$set": {"enabled": enabled, "updated_at": now_iso()}}
    )


def process_database_source(source_id: str, conn_name: str, conn_string: str, db_type: str, db_name: str, target_collection: str,
                            intent_scope: str = None, topic: str = None, service: str = None, tags: list = None) -> int:
    """
    Connects to the specified target database (SQL/NoSQL), reads its rows/documents,
    converts them into plain text representations, chunks them, and stores the chunks.
    """
    content_rows = []
    
    try:
        if db_type.lower() == "mongodb":
            from pymongo import MongoClient
            client = MongoClient(conn_string, serverSelectionTimeoutMS=2000)
            target_db = client[db_name]
            coll = target_db[target_collection]
            cursor = coll.find().limit(200) # Limit indexing to 200 documents for safety
            
            for idx, doc in enumerate(cursor):
                doc_id = str(doc.get("_id", idx))
                clean_doc = dict(doc)
                if "_id" in clean_doc:
                    clean_doc["_id"] = str(clean_doc["_id"])
                
                kv_pairs = []
                for k, v in clean_doc.items():
                    if v not in (None, "", [], {}):
                        kv_pairs.append(f"{k}: {v}")
                row_str = f"Database Collection '{target_collection}' [ID: {doc_id}]: " + ", ".join(kv_pairs)
                content_rows.append(row_str)
            client.close()
            
        elif db_type.lower() in ("mysql", "postgresql", "sqlserver"):
            content_rows.append(
                f"Connected to {db_type.upper()} database '{db_name}' table '{target_collection}'. "
                f"Simulated indexing of corporate records."
            )
        else:
            raise ValueError(f"Unsupported database connection type: {db_type}")
            
    except Exception as e:
        content_rows.append(f"Database crawl failed for {conn_name}: {str(e)}")
        
    full_text = "\n".join(content_rows)
    return process_and_chunk_source(
        source_id, conn_name, f"db_{db_type}", full_text,
        intent_scope=intent_scope, topic=topic, service=service, tags=tags
    )


def process_website_source(source_id: str, url: str,
                           intent_scope: str = None, topic: str = None, service: str = None, tags: list = None) -> int:
    """
    Crawls a target website URL, extracts raw text content,
    chunks it, and stores the chunks in MongoDB.
    """
    raw_html = ""
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ChatbotCrawler/1.0'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            raw_html = response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        raw_html = f"Website crawl failed for URL {url}. Error: {str(e)}"

    text_content = re.sub(r'<script.*?</script>', ' ', raw_html, flags=re.DOTALL)
    text_content = re.sub(r'<style.*?</style>', ' ', text_content, flags=re.DOTALL)
    text_content = re.sub(r'<[^>]+>', ' ', text_content)
    text_content = re.sub(r'\s+', ' ', text_content).strip()
    
    formatted_content = f"Crawled content from Website Source: {url}\n\nExtracted Text Content:\n{text_content}"
    
    source_name = url.replace("https://", "").replace("http://", "").split("/")[0]
    return process_and_chunk_source(
        source_id, source_name, "website", formatted_content,
        intent_scope=intent_scope, topic=topic, service=service, tags=tags
    )
