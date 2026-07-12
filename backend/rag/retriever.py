from __future__ import annotations

import os
import re
from typing import Any

import numpy as np
try:
    from rank_bm25 import BM25Okapi
except ImportError:
    class BM25Okapi:
        """Small dependency-free fallback used only when rank_bm25 is unavailable."""
        def __init__(self, corpus):
            self.corpus = corpus
            self.document_count = max(1, len(corpus))
            self.document_lengths = [max(1, len(doc)) for doc in corpus]
            self.average_length = sum(self.document_lengths) / self.document_count
            self.document_frequency = {}
            for doc in corpus:
                for token in set(doc):
                    self.document_frequency[token] = self.document_frequency.get(token, 0) + 1

        def get_scores(self, query_tokens):
            scores = []
            k1, b = 1.5, 0.75
            for doc, length in zip(self.corpus, self.document_lengths):
                frequencies = {}
                for token in doc:
                    frequencies[token] = frequencies.get(token, 0) + 1
                score = 0.0
                for token in query_tokens:
                    df = self.document_frequency.get(token, 0)
                    if not df:
                        continue
                    idf = np.log(1 + (self.document_count - df + 0.5) / (df + 0.5))
                    tf = frequencies.get(token, 0)
                    denominator = tf + k1 * (1 - b + b * length / self.average_length)
                    if denominator:
                        score += idf * (tf * (k1 + 1) / denominator)
                scores.append(score)
            return scores
from sklearn.metrics.pairwise import cosine_similarity

from database import knowledge_sources_collection, knowledge_chunks_collection
from rag.embeddings import embeddings_model
from rag.loader import (
    Document,
    load_any_file,
    load_csv,
    load_docx,
    load_json,
    load_pdf,
    load_txt,
    load_xlsx,
)
from rag.query_analyzer import analyze_query
from rag.ranker import rerank_chunks

sources_collection = knowledge_sources_collection
chunks_collection = knowledge_chunks_collection

USE_METADATA_RAG = os.getenv("USE_METADATA_RAG", "true").lower() == "true"
RAG_DEBUG = os.getenv("RAG_DEBUG", "false").lower() == "true"

STOPWORDS = {
    "the", "a", "an", "is", "are", "of", "to", "in", "for", "on", "and", "or", "what",
    "how", "why", "where", "who", "when", "you", "your", "we", "our", "this", "that",
    "with", "from", "do", "does", "did", "can", "could", "would", "please", "tell", "give",
    "about", "me", "have", "has", "had", "kitne", "kitna", "kya", "hai", "h", "ka", "ki",
    "ke", "me", "mein", "batao", "bata", "aap", "tum", "apke", "aapke",
}

GENERIC_WORDS = {
    "company", "service", "services", "project", "projects", "client", "clients", "support",
    "hiring", "system", "website", "application", "business", "information", "details",
}

UNAVAILABLE_PHRASES = (
    "verified information is unavailable",
    "verified total is unavailable",
    "does not contain a confirmed",
    "not currently available",
    "cannot be verified",
    "conflicting values",
    "conflicting claims",
    "request authorized confirmation",
    "must not be treated as the complete total",
    "should not be treated as the complete total",
)


def _word_tokens(text: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-z0-9][a-z0-9+./_-]*", (text or "").lower())
        if token not in STOPWORDS and len(token) > 1
    ]


def _contains(text: str, term: str) -> bool:
    term = term.lower().strip()
    if not term:
        return False
    if " " in term:
        return term in text
    return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text))


def _searchable_text(chunk: dict[str, Any]) -> str:
    return "\n".join([
        str(chunk.get("title", "")),
        str(chunk.get("category", "")),
        str(chunk.get("topic", "")),
        str(chunk.get("service", "")),
        str(chunk.get("summary", "")),
        str(chunk.get("retrieval_text") or chunk.get("chunk_text", "")),
        " ".join(str(value) for value in chunk.get("keywords", []) if isinstance(value, str)),
        " ".join(str(value) for value in chunk.get("sample_questions", []) if isinstance(value, str)),
    ]).strip()


def detect_query_topic(query: str) -> tuple[str, bool]:
    lower = query.lower()
    rules = [
        ("pricing", ("price", "pricing", "cost", "budget", "quote", "charges", "fees")),
        ("contact", ("contact", "address", "phone", "email", "office", "location", "opening hours")),
        ("portfolio", ("portfolio", "projects", "case study", "our work", "delivered")),
        ("policies", ("privacy", "policy", "refund", "terms", "cancellation", "legal")),
        ("technologies", ("technology", "tech stack", "framework", "python", "react", "node", "java")),
        ("services", ("services", "provide", "offer", "build", "develop", "solution")),
        ("careers", ("career", "job", "internship", "opening", "apply")),
    ]
    for topic, terms in rules:
        if any(term in lower for term in terms):
            return topic, True
    return "general", False


def detect_query_service(query: str) -> tuple[str, bool]:
    lower = query.lower()
    rules = [
        ("website", ("website", "web app", "web development", "wordpress", "cms")),
        ("mobile_app", ("mobile app", "ios", "android", "flutter", "react native")),
        ("ecommerce", ("ecommerce", "e-commerce", "shopify", "online store", "marketplace")),
        ("erp", ("erpnext", "odoo", "erp ", "enterprise resource planning")),
        ("crm", ("crm", "customer relationship management")),
        ("ai_automation", ("chatbot", "rag", "ai agent", "voice agent", "machine learning", "automation")),
        ("software", ("software", "saas", "backend", "database", "api", "cloud", "devops")),
    ]
    for service, terms in rules:
        if any(term in lower for term in terms):
            return service, True
    return "general", False


def build_metadata_filter(
    detected_intent,
    detected_topic,
    topic_confident,
    detected_service,
    service_confident,
    filter_level=0,
):
    """Backward-compatible helper.

    Metadata is intentionally soft in the new retriever, so this returns only tenant/source-safe
    neutral filters. Existing imports do not break, but wrong metadata cannot hide good chunks.
    """
    return {}


def _active_source_query(tenant_id: str | None) -> dict[str, Any]:
    query: dict[str, Any] = {"enabled": True}
    if tenant_id is not None:
        query["tenant_id"] = tenant_id
    return query


def _chunk_query(active_ids: list[str], tenant_id: str | None) -> dict[str, Any]:
    query: dict[str, Any] = {"source_id": {"$in": active_ids}, "status": {"$ne": "disabled"}}
    if tenant_id is not None:
        query["tenant_id"] = tenant_id
    return query


def get_filtered_candidates(
    active_ids,
    identifiers,
    specific_keywords,
    generic_keywords,
    metadata_filter,
    tenant_id: str | None = None,
):
    """Backward-compatible candidate API with safe full-pool scanning.

    Company knowledge bases are normally small enough to score all active chunks. This avoids
    losing the correct chunk because a noisy regex prefilter selected the wrong pool.
    """
    maximum = max(50, int(os.getenv("RAG_MAX_SCAN_CHUNKS", "1500")))
    query = _chunk_query([str(value) for value in active_ids], tenant_id)
    if metadata_filter:
        query = {"$and": [query, metadata_filter]}
    return list(chunks_collection.find(query).sort("created_at", -1).limit(maximum))


def _normalized_bm25(scores: np.ndarray) -> np.ndarray:
    if scores.size == 0:
        return scores
    maximum = float(np.max(scores))
    if maximum <= 0:
        return np.zeros_like(scores, dtype=float)
    return np.asarray(scores, dtype=float) / maximum


def _valid_embedding(embedding: Any, expected_dimension: int) -> bool:
    return (
        isinstance(embedding, list)
        and len(embedding) == expected_dimension
        and all(isinstance(value, (int, float)) for value in embedding)
    )


def _lexical_coverage(searchable: str, terms: list[str]) -> float:
    if not terms:
        return 0.0
    matched = sum(1 for term in terms if _contains(searchable, term))
    return matched / len(terms)


def _explicit_quantity_evidence(text: str, subject: str | None) -> bool:
    lower = text.lower()
    if any(phrase in lower for phrase in UNAVAILABLE_PHRASES):
        return False
    if not subject:
        return bool(re.search(r"\b(?:total|count|number of)\b.{0,40}\b\d[\d,]*\+?\b", lower))

    subject_patterns = {
        "projects": r"projects?",
        "clients": r"(?:clients?|customers?|businesses)",
        "employees": r"(?:employees?|developers?|team members?|staff)",
        "offices": r"(?:offices?|locations?|branches)",
        "reviews": r"(?:reviews?|ratings?)",
        "years": r"years?",
        "price": r"(?:price|cost|fee|charge|rate)",
    }
    noun = subject_patterns.get(subject, re.escape(subject))
    patterns = [
        rf"\b(?:total|confirmed|verified|completed|delivered|worked on)\b.{{0,45}}\b\d[\d,]*(?:\.\d+)?\+?\b.{{0,20}}\b{noun}\b",
        rf"\b\d[\d,]*(?:\.\d+)?\+?\b.{{0,20}}\b{noun}\b.{{0,35}}\b(?:total|completed|delivered|served|published|currently)\b",
        rf"\b(?:we|company|codeqlik)\b.{{0,35}}\b(?:completed|delivered|served|has|have)\b.{{0,20}}\b\d[\d,]*(?:\.\d+)?\+?\b.{{0,15}}\b{noun}\b",
    ]
    if subject == "price":
        patterns.extend([
            r"(?:₹|\$|€|£)\s*\d[\d,]*(?:\.\d+)?",
            r"\b\d[\d,]*(?:\.\d+)?\s*(?:INR|USD|EUR|GBP)\b",
        ])
    return any(re.search(pattern, lower, re.I) for pattern in patterns)


def _needs_exact_fact(query: str, analysis: dict[str, Any]) -> str | None:
    lower = query.lower()
    if analysis.get("requires_explicit_quantity"):
        return "quantity"
    if any(term in lower for term in ("ceo", "founder", "co-founder", "owner", "managing director")):
        return "leadership"
    if any(term in lower for term in ("iso", "certified", "certification", "soc 2", "hipaa", "gdpr compliant")):
        return "certification"
    if any(term in lower for term in ("annual revenue", "turnover", "company revenue")):
        return "revenue"
    return None


def _answerability(query: str, analysis: dict[str, Any], chunks: list[dict[str, Any]]) -> tuple[bool, str]:
    if not chunks:
        return False, "no_relevant_context"

    combined = "\n".join(str(chunk.get("content") or chunk.get("chunk_text", "")) for chunk in chunks)
    combined_lower = combined.lower()
    answer_modes = {str(chunk.get("answer_mode", "direct")) for chunk in chunks}
    verification_statuses = {str(chunk.get("verification_status", "")) for chunk in chunks}

    if "verified_information_unavailable" in answer_modes:
        return False, "verified_information_unavailable"

    exact_fact = _needs_exact_fact(query, analysis)
    if exact_fact and any(phrase in combined_lower for phrase in UNAVAILABLE_PHRASES):
        return False, "verified_information_unavailable"
    if exact_fact == "quantity":
        subject = analysis.get("quantitative_subject")
        supporting = [
            chunk for chunk in chunks
            if _explicit_quantity_evidence(str(chunk.get("content") or chunk.get("chunk_text", "")), subject)
        ]
        if not supporting:
            return False, "explicit_quantity_not_found"
        if all(
            str(chunk.get("answer_mode", "direct")) in {"requires_confirmation", "cautious_direct"}
            or str(chunk.get("verification_status", "")).endswith("requires_review")
            for chunk in supporting
        ):
            return False, "quantity_claim_requires_confirmation"

    if exact_fact in {"leadership", "certification", "revenue"}:
        direct_chunks = [
            chunk for chunk in chunks
            if str(chunk.get("answer_mode", "direct")) not in {"requires_confirmation", "cautious_direct"}
            and "conflicting" not in str(chunk.get("verification_status", "")).lower()
        ]
        if not direct_chunks:
            return False, f"{exact_fact}_not_verified"

    if exact_fact and "conflicting_source_claims" in verification_statuses:
        return False, "conflicting_source_claims"
    return True, "grounded_context_available"


def validate_context_relevance(query: str, chunks: list[dict], threshold: float = 0.30) -> bool:
    if not chunks:
        return False
    top = chunks[0]
    return (
        float(top.get("final_relevance_score", 0.0)) >= threshold
        and (
            float(top.get("semantic_score", 0.0)) >= float(os.getenv("RAG_MIN_SEMANTIC_SCORE", "0.20"))
            or float(top.get("lexical_coverage", 0.0)) >= 0.45
            or float(top.get("exact_phrase_score", 0.0)) > 0
        )
    )


def retrieve_company_context_details(
    query: str,
    limit: int = 4,
    intent: str = None,
    tenant_id: str = None,
) -> dict:
    analysis = analyze_query(query)
    if not analysis.get("should_use_rag", True):
        return {
            "context_text": "No RAG context needed for general chat.",
            "confidence": 0.0,
            "sources": [],
            "chunks": [],
            "answerable": False,
            "reason": "rag_not_needed",
            "query_analysis": analysis,
        }

    active_sources = list(
        sources_collection.find(
            _active_source_query(tenant_id),
            {"_id": 1, "title": 1, "tenant_id": 1},
        )
    )
    if not active_sources:
        return {
            "context_text": "No active knowledge sources are configured.",
            "confidence": 0.0,
            "sources": [],
            "chunks": [],
            "answerable": False,
            "reason": "no_active_sources",
            "query_analysis": analysis,
        }

    active_ids = [str(source["_id"]) for source in active_sources]
    active_titles = {str(source["_id"]): source.get("title", "Unknown Source") for source in active_sources}

    query_terms = list(dict.fromkeys(
        [str(value).lower() for value in analysis.get("keywords", []) if str(value).strip()]
        + _word_tokens(query)
    ))
    identifiers = [str(value) for value in analysis.get("entities", []) if str(value).strip()]
    meaningful_terms = [term for term in query_terms if term not in STOPWORDS]
    specific_keywords = [term for term in meaningful_terms if term not in GENERIC_WORDS]
    generic_keywords = [term for term in meaningful_terms if term in GENERIC_WORDS]

    detected_topic, topic_confident = detect_query_topic(query)
    detected_service, service_confident = detect_query_service(query)
    intent_map = {
        "client_lead": "client", "customer_support": "support", "hiring_support": "hiring",
        "general_chat": "greet", "client": "client", "support": "support", "hiring": "hiring",
        "greet": "greet", "all": "all",
    }
    detected_intent = intent_map.get(intent, "all")
    analysis.update({
        "detected_query_topic": detected_topic,
        "detected_query_service": detected_service,
        "detected_intent_scope": detected_intent,
    })

    candidates = get_filtered_candidates(
        active_ids,
        identifiers,
        specific_keywords,
        generic_keywords,
        {},
        tenant_id=tenant_id,
    )
    if not candidates:
        return {
            "context_text": "No highly relevant knowledge found.",
            "confidence": 0.0,
            "sources": [],
            "chunks": [],
            "answerable": False,
            "reason": "no_candidates",
            "query_analysis": analysis,
        }

    searchable_texts = [_searchable_text(candidate) for candidate in candidates]
    canonical_query = " ".join([query] + list(analysis.get("query_expansions", [])))
    tokenized_documents = [_word_tokens(text) for text in searchable_texts]
    tokenized_query = _word_tokens(canonical_query)
    bm25 = BM25Okapi(tokenized_documents)
    bm25_scores = _normalized_bm25(np.asarray(bm25.get_scores(tokenized_query), dtype=float))

    query_embedding = embeddings_model.embed_query(canonical_query)
    expected_dimension = len(query_embedding)
    document_embeddings: list[list[float] | None] = []
    missing_indices: list[int] = []
    missing_texts: list[str] = []
    for index, candidate in enumerate(candidates):
        embedding = candidate.get("embedding")
        if _valid_embedding(embedding, expected_dimension):
            document_embeddings.append(embedding)
        else:
            document_embeddings.append(None)
            missing_indices.append(index)
            missing_texts.append(searchable_texts[index])
    if missing_texts:
        computed = embeddings_model.embed_documents(missing_texts)
        for index, embedding in zip(missing_indices, computed):
            document_embeddings[index] = embedding

    similarities = cosine_similarity([query_embedding], document_embeddings)[0]
    quantity_subject = analysis.get("quantitative_subject")
    ranked_candidates: list[dict[str, Any]] = []

    for index, candidate in enumerate(candidates):
        searchable_lower = searchable_texts[index].lower()
        title_lower = str(candidate.get("title", "")).lower()
        semantic = max(0.0, float(similarities[index]))
        lexical = _lexical_coverage(searchable_lower, meaningful_terms)
        title_coverage = _lexical_coverage(title_lower, meaningful_terms)
        exact_phrase = 1.0 if len(query.strip()) >= 5 and query.lower().strip() in searchable_lower else 0.0
        identifier_score = 1.0 if identifiers and any(_contains(searchable_lower, identifier) for identifier in identifiers) else 0.0
        quantity_evidence = 1.0 if _explicit_quantity_evidence(str(candidate.get("content") or candidate.get("chunk_text", "")), quantity_subject) else 0.0

        metadata_bonus = 0.0
        if USE_METADATA_RAG:
            if topic_confident and str(candidate.get("topic", "")).lower() == detected_topic:
                metadata_bonus += 0.025
            if service_confident and str(candidate.get("service", "")).lower() == detected_service:
                metadata_bonus += 0.02
            if str(candidate.get("intent_scope", "all")).lower() in {detected_intent, "all"}:
                metadata_bonus += 0.01

        score = (
            semantic * 0.56
            + float(bm25_scores[index]) * 0.20
            + lexical * 0.12
            + title_coverage * 0.06
            + exact_phrase * 0.04
            + identifier_score * 0.08
            + quantity_evidence * (0.08 if analysis.get("requires_explicit_quantity") else 0.0)
            + metadata_bonus
        )

        # Count/list distinction: a portfolio-example chunk is related but insufficient for a total.
        if analysis.get("requires_explicit_quantity") and not quantity_evidence:
            score *= 0.74
        if str(candidate.get("answer_mode")) == "verified_information_unavailable":
            score += 0.10

        copy = dict(candidate)
        copy.update({
            "relevance_score": min(score, 1.0),
            "semantic_score": round(semantic, 5),
            "bm25_score": round(float(bm25_scores[index]), 5),
            "lexical_coverage": round(lexical, 5),
            "title_coverage": round(title_coverage, 5),
            "exact_phrase_score": exact_phrase,
            "quantity_evidence": bool(quantity_evidence),
            "match_reasons": [
                reason for reason, active in (
                    ("semantic", semantic >= 0.25), ("bm25", bm25_scores[index] > 0),
                    ("lexical", lexical > 0), ("title", title_coverage > 0),
                    ("exact_phrase", exact_phrase > 0), ("quantity_evidence", quantity_evidence > 0),
                ) if active
            ],
        })
        ranked_candidates.append(copy)

    ranked_candidates.sort(key=lambda item: item["relevance_score"], reverse=True)
    reranked = rerank_chunks(ranked_candidates[: min(30, len(ranked_candidates))], query, analysis)

    minimum_score = float(os.getenv("RAG_MIN_HYBRID_SCORE", "0.30"))
    relative_ratio = float(os.getenv("RAG_RELATIVE_SCORE_RATIO", "0.68"))
    if not reranked or not validate_context_relevance(query, reranked, threshold=minimum_score):
        return {
            "context_text": "No highly relevant knowledge found.",
            "confidence": 0.0,
            "sources": [],
            "chunks": [],
            "answerable": False,
            "reason": "relevance_below_threshold",
            "query_analysis": analysis,
        }

    top_score = float(reranked[0].get("final_relevance_score", 0.0))
    selected = [
        chunk for chunk in reranked
        if float(chunk.get("final_relevance_score", 0.0)) >= minimum_score
        and float(chunk.get("final_relevance_score", 0.0)) >= top_score * relative_ratio
    ][: max(1, limit)]

    answerable, reason = _answerability(query, analysis, selected)
    context_blocks: list[str] = []
    source_names: list[str] = []
    chunk_debug: list[dict[str, Any]] = []

    if not answerable:
        context_blocks.append(
            "=== GROUNDING GUARD ===\n"
            "The retrieved material does not explicitly verify the exact fact requested. "
            "Do not infer a total by counting examples and do not fill missing company facts from "
            "general model knowledge. State that verified information is unavailable or requires "
            "authorized confirmation."
        )

    for chunk in selected:
        source_id = str(chunk.get("source_id", ""))
        source_name = active_titles.get(source_id, chunk.get("source_name", "Unknown Source"))
        if source_name not in source_names:
            source_names.append(source_name)
        source_type = chunk.get("source_type", "text")
        category = chunk.get("category", "general")
        content = str(chunk.get("content") or chunk.get("chunk_text", "")).strip()
        metadata = chunk.get("metadata") or {}
        locator = metadata.get("source_locator") or {}
        locator_text = ""
        if locator:
            locator_text = " | Locator: " + ", ".join(f"{key}={value}" for key, value in locator.items() if value not in (None, ""))
        context_blocks.append(
            f"=== Source: {source_name} ({source_type}) | Category: {category}{locator_text} ===\n"
            f"Title: {chunk.get('title', '')}\n"
            f"Verification: {chunk.get('verification_status', 'unknown')} | Answer mode: {chunk.get('answer_mode', 'direct')}\n"
            f"{content}"
        )
        chunk_debug.append({
            "knowledge_id": chunk.get("knowledge_id"),
            "title": chunk.get("title"),
            "source": source_name,
            "final_score": chunk.get("final_relevance_score"),
            "semantic_score": chunk.get("semantic_score"),
            "bm25_score": chunk.get("bm25_score"),
            "lexical_coverage": chunk.get("lexical_coverage"),
            "quantity_evidence": chunk.get("quantity_evidence"),
            "verification_status": chunk.get("verification_status"),
            "answer_mode": chunk.get("answer_mode"),
            "risk_flags": chunk.get("risk_flags", []),
        })

    if RAG_DEBUG:
        print("\n========== RAG DEBUG ==========")
        print("Query:", query)
        print("Canonical query:", canonical_query)
        print("Analysis:", analysis)
        print("Candidates:", len(candidates))
        print("Selected:", chunk_debug)
        print("Answerable:", answerable, "Reason:", reason)
        print("================================\n")

    return {
        "context_text": "\n\n".join(context_blocks),
        "confidence": float(selected[0].get("final_relevance_score", 0.0)) if selected else 0.0,
        "sources": source_names,
        "chunks": chunk_debug,
        "answerable": answerable,
        "reason": reason,
        "query_analysis": analysis,
    }


def retrieve_company_context(query: str, limit: int = 4, tenant_id: str = None) -> str:
    """Backward-compatible wrapper."""
    return retrieve_company_context_details(query, limit=limit, tenant_id=tenant_id)["context_text"]
