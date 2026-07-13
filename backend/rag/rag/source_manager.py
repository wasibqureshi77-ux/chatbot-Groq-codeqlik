import os
import re
import urllib.request
from urllib.parse import urljoin, urlparse, urldefrag
import json
from datetime import datetime
from bson import ObjectId
from database import db, knowledge_sources_collection, knowledge_chunks_collection
from rag.chunker import chunk_document
from bs4 import BeautifulSoup

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
    
    # Embed chunks in a single batch to maximize execution performance
    from rag.embeddings import embeddings_model
    chunk_texts = [sc["chunk_text"] for sc in smart_chunks]
    embeddings = embeddings_model.embed_documents(chunk_texts) if chunk_texts else []

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
            "embedding": embeddings[idx] if idx < len(embeddings) else None,
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




# -----------------------------
# Website scraping helpers
# -----------------------------

SKIP_URL_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".pdf", ".zip", ".rar", ".7z",
    ".mp4", ".mp3", ".avi", ".mov", ".webm",
    ".css", ".js", ".map",
    ".woff", ".woff2", ".ttf", ".eot",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"
)


def _clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _normalize_url(url: str) -> str:
    url, _fragment = urldefrag(url)
    parsed = urlparse(url)

    scheme = parsed.scheme or "https"
    netloc = parsed.netloc.lower()
    path = re.sub(r"/+", "/", parsed.path or "/")

    if path != "/" and path.endswith("/"):
        path = path[:-1]

    # Remove tracking params
    query = parsed.query
    if query:
        kept = []
        for part in query.split("&"):
            key = part.split("=", 1)[0].lower()
            if not (key.startswith("utm_") or key in {"fbclid", "gclid", "mc_cid", "mc_eid"}):
                kept.append(part)
        query = "&".join(kept)

    return f"{scheme}://{netloc}{path}" + (f"?{query}" if query else "")


def _same_domain(url: str, base_domain: str) -> bool:
    netloc = urlparse(url).netloc.lower().replace("www.", "")
    return netloc == base_domain


def _is_scrapable_url(url: str, base_domain: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False

    if not _same_domain(url, base_domain):
        return False

    lower_url = url.lower()
    if lower_url.endswith(SKIP_URL_EXTENSIONS):
        return False

    skip_parts = [
        "/wp-admin", "/admin", "/login", "/signup",
        "/cart", "/checkout", "/account",
        "mailto:", "tel:", "javascript:",
    ]
    if any(part in lower_url for part in skip_parts):
        return False

    return True


def _fetch_html(url: str, timeout: int = 10):
    """
    Returns: (status_code, content_type, html_text)
    Uses urllib so this file does not require requests.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "ChatbotCrawler/1.0"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )

    with urllib.request.urlopen(req, timeout=timeout) as response:
        status_code = getattr(response, "status", 200)
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type.lower():
            return status_code, content_type, ""
        raw = response.read()
        html = raw.decode("utf-8", errors="ignore")
        return status_code, content_type, html


def _extract_website_text(html: str, url: str) -> str:
    """
    Extracts structured, RAG-friendly text from one HTML page.
    Requires: beautifulsoup4
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove noise
    for tag in soup([
        "script", "style", "noscript", "iframe", "svg",
        "header", "footer", "nav",
    ]):
        tag.decompose()

    title = _clean_space(soup.title.get_text(" ")) if soup.title else ""

    meta_description = ""
    meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    if meta and meta.get("content"):
        meta_description = _clean_space(meta.get("content"))

    headings = []
    for tag in soup.find_all(["h1", "h2", "h3"]):
        txt = _clean_space(tag.get_text(" "))
        if txt:
            headings.append(txt)

    paragraphs = []
    for tag in soup.find_all("p"):
        txt = _clean_space(tag.get_text(" "))
        if len(txt) >= 25:
            paragraphs.append(txt)

    list_items = []
    for tag in soup.find_all("li"):
        txt = _clean_space(tag.get_text(" "))
        if len(txt) >= 3:
            list_items.append(txt)

    table_texts = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [_clean_space(cell.get_text(" ")) for cell in tr.find_all(["th", "td"])]
            cells = [c for c in cells if c]
            if cells:
                rows.append(" | ".join(cells))
        if rows:
            table_texts.append("\n".join(rows))

    image_alts = []
    for img in soup.find_all("img"):
        alt = _clean_space(img.get("alt", ""))
        if alt:
            image_alts.append(alt)

    def dedupe(items):
        seen = set()
        result = []
        for item in items:
            key = item.lower()
            if key not in seen:
                result.append(item)
                seen.add(key)
        return result

    headings = dedupe(headings)
    paragraphs = dedupe(paragraphs)
    list_items = dedupe(list_items)
    image_alts = dedupe(image_alts)

    page_text = f"""
Website URL: {url}

Page Title:
{title}

Meta Description:
{meta_description}

Headings:
{chr(10).join("- " + h for h in headings)}

Paragraphs:
{chr(10).join(paragraphs)}

List Items:
{chr(10).join("- " + item for item in list_items)}

Tables:
{chr(10).join(table_texts)}

Image Alt Text:
{chr(10).join("- " + alt for alt in image_alts)}
"""

    return _clean_space(page_text)


def _extract_internal_links(html: str, current_url: str, base_domain: str, limit: int = 100):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()

    for a in soup.find_all("a", href=True):
        absolute = _normalize_url(urljoin(current_url, a["href"].strip()))
        if absolute in seen:
            continue
        if _is_scrapable_url(absolute, base_domain):
            links.append(absolute)
            seen.add(absolute)
        if len(links) >= limit:
            break

    return links


def _discover_sitemap_urls(start_url: str, base_domain: str, timeout: int = 10, max_urls: int = 100):
    """
    Basic sitemap.xml reader. Keeps same-domain HTML-looking URLs only.
    """
    parsed = urlparse(start_url)
    sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"

    try:
        req = urllib.request.Request(
            sitemap_url,
            headers={"User-Agent": "Mozilla/5.0 ChatbotCrawler/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            xml_text = response.read().decode("utf-8", errors="ignore")
    except Exception:
        return []

    urls = re.findall(r"<loc>\s*(.*?)\s*</loc>", xml_text, flags=re.I)
    cleaned = []
    seen = set()

    for u in urls:
        u = _normalize_url(u)
        if u.endswith(".xml"):
            continue
        if u not in seen and _is_scrapable_url(u, base_domain):
            cleaned.append(u)
            seen.add(u)
        if len(cleaned) >= max_urls:
            break

    return cleaned


def build_website_content(url: str, max_pages: int = 15, timeout: int = 10, delay_seconds: float = 0.3) -> str:
    """Fetches and formats website content without storing chunks."""
    if not url:
        return ""

    url = _normalize_url(url)
    parsed = urlparse(url)

    if not parsed.netloc:
        print(f"[Website Build Skipped] Invalid URL: {url}")
        return ""

    base_domain = parsed.netloc.lower().replace("www.", "")
    queue = [url]
    visited = set()
    page_texts = []

    for sitemap_url in _discover_sitemap_urls(url, base_domain, timeout=timeout, max_urls=max_pages * 3):
        if sitemap_url not in queue:
            queue.append(sitemap_url)

    while queue and len(page_texts) < max_pages:
        current_url = queue.pop(0)

        if current_url in visited:
            continue
        visited.add(current_url)

        if not _is_scrapable_url(current_url, base_domain):
            continue

        try:
            status_code, content_type, html = _fetch_html(current_url, timeout=timeout)

            if status_code != 200:
                print(f"[Website Build Skipped] URL={current_url}, Status={status_code}")
                continue

            if not html:
                print(f"[Website Build Skipped] URL={current_url}, Content-Type={content_type}")
                continue

            extracted_text = _extract_website_text(html, current_url)
            if len(extracted_text.split()) >= 30:
                page_texts.append(extracted_text)
                print(f"[Website Build Saved] {current_url}")

            for link in _extract_internal_links(html, current_url, base_domain):
                if link not in visited and link not in queue:
                    queue.append(link)

        except Exception as e:
            print(f"[Website Build Error] URL={current_url}, Error={str(e)}")
            continue

        if delay_seconds and delay_seconds > 0:
            try:
                import time
                time.sleep(delay_seconds)
            except Exception:
                pass

    if not page_texts:
        print(f"[Website Build Failed] No useful content extracted from {url}")
        return ""

    return (
        f"Crawled content from Website Source: {url}\n"
        f"Pages crawled: {len(page_texts)}\n\n"
        + "\n\n--- PAGE BREAK ---\n\n".join(page_texts)
    )


def process_website_source(source_id: str, url: str,
                           intent_scope: str = None, topic: str = None, service: str = None, tags: list = None,
                           max_pages: int = 15, timeout: int = 10, delay_seconds: float = 0.3) -> int:
    """
    Crawls a target website URL, extracts clean structured text,
    chunks it, and stores the chunks in MongoDB.
    """
    formatted_content = build_website_content(url, max_pages=max_pages, timeout=timeout, delay_seconds=delay_seconds)
    if not formatted_content:
        return 0

    return process_and_chunk_source(
        source_id, urlparse(url).netloc.lower().replace("www.", ""), "website", formatted_content,
        intent_scope=intent_scope, topic=topic, service=service, tags=tags
    )

