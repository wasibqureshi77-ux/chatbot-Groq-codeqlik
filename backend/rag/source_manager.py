from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import unquote, urldefrag, urljoin, urlparse

import numpy as np
from bson import ObjectId
from bs4 import BeautifulSoup

from database import knowledge_sources_collection, knowledge_chunks_collection
from rag.chunker import chunk_document
from rag.embeddings import embeddings_model
from rag.records import RawRecord, serialize_records

sources_collection = knowledge_sources_collection
chunks_collection = knowledge_chunks_collection

SENSITIVE_FIELD_RE = re.compile(
    r"(?:password|passwd|secret|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|"
    r"private[_ -]?key|otp|cvv|card[_ -]?number|auth[_ -]?token)",
    re.I,
)

METRIC_PATTERNS: dict[str, re.Pattern[str]] = {
    "project_count": re.compile(r"\b(\d[\d,]*)\+?\s+projects?\b", re.I),
    "client_count": re.compile(r"\b(\d[\d,]*)\+?\s+clients?\b", re.I),
    "employee_count": re.compile(r"\b(\d[\d,]*)\+?\s+(?:employees?|developers?|team members?)\b", re.I),
    "experience_years": re.compile(r"\b(\d+)\+?\s+years?\b", re.I),
    "founding_year": re.compile(r"\b(?:founded|began|started|established)\D{0,30}(20\d{2}|19\d{2})\b", re.I),
}

SKIP_URL_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".pdf", ".zip", ".rar", ".7z", ".mp4", ".mp3", ".avi", ".mov", ".webm",
    ".css", ".js", ".map", ".woff", ".woff2", ".ttf", ".eot",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _object_id_or_raw(value: str):
    try:
        return ObjectId(value)
    except Exception:
        return value


def _source_doc(source_id: str) -> dict[str, Any] | None:
    identifier = _object_id_or_raw(source_id)
    return sources_collection.find_one({"_id": identifier}) or sources_collection.find_one({"_id": source_id})


def _normalized_words(text: str) -> set[str]:
    stop = {
        "the", "and", "or", "to", "of", "in", "on", "for", "with", "a", "an", "is", "are",
        "we", "our", "you", "your", "this", "that", "from", "can", "company", "information",
    }
    return {
        word for word in re.findall(r"[a-z0-9][a-z0-9+./_-]*", (text or "").lower())
        if word not in stop and len(word) > 1
    }


def detect_topic(text: str, title: str, category: str, heading: str = "") -> str:
    combined = f"{title} {heading} {category} {text}".lower()
    rules = [
        ("pricing", ("pricing", "price", "cost", "budget", "quote", "charges", "rate", "fees")),
        ("contact", ("contact", "address", "phone", "email", "office", "location", "opening hours")),
        ("portfolio", ("portfolio", "case study", "our work", "published projects")),
        ("policies", ("policy", "privacy", "terms", "refund", "cancellation", "legal")),
        ("technologies", ("technology", "tech stack", "framework", "python", "javascript", "react", "node", "java")),
        ("services", ("service", "development", "integration", "software", "website", "mobile app", "erp", "crm", "chatbot")),
        ("careers", ("career", "job", "internship", "opening", "apply")),
    ]
    for topic, terms in rules:
        if any(term in combined for term in terms):
            return topic
    return "general"


def detect_service(text: str, title: str, category: str, heading: str = "") -> str:
    combined = f"{title} {heading} {category} {text}".lower()
    rules = [
        ("website", ("website", "web app", "web development", "frontend", "wordpress", "cms")),
        ("mobile_app", ("mobile app", "ios", "android", "flutter", "react native", "mobile application")),
        ("ecommerce", ("ecommerce", "e-commerce", "shopify", "woocommerce", "online store", "marketplace")),
        ("erp", ("erpnext", "odoo", "erp ", "enterprise resource planning")),
        ("crm", ("crm", "customer relationship management")),
        ("ai_automation", ("chatbot", "rag", "ai agent", "voice agent", "machine learning", "artificial intelligence", "automation")),
        ("software", ("software", "saas", "backend", "database", "api", "cloud", "devops")),
    ]
    for service, terms in rules:
        if any(term in combined for term in terms):
            return service
    return "general"


def detect_intent_scope(text: str, title: str, category: str, heading: str = "") -> str:
    """Classify source content conservatively.

    Informational service content stays `all`; words such as support or experience no longer
    automatically convert a knowledge chunk into a workflow-specific chunk.
    """
    combined = f"{title} {heading} {category} {text}".lower()
    if any(term in combined for term in ("job opening", "apply for", "send your resume", "internship opening", "career opportunity")):
        return "hiring"
    if any(term in combined for term in ("raise a ticket", "report an issue", "technical issue", "support ticket", "complaint process")):
        return "support"
    if any(term in combined for term in ("request a quote", "book a consultation", "project enquiry", "discuss your project", "sales enquiry")):
        return "client"
    return "all"


def _cosine(vector_a: list[float], vector_b: list[float]) -> float:
    a = np.asarray(vector_a, dtype=float)
    b = np.asarray(vector_b, dtype=float)
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator else 0.0


def _dedupe_chunks(chunks: list[dict], embeddings: list[list[float]], threshold: float = 0.94):
    if not chunks:
        return [], []
    kept_chunks: list[dict] = []
    kept_embeddings: list[list[float]] = []
    for chunk, embedding in zip(chunks, embeddings):
        duplicate_index = None
        for index, existing_embedding in enumerate(kept_embeddings):
            if _cosine(embedding, existing_embedding) >= threshold:
                duplicate_index = index
                break
        if duplicate_index is None:
            kept_chunks.append(chunk)
            kept_embeddings.append(embedding)
            continue
        existing = kept_chunks[duplicate_index]
        duplicate_locators = existing.setdefault("metadata", {}).setdefault("duplicate_locators", [])
        locator = (chunk.get("metadata") or {}).get("source_locator")
        if locator and locator not in duplicate_locators:
            duplicate_locators.append(locator)
        if len(chunk.get("content", "")) > len(existing.get("content", "")):
            merged_metadata = dict(chunk.get("metadata") or {})
            merged_metadata["duplicate_locators"] = duplicate_locators
            chunk["metadata"] = merged_metadata
            kept_chunks[duplicate_index] = chunk
            kept_embeddings[duplicate_index] = embedding
    return kept_chunks, kept_embeddings


def _detect_conflicts(chunks: list[dict]) -> list[dict[str, Any]]:
    values: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for chunk in chunks:
        content = chunk.get("content") or chunk.get("chunk_text") or ""
        locator = json.dumps((chunk.get("metadata") or {}).get("source_locator") or {}, sort_keys=True)
        for metric, pattern in METRIC_PATTERNS.items():
            for match in pattern.findall(content):
                values[metric][str(match).replace(",", "")].add(locator)
    return [
        {"metric": metric, "values": {value: sorted(locators) for value, locators in metric_values.items()}}
        for metric, metric_values in values.items()
        if len(metric_values) > 1
    ]


def _conflict_chunk(conflict: dict[str, Any], source_name: str) -> dict[str, Any]:
    metric = conflict["metric"]
    readable = {
        "project_count": "total project count",
        "client_count": "total client count",
        "employee_count": "employee count",
        "experience_years": "years of experience",
        "founding_year": "founding year",
    }.get(metric, metric.replace("_", " "))
    values = ", ".join(sorted(conflict["values"].keys()))
    content = (
        f"The source contains conflicting values for the company's {readable}: {values}. "
        f"The verified {readable} is therefore unavailable. Do not choose one value, average the "
        f"values, or infer a total by counting examples. Request authorized confirmation."
    )
    return {
        "chunk_text": content,
        "content": content,
        "retrieval_text": (
            f"Title: Verified {readable}\nCategory: policies\nTopic: {metric}\nContent: {content}\n"
            f"Questions: What is the company's {readable}? | How many {readable} are there?\n"
            f"Keywords: {readable}, conflicting claims, verified information"
        ),
        "chunk_summary": content,
        "summary": content,
        "title": f"Verified {readable}",
        "keywords": [readable, "conflicting claims", "verified information"],
        "sample_questions": [f"What is the company's {readable}?", f"How many {readable} are there?"],
        "category": "policies",
        "topic": metric,
        "risk_flags": [metric],
        "answer_mode": "verified_information_unavailable",
        "verification_status": "conflicting_source_claims",
        "content_hash": f"conflict:{metric}:{values}",
        "knowledge_id": f"kb_conflict_{metric}",
        "volatile": True,
        "metadata": {"source_name": source_name, "conflict_values": conflict["values"]},
    }


def process_and_chunk_source(
    source_id: str,
    source_name: str,
    source_type: str,
    content: str,
    intent_scope: str = None,
    topic: str = None,
    service: str = None,
    tags: list = None,
) -> int:
    """Build and persist RAG-ready chunks while preserving the old public API."""
    source_doc = _source_doc(source_id) or {}
    tenant_id = source_doc.get("tenant_id")
    delete_filter: dict[str, Any] = {"source_id": source_id}
    if tenant_id is not None:
        delete_filter["tenant_id"] = tenant_id
    chunks_collection.delete_many(delete_filter)

    if not content or not content.strip():
        sources_collection.update_one(
            {"_id": source_doc.get("_id", _object_id_or_raw(source_id))},
            {"$set": {"processing_status": "failed", "processing_error": "No extractable content", "updated_at": now_iso()}},
        )
        return 0

    category = source_doc.get("category", "Company Information")
    title = source_doc.get("title", source_name)
    base_metadata = {
        "source_name": source_name,
        "title": title,
        "category": category,
        "tenant_id": tenant_id,
    }
    smart_chunks = chunk_document(source_type, content, base_metadata=base_metadata)
    if os.getenv("RAG_LLM_REFINER", "false").lower() == "true":
        try:
            from rag.refiner import refine_chunks
            smart_chunks = refine_chunks(smart_chunks)
        except Exception:
            # Refinement is quality enhancement only; deterministic ingestion must continue.
            pass
    if not smart_chunks:
        sources_collection.update_one(
            {"_id": source_doc.get("_id", _object_id_or_raw(source_id))},
            {"$set": {"processing_status": "failed", "processing_error": "No valid knowledge chunks", "updated_at": now_iso()}},
        )
        return 0

    conflicts = _detect_conflicts(smart_chunks)
    smart_chunks.extend(_conflict_chunk(conflict, source_name) for conflict in conflicts)

    retrieval_texts = [chunk.get("retrieval_text") or chunk.get("chunk_text", "") for chunk in smart_chunks]
    embeddings = embeddings_model.embed_documents(retrieval_texts)
    smart_chunks, embeddings = _dedupe_chunks(
        smart_chunks,
        embeddings,
        threshold=float(os.getenv("RAG_INGEST_DUPLICATE_THRESHOLD", "0.94")),
    )

    now = now_iso()
    chunk_docs: list[dict[str, Any]] = []
    for index, (chunk, embedding) in enumerate(zip(smart_chunks, embeddings)):
        heading = (chunk.get("metadata") or {}).get("section_title", chunk.get("title", ""))
        final_intent = intent_scope or detect_intent_scope(chunk.get("content", ""), title, category, heading)
        final_topic = topic or chunk.get("topic") or detect_topic(chunk.get("content", ""), title, category, heading)
        final_service = service or detect_service(chunk.get("content", ""), title, category, heading)

        document = {
            "source_id": source_id,
            "title": chunk.get("title") or title,
            "category": chunk.get("category") or category,
            "source_type": source_type,
            "chunk_index": index,
            "chunk_text": chunk.get("content") or chunk.get("chunk_text", ""),
            "content": chunk.get("content") or chunk.get("chunk_text", ""),
            "retrieval_text": chunk.get("retrieval_text") or chunk.get("chunk_text", ""),
            "embedding": list(map(float, embedding)),
            "keywords": chunk.get("keywords", []),
            "sample_questions": chunk.get("sample_questions", []),
            "summary": chunk.get("summary") or chunk.get("chunk_summary", ""),
            "metadata": chunk.get("metadata", {}),
            "knowledge_id": chunk.get("knowledge_id"),
            "content_hash": chunk.get("content_hash"),
            "verification_status": chunk.get("verification_status", "source_grounded"),
            "answer_mode": chunk.get("answer_mode", "direct"),
            "risk_flags": chunk.get("risk_flags", []),
            "volatile": bool(chunk.get("volatile", False)),
            "status": "active",
            "intent_scope": final_intent,
            "topic": final_topic,
            "service": final_service,
            "priority": 1,
            "tags": tags or [],
            "created_at": now,
            "updated_at": now,
            "upload_date": now,
        }
        if tenant_id is not None:
            document["tenant_id"] = tenant_id
        chunk_docs.append(document)

    if chunk_docs:
        chunks_collection.insert_many(chunk_docs)

    source_update = {
        "processing_status": "completed",
        "processing_error": None,
        "chunk_count": len(chunk_docs),
        "conflicts": conflicts,
        "updated_at": now,
    }
    sources_collection.update_one(
        {"_id": source_doc.get("_id", _object_id_or_raw(source_id))},
        {"$set": source_update},
    )
    return len(chunk_docs)


def delete_source_data(source_id: str):
    source_doc = _source_doc(source_id) or {}
    chunk_filter: dict[str, Any] = {"source_id": source_id}
    if source_doc.get("tenant_id") is not None:
        chunk_filter["tenant_id"] = source_doc["tenant_id"]
    chunks_collection.delete_many(chunk_filter)
    sources_collection.delete_one({"_id": source_doc.get("_id", _object_id_or_raw(source_id))})


def set_source_active_state(source_id: str, enabled: bool):
    sources_collection.update_one(
        {"_id": _object_id_or_raw(source_id)},
        {"$set": {"enabled": enabled, "updated_at": now_iso()}},
    )


def _safe_mapping_text(mapping: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in mapping.items():
        if SENSITIVE_FIELD_RE.search(str(key)) or value in (None, "", [], {}):
            continue
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        else:
            rendered = str(value)
        lines.append(f"{str(key).replace('_', ' ').title()}: {rendered}")
    return "\n".join(lines)


def _safe_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.$-]*", value or ""):
        raise ValueError("Invalid table or collection name")
    return value


def process_database_source(
    source_id: str,
    conn_name: str,
    conn_string: str,
    db_type: str,
    db_name: str,
    target_collection: str,
    intent_scope: str = None,
    topic: str = None,
    service: str = None,
    tags: list = None,
) -> int:
    """Read real database records and index one coherent record per row/document."""
    database_type = (db_type or "").lower()
    max_records = max(1, int(os.getenv("RAG_DB_MAX_RECORDS", "1000")))
    records: list[RawRecord] = []
    connection = None

    try:
        if database_type == "mongodb":
            from pymongo import MongoClient

            connection = MongoClient(conn_string, serverSelectionTimeoutMS=5000)
            collection = connection[db_name][_safe_identifier(target_collection)]
            for index, document in enumerate(collection.find({}, limit=max_records)):
                document_id = str(document.get("_id", index))
                clean_document = {key: value for key, value in document.items() if key != "_id"}
                text = _safe_mapping_text(clean_document)
                if text:
                    records.append(
                        RawRecord(
                            title=f"{target_collection} — {document_id}",
                            text=text,
                            source_type="db_mongodb",
                            source_locator={"collection": target_collection, "record_id": document_id},
                            record_id=document_id,
                        )
                    )

        elif database_type == "postgresql":
            import psycopg2

            connection = psycopg2.connect(conn_string)
            cursor = connection.cursor()
            table = _safe_identifier(target_collection)
            quoted_table = ".".join(f'\"{part}\"' for part in table.split('.'))
            cursor.execute(f'SELECT * FROM {quoted_table} LIMIT %s', (max_records,))
            headers = [description[0] for description in cursor.description]
            for row_index, row in enumerate(cursor.fetchall(), start=1):
                mapping = dict(zip(headers, row))
                text = _safe_mapping_text(mapping)
                if text:
                    records.append(RawRecord(f"{table} — Row {row_index}", text, "db_postgresql", {"table": table, "row_index": row_index}, str(row_index)))
            cursor.close()

        elif database_type == "mysql":
            import pymysql

            if isinstance(conn_string, dict):
                mysql_options = dict(conn_string)
            else:
                raw_connection = str(conn_string).strip()
                if raw_connection.startswith("{"):
                    mysql_options = json.loads(raw_connection)
                elif "://" in raw_connection:
                    parsed_connection = urlparse(raw_connection)
                    mysql_options = {
                        "host": parsed_connection.hostname or "localhost",
                        "port": parsed_connection.port or 3306,
                        "user": unquote(parsed_connection.username or ""),
                        "password": unquote(parsed_connection.password or ""),
                        "database": parsed_connection.path.lstrip("/") or db_name,
                    }
                else:
                    mysql_options = {"host": raw_connection or "localhost", "database": db_name}
            connection = pymysql.connect(**mysql_options)
            cursor = connection.cursor()
            table = _safe_identifier(target_collection)
            quoted_table = ".".join(f"`{part}`" for part in table.split("."))
            cursor.execute(f"SELECT * FROM {quoted_table} LIMIT %s", (max_records,))
            headers = [description[0] for description in cursor.description]
            for row_index, row in enumerate(cursor.fetchall(), start=1):
                mapping = dict(zip(headers, row))
                text = _safe_mapping_text(mapping)
                if text:
                    records.append(RawRecord(f"{table} — Row {row_index}", text, "db_mysql", {"table": table, "row_index": row_index}, str(row_index)))
            cursor.close()

        elif database_type == "sqlserver":
            import pyodbc

            connection = pyodbc.connect(conn_string)
            cursor = connection.cursor()
            table = _safe_identifier(target_collection)
            quoted_table = ".".join(f"[{part}]" for part in table.split("."))
            cursor.execute(f"SELECT TOP {max_records} * FROM {quoted_table}")
            headers = [description[0] for description in cursor.description]
            for row_index, row in enumerate(cursor.fetchall(), start=1):
                mapping = dict(zip(headers, row))
                text = _safe_mapping_text(mapping)
                if text:
                    records.append(RawRecord(f"{table} — Row {row_index}", text, "db_sqlserver", {"table": table, "row_index": row_index}, str(row_index)))
            cursor.close()
        else:
            raise ValueError(f"Unsupported database connection type: {db_type}")
    except Exception as exc:
        source_doc = _source_doc(source_id) or {}
        sources_collection.update_one(
            {"_id": source_doc.get("_id", _object_id_or_raw(source_id))},
            {"$set": {"processing_status": "failed", "processing_error": str(exc), "updated_at": now_iso()}},
        )
        return 0
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    return process_and_chunk_source(
        source_id,
        conn_name,
        f"db_{database_type}",
        serialize_records(records),
        intent_scope=intent_scope,
        topic=topic,
        service=service,
        tags=tags,
    )


def _clean_space(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text or "").strip()


def _normalize_url(url: str) -> str:
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc.lower()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    kept_query: list[str] = []
    for part in parsed.query.split("&") if parsed.query else []:
        key = part.split("=", 1)[0].lower()
        if not (key.startswith("utm_") or key in {"fbclid", "gclid", "mc_cid", "mc_eid"}):
            kept_query.append(part)
    query = "&".join(kept_query)
    return f"{scheme}://{netloc}{path}" + (f"?{query}" if query else "")


def _same_domain(url: str, base_domain: str) -> bool:
    return urlparse(url).netloc.lower().replace("www.", "") == base_domain


def _is_scrapable_url(url: str, base_domain: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not _same_domain(url, base_domain):
        return False
    lower = url.lower()
    if lower.endswith(SKIP_URL_EXTENSIONS):
        return False
    return not any(part in lower for part in ("/wp-admin", "/admin", "/login", "/signup", "/cart", "/checkout", "/account"))


def _fetch_html(url: str, timeout: int = 10):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; CompanyKnowledgeCrawler/2.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status_code = getattr(response, "status", 200)
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type.lower():
            return status_code, content_type, ""
        return status_code, content_type, response.read().decode("utf-8", errors="ignore")


def _extract_website_records(html: str, url: str) -> tuple[list[RawRecord], list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "header", "footer", "nav"]):
        tag.decompose()

    page_title = _clean_space(soup.title.get_text(" ")) if soup.title else url
    meta_description = ""
    meta = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if meta and meta.get("content"):
        meta_description = _clean_space(meta["content"])

    root = soup.find("main") or soup.find("article") or soup.body or soup
    records: list[RawRecord] = []
    heading_path: list[str] = []
    buffer: list[str] = []
    section_index = 0

    def flush() -> None:
        nonlocal buffer, section_index
        text = "\n".join(line for line in buffer if line).strip()
        if meta_description and section_index == 0 and meta_description.lower() not in text.lower():
            text = f"{meta_description}\n{text}".strip()
        if len(text) < 50:
            buffer = []
            return
        section_index += 1
        title = " > ".join(heading_path) or page_title
        records.append(
            RawRecord(
                title=title,
                text=text,
                source_type="website",
                source_locator={"url": url, "section_index": section_index, "heading_path": list(heading_path)},
                record_id=f"{url}#section-{section_index}",
                metadata={"source_url": url, "page_title": page_title},
            )
        )
        buffer = []

    for element in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "table"], recursive=True):
        if element.name in {"h1", "h2", "h3", "h4"}:
            heading = _clean_space(element.get_text(" "))
            if not heading:
                continue
            flush()
            level = int(element.name[1])
            heading_path[:] = heading_path[: level - 1]
            heading_path.append(heading)
        elif element.name == "table":
            rows: list[str] = []
            for table_row in element.find_all("tr"):
                cells = [_clean_space(cell.get_text(" ")) for cell in table_row.find_all(["th", "td"])]
                cells = [cell for cell in cells if cell]
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                buffer.append("\n".join(rows))
        else:
            text = _clean_space(element.get_text(" "))
            if len(text) >= (3 if element.name == "li" else 20):
                prefix = "- " if element.name == "li" else ""
                buffer.append(prefix + text)
    flush()

    links: list[str] = []
    base_domain = urlparse(url).netloc.lower().replace("www.", "")
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        absolute = _normalize_url(urljoin(url, anchor["href"].strip()))
        if absolute not in seen and _is_scrapable_url(absolute, base_domain):
            seen.add(absolute)
            links.append(absolute)
    return records, links


def _extract_website_text(html: str, url: str) -> str:
    """Backward-compatible helper; now preserves sections using structured records."""
    records, _ = _extract_website_records(html, url)
    return serialize_records(records)


def _extract_internal_links(html: str, current_url: str, base_domain: str, limit: int = 100):
    _, links = _extract_website_records(html, current_url)
    return [link for link in links if _same_domain(link, base_domain)][:limit]


def _discover_sitemap_urls(start_url: str, base_domain: str, timeout: int = 10, max_urls: int = 300):
    parsed = urlparse(start_url)
    queue = [f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"]
    result: list[str] = []
    seen_xml: set[str] = set()
    seen_urls: set[str] = set()

    while queue and len(result) < max_urls:
        sitemap_url = queue.pop(0)
        if sitemap_url in seen_xml:
            continue
        seen_xml.add(sitemap_url)
        try:
            request = urllib.request.Request(sitemap_url, headers={"User-Agent": "Mozilla/5.0 CompanyKnowledgeCrawler/2.0"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                xml_text = response.read().decode("utf-8", errors="ignore")
        except Exception:
            continue
        for location in re.findall(r"<loc>\s*(.*?)\s*</loc>", xml_text, flags=re.I):
            normalized = _normalize_url(location)
            if normalized.lower().endswith(".xml"):
                if normalized not in seen_xml:
                    queue.append(normalized)
            elif normalized not in seen_urls and _is_scrapable_url(normalized, base_domain):
                seen_urls.add(normalized)
                result.append(normalized)
                if len(result) >= max_urls:
                    break
    return result


def _remove_cross_page_boilerplate(page_records: list[list[RawRecord]]) -> list[RawRecord]:
    if not page_records:
        return []
    normalized_per_page = [
        {re.sub(r"\W+", " ", record.text.lower()).strip() for record in records if len(record.text) < 700}
        for records in page_records
    ]
    counts = Counter()
    for values in normalized_per_page:
        counts.update(values)
    repeated_threshold = max(3, int(len(page_records) * 0.45))
    repeated = {value for value, count in counts.items() if count >= repeated_threshold and len(value) >= 30}

    output: list[RawRecord] = []
    for records in page_records:
        for record in records:
            normalized = re.sub(r"\W+", " ", record.text.lower()).strip()
            if normalized in repeated:
                continue
            output.append(record)
    return output


def build_website_content(url: str, max_pages: int = 100, timeout: int = 10, delay_seconds: float = 0.3) -> str:
    if not url:
        return ""
    normalized_url = _normalize_url(url)
    parsed = urlparse(normalized_url)
    if not parsed.netloc:
        return ""

    max_pages = max(1, int(max_pages or 100))
    base_domain = parsed.netloc.lower().replace("www.", "")
    queue = [normalized_url]
    for sitemap_url in _discover_sitemap_urls(normalized_url, base_domain, timeout, max_urls=max_pages * 3):
        if sitemap_url not in queue:
            queue.append(sitemap_url)

    visited: set[str] = set()
    page_records: list[list[RawRecord]] = []

    while queue and len(page_records) < max_pages:
        current_url = queue.pop(0)
        if current_url in visited or not _is_scrapable_url(current_url, base_domain):
            continue
        visited.add(current_url)
        try:
            status_code, content_type, html = _fetch_html(current_url, timeout)
            if status_code != 200 or not html:
                continue
            records, links = _extract_website_records(html, current_url)
            if records:
                page_records.append(records)
            for link in links:
                if link not in visited and link not in queue:
                    queue.append(link)
        except Exception:
            continue
        if delay_seconds and delay_seconds > 0:
            time.sleep(delay_seconds)

    final_records = _remove_cross_page_boilerplate(page_records)
    return serialize_records(final_records)


def process_website_source(
    source_id: str,
    url: str,
    intent_scope: str = None,
    topic: str = None,
    service: str = None,
    tags: list = None,
    max_pages: int = 100,
    timeout: int = 10,
    delay_seconds: float = 0.3,
) -> int:
    formatted_content = build_website_content(url, max_pages=max_pages, timeout=timeout, delay_seconds=delay_seconds)
    if not formatted_content:
        return 0
    return process_and_chunk_source(
        source_id,
        urlparse(url).netloc.lower().replace("www.", ""),
        "website",
        formatted_content,
        intent_scope=intent_scope,
        topic=topic,
        service=service,
        tags=tags,
    )
