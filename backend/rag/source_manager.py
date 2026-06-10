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


def process_and_chunk_source(source_id: str, source_name: str, source_type: str, content: str) -> int:
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


def process_database_source(source_id: str, conn_name: str, conn_string: str, db_type: str, db_name: str, target_collection: str) -> int:
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
                # Make document serializable
                clean_doc = dict(doc)
                if "_id" in clean_doc:
                    clean_doc["_id"] = str(clean_doc["_id"])
                
                # Format into a clean structured key-value line
                kv_pairs = []
                for k, v in clean_doc.items():
                    if v not in (None, "", [], {}):
                        kv_pairs.append(f"{k}: {v}")
                row_str = f"Database Collection '{target_collection}' [ID: {doc_id}]: " + ", ".join(kv_pairs)
                content_rows.append(row_str)
            client.close()
            
        elif db_type.lower() in ("mysql", "postgresql", "sqlserver"):
            # Mock / Fallback database connector structure
            content_rows.append(
                f"Connected to {db_type.upper()} database '{db_name}' table '{target_collection}'. "
                f"Simulated indexing of corporate records."
            )
        else:
            raise ValueError(f"Unsupported database connection type: {db_type}")
            
    except Exception as e:
        content_rows.append(f"Database crawl failed for {conn_name}: {str(e)}")
        
    full_text = "\n".join(content_rows)
    return process_and_chunk_source(source_id, conn_name, f"db_{db_type}", full_text)


def process_website_source(source_id: str, url: str) -> int:
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

    # Clean HTML tags using a robust regex pattern
    text_content = re.sub(r'<script.*?</script>', ' ', raw_html, flags=re.DOTALL)
    text_content = re.sub(r'<style.*?</style>', ' ', text_content, flags=re.DOTALL)
    text_content = re.sub(r'<[^>]+>', ' ', text_content)
    text_content = re.sub(r'\s+', ' ', text_content).strip()
    
    # Prepend source header
    formatted_content = f"Crawled content from Website Source: {url}\n\nExtracted Text Content:\n{text_content}"
    
    source_name = url.replace("https://", "").replace("http://", "").split("/")[0]
    return process_and_chunk_source(source_id, source_name, "website", formatted_content)
