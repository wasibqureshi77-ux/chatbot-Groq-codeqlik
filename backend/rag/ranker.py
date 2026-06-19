def rerank_chunks(chunks: list[dict], query: str, analyzer_res: dict) -> list[dict]:
    """
    Reranks chunks based on relevance_score, category boosting, source priority,
    and query type alignment.
    Returns the top chunks sorted by final score descending.
    """
    reranked = []
    
    category_boost = analyzer_res.get("category_boost", "None")
    query_type = analyzer_res.get("query_type", "general")
    query_lower = query.lower()

    for chunk in chunks:
        # Start with base relevance score calculated in filters
        score = chunk.get("relevance_score", 0.1)
        
        # 1. Category Boosting
        chunk_category = chunk.get("category", "")
        if category_boost != "None" and chunk_category.lower() == category_boost.lower():
            score += 0.2
            
        # 2. Source Type Priority Boosting
        source_type = chunk.get("source_type", "").lower()
        
        # Database/CSV record boosting for product/inventory inquiries
        if query_type == "service_inquiry" or "product" in query_lower:
            if source_type in ("database", "csv", "xlsx", "db_mongodb", "db_mysql", "db_postgresql", "db_sqlserver"):
                score += 0.15
        
        # Policy boosting for policy questions
        if query_type == "policy_question" and source_type in ("document", "manual"):
            score += 0.1
            
        # 3. Exact phrase match boost
        if query_lower in chunk.get("chunk_text", "").lower():
            score += 0.1
            
        # 4. Metadata boosts (RAG improvements)
        detected_topic = analyzer_res.get("detected_query_topic")
        detected_service = analyzer_res.get("detected_query_service")
        detected_intent = analyzer_res.get("detected_intent_scope")

        ch_topic = chunk.get("topic", chunk.get("category", "general"))
        ch_service = chunk.get("service", "general")
        ch_intent = chunk.get("intent_scope", "all")

        if detected_topic and ch_topic.lower() == detected_topic.lower():
            score += 0.15
        if detected_service and ch_service.lower() == detected_service.lower():
            score += 0.10
        if detected_intent and ch_intent.lower() == detected_intent.lower():
            score += 0.10

        # 5. Limit score to max of 1.0
        final_score = min(score, 1.0)
        
        # Create chunk copy with updated score
        chunk_copy = dict(chunk)
        chunk_copy["final_relevance_score"] = round(final_score, 3)
        
        # Include reason matched for metadata visibility
        reasons = []
        if category_boost != "None" and chunk_category.lower() == category_boost.lower():
            reasons.append("category_boost")
        if query_lower in chunk.get("chunk_text", "").lower():
            reasons.append("exact_phrase_match")
        if not reasons:
            reasons.append("keyword_match")
        chunk_copy["match_reason"] = ", ".join(reasons)
        
        reranked.append(chunk_copy)
        
    # Sort by final score descending
    reranked.sort(key=lambda x: x["final_relevance_score"], reverse=True)
    return reranked
