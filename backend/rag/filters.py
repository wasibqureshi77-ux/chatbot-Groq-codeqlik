from __future__ import annotations

import re

GENERIC_WORDS = {
    "company", "service", "services", "project", "projects", "client", "clients", "support",
    "hiring", "system", "website", "application", "business", "information", "details",
}
STOPWORDS = {
    "the", "a", "an", "is", "are", "of", "to", "in", "for", "on", "and", "or", "what",
    "how", "why", "where", "who", "you", "your", "we", "our", "with", "from", "have", "has",
}


def _contains(text: str, phrase: str) -> bool:
    phrase = phrase.strip().lower()
    if not phrase:
        return False
    if " " in phrase:
        return phrase in text
    return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text))


def get_relevance_score(chunk: dict, query: str, keywords: list, entities: list) -> float:
    searchable = "\n".join([
        str(chunk.get("title", "")), str(chunk.get("category", "")), str(chunk.get("topic", "")),
        str(chunk.get("retrieval_text") or chunk.get("chunk_text", "")),
        " ".join(str(value) for value in chunk.get("keywords", []) if isinstance(value, str)),
        " ".join(str(value) for value in chunk.get("sample_questions", []) if isinstance(value, str)),
    ]).lower()
    if not searchable.strip():
        return 0.0

    query_lower = query.lower().strip()
    score = 0.0
    if len(query_lower) >= 5 and query_lower in searchable:
        score += 0.45

    meaningful = [
        str(keyword).lower() for keyword in keywords
        if str(keyword).lower() not in STOPWORDS and len(str(keyword)) > 1
    ]
    matched = sum(1 for keyword in meaningful if _contains(searchable, keyword))
    if meaningful:
        score += 0.35 * (matched / len(meaningful))

    title = str(chunk.get("title", "")).lower()
    for keyword in meaningful:
        if _contains(title, keyword):
            score += 0.06

    for entity in entities:
        entity_text = str(entity).lower().strip()
        if entity_text and _contains(searchable, entity_text):
            score += 0.12

    if matched and all(keyword in GENERIC_WORDS for keyword in meaningful if _contains(searchable, keyword)):
        score *= 0.35
    return round(min(score, 1.0), 4)


def filter_chunks(chunks: list[dict], query: str, keywords: list, entities: list, enabled_source_ids: list[str], threshold: float = 0.18) -> list[dict]:
    enabled = {str(value) for value in enabled_source_ids}
    filtered: list[dict] = []
    for chunk in chunks:
        if str(chunk.get("source_id", "")) not in enabled:
            continue
        score = get_relevance_score(chunk, query, keywords, entities)
        if score < threshold:
            continue
        copy = dict(chunk)
        copy["relevance_score"] = score
        filtered.append(copy)
    return filtered
