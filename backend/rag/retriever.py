import re
import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.metrics.pairwise import cosine_similarity

from database import knowledge_sources_collection, knowledge_chunks_collection
from rag.query_analyzer import analyze_query
from rag.ranker import rerank_chunks

sources_collection = knowledge_sources_collection
chunks_collection = knowledge_chunks_collection

def validate_context_relevance(query: str, chunks: list[dict], threshold: float = 0.25) -> bool:
    """
    Checks if the retrieved chunks are relevant to the latest user query.
    If the top chunk has a score below the threshold, the context is deemed irrelevant.
    """
    if not chunks:
        return False
    # Check the top chunk's score (chunks are already sorted descending)
    top_score = chunks[0].get("final_relevance_score", 0.0)
    return top_score >= threshold

def retrieve_company_context_details(query: str, limit: int = 4) -> dict:
    """
    Analyzes the query, retrieves chunks from active sources, performs hybrid search
    (BM25, Semantic, Entity Matching, Exact Matching), merges scores, reranks,
    validates, and formats the result.
    Returns:
    {
      "context_text": str,
      "confidence": float,
      "sources": list[str]
    }
    """
    # 1. Query Analysis
    analysis = analyze_query(query)
    if not analysis.get("should_use_rag", True):
        return {
            "context_text": "No RAG context needed for general chat.",
            "confidence": 0.0,
            "sources": []
        }

    # 2. Get active/enabled source IDs
    active_sources = list(sources_collection.find({"enabled": True}, {"_id": 1, "title": 1}))
    if not active_sources:
        return {
            "context_text": "No active knowledge sources are configured. Respond with general polite support protocols.",
            "confidence": 0.0,
            "sources": []
        }

    active_ids = [str(s["_id"]) for s in active_sources]
    active_titles = {str(s["_id"]): s.get("title", "Unknown Source") for s in active_sources}

    # 3. Query MongoDB for candidate chunks (retrieve a wider candidate pool of 60 for hybrid matching)
    query_filter = {"source_id": {"$in": active_ids}}
    
    keywords = list(analysis.get("keywords", []))
    # Extract alphanumeric terms (like Order IDs, codes) from query to ensure they are searched
    query_terms = re.findall(r'[a-zA-Z0-9\-]{3,}', query)
    for term in query_terms:
        term_lower = term.lower()
        if term_lower not in [k.lower() for k in keywords] and term_lower not in {"give", "details", "order", "what", "who", "where", "how", "with", "from", "that", "this"}:
            keywords.append(term)

    # Three-stage candidate retrieval: unique identifiers (like numbers/codes) prioritized first to prevent being drowned out by generic keywords
    identifiers = []
    # Match pure digits (4 or more)
    for num in re.findall(r'\b\d{4,}\b', query):
        identifiers.append(num)
    # Match alphanumeric codes like CQ-100518
    for code in re.findall(r'\b[a-zA-Z]+-\d+\b', query):
        identifiers.append(code)

    GENERIC_WORDS = {"id", "give", "details", "order", "what", "who", "where", "how", "with", "from", "that", "this", "company", "service", "project", "client", "support", "hiring", "system", "website", "application", "business", "info", "information"}
    specific_keywords = [k for k in keywords if k.lower() not in GENERIC_WORDS and k not in identifiers]
    generic_keywords = [k for k in keywords if k.lower() in GENERIC_WORDS and k not in identifiers]

    candidates = []
    candidate_ids = set()

    # Stage 1: Unique Identifiers (up to 20 candidates)
    if identifiers:
        id_filter = {"source_id": {"$in": active_ids}}
        regex_conditions = []
        for kw in identifiers:
            regex_conditions.extend([
                {"chunk_text": re.compile(re.escape(kw), re.I)},
                {"title": re.compile(re.escape(kw), re.I)},
                {"category": re.compile(re.escape(kw), re.I)},
                {"keywords": re.compile(re.escape(kw), re.I)}
            ])
        id_filter["$or"] = regex_conditions
        
        id_candidates = list(chunks_collection.find(id_filter).sort("created_at", -1).limit(20))
        for c in id_candidates:
            c_id = str(c["_id"])
            if c_id not in candidate_ids:
                candidates.append(c)
                candidate_ids.add(c_id)

    # Stage 2: Specific keywords (up to 40 candidates)
    if len(candidates) < 60 and specific_keywords:
        specific_filter = {"source_id": {"$in": active_ids}}
        regex_conditions = []
        for kw in specific_keywords:
            regex_conditions.extend([
                {"chunk_text": re.compile(re.escape(kw), re.I)},
                {"title": re.compile(re.escape(kw), re.I)},
                {"category": re.compile(re.escape(kw), re.I)},
                {"keywords": re.compile(re.escape(kw), re.I)}
            ])
        specific_filter["$or"] = regex_conditions
        
        specific_candidates = list(chunks_collection.find(specific_filter).sort("created_at", -1).limit(40))
        for c in specific_candidates:
            c_id = str(c["_id"])
            if c_id not in candidate_ids:
                candidates.append(c)
                candidate_ids.add(c_id)

    # Stage 3: Generic keywords (fill up to 60 candidates)
    if len(candidates) < 60 and generic_keywords:
        generic_filter = {"source_id": {"$in": active_ids}}
        regex_conditions = []
        for kw in generic_keywords:
            regex_conditions.extend([
                {"chunk_text": re.compile(re.escape(kw), re.I)},
                {"title": re.compile(re.escape(kw), re.I)},
                {"category": re.compile(re.escape(kw), re.I)},
                {"keywords": re.compile(re.escape(kw), re.I)}
            ])
        generic_filter["$or"] = regex_conditions
        
        generic_candidates = list(chunks_collection.find(generic_filter).sort("created_at", -1).limit(60 - len(candidates)))
        for c in generic_candidates:
            c_id = str(c["_id"])
            if c_id not in candidate_ids:
                candidates.append(c)
                candidate_ids.add(c_id)

    # Fallback: if keywords matched nothing, fetch some recent chunks
    if not candidates:
        candidates = list(chunks_collection.find({"source_id": {"$in": active_ids}}).sort("created_at", -1).limit(40))

    if not candidates:
        return {
            "context_text": "No highly relevant knowledge found.",
            "confidence": 0.0,
            "sources": []
        }

    chunks_text = [c.get("chunk_text", "") for c in candidates]

    # --- BM25 Search ---
    tokenized_chunks = [re.findall(r'[\w-]+', chunk.lower()) for chunk in chunks_text]
    tokenized_query = re.findall(r'[\w-]+', query.lower())
    
    bm25 = BM25Okapi(tokenized_chunks)
    bm25_scores = bm25.get_scores(tokenized_query)
    bm25_indices = np.argsort(bm25_scores)[::-1][:20].tolist()

    # --- Semantic Search ---
    from rag.embeddings import Embeddings
    embeddings_model = Embeddings()
    query_embedding = embeddings_model.embed_query(query)
    doc_embeddings = embeddings_model.embed_documents(chunks_text)
    
    similarities = cosine_similarity([query_embedding], doc_embeddings)[0]
    semantic_indices = similarities.argsort()[::-1][:25].tolist()

    # --- Entity Matching Search ---
    entity_indices = []
    query_entities = analysis.get("entities", [])
    for idx, chunk in enumerate(chunks_text):
        chunk_lower = chunk.lower()
        for ent in query_entities:
            ent_text = ent["text"] if isinstance(ent, dict) else str(ent)
            if ent_text.lower() in chunk_lower:
                entity_indices.append(idx)
                break

    # --- Exact Match Search ---
    exact_indices = []
    query_terms = re.findall(r'[a-zA-Z0-9\-]{4,}', query.lower())
    for idx, chunk in enumerate(chunks_text):
        chunk_lower = chunk.lower()
        for term in query_terms:
            if term in chunk_lower:
                exact_indices.append(idx)
                break

    # --- Merge Hybrid Results ---
    scores = {}
    
    # Semantic Score
    for idx in semantic_indices:
        scores[idx] = scores.get(idx, 0.0) + (similarities[idx] * 0.5)

    # BM25 Score
    for rank, idx in enumerate(bm25_indices):
        bm25_score = ((len(bm25_indices) - rank) / len(bm25_indices))
        scores[idx] = scores.get(idx, 0.0) + (bm25_score * 0.3)

    # Entity Match Score
    for idx in entity_indices:
        scores[idx] = scores.get(idx, 0.0) + 0.2

    # Exact Match Bonus
    for idx in exact_indices:
        scores[idx] = scores.get(idx, 0.0) + 0.4

    # Final Ranking
    ranked_indices = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    
    # Map back to candidate chunks and inject relevance score
    ranked_candidates = []
    for idx, hybrid_score in ranked_indices[:20]:
        candidate = dict(candidates[idx])
        candidate["relevance_score"] = min(hybrid_score, 1.0)
        ranked_candidates.append(candidate)

    # 5. Reranking
    reranked = rerank_chunks(ranked_candidates, query, analysis)

    # 6. Context Validation
    is_valid = validate_context_relevance(query, reranked, threshold=0.22)
    
    if not is_valid:
        return {
            "context_text": "No highly relevant knowledge found.",
            "confidence": 0.0,
            "sources": []
        }

    # Take top limit chunks
    top_chunks = reranked[:limit]
    
    # Format context blocks
    context_blocks = []
    sources_used = []
    
    for chunk in top_chunks:
        src_id = chunk.get("source_id")
        source_name = active_titles.get(src_id, chunk.get("source_name", "Unknown Source"))
        source_type = chunk.get("source_type", "Text")
        category = chunk.get("category", "General")
        text = chunk.get("chunk_text", "").strip()
        
        # Format block
        meta_str = f"Source: {source_name} ({source_type}) | Category: {category}"
        meta = chunk.get("metadata", {})
        if "page_number" in meta:
            meta_str += f" | Page: {meta['page_number']}"
        if "sheet_name" in meta:
            meta_str += f" | Sheet: {meta['sheet_name']}"
            
        context_blocks.append(f"=== {meta_str} ===\n{text}")
        if source_name not in sources_used:
            sources_used.append(source_name)

    # Confidence is the score of the top chunk
    top_confidence = top_chunks[0].get("final_relevance_score", 0.0) if top_chunks else 0.0

    return {
        "context_text": "\n\n".join(context_blocks),
        "confidence": float(top_confidence),
        "sources": sources_used
    }

def retrieve_company_context(query: str, limit: int = 4) -> str:
    """
    Wrapper for backward compatibility.
    """
    details = retrieve_company_context_details(query, limit)
    return details["context_text"]

