from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any

from rag.records import RawRecord, parse_records

STOPWORDS = {
    "the", "a", "an", "is", "are", "of", "to", "in", "for", "on", "and", "or",
    "what", "how", "why", "where", "you", "me", "this", "that", "with", "from",
    "your", "our", "we", "they", "them", "he", "she", "it", "has", "have", "had",
    "been", "was", "were", "be", "do", "does", "did", "can", "could", "would",
    "should", "will", "shall", "may", "might", "must", "about", "into", "than",
    "company", "information", "details", "please", "provide", "using", "used",
}

LOW_VALUE_PATTERNS = (
    r"^read more$", r"^learn more$", r"^get started$", r"^contact us$",
    r"^let'?s talk!?$", r"^all rights reserved", r"^copyright\b", r"^follow us\b",
)

RISK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("project_count", re.compile(r"\b\d[\d,]*\+?\s+projects?\b", re.I)),
    ("client_count", re.compile(r"\b\d[\d,]*\+?\s+clients?\b", re.I)),
    ("employee_count", re.compile(r"\b\d[\d,]*\+?\s+(?:employees?|developers?|team members?)\b", re.I)),
    ("experience_years", re.compile(r"\b\d+\+?\s+years?\b", re.I)),
    ("percentage_claim", re.compile(r"\b\d+(?:\.\d+)?%\b")),
    ("certification_or_compliance", re.compile(r"\b(?:ISO\s*\d+|SOC\s*2|HIPAA|GDPR|ZATCA)\b", re.I)),
    ("partnership_claim", re.compile(r"\b(?:certified|official|silver|gold)\s+(?:partner|provider)\b", re.I)),
    ("guarantee_claim", re.compile(r"\b(?:guaranteed|zero downtime|100% secure|always available)\b", re.I)),
    ("leadership_claim", re.compile(r"\b(?:CEO|founder|co-founder|managing director)\b", re.I)),
    ("price_claim", re.compile(r"(?:₹|\$|€|£)\s*\d|\b\d[\d,]*\s*(?:INR|USD|EUR|GBP)\b", re.I)),
]

CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("contact", ("contact", "phone", "email", "address", "office", "opening hours", "location")),
    ("careers", ("career", "job", "opening", "intern", "apply", "resume", "vacancy")),
    ("portfolio", ("portfolio", "case study", "project", "our work", "client success")),
    ("pricing", ("pricing", "price", "cost", "budget", "quote", "rate", "fee")),
    ("policies", ("privacy", "terms", "refund", "cancellation", "policy", "legal")),
    ("technologies", ("technology", "framework", "language", "python", "react", "node", "java", "php")),
    ("industries", ("industry", "healthcare", "education", "real estate", "manufacturing", "hospitality")),
    ("services", (
        "service", "development", "integration", "software", "website", "mobile app",
        "chatbot", "voice agent", "machine learning", "erp", "crm", "odoo", "erpnext",
        "devops", "cloud", "hosting", "e-commerce", "api", "staff augmentation",
    )),
    ("company", ("about", "mission", "vision", "history", "value", "company", "who we are")),
]


def _normalize_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_tokens(text: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-z0-9][a-z0-9+./_-]*", text.lower())
        if token not in STOPWORDS and len(token) > 1
    ]


def _is_low_value(text: str) -> bool:
    value = _normalize_text(text).lower()
    return not value or any(re.search(pattern, value, re.I) for pattern in LOW_VALUE_PATTERNS)


def extract_keywords_from_text(text: str, max_keywords: int = 10) -> list[str]:
    frequencies = Counter(_normalize_tokens(text))
    return [word for word, _ in frequencies.most_common(max_keywords)]


def generate_summary(text: str, max_sentences: int = 1) -> str:
    sentences = re.split(r"(?<=[.!?])\s+|\n+", _normalize_text(text))
    sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
    return " ".join(sentences[:max_sentences])


def _sentence_units(text: str) -> list[str]:
    text = _normalize_text(text)
    if not text:
        return []
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", paragraph)
        units.extend(part.strip() for part in parts if part.strip())
    return units


def split_text(text: str, chunk_size: int = 900, chunk_overlap: int = 120) -> list[str]:
    """Backward-compatible semantic splitter.

    It prefers paragraph/sentence boundaries and only uses a hard character window for a
    single oversized sentence. The old function name/signature remains unchanged.
    """
    text = _normalize_text(text)
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    units = _sentence_units(text)
    chunks: list[str] = []
    current = ""

    def append_current() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for unit in units:
        if len(unit) > chunk_size:
            append_current()
            step = max(1, chunk_size - min(chunk_overlap, chunk_size // 3))
            for start in range(0, len(unit), step):
                piece = unit[start : start + chunk_size].strip()
                if piece:
                    chunks.append(piece)
                if start + chunk_size >= len(unit):
                    break
            continue

        candidate = f"{current} {unit}".strip()
        if not current or len(candidate) <= chunk_size:
            current = candidate
            continue

        previous = current
        append_current()
        overlap = previous[-chunk_overlap:].strip() if chunk_overlap else ""
        current = f"{overlap} {unit}".strip() if overlap else unit
        if len(current) > chunk_size:
            current = unit

    append_current()
    return chunks


def _looks_like_heading(line: str) -> bool:
    line = line.strip()
    if not line or len(line) > 120 or line.endswith((".", "?", "!", ";")):
        return False
    words = line.split()
    if not 1 <= len(words) <= 14:
        return False
    return line.isupper() or sum(word[:1].isupper() for word in words) >= max(1, len(words) // 2)


def _split_plain_sections(content: str, default_title: str) -> list[RawRecord]:
    content = _normalize_text(content)
    if not content:
        return []

    records: list[RawRecord] = []
    current_title = default_title
    current_lines: list[str] = []
    section_index = 0

    def flush() -> None:
        nonlocal current_lines, section_index
        text = _normalize_text("\n".join(current_lines))
        if text and not _is_low_value(text):
            section_index += 1
            records.append(
                RawRecord(
                    title=current_title,
                    text=text,
                    source_type="text",
                    source_locator={"section_index": section_index},
                    record_id=f"section-{section_index}",
                )
            )
        current_lines = []

    for line in content.splitlines():
        line = line.strip()
        if not line:
            current_lines.append("")
            continue
        if _looks_like_heading(line):
            flush()
            current_title = line
        else:
            current_lines.append(line)
    flush()

    return records or [
        RawRecord(default_title, content, "text", {"section_index": 1}, "section-1")
    ]


def _split_markdown_sections(content: str, default_title: str) -> list[RawRecord]:
    lines = content.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    heading_path: list[str] = []
    buffer: list[str] = []
    records: list[RawRecord] = []
    section_index = 0
    in_code_block = False

    def flush() -> None:
        nonlocal buffer, section_index
        text = _normalize_text("\n".join(buffer))
        if text and not _is_low_value(text):
            section_index += 1
            title = " > ".join(heading_path) or default_title
            records.append(
                RawRecord(
                    title=title,
                    text=text,
                    source_type="markdown",
                    source_locator={"section_index": section_index, "heading_path": list(heading_path)},
                    record_id=f"section-{section_index}",
                )
            )
        buffer = []

    for line in lines:
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            buffer.append(line)
            continue
        if not in_code_block:
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if match:
                flush()
                level = len(match.group(1))
                heading_path[:] = heading_path[: level - 1]
                heading_path.append(match.group(2).strip())
                continue
        buffer.append(line)
    flush()
    return records or _split_plain_sections(content, default_title)


def detect_risk_flags(text: str) -> list[str]:
    return sorted({name for name, pattern in RISK_PATTERNS if pattern.search(text or "")})


def _classify(title: str, text: str, base_metadata: dict[str, Any]) -> tuple[str, str]:
    combined = f"{title} {text}".lower()
    category = str(base_metadata.get("category") or "").strip().lower()
    if not category:
        category = "general"
        for candidate, terms in CATEGORY_RULES:
            if any(term in combined for term in terms):
                category = candidate
                break
    topic_tokens = _normalize_tokens(title)[:6] or _normalize_tokens(text)[:4]
    topic = "_".join(topic_tokens) or "general"
    return category, topic


def _sample_questions(title: str, category: str, keywords: list[str]) -> list[str]:
    clean_title = title.strip().rstrip(".") or "this topic"
    templates = {
        "services": [f"Does the company provide {clean_title.lower()}?", f"What is included in {clean_title.lower()}?"],
        "portfolio": [f"What is {clean_title}?", "Which projects are in the published portfolio?"],
        "contact": [f"What are the {clean_title.lower()}?", "How can I contact the company?"],
        "careers": [f"What does the company say about {clean_title.lower()}?", "How can I apply?"],
        "pricing": [f"What is the policy for {clean_title.lower()}?", "How is project pricing decided?"],
        "policies": [f"What does the {clean_title.lower()} say?"],
        "technologies": [f"Does the company work with {clean_title}?", "Which technologies are supported?"],
        "industries": [f"Does the company work with {clean_title.lower()}?", "Which industries are supported?"],
        "company": [f"What is the company's {clean_title.lower()}?", "Tell me about the company."],
    }
    result = templates.get(category, [f"What does the source say about {clean_title.lower()}?"])
    if keywords:
        result.append(f"Can you tell me about {keywords[0]}?")
    deduped: list[str] = []
    seen: set[str] = set()
    for question in result:
        key = question.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(question)
    return deduped[:4]


def _stable_hash(*parts: str) -> str:
    return hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()


def _build_chunk(
    record: RawRecord,
    text: str,
    index: int,
    base_metadata: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(base_metadata)
    metadata.update(record.metadata or {})
    metadata["source_locator"] = dict(record.source_locator or {})
    metadata["record_id"] = record.record_id
    metadata["section_title"] = record.title

    category, topic = _classify(record.title, text, metadata)
    provided_keywords = metadata.get("provided_keywords") or []
    keywords = [str(value).strip() for value in provided_keywords if str(value).strip()]
    if not keywords:
        keywords = extract_keywords_from_text(f"{record.title} {text}")

    provided_questions = metadata.get("sample_questions") or []
    sample_questions = [str(value).strip() for value in provided_questions if str(value).strip()]
    if not sample_questions:
        sample_questions = _sample_questions(record.title, category, keywords)

    detected_risks = detect_risk_flags(text)
    provided_risks = [str(value) for value in (metadata.get("risk_flags") or [])]
    risk_flags = sorted(set(detected_risks + provided_risks))

    answer_mode = metadata.get("answer_mode")
    verification_status = metadata.get("verification_status")
    if not answer_mode:
        answer_mode = "requires_confirmation" if risk_flags else "direct"
    if not verification_status:
        verification_status = "source_claim_requires_review" if risk_flags else "source_grounded"

    summary = generate_summary(text, 2)
    retrieval_text = (
        f"Title: {record.title}\n"
        f"Category: {category}\n"
        f"Topic: {topic}\n"
        f"Content: {text}\n"
        f"Questions: {' | '.join(sample_questions)}\n"
        f"Keywords: {', '.join(keywords)}"
    ).strip()

    content_hash = _stable_hash(re.sub(r"\W+", " ", text.lower()).strip())
    knowledge_id = "kb_" + _stable_hash(
        str(base_metadata.get("source_name", "")),
        record.title,
        record.record_id or str(index),
        content_hash,
    )[:14]

    return {
        "chunk_text": text,
        "content": text,
        "retrieval_text": retrieval_text,
        "chunk_summary": summary,
        "summary": summary,
        "title": record.title,
        "keywords": keywords,
        "sample_questions": sample_questions,
        "category": category,
        "topic": topic,
        "risk_flags": risk_flags,
        "answer_mode": answer_mode,
        "verification_status": verification_status,
        "content_hash": content_hash,
        "knowledge_id": knowledge_id,
        "volatile": bool(risk_flags) or category in {"pricing", "careers", "policies"},
        "metadata": metadata,
    }


def chunk_document(doc_type: str, content: str, base_metadata: dict | None = None) -> list[dict]:
    """Convert any supported input into self-contained, evidence-aware RAG chunks.

    The public signature is unchanged. Structured loaders encode records into `content`;
    plain TXT/Markdown continues to work as before.
    """
    base_metadata = dict(base_metadata or {})
    normalized_type = (doc_type or "text").lower().replace(".", "")
    if not content or not content.strip():
        return []

    records = parse_records(content)
    if not records:
        default_title = str(base_metadata.get("title") or base_metadata.get("source_name") or "Document")
        if normalized_type in {"md", "markdown"}:
            records = _split_markdown_sections(content, default_title)
        else:
            records = _split_plain_sections(content, default_title)

    chunks: list[dict] = []
    seen_hashes: set[str] = set()
    chunk_index = 0

    for record in records:
        record_text = _normalize_text(record.text)
        if not record_text or _is_low_value(record_text):
            continue
        parts = split_text(record_text, chunk_size=1050, chunk_overlap=120)
        for part_index, part in enumerate(parts, start=1):
            if len(part.strip()) < 20:
                continue
            title = record.title if len(parts) == 1 else f"{record.title} — Part {part_index}"
            part_record = RawRecord(
                title=title,
                text=part,
                source_type=record.source_type or normalized_type,
                source_locator={**record.source_locator, "part_index": part_index},
                record_id=(f"{record.record_id}:part-{part_index}" if record.record_id else f"part-{part_index}"),
                metadata=dict(record.metadata),
            )
            chunk = _build_chunk(part_record, part, chunk_index, base_metadata)
            if chunk["content_hash"] in seen_hashes:
                continue
            seen_hashes.add(chunk["content_hash"])
            chunks.append(chunk)
            chunk_index += 1

    return chunks
