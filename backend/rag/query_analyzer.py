import json
import re
from langchain_core.messages import HumanMessage
from llm_client import FailoverChatGroq

# Initialize LLM for query analysis
llm = FailoverChatGroq(
    model="llama-3.1-8b-instant",
    temperature=0.1,
)

def safe_json_loads(text: str, fallback: dict) -> dict:
    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return fallback
    return fallback

def analyze_query(query: str) -> dict:
    """
    Analyzes the latest user message to extract structured query info.
    Returns:
    {
      "query_type": "portfolio_examples | service_inquiry | policy_question | company_faq | general",
      "keywords": [...],
      "entities": [...],
      "category_boost": "Company Information | Services | Pricing | Policies | FAQs | Hiring Information | Support Guides | None",
      "domain": "support | hiring | sales | generic",
      "should_use_rag": true | false
    }
    """
    if not query or not query.strip():
        return {
            "query_type": "general",
            "keywords": [],
            "entities": [],
            "category_boost": "None",
            "domain": "generic",
            "should_use_rag": False
        }

    # First, rule-based check for very generic messages to save API calls/time
    words = re.findall(r"\w+", query.lower())
    if len(words) <= 2 and all(w in {"hi", "hello", "thanks", "thank", "hey", "bye", "ok", "yes", "no", "sure"} for w in words):
        return {
            "query_type": "general",
            "keywords": words,
            "entities": [],
            "category_boost": "None",
            "domain": "generic",
            "should_use_rag": False
        }

    prompt = f"""
You are a Query Analyzer for an enterprise chatbot RAG system.
Your job is to analyze the user's latest query and extract metadata to optimize knowledge retrieval.

Latest Query: "{query}"

Analyze the query and return ONLY a valid JSON object matching the following structure:
{{
  "query_type": "portfolio_examples | service_inquiry | policy_question | company_faq | general",
  "keywords": ["list", "of", "important", "search", "terms"],
  "entities": ["company names", "services", "products", "technologies"],
  "category_boost": "Company Information | Services | Pricing | Policies | FAQs | Hiring Information | Support Guides | None",
  "domain": "support | hiring | sales | generic",
  "should_use_rag": true
}}

Rules for extraction:
1. "should_use_rag" should be false for greetings, goodbyes, generic conversational agreements/refusals (e.g. "I don't want to share my details", "skip"), and true for any question about company services, portfolio, examples, policies, hiring, support, or pricing.
2. "category_boost" maps to:
   - "Policies" for questions about refunds, returns, privacy, legal rules.
   - "Pricing" for questions about cost, price, budget, quote, fees.
   - "Hiring Information" for questions about jobs, internship, resume, hiring.
   - "Services" for questions about what the company offers or builds (e.g., website, app, chatbot development).
   - "FAQs" for general questions like "where are you located", "who are your clients".
   - "Company Information" for general brand inquiries.
   - "None" if not clear.

Return ONLY valid JSON.
"""

    try:
        json_llm = llm.bind(response_format={"type": "json_object"})
        result = json_llm.invoke([HumanMessage(content=prompt)]).content
        parsed = safe_json_loads(result, {})
    except Exception:
        parsed = {}

    # Defaults and fallbacks
    return {
        "query_type": parsed.get("query_type", "general"),
        "keywords": parsed.get("keywords", [w for w in words if len(w) > 3]),
        "entities": parsed.get("entities", []),
        "category_boost": parsed.get("category_boost", "None"),
        "domain": parsed.get("domain", "generic"),
        "should_use_rag": parsed.get("should_use_rag", True)
    }
