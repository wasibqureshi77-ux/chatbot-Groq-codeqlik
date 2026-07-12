from __future__ import annotations

import json
import os
import re
from typing import Any

STOPWORDS = {
    "the", "a", "an", "is", "are", "of", "to", "in", "for", "on", "and", "or", "what",
    "how", "why", "where", "who", "when", "you", "your", "we", "our", "this", "that",
    "with", "from", "do", "does", "did", "can", "could", "would", "please", "tell", "give",
    "about", "me", "have", "has", "had", "kitne", "kitna", "kya", "hai", "h", "ka", "ki",
    "ke", "me", "mein", "batao", "bata", "aap", "tum", "apke", "aapke",
}

COUNT_PATTERNS = (
    r"\bhow many\b", r"\bnumber of\b", r"\btotal\b", r"\bcount\b",
    r"\bkitne\b", r"\bkitni\b", r"\bkul\b",
)

SUBJECT_RULES = [
    ("projects", ("project", "projects", "case studies", "deliveries")),
    ("clients", ("client", "clients", "customers", "businesses")),
    ("employees", ("employee", "employees", "team members", "developers", "staff")),
    ("offices", ("office", "offices", "locations", "branches")),
    ("reviews", ("review", "reviews", "ratings")),
    ("years", ("years", "experience", "founded", "started", "established")),
    ("price", ("price", "cost", "pricing", "budget", "charges", "fees", "rate")),
]


def safe_json_loads(text: str, fallback: dict) -> dict:
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text or "", re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
    return fallback


def _tokens(query: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9+./_-]*", query.lower())
        if token not in STOPWORDS and len(token) > 1
    ]


def _detect_subject(query_lower: str) -> str | None:
    for subject, terms in SUBJECT_RULES:
        if any(term in query_lower for term in terms):
            return subject
    return None


def _rule_analysis(query: str) -> dict[str, Any]:
    query_lower = query.lower().strip()
    words = _tokens(query)
    is_greeting = bool(re.fullmatch(r"\s*(?:hi|hello|hey|thanks|thank you|bye|ok|okay|yes|no|sure)[!. ]*", query_lower))
    is_count = any(re.search(pattern, query_lower) for pattern in COUNT_PATTERNS)
    subject = _detect_subject(query_lower)

    if any(term in query_lower for term in ("refund", "privacy", "terms", "policy", "cancellation", "legal")):
        query_type = "policy_question"
        category_boost = "Policies"
        domain = "generic"
    elif any(term in query_lower for term in ("price", "cost", "pricing", "budget", "quote", "fees", "charges")):
        query_type = "pricing_question"
        category_boost = "Pricing"
        domain = "sales"
    elif any(term in query_lower for term in ("job", "career", "internship", "opening", "vacancy", "apply", "resume")):
        query_type = "hiring_question"
        category_boost = "Hiring Information"
        domain = "hiring"
    elif any(term in query_lower for term in ("service", "provide", "offer", "build", "develop", "website", "mobile app", "chatbot", "erp", "crm", "api")):
        query_type = "service_inquiry"
        category_boost = "Services"
        domain = "sales"
    elif any(term in query_lower for term in ("portfolio", "case study", "projects", "our work")):
        query_type = "portfolio_count" if is_count else "portfolio_examples"
        category_boost = "Company Information"
        domain = "sales"
    else:
        query_type = "company_faq" if not is_greeting else "general"
        category_boost = "Company Information" if not is_greeting else "None"
        domain = "generic"

    identifiers = re.findall(r"\b(?:[A-Z]{2,}[A-Z0-9-]*|[A-Za-z]+-\d+[A-Za-z0-9-]*)\b", query)
    numbers = re.findall(r"\b\d+(?:\.\d+)?\b", query)

    expansions: list[str] = []
    if is_count and subject:
        expansions.extend([
            f"total {subject}", f"number of {subject}", f"confirmed {subject} count",
            f"verified {subject} count",
        ])
        if subject == "projects":
            expansions.extend(["projects completed", "projects delivered"])
    if subject == "price":
        expansions.extend(["pricing policy", "project estimate", "fixed price"])

    return {
        "query_type": query_type,
        "keywords": list(dict.fromkeys(words + identifiers + numbers)),
        "entities": identifiers,
        "category_boost": category_boost,
        "domain": domain,
        "should_use_rag": not is_greeting,
        "is_quantitative": is_count,
        "requires_explicit_quantity": bool(is_count and subject),
        "quantitative_subject": subject,
        "query_expansions": list(dict.fromkeys(expansions)),
    }


def analyze_query(query: str) -> dict:
    """Analyze a query without making retrieval depend on an LLM.

    Set RAG_QUERY_ANALYZER_LLM=true to optionally enrich keywords. Rule-derived safety
    facets always remain authoritative.
    """
    if not query or not query.strip():
        return {
            "query_type": "general", "keywords": [], "entities": [], "category_boost": "None",
            "domain": "generic", "should_use_rag": False, "is_quantitative": False,
            "requires_explicit_quantity": False, "quantitative_subject": None,
            "query_expansions": [],
        }

    result = _rule_analysis(query)
    if os.getenv("RAG_QUERY_ANALYZER_LLM", "false").lower() != "true":
        return result

    try:
        from langchain_core.messages import HumanMessage
        from llm_client import FailoverChatGroq

        llm = FailoverChatGroq(model="llama-3.1-8b-instant", temperature=0.0)
        prompt = (
            "Extract only additional search keywords and named entities from the user query. "
            "Return JSON: {\"keywords\":[],\"entities\":[]}. Do not classify or answer.\n\n"
            f"Query: {query}"
        )
        response = llm.bind(response_format={"type": "json_object"}).invoke([HumanMessage(content=prompt)])
        parsed = safe_json_loads(response.content, {})
        result["keywords"] = list(dict.fromkeys(result["keywords"] + [str(v) for v in parsed.get("keywords", [])]))
        result["entities"] = list(dict.fromkeys(result["entities"] + [str(v) for v in parsed.get("entities", [])]))
    except Exception:
        pass
    return result
