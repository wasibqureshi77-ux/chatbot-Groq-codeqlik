from __future__ import annotations


def rerank_chunks(chunks: list[dict], query: str, analyzer_res: dict) -> list[dict]:
    """Apply only soft metadata boosts; never rescue a semantically weak chunk."""
    category_boost = str(analyzer_res.get("category_boost", "None")).lower()
    detected_topic = str(analyzer_res.get("detected_query_topic") or "").lower()
    detected_service = str(analyzer_res.get("detected_query_service") or "").lower()
    detected_intent = str(analyzer_res.get("detected_intent_scope") or "").lower()
    query_lower = query.lower().strip()

    reranked: list[dict] = []
    for chunk in chunks:
        score = float(chunk.get("relevance_score", 0.0))
        reasons = list(chunk.get("match_reasons", []))

        chunk_category = str(chunk.get("category", "")).lower()
        chunk_topic = str(chunk.get("topic", "")).lower()
        chunk_service = str(chunk.get("service", "")).lower()
        chunk_intent = str(chunk.get("intent_scope", "all")).lower()
        title = str(chunk.get("title", "")).lower()
        searchable = str(chunk.get("retrieval_text") or chunk.get("chunk_text", "")).lower()

        if category_boost not in {"", "none"} and category_boost in chunk_category:
            score += 0.035
            reasons.append("category")
        if detected_topic and detected_topic == chunk_topic:
            score += 0.04
            reasons.append("topic")
        if detected_service and detected_service == chunk_service:
            score += 0.03
            reasons.append("service")
        if detected_intent and chunk_intent in {detected_intent, "all"}:
            score += 0.02
            reasons.append("intent")
        if len(query_lower) >= 5 and (query_lower in title or query_lower in searchable):
            score += 0.05
            reasons.append("exact_phrase")

        copy = dict(chunk)
        copy["final_relevance_score"] = round(min(score, 1.0), 5)
        copy["match_reason"] = ", ".join(dict.fromkeys(reasons)) or "hybrid_match"
        reranked.append(copy)

    reranked.sort(key=lambda item: item["final_relevance_score"], reverse=True)
    return reranked
