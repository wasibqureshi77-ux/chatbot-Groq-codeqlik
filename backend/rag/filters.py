import re

GENERIC_WORDS = {"company", "service", "project", "client", "support", "hiring", "system", "website", "application", "business"}

def get_relevance_score(chunk: dict, query: str, keywords: list, entities: list) -> float:
    """
    Computes a heuristic relevance score between 0.0 and 1.0 for a retrieved chunk.
    """
    text = chunk.get("chunk_text", "").lower()
    title = chunk.get("title", "").lower()
    category = chunk.get("category", "").lower()
    chunk_keywords = [k.lower() for k in chunk.get("keywords", []) if isinstance(k, str)]
    
    score = 0.0
    query_lower = query.lower()

    if not text:
        return 0.0

    # 1. Exact phrase match (High weight)
    if query_lower in text:
        score += 0.5
        
    # 2. Match individual keywords
    kw_matches = 0
    non_generic_kws = [k for k in keywords if k.lower() not in GENERIC_WORDS]
    if not non_generic_kws:
        non_generic_kws = keywords

    for kw in non_generic_kws:
        kw_lower = kw.lower()
        if kw_lower in text:
            kw_matches += 1
            score += 0.1
        if kw_lower in title:
            score += 0.15 # Strong weight for title match
        if kw_lower in category:
            score += 0.05
        if kw_lower in chunk_keywords:
            score += 0.08

    # 3. Match entities
    entity_matches = 0
    for ent in entities:
        ent_lower = ent.lower()
        if ent_lower in text:
            entity_matches += 1
            score += 0.2
        if ent_lower in title:
            score += 0.25

    # Normalize score to max of 1.0
    final_score = min(score, 1.0)
    
    # Penalize if it only matches generic words
    matched_words = re.findall(r"\w+", query_lower)
    matched_non_generic = [w for w in matched_words if w in text and w not in GENERIC_WORDS and len(w) > 2]
    if not matched_non_generic and kw_matches > 0:
        final_score *= 0.1  # Heavy penalty for only generic matches

    return round(final_score, 3)

def filter_chunks(chunks: list[dict], query: str, keywords: list, entities: list, enabled_source_ids: list[str], threshold: float = 0.15) -> list[dict]:
    """
    Filters retrieved chunks:
    - Excludes chunks belonging to disabled/deleted sources (source_id not in enabled_source_ids)
    - Computes a score for each chunk and excludes chunks with scores below threshold.
    - Excludes chunks that only match generic words.
    """
    filtered = []
    
    for chunk in chunks:
        # Check source activation
        src_id = str(chunk.get("source_id", ""))
        if src_id not in enabled_source_ids:
            continue
            
        score = get_relevance_score(chunk, query, keywords, entities)
        if score < threshold:
            continue
            
        # Store score inside chunk dict for ranking
        chunk_copy = dict(chunk)
        chunk_copy["relevance_score"] = score
        filtered.append(chunk_copy)
        
    return filtered
