from typing import Annotated, Optional
from typing_extensions import TypedDict
import json
import re

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from database import (
    save_chat_to_mongo,
    save_collection_data,
    get_chatbot_settings,
    get_booked_meeting_slots,
)
from rag.retriever import retrieve_company_context_details
from llm_client import FailoverChatGroq, thread_id_var, node_name_var
from langsmith import traceable


llm = FailoverChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0.4,
)


REQUIRED_FIELDS = {
    "client_lead": [
        "name",
        "email",
        "phone",
        "company",
        "project_type",
        "requirements",
        "budget",
        "timeline",
    ],
    "customer_support": [
        "name",
        "email",
        "phone",
        "issue_type",
        "issue_details",
        "urgency",
    ],
    "hiring_support": [
        "name",
        "email",
        "phone",
        "role",
        "experience",
        "skills",
        "resume_or_portfolio",
    ],
    "meeting_booking": [
        "name",
        "email",
        "phone",
        "company",
        "work_details",
        "meeting_mode",
        "date",
        "time_slot",
    ]
}

COLLECTION_INTENTS = {"client_lead", "customer_support", "hiring_support", "meeting_booking"}

MEETING_TIME_SLOT_OPTIONS = [
    {"label": "10:00 AM", "value": "10:00 AM"},
    {"label": "02:00 PM", "value": "02:00 PM"},
    {"label": "04:00 PM", "value": "04:00 PM"},
]

VALID_INTENTS = [
    "company_info",
    "client_lead",
    "customer_support",
    "hiring_support",
    "meeting_booking",
    "general_chat",
    "unrelated_query",
]


# Broad business/service vocabulary.
# Keep this separate from lead-detection words so informational questions like
# "tell me about e-commerce" are answered instead of treated as unrelated.
BUSINESS_DOMAIN_KEYWORDS = [
    "e commerce", "e-commerce", "ecommerce", "online store", "online shop",
    "shopping platform", "marketplace", "retail", "retail platform",
    "payment gateway", "payment integration", "apple pay", "google pay",
    "razorpay", "stripe", "paypal", "cod", "cash on delivery",
    "cart", "checkout", "order management", "product catalog",
    "inventory", "billing", "invoice", "erp", "business management",
    "management system", "admin panel", "dashboard", "customer portal",
    "vendor portal", "mobile commerce", "m-commerce", "crm", "cms",
    "pos", "booking system", "appointment system", "learning management",
    "lms", "hrm", "hrms", "saas", "automation tools",
    "ai-powered automation", "ai automation", "workflow automation",
]


class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    intent: Optional[str]
    primary_intent: Optional[str]
    active_collection: Optional[str]
    pending_field: Optional[str]
    user_goal: Optional[str]
    confidence: Optional[float]
    profile: dict
    required_fields: list[str]
    missing_fields: list[str]
    qualified: bool
    company_context: Optional[str]
    response_text: Optional[str]
    thread_id: Optional[str]
    last_pending_field: Optional[str]
    current_question: Optional[str]
    conversation_summary: Optional[str]
    retrieved_context: Optional[str]
    rag_confidence: Optional[float]
    rag_sources: list[str]
    response_mode: Optional[str]
    is_field_answer: Optional[bool]
    saved_collection: Optional[bool]
    intro_context: Optional[str]
    slot_conflict: Optional[bool]
    no_slots_available: Optional[bool]


# ---------------------------------------------------------------------
# Basic helpers
# ---------------------------------------------------------------------

def latest_user_message(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg.content
    return ""


def format_history(messages: list[BaseMessage], limit: int = 4) -> str:
    history_msgs = []
    for msg in messages[-limit:]:
        role = "User" if isinstance(msg, HumanMessage) or getattr(msg, "type", "") == "human" else "Assistant"
        history_msgs.append(f"{role}: {msg.content}")
    return "\n".join(history_msgs)


def safe_json_loads(text: str, fallback: dict) -> dict:
    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return fallback

    return fallback


def normalize(text) -> str:
    return str(text or "").strip().lower()


INVALID_VALUES = {
    "",
    "none",
    "null",
    "n/a",
    "na",
    "not provided",
    "unknown",
    "not mentioned",
    "i don't know",
    "dont know",
    "don't know",
    "what",
    "ok",
    "okay",
    "yes",
    "no",
    "sure",
    "go ahead",
    "hmm",
}

DECLINED_VALUES = {"declined", "refused", "skip", "skipped"}




# ---------------------------------------------------------------------
# Semantic compatibility helpers (old-flow safe)
# ---------------------------------------------------------------------
# Goal:
# - Keep the existing graph/state/save contract exactly the same.
# - Do NOT let LLM decide pending fields or qualification.
# - Only improve understanding for Hinglish, typos, reference products,
#   and new phrasing before the old deterministic state manager runs.

SEMANTIC_COMPAT_ENABLED = True
SEMANTIC_INTENT_MIN_CONFIDENCE = 0.76


def _space(text: str) -> str:
    return f" {normalize(text)} "


def _has_any(text: str, phrases: list[str]) -> bool:
    t = normalize(text)
    return any(p in t for p in phrases)


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", normalize(text)) is not None


# Roman Hindi / Hinglish question forms. These are used only to avoid treating
# real questions as field values; they do not start or change flow by themselves.
def is_hinglish_question(text: str) -> bool:
    t = normalize(text)
    if not t:
        return False

    starters = (
        "kya ", "kaise ", "kaisa ", "kaisi ", "kitna ", "kitni ",
        "kitne ", "kab ", "kaha ", "kahan ", "kidhar ", "kon ",
        "kaun ", "kaunsa ", "kaunsi ", "kyu ", "kyun ", "batao",
        "btao", "batado", "bta do", "samjhao", "samjha do",
    )
    if t.startswith(starters):
        return True

    question_patterns = [
        " kya ", " kaise ", " kitna ", " kitni ", " kitne ",
        " kab ", " kaha ", " kahan ", " kyun ", " kyu ",
        " batao", " btao", " batado", " bta do", " samjhao",
        " kar sakte ho", " bana sakte ho", " ban sakta hai",
        " ho sakta hai", " price", " cost", " estimate",
        " charges", " approx", " kaise banega", " kitna hoga",
    ]
    return any(p in f" {t} " for p in question_patterns)


# Project creation context must be allowed even if the domain word is normally
# unrelated. Example: "cricket scoring app banana hai" is a client lead, while
# "cricket score kya hai" is unrelated.
def has_project_creation_context(text: str) -> bool:
    t = normalize(text)
    if not t:
        return False

    build_cues = [
        "i need", "i want", "we need", "we want", "need", "want",
        "build", "develop", "create", "make", "design", "implement",
        "setup", "set up", "quote", "proposal", "estimate", "price for",
        "cost for", "how much", "charges for", "mujhe", "hame", "hume",
        "humko", "chahiye", "chahie", "chaiye", "banana", "banani",
        "banwana", "banwani", "banwa", "banva", "bana do", "bna do",
        "banado", "banani hai", "banana hai", "banwana hai", "banwani hai",
        "ready karwana", "karwana", "karwa do", "design kar", "develop kar",
        "bana sakte", "ban sakta", "kar sakte", "kar sakta",
    ]

    service_cues = [
        "website", "web site", "site", "web app", "web application",
        "mobile app", "android", "ios", "app", "application", "software",
        "portal", "platform", "system", "management system", "crm", "erp",
        "dashboard", "admin panel", "ecommerce", "e-commerce", "online store",
        "booking", "saas", "chatbot", "automation", "api", "panel",
    ]

    reference_cues = [
        " like ", " similar to ", " just like ", " same as ", " clone",
        " jaisa", " jaise", " jesi", " jese", " type", " tarah ka",
        " tarah ki", " ke jaisa", " ke jaise",
    ]

    has_build = any(cue in t for cue in build_cues)
    has_service = any(cue in t for cue in service_cues)
    has_reference = any(cue in f" {t} " for cue in reference_cues)

    return (has_build and (has_service or has_reference)) or (has_reference and has_service)


def has_semantic_client_buying_intent(text: str) -> bool:
    t = normalize(text)
    if not t:
        return False

    # Explanation-only questions should stay information answers, not leads.
    info_starters = (
        "what is ", "what are ", "explain ", "tell me about ", "describe ",
        "define ", "how does ", "how do ", "kya hota", "kya hai",
        "kaise kaam", "samjhao", "batao software kya",
    )
    if t.startswith(info_starters) and not has_project_creation_context(t):
        return False

    return has_project_creation_context(t)


def has_semantic_support_intent(text: str) -> bool:
    t = normalize(text)
    if not t:
        return False

    support_phrases = [
        "not working", "not opening", "crashing", "crash", "error", "bug",
        "issue", "problem", "broken", "server error", "login issue", "payment failed",
        "website down", "app down", "portal failing", "nahi chal", "nahin chal",
        "nhi chal", "kaam nahi", "kaam nhi", "open nahi", "open nhi",
        "login nahi", "login nhi", "error aa", "problem aa", "issue aa",
        "crash ho", "band ho", "server down", "payment nahi", "payment nhi",
        "website nahi khul", "site nahi khul", "app nahi khul",
    ]
    return any(p in t for p in support_phrases)


def has_semantic_hiring_intent(text: str) -> bool:
    t = normalize(text)
    if not t:
        return False

    hiring_phrases = [
        "job", "internship", "career", "hiring", "vacancy", "opening",
        "apply", "resume", "cv", "portfolio", "fresher", "candidate",
        "naukri", "job chahiye", "internship chahiye", "apply karna",
        "apply karna hai", "resume bhejna", "resume submit", "kaam chahiye",
        "role available", "roles available", "opening hai", "vacancy hai",
    ]
    return any(p in t for p in hiring_phrases)


def has_semantic_company_info_intent(text: str) -> bool:
    t = normalize(text)
    if not t:
        return False

    info_phrases = [
        "what services", "services do you", "who are you", "what do you do",
        "about codeqlik", "contact", "address", "office", "portfolio",
        "pricing", "cost", "technology", "technologies", "kya service",
        "kya services", "aap kya karte", "tum kya karte", "codeqlik kya",
        "company ke bare", "company ke baare", "office kaha", "office kahan",
        "contact kaise", "price list", "charges", "services batao",
    ]
    return any(p in t for p in info_phrases)


def looks_like_reference_product(text: str) -> bool:
    t = normalize(text)
    if not t:
        return False
    reference_markers = [
        "just like", "similar to", "same as", "like ", " clone", "jaisa",
        "jaise", "jesa", "jese", "type", "tarah ka", "tarah ki",
    ]
    if not any(m in t for m in reference_markers):
        return False
    # Short reference replies are common after the bot asks what kind of app/site.
    return len(t.split()) <= 12 or any(s in t for s in ["app", "website", "software", "platform", "system"])


def extract_reference_requirement_value(text: str) -> Optional[str]:
    raw = str(text or "").strip()
    if not raw or not looks_like_reference_product(raw):
        return None

    cleaned = re.sub(r"(?i)^\s*(ok|okay|yeah|yes|sure|right|hmm|just)\s+", "", raw).strip()

    patterns = [
        r"(?i)\b(?:just\s+like|similar\s+to|same\s+as|like)\s+([a-z0-9][a-z0-9& ._-]{1,60})",
        r"(?i)\b([a-z0-9][a-z0-9& ._-]{1,60})\s+(?:jaisa|jaise|jesa|jese|type|clone)\b",
        r"(?i)\b(?:jaisa|jaise|jesa|jese|type)\s+([a-z0-9][a-z0-9& ._-]{1,60})",
    ]
    for pattern in patterns:
        m = re.search(pattern, cleaned)
        if m:
            ref = m.group(1).strip(" .,-_")
            # Avoid swallowing generic service words as the reference name.
            ref = re.sub(r"(?i)\s+(app|application|website|site|software|platform|system)\s*$", "", ref).strip()
            if ref:
                return f"similar to {ref}"

    return cleaned



def detect_requested_service_topic(text: str) -> Optional[str]:
    """
    Latest-message service/topic detector with strict priority.

    Why this exists:
    - "web app" contains the generic word "app".
    - Older logic sometimes matched generic "app" first and replied as if
      the user asked for an Android/mobile app.
    - This helper always checks more specific services before generic words.

    It is intentionally read-only: it does not change intent, pending fields,
    profile save rules, or collection order.
    """
    t = normalize(text)
    if not t:
        return None

    # Exact/specific web terms before any generic app terms.
    if re.search(r"\b(web\s+app|web\s+application|web\s+portal)\b", t):
        return "web app"

    # E-commerce is more specific than a generic website.
    if re.search(r"\b(e[-\s]?commerce|ecommerce|online\s+store|shopping\s+(app|site|website|platform))\b", t):
        return "e-commerce platform"

    # Website/site is separate from web app.
    if re.search(r"\b(website|web\s+site|landing\s+page|business\s+site)\b", t):
        return "website"
    if re.search(r"\bsite\b", t) and not re.search(r"\bapp\b", t):
        return "website"

    # Platform/product types.
    if re.search(r"\bcrm\b", t):
        return "CRM system"
    if re.search(r"\b(erp|odoo)\b", t):
        return "ERP system"
    if re.search(r"\b(ai\s+chatbot|chatbot|bot|ai\s+automation|automation)\b", t):
        return "AI chatbot/automation"

    # Mobile-specific terms after web-app checks, but before add-on features
    # like admin panel/dashboard.
    if re.search(r"\bandroid\b", t):
        return "Android app"
    if re.search(r"\b(ios|iphone|ipad)\b", t):
        return "iOS app"
    if re.search(r"\b(mobile\s+app|mobile\s+application|cross[-\s]?platform\s+app)\b", t):
        return "mobile app"

    # Generic "app/application" last among app types. Do not let it override web app.
    if re.search(r"\b(app|application)\b", t):
        return "mobile app"

    # Dashboard/admin panel is often an add-on ("mobile app with admin panel").
    # Classify as dashboard only when no stronger app/site/system type was found.
    if re.search(r"\b(dashboard|admin\s+panel|analytics\s+panel|reporting\s+panel)\b", t):
        return "dashboard/admin panel"

    if re.search(r"\b(software|system|platform|portal)\b", t):
        return "software system"

    return None


def build_service_specific_capability_reply(user_text: str, company_name: str = "CodeQlik", language_hint: Optional[str] = None) -> str:
    """
    Deterministic latest-question answer used only as a safe fallback/guard.
    It does not ask fields and does not update state. Pending-field enforcement
    happens separately in response_generator_node.
    """
    topic = detect_requested_service_topic(user_text)
    lang = language_hint or detect_response_language(user_text)
    hinglish = lang in {"hinglish", "hindi"}
    t = normalize(user_text)

    if hinglish:
        if topic == "web app":
            return f"Haan, {company_name} custom web apps bana sakta hai — jaise dashboards, portals, admin panels, APIs aur business workflows."
        if topic == "website":
            return f"Haan, {company_name} business websites, landing pages, e-commerce sites aur custom website solutions bana sakta hai."
        if topic == "Android app":
            return f"Haan, {company_name} custom Android apps design aur develop kar sakta hai."
        if topic == "iOS app":
            return f"Haan, {company_name} iOS apps design aur develop kar sakta hai."
        if topic == "mobile app":
            return f"Haan, {company_name} mobile apps develop kar sakta hai — Android, iOS ya cross-platform requirement ke hisaab se."
        if topic == "e-commerce platform":
            return f"Haan, {company_name} e-commerce platforms bana sakta hai — product catalog, cart, checkout, payments aur admin panel ke saath."
        if topic == "CRM system":
            return f"Haan, {company_name} CRM systems bana sakta hai — leads, customers, follow-ups, dashboards aur reports ke saath."
        if topic == "ERP system":
            return f"Haan, {company_name} ERP/business management systems me help kar sakta hai — inventory, billing, reports aur workflows ke saath."
        if topic == "AI chatbot/automation":
            return f"Haan, {company_name} AI chatbots aur automation workflows bana sakta hai."
        if topic == "dashboard/admin panel":
            return f"Haan, {company_name} admin dashboards/panels bana sakta hai — users, reports, roles aur business data manage karne ke liye."
        if "requirement" in t or "requirements" in t:
            return "Web app requirements me usually login, dashboard, admin panel, database, APIs, reports aur integrations discuss hote hain."
        if "price" in t or "cost" in t or "estimate" in t or "kitna" in t:
            return "Haan, rough estimate de sakte hain, but exact cost features, design, admin panel, integrations aur timeline par depend karegi."
        return f"Haan, {company_name} is project me help kar sakta hai."

    if topic == "web app":
        return f"Yes, {company_name} can build custom web apps — including dashboards, portals, admin panels, APIs, and business workflows."
    if topic == "website":
        return f"Yes, {company_name} can design and build business websites, landing pages, e-commerce sites, and custom website solutions."
    if topic == "Android app":
        return f"Yes, {company_name} can design and develop custom Android apps."
    if topic == "iOS app":
        return f"Yes, {company_name} can design and develop custom iOS apps."
    if topic == "mobile app":
        return f"Yes, {company_name} can develop mobile apps for Android, iOS, or cross-platform use depending on your requirement."
    if topic == "e-commerce platform":
        return f"Yes, {company_name} can build e-commerce platforms with product catalog, cart, checkout, payments, and admin management."
    if topic == "CRM system":
        return f"Yes, {company_name} can build CRM systems for leads, customers, follow-ups, dashboards, and reports."
    if topic == "ERP system":
        return f"Yes, {company_name} can help with ERP/business management systems for inventory, billing, reporting, and workflows."
    if topic == "AI chatbot/automation":
        return f"Yes, {company_name} can build AI chatbots and automation workflows for business use cases."
    if topic == "dashboard/admin panel":
        return f"Yes, {company_name} can build admin dashboards/panels to manage users, reports, roles, and business data."
    if "requirement" in t or "requirements" in t:
        return "For a web app, we usually discuss login, dashboard, admin panel, database, APIs, reports, and integrations."
    if "price" in t or "cost" in t or "estimate" in t or "how much" in t:
        return "Yes, we can share a rough estimate, but the exact price depends on features, design, admin panel, integrations, and timeline."
    return f"Yes, {company_name} can help with this project."


def should_try_semantic_intent_fallback(user_text: str, rule_intent: str, active_collection: Optional[str]) -> bool:
    if not SEMANTIC_COMPAT_ENABLED:
        return False
    if active_collection:
        return False
    if rule_intent not in {"general_chat", "unrelated_query"}:
        return False
    if is_small_talk(user_text) or is_sensitive_or_unsafe(user_text):
        return False
    t = normalize(user_text)
    if not t or len(t.split()) < 2:
        return False
    if is_plain_value_without_context(user_text):
        return False
    # Call LLM only for messages that look like business/user-intent language but
    # the deterministic rules could not map confidently.
    return (
        is_hinglish_question(user_text)
        or has_project_creation_context(user_text)
        or looks_like_reference_product(user_text)
        or has_semantic_company_info_intent(user_text)
        or any(w in t for w in ["website", "app", "software", "system", "portal", "project", "business", "budget", "price", "support", "job"])
    )


def has_unrelated_topic_without_project_context(text: str) -> bool:
    t = normalize(text)
    unrelated_topics = [
        "trip", "travel", "tour", "hotel", "flight", "recipe", "cook",
        "pizza", "pasta", "sports", "cricket", "score", "movie", "song",
        "weather", "news", "geography", "history", "capital of",
        "himachal", "goa", "manali", "shimla", "president", "prime minister",
    ]
    return any(k in t for k in unrelated_topics) and not has_project_creation_context(text)


def safe_semantic_intent_override(user_text: str, rule_intent: str, semantic: dict) -> Optional[str]:
    intent = semantic.get("intent")
    confidence = float(semantic.get("confidence", 0.0) or 0.0)
    if intent not in VALID_INTENTS or confidence < SEMANTIC_INTENT_MIN_CONFIDENCE:
        return None

    # Never let semantic fallback turn clearly unrelated/hard unsafe content into a lead.
    if is_sensitive_or_unsafe(user_text) or has_unrelated_topic_without_project_context(user_text):
        return "unrelated_query"

    # Conservative: fallback may upgrade unclear general/unrelated messages into
    # company/client/support/hiring, but must not force random small talk into collection.
    if intent in COLLECTION_INTENTS or intent in {"company_info", "unrelated_query"}:
        return intent
    if rule_intent == "unrelated_query" and intent == "general_chat":
        return "general_chat"
    return None

def is_question(text: str) -> bool:
    t = normalize(text)
    return (
        "?" in t
        or t.startswith(("what ", "why ", "how ", "have ", "when ", "where ", "who ", "which "))
        or t.startswith(("can you", "can u", "do you", "does ", "did ", "are you", "is there", "tell me about", "could you", "would you", "should "))
        or is_hinglish_question(t)
    )


def is_ack(text: str) -> bool:
    return normalize(text) in {"ok", "okay", "yes", "yeah", "yep", "sure", "go ahead", "fine", "hmm","yes sure", "sure thing", "sounds good"}


def is_small_talk(text: str) -> bool:
    t = normalize(text)

    smalltalk_exact = {
        "hi",
        "hello",
        "hey",
        "hii",
        "hiii",
        "how are you",
        "how r u",
        "how are u",
        "what are you doing",
        "what's up",
        "whats up",
        "what's going on",
        "whats going on",
        "what is going on",
        "who are you",
        "what can you do",
        "are you a bot",
        "are you human",
        "nice",
        "great",
        "good",
        "thanks",
        "thank you",
        "bye",
        "good morning",
        "good evening",
        "good afternoon",
    }

    if t in smalltalk_exact:
        return True

    smalltalk_patterns = [
        "how are you",
        "what are you doing",
        "how is it going",
        "what's going on",
        "whats going on",
        "who are you",
        "what can you do",
        "are you a bot",
        "are you human",
        "nice to meet you",
    ]

    return any(p in t for p in smalltalk_patterns)



def looks_like_intro_context(text: str) -> bool:
    """
    Temporary intro detector for general_chat.
    We do NOT save this to profile immediately. We only buffer it and use it
    if the user later starts client/support/hiring collection.
    """
    t = normalize(text)
    if not t or is_hard_unrelated_or_unsafe(t):
        return False

    intro_cues = [
        "my name is", "i am", "i'm", "myself", "this is",
        "my company", "company is", "company name", "work at", "working at",
        "from ", " at "
    ]
    return any(cue in t for cue in intro_cues)


def is_company_or_business_info_query(text: str) -> bool:
    """
    Company/business/hiring information questions should be answered dynamically.
    They may use RAG/context, and if a collection is active, the bot should answer
    first and then ask the pending field.
    """
    t = normalize(text)

    phrases = [
        "who are you",
        "what can you do",
        "what do you do",
        "about codeqlik",
        "what is codeqlik",
        "tell me about codeqlik",
        "your services",
        "what services",
        "services do you",
        "software development",
        "web development",
        "app development",
        "ai development",
        "chatbot",
        "automation",
        "crm",
        "saas",
        "technology",
        "technologies",
        "pricing",
        "cost",
        "contact",
        "office",
        "address",
        "portfolio",
        "opening",
        "openings",
        "current opening",
        "current openings",
        "available role",
        "available roles",
        "roles available",
        "job role",
        "job roles",
        "vacancy",
        "vacancies",
        "hiring",
        "internship",
        "career",
    ]

    return any(p in t for p in phrases) or has_business_domain_keyword(t)


def is_explanatory_or_company_question(text: str) -> bool:
    """
    Company/info questions should be answered but must not be stored as profile fields.
    Examples: explain software development, what is CodeQlik, tell me about services.
    """
    t = normalize(text)

    starters = (
        "explain ",
        "what is ",
        "what are ",
        "tell me ",
        "tell me about",
        "describe ",
        "define ",
        "how does ",
        "how do ",
        "why ",
        "can you explain",
    )

    if t.startswith(starters):
        return True

    info_words = [
        "software development",
        "web development",
        "app development",
        "ai development",
        "chatbot",
        "automation",
        "services",
        "technology",
        "technologies",
        "pricing",
        "cost",
        "codeqlik",
        "company",
    ]

    if (any(w in t for w in info_words) or has_business_domain_keyword(t)) and not any(x in t for x in ["i need", "i want", "build", "create", "hire", "quote"]):
        if is_question(t) or t.startswith(("explain", "tell", "describe", "define")):
            return True

    return False


def is_field_like_answer(text: str, expected_field: Optional[str]) -> bool:
    """
    Blocks normal questions/explanations from being saved into profile.
    Allows real field values, labeled values, emails/phones, and explicit refusals.
    """
    t = normalize(text)

    if not expected_field:
        return False

    if is_small_talk(t) or is_ack(t) or is_gibberish(t):
        return False

    if is_hard_unrelated_or_unsafe(t):
        return False

    if expected_field in {"name", "company", "work_details"} and is_booking_control_phrase(t):
        return False

    # Critical compatibility guard:
    # If the bot is waiting for identity fields (name/company) but the user
    # continues describing the project (e.g. "can you design an Android app",
    # "just like CricHeroes"), that message must NOT be treated as the
    # pending identity value. It can still be saved by project/requirements
    # extraction, but not as name/company.
    if expected_field in {"name", "company"} and (
        looks_like_reference_product(t) or has_project_creation_context(t)
    ):
        return False

    if is_explanatory_or_company_question(t):
        return False

    if is_company_or_business_info_query(t) and (
        is_question(t) or t.startswith(("explain", "tell", "describe", "define", "what ", "why ", "how ","have", "when ", "where ", "who ", "which " ))
    ):
        return False

    if looks_like_refusal(t):
        return True

    if expected_field in {"email_or_phone", "email", "phone"}:
        return bool(extract_email(t) or extract_phone(t))

    label_words = [
        "my name", "name", "i am", "i'm",
        "company", "company name", "my company",
        "project type", "requirements", "requirement",
        "budget", "timeline", "issue type", "issue details",
        "urgency", "role", "position", "experience",
        "skills", "resume", "portfolio", "work details",
        "meeting mode", "mode", "meeting date", "date",
        "time slot", "slot", "time",
    ]
    if any(t.startswith(lbl) for lbl in label_words):
        return True

    if is_question(t):
        return False

    return True


def is_gibberish(text: str) -> bool:
    t = normalize(text)
    if not t:
        return True

    # IMPORTANT:
    # Pure numbers can be valid phone, budget, or timeline data.
    # Do not treat them as gibberish.
    if re.fullmatch(r"\d+", t):
        return False

    # Common contact/budget/timeline symbols should not make the value gibberish.
    if extract_email(t) or extract_phone(t):
        return False

    if re.fullmatch(r"[\W_]+", t):
        return True

    if "asdf" in t or "qwerty" in t:
        return True

    # Only alphabetic nonsense without vowels is gibberish.
    if re.fullmatch(r"[a-z]+", t) and len(t) > 7 and not re.search(r"[aeiou]", t):
        return True

    return False


def has_email(text: str) -> bool:
    return bool(re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text or ""))


def extract_email(text: str) -> Optional[str]:
    m = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", text or "")
    return m.group(0) if m else None


def extract_phone(text: str) -> Optional[str]:
    digits = re.sub(r"\D", "", text or "")
    if 7 <= len(digits) <= 15:
        return digits
    return None


def extract_meeting_mode(text: str) -> Optional[str]:
    low = normalize(text)
    if not low:
        return None

    google_meet_patterns = [
        r"\bgoogle\s*meet\b",
        r"\bgmeet\b",
        r"\bgoogle-meet\b",
        r"\bmeet\s+link\b",
        r"\bvideo\s+(?:call|meeting)\b",
        r"\bonline\s+(?:call|meeting)\b",
    ]
    if any(re.search(pattern, low) for pattern in google_meet_patterns):
        return "google_meet"

    phone_call_patterns = [
        r"\bphone\s*call\b",
        r"\bdirect\s*call\b",
        r"\bvoice\s*call\b",
        r"\bcall\s+me\b",
        r"\btelephone\b",
        r"\bmobile\s*call\b",
    ]
    if any(re.search(pattern, low) for pattern in phone_call_patterns):
        return "phone_call"

    if low.strip() in {"call", "phone", "phone call"}:
        return "phone_call"

    return None


def extract_meeting_date(text: str) -> Optional[str]:
    raw = str(text or "").strip()
    low = normalize(raw)
    if not low:
        return None

    relative_patterns = [
        r"\bday\s+after\s+tomorrow\b",
        r"\btoday\b",
        r"\btomorrow\b",
        r"\bnext\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month)\b",
        r"\bthis\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month)\b",
        r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    ]
    for pattern in relative_patterns:
        match = re.search(pattern, low)
        if match:
            return match.group(0)

    date_patterns = [
        r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b",
        r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b",
        r"\b\d{1,2}\s+(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)(?:\s+\d{2,4})?\b",
        r"\b(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\s+\d{1,2}(?:,?\s+\d{2,4})?\b",
    ]
    for pattern in date_patterns:
        match = re.search(pattern, low)
        if match:
            return raw[match.start():match.end()]

    return None


def extract_time_slot(text: str) -> Optional[str]:
    low = normalize(text)
    if not low:
        return None

    slot_map = {
        "1": "10:00 AM",
        "2": "02:00 PM",
        "3": "04:00 PM",
        "first": "10:00 AM",
        "second": "02:00 PM",
        "third": "04:00 PM",
    }

    option_match = re.search(r"\b(?:slot|option|no\.?|number)?\s*(1|2|3)\b", low)
    if option_match and len(re.sub(r"\D", "", low)) <= 1:
        return slot_map[option_match.group(1)]

    for word, slot in slot_map.items():
        if re.fullmatch(rf"(?:slot|option)?\s*{re.escape(word)}", low):
            return slot

    if re.search(r"\b10(?::?00)?\s*(?:am|a\.m\.)?\b", low):
        return "10:00 AM"
    if re.search(r"\b(?:2|02)(?::?00)?\s*(?:pm|p\.m\.)\b", low) or re.search(r"\b14:?00\b", low):
        return "02:00 PM"
    if re.search(r"\b(?:4|04)(?::?00)?\s*(?:pm|p\.m\.)\b", low) or re.search(r"\b16:?00\b", low):
        return "04:00 PM"

    if "morning" in low:
        return "10:00 AM"
    if "afternoon" in low:
        return "02:00 PM"
    if "evening" in low:
        return "04:00 PM"
    if any(phrase in low for phrase in ["any slot", "any time", "no preference", "whatever works"]):
        return None

    return None


def is_booking_control_phrase(text: str) -> bool:
    """
    Detect short messages that start/confirm the booking flow, not field values.
    Example: "book a meeting" should not be saved as the user's name.
    """
    low = normalize(text)
    if not low:
        return False

    exact_phrases = {
        "book",
        "booking",
        "meeting",
        "call",
        "appointment",
        "book meeting",
        "book a meeting",
        "book appointment",
        "book an appointment",
        "book a call",
        "schedule meeting",
        "schedule a meeting",
        "schedule call",
        "schedule a call",
        "schedule appointment",
        "schedule an appointment",
        "set up meeting",
        "set up a meeting",
        "meeting book",
        "call book",
        "appointment book",
        "i want to book a meeting",
        "i want book a meeting",
        "want to book a meeting",
        "want book a meeting",
        "i need to book a meeting",
        "need to book a meeting",
        "mujhe meeting book karni hai",
        "meeting book karni hai",
        "meeting book karo",
        "call schedule karo",
    }
    if low in exact_phrases:
        return True

    booking_words = [
        "book a meeting",
        "book meeting",
        "schedule a meeting",
        "schedule meeting",
        "book a call",
        "schedule a call",
        "book appointment",
        "schedule appointment",
        "meeting book",
        "call schedule",
    ]
    has_booking_intent = any(phrase in low for phrase in booking_words)
    if not has_booking_intent:
        return False

    has_real_topic = bool(detect_requested_service_topic(low) or has_project_creation_context(low))
    return not has_real_topic and len(low.split()) <= 12


def looks_like_refusal(text: str) -> bool:
    t = normalize(text)
    phrases = [
        "i don't want",
        "i dont want",
        "i do not want",
        "do not want to share",
        "don't want to share",
        "dont want to share",
        "not comfortable",
        "private",
        "skip",
        "skip this",
        "no thanks",
        "don't ask",
        "dont ask",
        "i won't",
        "i will not",
        "rather not",
        "not interested in sharing",
        "can't share",
        "cannot share",
        "share nahi karna",
        "share nhi karna",
        "nahi batana",
        "nhi batana",
        "mat pucho",
        "skip karo",
        "skip kar do",
    ]
    return any(p in t for p in phrases)


def is_valid_field_value(value, field_name=None):
    if value is None:
        return False

    text = str(value).strip()
    low = text.lower()

    if low in INVALID_VALUES:
        return False

    if low in DECLINED_VALUES:
        return False

    if field_name:
        field = field_name.lower()

        if field == "email_or_phone":
            return bool(extract_email(text) or extract_phone(text))

        if field == "email":
            return bool(extract_email(text))

        if field == "phone":
            return bool(extract_phone(text))

    return True


def is_answered(value, field_name=None):
    if value is None:
        return False
    if normalize(value) in DECLINED_VALUES:
        return True
    return is_valid_field_value(value, field_name)


def check_missing_fields(profile: dict, required_fields: list[str]) -> list[str]:
    profile = profile or {}
    missing = []
    for field in required_fields:
        if not is_answered(profile.get(field), field):
            missing.append(field)
    return missing


def sync_collection_state(category: Optional[str], profile: dict) -> dict:
    if not category:
        return {
            "required_fields": [],
            "missing_fields": [],
            "qualified": False,
            "pending_field": None,
            "last_pending_field": None,
            "active_collection": None,
        }

    required = REQUIRED_FIELDS.get(category, [])
    missing = check_missing_fields(profile or {}, required)
    pending = missing[0] if missing else None

    return {
        "required_fields": required,
        "missing_fields": missing,
        "qualified": len(missing) == 0,
        "pending_field": pending,
        "last_pending_field": pending,
        "active_collection": category if missing else None,
    }


def merge_profile(old: dict, new: dict, category: Optional[str] = None) -> dict:
    merged = dict(old or {})
    allowed = set(REQUIRED_FIELDS.get(category or "", []))

    # Preserve contact aliases in state for display/debug, but only required fields drive flow.
    aliases = {"email", "phone"}
    allowed_with_aliases = allowed | aliases

    for key, value in (new or {}).items():
        if category and key not in allowed_with_aliases:
            continue
        if value in [None, "", [], {}]:
            continue

        old_value = merged.get(key)

        # Append issue details instead of replacing useful earlier information.
        # Example: "my website is not opening" + "it shows server error"
        # becomes: "my website is not opening; it shows server error".
        if key == "issue_details" and is_answered(old_value, key) and normalize(value) not in DECLINED_VALUES:
            old_text = str(old_value).strip()
            new_text = str(value).strip()
            if new_text and normalize(new_text) not in normalize(old_text):
                merged[key] = f"{old_text}; {new_text}"
            continue

        # Contact fields can be updated if the user provides a new explicit email/phone.
        if key in {"email_or_phone", "email", "phone"}:
            merged[key] = value
            continue

        # Protect already-collected identity fields from accidental overwrite.
        # Example fixed:
        # name="Amit" should NOT become "SalesPro" when user later says
        # "company name is SalesPro".
        #
        # Contact fields are handled above and can still be updated explicitly.
        # project_type is intentionally NOT locked here because project details can
        # be refined later and are controlled by pending-field extraction rules.
        if key in {"name", "company", "role"}:
            if is_answered(old_value, key) and normalize(value) not in DECLINED_VALUES:
                # Keep the existing verified value unless the new value is identical.
                # This avoids cross-field overwrite caused by regex/LLM false positives.
                if normalize(old_value) != normalize(value):
                    continue
                continue

            merged[key] = value
            continue

        # project_type can still be set/refined by the active pending-field logic.
        if key == "project_type":
            merged[key] = value
            continue

        # For other fields, keep old value unless old is missing/invalid.
        if is_answered(old_value, key) and normalize(value) not in DECLINED_VALUES:
            if normalize(old_value) == normalize(value):
                continue
            # requirements can grow over time, but avoid duplicate text.
            if key == "requirements":
                old_text = str(old_value).strip()
                new_text = str(value).strip()
                if new_text and normalize(new_text) not in normalize(old_text):
                    merged[key] = f"{old_text}; {new_text}"
            continue

        merged[key] = value

    return merged




def has_business_domain_keyword(text: str) -> bool:
    """Broad, non-lead business vocabulary for company/service info questions."""
    t = normalize(text)
    return any(k in t for k in BUSINESS_DOMAIN_KEYWORDS)


def rag_suggests_company_relevance(text: str, threshold: float = 0.40) -> bool:
    """Use RAG only as a fallback for ambiguous questions to avoid false refusals."""
    if not text or is_small_talk(text) or is_hard_unrelated_or_unsafe(text):
        return False
    try:
        details = retrieve_company_context_details(text)
        confidence = float(details.get("confidence", 0.0) or 0.0)
        return confidence >= threshold
    except Exception as e:
        print("[Relevance RAG] skipped:", e)
        return False


def llm_suggests_company_relevance(text: str) -> bool:
    """Last-resort ambiguity check; never overrides hard unsafe/unrelated topics."""
    if not text or is_small_talk(text) or is_hard_unrelated_or_unsafe(text):
        return False

    prompt = f"""Classify whether this user message is related to CodeQlik's business scope.

CodeQlik scope includes: software development, websites, web apps, mobile apps, e-commerce, CRM, ERP, dashboards, SaaS, AI automation, chatbots, support issues, hiring, pricing, contact, and company information.

Unrelated examples: travel, weather, sports, movies, food recipes, politics, religion, hacking, adult content.

User message: {text}

Return JSON only:
{{"company_related": true, "reason": ""}}
"""
    try:
        node_name_var.set("relevance_check")
        json_llm = llm.bind(response_format={"type": "json_object"})
        result = json_llm.invoke([HumanMessage(content=prompt)]).content
        parsed = safe_json_loads(result, {"company_related": False})
        return bool(parsed.get("company_related", False))
    except Exception as e:
        print("[Relevance LLM] skipped:", e)
        return False

# ---------------------------------------------------------------------
# Relevance / safety
# ---------------------------------------------------------------------

def is_company_related(text: str) -> bool:
    t = normalize(text)
    keywords = [
        "codeqlik",
        "company",
        "service",
        "services",
        "pricing",
        "price",
        "cost",
        "contact",
        "phone",
        "email",
        "address",
        "office",
        "portfolio",
        "technology",
        "technologies",
        "project",
        "website",
        "web",
        "app",
        "mobile app",
        "software",
        "crm",
        "saas",
        "automation",
        "ai",
        "chatbot",
        "support",
        "bug",
        "issue",
        "complaint",
        "not opening",
        "crashing",
        "error",
        "intern",
        "internship",
        "job",
        "career",
        "hiring",
        "resume",
        "developer",
        "developers",
        "hire",
        "quote",
        "proposal",
        "budget",
        "timeline",
        "requirements",
        "opening",
        "openings",
        "role",
        "roles",
        "available role",
        "available roles",
        "vacancy",
        "vacancies",
        "who are you",
        "what can you do",
        "what do you do",
        # Business/project discussion terms that are valid during client lead flow
        "business management",
        "management system",
        "erp",
        "inventory",
        "billing",
        "invoice",
        "dashboard",
        "admin panel",
        "employee management",
        "attendance",
        "sales",
        "purchase",
        "reporting",
        "analytics",
        "customer portal",
        "vendor portal",
        "accounting",
        "business management system",
        "management software",
        "custom software",
        "business software",
    ]
    return any((re.search(r"\bai\b", t) is not None) if k == "ai" else (k in t) for k in keywords) or has_business_domain_keyword(t)


def is_sensitive_or_unsafe(text: str) -> bool:
    t = normalize(text)
    unsafe = [
        "system prompt",
        "ignore previous instructions",
        "developer message",
        "api key",
        "secret key",
        "mongodb uri",
        "database password",
        "hack",
        "hacking",
        "malware",
        "phishing",
        "payload",
        "sql injection",
        "exploit",
        "adult",
        "porn",
        "religion",
        "politics",
        "prime minister",
        "president",
        "which llm",
        "model provider",
        "internal instruction",
    ]
    return any(k in t for k in unsafe)


def is_hard_unrelated_or_unsafe(text: str) -> bool:
    """
    Strong refusal list used while a lead/support/hiring collection is active.
    During an active collection, broad project questions must NOT be rejected
    just because they are questions. Only clearly unsafe or clearly off-company
    topics should be refused.

    Semantic-compat note:
    Domain words like cricket/travel/hotel are blocked only when they are casual
    questions. If the user is asking to build an app/site/system for that domain,
    it is a valid client lead.
    """
    t = normalize(text)

    unsafe_blocks = [
        "system prompt",
        "ignore previous instructions",
        "developer message",
        "api key",
        "secret key",
        "mongodb uri",
        "database password",
        "hack",
        "hacking",
        "malware",
        "phishing",
        "payload",
        "sql injection",
        "exploit",
        "adult",
        "porn",
        "politics",
        "prime minister",
        "president",
        "which llm",
        "model provider",
        "internal instruction",
    ]
    if any(k in t for k in unsafe_blocks):
        return True

    # "travel booking app", "hotel website", "cricket scoring app" are valid
    # project leads, not unrelated topic questions.
    if has_project_creation_context(t):
        return False

    topic_blocks = [
        "trip",
        "travel",
        "tour",
        "hotel",
        "flight",
        "recipe",
        "cook",
        "pizza",
        "pasta",
        "sports",
        "cricket",
        "movie",
        "song",
        "weather",
        "news",
        "geography",
        "history",
        "capital of",
        "himachal",
        "goa",
        "manali",
        "shimla",
    ]
    return any(k in t for k in topic_blocks)


def is_unrelated_query(text: str) -> bool:
    t = normalize(text)

    if is_small_talk(t):
        return False

    if has_project_creation_context(t) or has_semantic_support_intent(t) or has_semantic_hiring_intent(t):
        return False

    if is_company_or_business_info_query(t) or has_semantic_company_info_intent(t):
        return False

    if is_company_related(t):
        return False

    unrelated = [
        "trip",
        "travel",
        "tour",
        "hotel",
        "flight",
        "recipe",
        "cook",
        "pizza",
        "pasta",
        "sports",
        "cricket",
        "movie",
        "song",
        "weather",
        "news",
        "geography",
        "history",
        "capital of",
        "himachal",
        "goa",
        "manali",
        "shimla",
    ]
    if any(k in t for k in unrelated):
        return True

    if is_question(t) and not is_company_related(t):
        return True

    return False


# ---------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------



def is_plain_value_without_context(text: str) -> bool:
    """
    Standalone values like "Anurag", "Rahul Sharma", "SalesPro" should not start a flow
    when the bot has not asked for that field.
    """
    t = normalize(text)

    if not t or is_question(t) or is_small_talk(t) or is_ack(t):
        return False

    if extract_email(t) or extract_phone(t):
        return True

    business_action_words = [
        "need", "want", "build", "develop", "create", "make", "quote", "proposal",
        "hire", "apply", "intern", "internship", "job", "opening", "vacancy",
        "bug", "issue", "problem", "not working", "not opening", "error", "crash",
        "service", "services", "pricing", "technology", "software", "website", "app",
        "crm", "automation", "chatbot", "support",
        "chahiye", "chaiye", "chahie", "banana", "banwana", "banwani",
        "bana do", "bna do", "karwana", "jaisa", "jaise", "similar", "design"
    ]

    if any(w in t for w in business_action_words):
        return False

    # 1-4 normal words are likely a name/company/short value, not a new intent.
    if 1 <= len(t.split()) <= 4:
        return True

    return False


def has_client_buying_intent(text: str) -> bool:
    """
    Detect dynamic client/project buying intent without making every service word a lead.
    A service term alone (for example, "ERP") is not enough. It needs a buying/help/cost cue.
    This keeps general info questions like "what is ERP" separate from client leads.
    """
    t = normalize(text)
    if not t or is_small_talk(t) or is_sensitive_or_unsafe(t):
        return False

    info_cues = [
        "what is", "what are", "explain", "tell me about", "describe",
        "define", "how does", "how do"
    ]
    if any(t.startswith(cue) for cue in info_cues):
        return False

    buying_cues = [
        "i need", "i want", "we need", "we want", "need", "want",
        "looking for", "we are looking for", "i am looking for",
        "help me with", "can you help me with", "need help with",
        "interested in", "want to discuss", "planning to build",
        "planning for", "require", "required", "requirement for",
        "solution for", "solutions for", "need solution", "need solutions",
        "business solution", "software solution", "build", "develop",
        "create", "make", "implement", "implementation", "integrate",
        "setup", "set up", "customize", "quote", "proposal",
        "cost for", "price for", "pricing for", "quote for",
        "estimate for", "how much", "charges for"
    ]

    service_terms = [
        "website", "web app", "web application", "mobile app", "android", "ios",
        "app", "application", "crm", "erp", "odoo", "odoo erp",
        "dashboard", "admin panel", "management system", "business management",
        "business management system", "ecommerce", "e-commerce", "online store",
        "shopping app", "payment gateway", "automation", "workflow automation",
        "chatbot", "ai chatbot", "ai automation", "software", "custom software",
        "saas", "portal", "inventory", "billing", "invoice", "hrm", "hrms",
        "pos", "booking system"
    ]

    return (
        any(cue in t for cue in buying_cues) and any(term in t for term in service_terms)
    ) or has_semantic_client_buying_intent(t)


def has_hiring_info_intent(text: str) -> bool:
    t = normalize(text)
    return any(k in t for k in [
        "opening", "openings", "available role", "available roles",
        "roles available", "vacancy", "vacancies", "hiring",
        "career", "internship", "job"
    ]) or has_semantic_hiring_intent(t)


def classify_intent_semantic(user_text: str, active_collection: Optional[str]) -> dict:
    """
    LLM semantic classifier.
    It only classifies intent/switch behavior.
    It must NOT extract profile, decide pending field, or decide qualification.
    Deterministic state manager still controls the flow.
    """
    prompt = f"""You are an intent classifier for CodeQlik's company support chatbot.

Classify ONLY the latest user message.

Allowed intents:
- client_lead: user wants to buy/build/hire CodeQlik for website, app, CRM, AI chatbot, automation, software, project, quote, proposal, development work.
- customer_support: user has a bug, issue, complaint, existing product/service problem, app/site not working, login/server/error/crash problem.
- hiring_support: user asks for job, internship, vacancy, opening, career, available roles, or wants to apply.
- meeting_booking: user wants to book, schedule, or reschedule a meeting, appointment, slot, call, or discussion.
- company_info: user asks about CodeQlik, services, pricing, technologies, contact, portfolio, what you do, who you are.
- general_chat: greeting, thanks, bye, casual friendly chat.
- unrelated_query: travel, food, movie, politics, religion, adult, hacking, or anything unrelated to CodeQlik services/support/hiring/company.

Current active_collection: {active_collection}
Latest user message: {user_text}

Important rules:
1. Do NOT extract name, email, phone, company, budget, or any profile data.
2. Do NOT decide next pending field.
3. If current active_collection exists and user is just answering a field, keep same intent.
4. If user clearly switches topic, set is_clear_switch=true.
5. If user asks company/service/hiring info during active_collection, keep same active intent but answer_type should be "company_answer".
6. New wording should be understood semantically, not only by keywords.
7. Unsafe/unrelated requests must be unrelated_query.

Return JSON only:
{{
  "intent": "client_lead|customer_support|hiring_support|meeting_booking|company_info|general_chat|unrelated_query",
  "is_clear_switch": true,
  "answer_type": "field_answer|company_answer|small_talk|refusal",
  "confidence": 0.0,
  "reason": ""
}}"""

    fallback = {
        "intent": None,
        "is_clear_switch": False,
        "answer_type": "company_answer",
        "confidence": 0.0,
        "reason": "fallback"
    }

    try:
        node_name_var.set("intent_detection")
        json_llm = llm.bind(response_format={"type": "json_object"})
        result = json_llm.invoke([HumanMessage(content=prompt)]).content
        parsed = safe_json_loads(result, fallback)

        intent = parsed.get("intent")
        if intent not in VALID_INTENTS:
            parsed["intent"] = None

        parsed["confidence"] = float(parsed.get("confidence", 0.0) or 0.0)
        parsed["is_clear_switch"] = bool(parsed.get("is_clear_switch", False))
        parsed["answer_type"] = parsed.get("answer_type") or "company_answer"
        return parsed

    except Exception:
        return fallback


def classify_intent_rules_fallback(user_text: str, active_collection: Optional[str]) -> str:

    t = normalize(user_text)

    # Small talk must be allowed before unrelated-question detection.
    # Without this, "how are you" becomes unrelated because it is a question.
    if is_small_talk(t):
        if active_collection:
            return active_collection
        return "general_chat"

    # Company/hiring info query should not be refused.
    # If a collection is active, keep it so response_generator can answer first
    # and then ask the pending field.
    if is_company_or_business_info_query(t):
        if active_collection:
            return active_collection
        if has_hiring_info_intent(t):
            return "hiring_support"
        return "company_info"

    if is_sensitive_or_unsafe(t) or is_unrelated_query(t):
        return "unrelated_query"

    # Semantic compatibility checks: Hinglish/typo/new wording mapped to the
    # same old intents, without changing state/pending-field behavior.
    if has_semantic_support_intent(t):
        return "customer_support"
    if has_semantic_hiring_intent(t):
        return "hiring_support"
    if has_semantic_client_buying_intent(t):
        return "client_lead"

    # Support/client clear switches must happen before active-flow field-answer locking.
    # Example: "actually my existing app has a bug" should switch from client_lead to customer_support.
    support_keywords = [
        "bug",
        "issue",
        "problem",
        "complaint",
        "not working",
        "not opening",
        "crashing",
        "crash",
        "error",
        "broken",
        "downtime",
        "server error",
        "login issue",
        "website is not opening",
        "app is not opening",
        "existing app has a bug",
        "existing website has a bug",
    ]
    if any(k in t for k in support_keywords):
        return "customer_support"

    hiring_keywords = [
        "intern",
        "internship",
        "fresher",
        "job seeker",
        "apply",
        "resume",
        "cv",
        "portfolio",
        "career",
        "vacancy",
        "candidate",
        "job opening",
        "internship opening",
        "openings for internship",
        "current opening",
        "current openings",
        "available role",
        "available roles",
        "roles available",
        "job roles",
        "job role",
    ]
    if any(k in t for k in hiring_keywords):
        return "hiring_support"

    client_keywords = [
        "i need",
        "i want",
        "build",
        "develop",
        "create",
        "make",
        "quote",
        "proposal",
        "hire your company",
        "hire developer",
        "need website",
        "need app",
        "need crm",
        "need chatbot",
        "want website",
        "want app",
        "want crm",
        "want chatbot",
        "software for",
        "automation software",
        "crm software",
    ]
    if any(k in t for k in client_keywords) or has_client_buying_intent(t):
        return "client_lead"

    # If hiring collection is active, normal non-question answers like
    # "python developer" must stay inside hiring flow as role/experience/skills,
    # but only after clear client/support switches have been checked.
    if active_collection == "hiring_support" and not is_question(t):
        return "hiring_support"

    company_info_keywords = [
        "what services",
        "services do you",
        "technology",
        "technologies",
        "pricing",
        "cost",
        "contact",
        "phone",
        "email",
        "address",
        "office",
        "portfolio",
        "team",
        "developers",
        "support email",
        "who are you",
        "about company",
    ]
    if any(k in t for k in company_info_keywords):
        return "general_chat"

    # Only now keep active flow for short/non-question field answers.
    # This prevents topic-switch messages from being trapped in the old flow.
    if active_collection and not is_question(t):
        return active_collection

    if t in {"hi", "hello", "hey", "thanks", "thank you", "bye", "good morning", "good evening"}:
        return "general_chat"

    if active_collection:
        return active_collection

    return "general_chat"

def classify_intent_rules(user_text: str, active_collection: Optional[str]) -> str:
    """
    Safer hybrid intent classification:
    - Deterministic state/flow protection first.
    - Semantic compatibility only maps new wording into the same old intents.
    - LLM fallback is conservative and only used when rules would otherwise fail.
    - LLM never controls profile/pending/qualification.
    """
    t = normalize(user_text)

    if is_small_talk(t):
        if active_collection:
            return active_collection
        return "general_chat"

    if is_sensitive_or_unsafe(t):
        return "unrelated_query"

    clear_support_phrases = [
        "bug", "issue", "problem", "complaint", "not working", "not opening",
        "crashing", "crash", "error", "broken", "downtime", "server error",
        "login issue", "existing app", "existing website", "after login",
        "keeps failing", "failing after login", "portal failing"
    ]
    if any(k in t for k in clear_support_phrases) or has_semantic_support_intent(t):
        return "customer_support"

    clear_booking_phrases = [
        "meeting", "appointment", "booking", "schedule", "reschedule", "slot", "slots",
        "book a call", "schedule a call", "book meeting", "book appointment", "appointment book"
    ]
    if any(k in t for k in clear_booking_phrases):
        return "meeting_booking"

    clear_hiring_phrases = [
        "i want internship", "want internship", "need internship",
        "apply", "apply for", "want to apply", "i want to apply",
        "job", "internship", "fresher", "resume", "cv",
        "career", "hiring", "vacancy", "opening", "openings",
        "available role", "available roles", "roles available",
        "python developer job", "ai intern", "ml intern"
    ]
    if any(k in t for k in clear_hiring_phrases) or has_semantic_hiring_intent(t):
        return "hiring_support"

    # Active flow protection before broad client phrases.
    # This keeps hiring answers like "Python developer" or support answers from
    # being misread as a new client project because they contain words like
    # "developer"/"develop". Clear support/hiring switches were already handled.
    if active_collection:
        if is_hard_unrelated_or_unsafe(t):
            return "unrelated_query"
        if active_collection != "client_lead" and active_collection != "meeting_booking" and has_semantic_client_buying_intent(t):
            return "client_lead"
        return active_collection

    clear_client_phrases = [
        "i need", "i want", "build", "develop", "create", "make", "design",
        "quote", "proposal", "need website", "need app", "need crm",
        "need chatbot", "want website", "want app", "want crm",
        "want chatbot", "website for my business", "for my business",
        "can you make", "can u make", "can you build", "can u build",
        "can you design", "can u design", "ecommerce", "e-commerce",
        "software for my business"
    ]
    if any(k in t for k in clear_client_phrases) or has_client_buying_intent(t) or has_semantic_client_buying_intent(t):
        return "client_lead"

    # Broad service/domain informational questions should be answered, not refused.
    if is_company_or_business_info_query(t) or has_semantic_company_info_intent(t) or (is_question(t) and has_business_domain_keyword(t)):
        return "company_info"

    # Ambiguous questions get RAG first, then LLM fallback before refusing.
    if is_unrelated_query(t):
        if is_question(t) and (rag_suggests_company_relevance(t) or llm_suggests_company_relevance(t)):
            return "general_chat"
        # Before refusing, use the existing semantic classifier as a conservative
        # fallback for business-like Hinglish/new wording that keyword rules missed.
        if should_try_semantic_intent_fallback(user_text, "unrelated_query", active_collection):
            semantic = classify_intent_semantic(user_text, active_collection)
            override = safe_semantic_intent_override(user_text, "unrelated_query", semantic)
            if override:
                return override
        return "unrelated_query"

    if is_plain_value_without_context(t):
        return "general_chat"

    if is_company_or_business_info_query(t) or has_semantic_company_info_intent(t):
        if has_hiring_info_intent(t):
            return "hiring_support"
        return "company_info"

    fallback_intent = classify_intent_rules_fallback(user_text, active_collection)
    if should_try_semantic_intent_fallback(user_text, fallback_intent, active_collection):
        semantic = classify_intent_semantic(user_text, active_collection)
        override = safe_semantic_intent_override(user_text, fallback_intent, semantic)
        if override:
            return override

    return fallback_intent

def is_clear_flow_switch(user_text: str, current_active: Optional[str], new_intent: str) -> bool:
    if not current_active:
        return True

    if new_intent == current_active:
        return True

    if new_intent == "unrelated_query":
        return True

    if current_active == "meeting_booking" and new_intent == "client_lead":
        return False

    t = normalize(user_text)

    if new_intent == "customer_support":
        return has_semantic_support_intent(t) or any(k in t for k in ["actually", "existing", "bug", "issue", "problem", "not working", "not opening", "crashing", "error", "downtime", "server error", "login issue", "after login", "keeps failing", "failing"])

    if new_intent == "hiring_support":
        return has_semantic_hiring_intent(t) or any(k in t for k in ["actually", "apply", "internship", "job", "resume", "career", "hiring"])

    if new_intent == "client_lead":
        return has_semantic_client_buying_intent(t) or any(k in t for k in [
            "actually", "i need", "i want", "we need", "we want",
            "build", "develop", "create", "quote", "hire your company",
            "for my business", "need website", "need app", "need crm",
            "can you make", "can you build", "help me with", "looking for",
            "interested in", "require", "solution for", "erp", "odoo",
            "crm", "management system", "cost for", "price for", "estimate for"
        ]) or has_client_buying_intent(t)

    return False


@traceable
def is_unsupported_meeting_topic(text: str) -> bool:
    low = normalize(text)
    unrelated_words = [
        "trip", "travel", "vacation", "holiday", "tour", "recipe", "cooking", "food",
        "movie", "film", "politics", "election", "religion", "god", "medical", "doctor",
        "health", "legal", "lawyer", "court", "finance", "investment", "stock"
    ]
    company_keywords = ["website", "app", "software", "development", "crm", "saas", "automation", "codeqlik", "project", "it solutions"]
    if any(w in low for w in unrelated_words) and not any(k in low for k in company_keywords):
        return True
    return False


def build_meeting_prefill_from_profile(profile: dict) -> dict:
    profile = profile or {}
    contact_value = profile.get("email_or_phone") or ""
    email = profile.get("email") or extract_email(contact_value)
    phone = profile.get("phone") or extract_phone(contact_value)
    work_details = (
        profile.get("work_details")
        or profile.get("requirements")
        or profile.get("project_type")
        or profile.get("issue_details")
        or profile.get("issue_type")
    )

    prefilled = {
        "name": profile.get("name"),
        "email": email,
        "phone": phone,
        "company": profile.get("company"),
        "work_details": work_details,
        "meeting_mode": profile.get("meeting_mode"),
        "date": profile.get("date"),
        "time_slot": profile.get("time_slot"),
        "status": profile.get("status") or "confirmed",
    }
    return {k: v for k, v in prefilled.items() if v}


def intent_classifier_node(state: ChatState) -> dict:
    user_text = latest_user_message(state["messages"])
    current_active = state.get("active_collection")
    original_active = current_active
    current_profile = state.get("profile", {}) or {}
    summary = state.get("conversation_summary", "")

    # Auto transition from qualified client lead to meeting booking on positive user response
    is_positive_response = any(w in normalize(user_text) for w in ["yes", "haan", "sure", "ok", "karo", "kardo", "yeah", "yep", "booking", "book"])
    completed_lead_waiting_for_booking = (
        not current_active
        and state.get("qualified", False)
        and state.get("user_goal") == "client_lead"
        and has_saved_business_context(current_profile)
    )
    if completed_lead_waiting_for_booking and is_positive_response:
        primary_intent = "meeting_booking"
        current_active = "meeting_booking"
        current_profile = build_meeting_prefill_from_profile(current_profile)
    else:
        primary_intent = classify_intent_rules(user_text, current_active)

    if primary_intent == "meeting_booking" and current_active != "meeting_booking":
        current_profile = build_meeting_prefill_from_profile(current_profile)

    # Profile-based context fallback:
    # After a collection is complete, active_collection becomes None.
    # Short follow-up questions like "how will you create it" or
    # "what you use in it" may look unrelated if we only inspect latest text.
    # If the saved profile has project/support/hiring context, keep the previous
    # business intent instead of refusing.
    if (
        primary_intent == "unrelated_query"
        and state.get("qualified", False)
        and has_saved_business_context(current_profile)
        and is_context_followup(user_text)
    ):
        previous_business_intent = state.get("user_goal")
        if previous_business_intent in COLLECTION_INTENTS:
            primary_intent = previous_business_intent
        elif current_profile.get("issue_type") or current_profile.get("issue_details"):
            primary_intent = "customer_support"
        elif current_profile.get("role") or current_profile.get("skills"):
            primary_intent = "hiring_support"
        else:
            primary_intent = "client_lead"

    # Active flow lock.
    if current_active and primary_intent in COLLECTION_INTENTS and not is_clear_flow_switch(user_text, current_active, primary_intent):
        primary_intent = current_active

    if primary_intent == "company_info":
        primary_intent = "client_lead"

    if primary_intent not in VALID_INTENTS:
        primary_intent = "general_chat"

    if primary_intent in COLLECTION_INTENTS:
        active_collection = primary_intent
    elif primary_intent == "unrelated_query":
        active_collection = current_active
    else:
        active_collection = current_active

    synced = sync_collection_state(active_collection, current_profile) if active_collection else sync_collection_state(None, current_profile)

    user_goal = state.get("user_goal") or primary_intent
    if primary_intent in COLLECTION_INTENTS and primary_intent != original_active:
        user_goal = primary_intent

    return {
        "intent": primary_intent,
        "primary_intent": primary_intent,
        "active_collection": synced["active_collection"],
        "user_goal": user_goal,
        "profile": current_profile,
        "required_fields": synced["required_fields"],
        "missing_fields": synced["missing_fields"],
        "qualified": synced["qualified"],
        "pending_field": synced["pending_field"],
        "last_pending_field": synced["last_pending_field"],
        "current_question": user_text,
        "conversation_summary": summary,
        "confidence": 0.95,
        "response_mode": "decline_unrelated" if primary_intent == "unrelated_query" else None,
        "is_field_answer": False,
    }


def route_by_intent(state: ChatState) -> str:
    return state.get("primary_intent") or state.get("intent") or "general_chat"


# ---------------------------------------------------------------------
# Deterministic extraction
# ---------------------------------------------------------------------

def has_extra_question_after_field(text: str) -> bool:
    t = normalize(text)
    return (
        "?" in t
        or " can you " in f" {t} "
        or " can i " in f" {t} "
        or " explain " in f" {t} "
        or " know about " in f" {t} "
        or "how " in t
        or "what " in t
        or "why " in t
        or "when " in t
        or "where " in t
        or "which " in t
        or "who " in t
        or "have" in t
        or "tell" in t
        or is_hinglish_question(t)
    )


def is_context_followup(text: str) -> bool:
    """
    Detect short follow-up questions that refer to already saved profile context.
    Example after a completed lead/support flow:
    - what you use in it
    - how will you create it
    - how will you fix it
    - can you explain this
    These should use saved profile context instead of being treated as unrelated.
    """
    t = normalize(text)
    if not t:
        return False

    followup_phrases = [
        "it", "this", "that", "these", "those", "them",
        "what you use", "what do you use", "what will you use",
        "what technologies", "what technology", "what stack",
        "how will you", "how would you", "how do you", "how can you",
        "how will it", "how does it", "how it",
        "can you explain", "explain it", "explain this",
        "features", "modules", "process", "steps", "workflow",
        "create it", "build it", "develop it", "fix it", "solve it",
        "in it", "for it", "about it",
        "kaise banega", "kaise banaoge", "kaise karoge", "isme kya",
        "features kya", "kitna time", "kitna cost", "price kitna",
        "usme", "isme", "ye", "wo", "kya use", "technology kya",
    ]
    return any(p in t for p in followup_phrases)


def has_saved_business_context(profile: dict) -> bool:
    profile = profile or {}
    return bool(
        profile.get("project_type")
        or profile.get("requirements")
        or profile.get("issue_type")
        or profile.get("issue_details")
        or profile.get("role")
        or profile.get("skills")
        or profile.get("work_details")
    )

def remove_label_prefix(text: str, labels: list[str]) -> Optional[str]:
    raw = str(text or "").strip()

    for label in labels:
        pattern = rf"(?i)\b{re.escape(label)}\s*(?:is|:|-)?\s+(.+?)(?=\s+\b(?:and|but|also|then)\b|\?|,|\.|$)"
        match = re.search(pattern, raw)
        if match:
            value = match.group(1).strip()
            if value:
                return value

    return None


def extract_inline_labeled_values(text: str, labels: list[str]) -> list[str]:
    """
    Extract labeled values even when multiple fields are in one sentence:
    "my name is Karan and company is RetailX"
    "company is SalesPro and project type is CRM"
    """
    raw = str(text or "").strip()
    values = []

    for label in labels:
        pattern = rf"(?i)\b{re.escape(label)}\s*(?:is|:|-)?\s+(.+?)(?=\s+and\s+\w+(?:\s+\w+)?\s*(?:is|:|-)|[,.;]|$)"
        for match in re.finditer(pattern, raw):
            value = match.group(1).strip()
            if value:
                values.append(value)

    return values



def validate_extracted_field(key: str, value, category: str) -> Optional[str]:
    """
    Strict validation layer for LLM/regex extracted fields.
    Rejects accidental long sentences, generic words, and question-like values.
    """
    if value is None:
        return None

    text = str(value).strip().strip('"').strip("'")
    if not text:
        return None

    low = normalize(text)

    if key in {"name", "company"}:
        # Clean common Roman-Hindi label leftovers produced by generic label regex.
        text = re.sub(r"(?i)\s+(hai|h|hu|hoon|hun)$", "", text).strip()
        if key == "company":
            text = re.sub(r"(?i)^(ka\s+naam|name)\s+", "", text).strip()
        low = normalize(text)

    if low in INVALID_VALUES:
        return None

    if low in DECLINED_VALUES:
        return "declined"

    if key not in {"requirements", "issue_details"}:
        if is_question(text) or low.startswith(("explain ", "tell me", "describe ", "what ", "why ", "how ")):
            return None

    if key == "email_or_phone":
        email = extract_email(text)
        phone = extract_phone(text)
        return email or phone

    if key == "email":
        return extract_email(text)

    if key == "phone":
        return extract_phone(text)

    if key == "name":
        if is_booking_control_phrase(text):
            return None
        forbidden = [
            "product manager", "manager at", "company", "solutions", "project",
            "requirement", "requirements", "mobile app", "application", "platform",
            "development", "dashboard", "invoice", "export", "support", "details",
            "we're", "we are", "looking", "build", "create", "proposal", "email",
            "phone", "budget", "timeline",
            "e-commerce", "ecommerce", "website", "web site", "app",
            "application", "crm", "chatbot", "platform", "portal",
            "software", "store", "shop", "business", "landing page",
            "informational site", "online store", "like", "similar", "jaisa",
            "jaise", "jesa", "jese", "type", "clone", "chahiye", "chaiye",
            "banwana", "banwani", "banana", "bana do",
            "book", "booking", "meeting", "call", "schedule", "appointment"
        ]
        words = text.split()
        if len(words) > 4:
            return None
        if any(f in low for f in forbidden):
            return None
        if not re.search(r"[A-Za-z]", text):
            return None
        return text

    if key == "company":
        if is_booking_control_phrase(text):
            return None
        forbidden_exact = {"details", "project", "requirements", "mobile app", "app", "website", "crm", "yes", "no", "ok"}
        if low in forbidden_exact:
            return None
        if looks_like_reference_product(text) or has_project_creation_context(text):
            return None
        if len(text.split()) > 6:
            return None
        if is_question(text):
            return None
        return text

    if key == "project_type":
        if low in {"details", "yes", "no", "ok", "name", "company"}:
            return None
        project_keywords = [
            "mobile app", "android", "ios", "cross-platform", "cross platform",
            "website", "web app", "e-commerce", "ecommerce", "crm", "dashboard",
            "management system", "software", "chatbot", "automation", "portal",
            "erp", "saas", "application", "app"
        ]
        if any(w in low for w in project_keywords):
            return text
        if len(text.split()) <= 12:
            return text
        return None

    if key == "budget":
        if looks_like_refusal(text):
            return "declined"
        if re.search(r"(\d|rs|inr|usd|dollar|₹|\$|lakh|lakhs|k\b|budget|around|approx)", low):
            return text
        return None

    if key == "timeline":
        if re.search(r"(\d+\s*(day|days|week|weeks|month|months|year|years)|next\s+\w+|this\s+\w+|quarter|asap)", low):
            return text
        return None

    if key == "urgency":
        if any(k in low for k in ["urgent", "high", "medium", "low", "critical"]):
            return text
        return None

    if key == "experience":
        if re.search(r"(fresher|\d+\s*(month|months|year|years))", low):
            return text
        return None

    if key == "resume_or_portfolio":
        if re.search(r"(https?://\S+|[\w.-]+\.(com|dev|io|in|net)/?\S*)", text):
            return text
        if looks_like_refusal(text):
            return "declined"
        return None

    if key == "work_details":
        if is_booking_control_phrase(text):
            return None
        if low in {"details", "yes", "no", "ok", "meeting", "call", "booking"}:
            return None
        if extract_meeting_mode(text) or extract_time_slot(text):
            return None
        date_value = extract_meeting_date(text)
        if date_value and len(text.split()) <= 5:
            return None
        return text

    if key in {"requirements", "issue_type", "issue_details", "role", "skills"}:
        if low in {"details", "yes", "no", "ok"} and key != "issue_type":
            return None
        return text

    if key == "meeting_mode":
        return extract_meeting_mode(text)

    if key == "date":
        return extract_meeting_date(text)

    if key == "time_slot":
        return extract_time_slot(text)

    return text


def validate_extracted_profile(raw: dict, category: str) -> dict:
    allowed = set(REQUIRED_FIELDS.get(category, [])) | {"email", "phone", "email_or_phone"}
    clean = {}

    for key, value in (raw or {}).items():
        if key not in allowed:
            continue

        validated = validate_extracted_field(key, value, category)
        if validated is None:
            continue

        clean[key] = validated

        if key == "email_or_phone":
            if extract_email(validated):
                clean["email"] = validated
            elif extract_phone(validated):
                clean["phone"] = validated

    # Ensure email_or_phone is populated for compatibility
    if "email" in clean and clean["email"]:
        clean["email_or_phone"] = clean.get("email_or_phone") or clean["email"]
    elif "phone" in clean and clean["phone"]:
        clean["email_or_phone"] = clean.get("email_or_phone") or clean["phone"]

    return clean


def llm_verify_uncertain_field(field: Optional[str], user_text: str, category: str) -> Optional[str]:
    """
    Last-resort verifier for uncertain field answers.

    Important:
    - Deterministic extraction must run first.
    - This verifier is only for fields where natural wording is ambiguous.
    - It does NOT run for email/phone/budget/timeline/urgency because rules are safer there.
    - It returns one validated value or None; it never updates profile directly.
    """
    if not field:
        return None

    verifier_fields = {
        "name",
        "company",
        "role",
        "project_type",
        "issue_type",
        "skills",
        "requirements",
        "issue_details",
        "resume_or_portfolio",
        "work_details",
        "meeting_mode",
        "date",
        "time_slot",
    }

    if field not in verifier_fields:
        return None

    if is_small_talk(user_text) or is_ack(user_text) or is_gibberish(user_text):
        return None

    if is_hard_unrelated_or_unsafe(user_text):
        return None

    prompt = f"""You are a strict verifier for CodeQlik chatbot field collection.

The chatbot is currently expecting exactly this field:
{field}

Category:
{category}

Latest user message:
{user_text}

Decide whether the latest user message clearly provides a value for the expected field.

Rules:
- Return valid=true only if the message clearly provides the expected field.
- Do NOT guess.
- Do NOT infer from old context.
- Do NOT use examples as facts.
- If unsure, valid=false.
- For name:
  - valid=true for: "my name is Anurag", "I am Anurag", "myself Kunal Singh", "this is Rahul", "Anurag here", "Anurag, why is it not working?"
  - valid=false for: "fix it fast", "payment is not working", "why is it not working", "app issue"
- For company:
  - valid=true only if a company/business/organization is clearly provided.
- For project_type, issue_type, role, skills, requirements:
  - valid=true only if the message clearly provides that field.

Return JSON only:
{{
  "valid": true/false,
  "value": "extracted value or null"
}}
"""

    try:
        node_name_var.set("field_extraction")
        json_llm = llm.bind(response_format={"type": "json_object"})
        result = json_llm.invoke([HumanMessage(content=prompt)]).content
        parsed = safe_json_loads(result, {"valid": False, "value": None})

        if not parsed.get("valid"):
            return None

        value = parsed.get("value")
        validated = validate_extracted_field(field, value, category)
        return validated
    except Exception as e:
        print("[Field Verifier LLM] skipped:", e)
        return None



def extract_structured_profile_llm(user_text: str, category: str, current_profile: dict, expected_field: Optional[str]) -> dict:
    """
    LLM-based structured extractor.
    It extracts only explicitly mentioned fields from the latest user message.
    It does NOT infer missing fields and does NOT decide pending/qualified.
    Validation runs after this before saving.
    """
    if is_small_talk(user_text) or is_ack(user_text) or is_gibberish(user_text):
        return {}

    if is_hard_unrelated_or_unsafe(user_text):
        return {}

    # Selective LLM extraction: allow the LLM only when the latest message has
    # explicit business/profile/project signals. This restores dynamic extraction
    # for rich messages while preventing hallucinated demo values on vague inputs.
    low_text = normalize(user_text)
    explicit_cues = [
        "my name", "i am", "i'm", "company", "from ", " at ",
        "email", "phone", "budget", "timeline", "deadline", "within", "next",
        "project type", "requirements", "requirement", "features", "proposal",
        "issue type", "issue details", "urgency", "role", "experience",
        "skills", "resume", "portfolio", "mobile app", "android", "ios",
        "cross-platform", "cross platform", "website", "web app", "e-commerce",
        "ecommerce", "crm", "dashboard", "management system", "software",
        "chatbot", "automation", "apple pay", "payment", "business management",
        "chahiye", "chaiye", "banwana", "banwani", "banana", "bana do",
        "jaisa", "jaise", "similar to", "type", "mera naam", "company ka naam",
        "nahi chal", "nhi chal", "kaam nahi", "kaam nhi", "naukri",
        "meeting", "appointment", "schedule", "book", "google meet",
        "gmeet", "phone call", "date", "slot", "time", "tomorrow",
        "today", "discuss", "talk about",
    ]
    has_contact = bool(extract_email(user_text) or extract_phone(user_text))
    if not has_contact and not any(cue in low_text for cue in explicit_cues):
        return {}

    required = REQUIRED_FIELDS.get(category, [])
    schema_hint = {field: None for field in required}

    prompt = f"""You extract structured profile fields for CodeQlik chatbot.

Extract ONLY fields explicitly mentioned in the latest user message.
Do NOT guess.
Do NOT fill a field just because it is pending.
Do NOT put the whole message into a field.
If a value is not clearly present, return null for that field.
If user refuses/skips a field, use "declined".

Category: {category}
Expected pending field: {expected_field}
Existing profile: {json.dumps(current_profile or {}, ensure_ascii=False)}
Allowed output fields: {list(schema_hint.keys())}

Latest user message:
{user_text}

Rules:
- Extract ONLY from the latest user message, not from old profile, examples, or assumptions.
- Never invent name, company, contact, project type, requirements, budget, or timeline.
- Name/company/contact values must appear in the latest user message.
- Project type may be a short phrase explicitly supported by the message, e.g. "cross-platform iOS and Android mobile app".
- Requirements may summarize explicitly stated features, e.g. "e-commerce platform with Apple Pay integration".
- Budget/timeline must be explicitly present; do not infer them.
- For vague messages like "i need an app", extract only project_type="app" if appropriate; leave name/company/budget/timeline null.
- For meeting_booking, extract work_details/topic, meeting_mode, date, and time_slot only when explicitly stated.
- For pure explanation/company questions like "explain software development", return all fields null.

Return JSON only:
{json.dumps(schema_hint, indent=2)}
"""

    try:
        node_name_var.set("field_extraction")
        json_llm = llm.bind(response_format={"type": "json_object"})
        result = json_llm.invoke([HumanMessage(content=prompt)]).content
        parsed = safe_json_loads(result, {})
        clean = validate_extracted_profile(parsed, category)

        # Hard evidence check for identity/contact fields to prevent hallucination.
        low_msg = normalize(user_text)
        for identity_key in ["name", "company", "email", "phone", "email_or_phone"]:
            val = clean.get(identity_key)
            if val and normalize(val) not in low_msg:
                # Phone may be normalized digits while the message contains separators.
                if identity_key in {"phone", "email_or_phone"} and extract_phone(user_text) == str(val):
                    continue
                clean.pop(identity_key, None)

        return clean
    except Exception:
        return {}


def extract_obvious_profile_regex(user_text: str, category: str) -> dict:
    """
    Deterministic supplement for common natural phrases.
    """
    text = str(user_text or "").strip()
    out = {}

    email = extract_email(text)
    phone = extract_phone(text)

    if category in {"client_lead", "customer_support", "hiring_support", "meeting_booking"}:
        if email:
            out["email"] = email
            out["email_or_phone"] = email
        if phone:
            out["phone"] = phone
            if "email_or_phone" not in out:
                out["email_or_phone"] = phone

    # Extract names without swallowing "from/at <company>".
    # Example: "i am deepak kumar from technohub" -> name="deepak kumar"
    m = re.search(r"(?i)\b(?:i am|i'm|my name is|myself)\s+([a-z][a-z.'-]*(?:\s+[a-z][a-z.'-]*){0,2})(?=\s+(?:from|at)\b|[,.;]|$)", text)
    if m:
        candidate_name = re.sub(r"(?i)\s+\b(from|at)\b\s*$", "", m.group(1).strip())
        if candidate_name:
            out["name"] = candidate_name

    m = re.search(r"(?i)\b(?:at|from)\s+([A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*){0,4})(?:\.|,|$)", text)
    if m:
        company = m.group(1).strip()
        if normalize(company) not in {"product manager", "software engineer", "senior software engineer"}:
            out["company"] = company

    m = re.search(r"(?i)\b(?:work at|working at|works at)\s+([A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*){0,4})(?:\.|,|$|\s+and\b)", text)
    if m:
        company = m.group(1).strip()
        if normalize(company) not in {"product manager", "software engineer", "senior software engineer"}:
            out["company"] = company

    if category == "client_lead":
        low = normalize(text)
        project_markers = [
            "mobile app", "android", "ios", "cross-platform", "cross platform",
            "website", "web app", "e-commerce", "ecommerce", "crm", "dashboard",
            "management system", "software", "chatbot", "automation", "portal", "app"
        ]
        requirement_markers = [
            "apple pay", "payment", "integration", "feature", "features",
            "business management", "inventory", "billing", "e-commerce", "ecommerce"
        ]
        service_topic = detect_requested_service_topic(text)
        if service_topic:
            out.setdefault("project_type", service_topic)
        elif any(k in low for k in project_markers):
            # Keep the whole sentence for validation; LLM can later refine it.
            out.setdefault("project_type", text)
        if any(k in low for k in requirement_markers):
            out.setdefault("requirements", text)
        budget_match = re.search(r"(?i)(?:budget(?:\s+is|\s+around|\s+of)?|around|approx(?:imately)?)\s*([₹$]?\s*[\d,]+(?:\.\d+)?\s*(?:usd|inr|rs|k|lakh|lakhs|crore|cr)?)", text)
        if budget_match:
            out.setdefault("budget", budget_match.group(0).strip())
        timeline_match = re.search(r"(?i)(within\s+the\s+next\s+\d+\s*(?:days?|weeks?|months?|years?)|within\s+\d+\s*(?:days?|weeks?|months?|years?)|next\s+\d+\s*(?:days?|weeks?|months?|years?)|\d+\s*(?:days?|weeks?|months?|years?))", text)
        if timeline_match:
            out.setdefault("timeline", timeline_match.group(0).strip())

    if category == "meeting_booking":
        low = normalize(text)
        mode = extract_meeting_mode(text)
        date_value = extract_meeting_date(text)
        slot = extract_time_slot(text)

        if mode:
            out.setdefault("meeting_mode", mode)
        if date_value:
            out.setdefault("date", date_value)
        if slot:
            out.setdefault("time_slot", slot)

        service_topic = detect_requested_service_topic(text)
        if service_topic:
            out.setdefault("work_details", service_topic)

        detail_match = re.search(
            r"(?i)\b(?:discuss|talk about|meeting about|call about|discussion about)\s+(.+?)(?=[,.;]|\b(?:on|at|tomorrow|today|next|this)\b|$)",
            text,
        )
        if detail_match:
            details = detail_match.group(1).strip()
            if details and not extract_meeting_mode(details) and not extract_time_slot(details):
                out.setdefault("work_details", details)
        elif any(k in low for k in ["website", "web app", "mobile app", "crm", "software", "automation", "project", "support issue"]):
            out.setdefault("work_details", text)

    return validate_extracted_profile(out, category)


def extract_expected_field(user_text: str, expected_field: Optional[str], category: str) -> dict:
    text = str(user_text or "").strip()
    low = normalize(text)

    if not expected_field:
        return {}

    if is_gibberish(text) or is_ack(text):
        return {}

    if is_hard_unrelated_or_unsafe(text):
        return {}

    # Do not block extraction just because the message also contains a question.
    # Example: "Anurag, why is it not working?" can provide name AND ask a question.
    # The response layer will still answer the question; this layer only saves a verified field.
    if is_question(text):
        verified = llm_verify_uncertain_field(expected_field, text, category)
        if verified:
            return {expected_field: verified}
        return {}

    if looks_like_refusal(text):
        return {expected_field: "declined"}

    email = extract_email(text)
    phone = extract_phone(text)

    if expected_field == "email_or_phone":
        if email:
            return {"email_or_phone": email, "email": email}
        if phone:
            return {"email_or_phone": phone, "phone": phone}
        return {}

    if expected_field == "email":
        return {"email": email} if email else {}

    if expected_field == "phone":
        return {"phone": phone} if phone else {}

    if expected_field == "name":
        if is_booking_control_phrase(text):
            return {}

        has_name_label = any(lbl in low for lbl in ["my name", "mera naam", "naam", "i am", "i'm", "myself", "this is"])
        if (not has_name_label) and (
            looks_like_reference_product(text)
            or has_project_creation_context(text)
            or has_semantic_support_intent(text)
            or has_semantic_hiring_intent(text)
        ):
            return {}

        value = remove_label_prefix(text, ["my name", "name", "i am", "i'm", "myself", "this is", "mera naam", "naam"])

        # Mixed field + question/action fallback:
        # If the bot is waiting for name and the user writes like
        # "Anurag, why is it not working?" or "Anurag, fix it fast",
        # treat the short leading phrase before comma as a possible name only
        # after strict validation/blocked-word checks.
        if not value:
            m = re.match(r"(?i)^\s*([a-z][a-z.'-]*(?:\s+[a-z][a-z.'-]*){0,2})\s*,\s+(.+)$", text)
            if m:
                candidate = m.group(1).strip()
                rest = normalize(m.group(2))
                bad_name_words = {
                    "why", "what", "how", "please", "fix", "urgent", "asap",
                    "app", "website", "payment", "issue", "problem", "error",
                    "support", "help", "bug", "server", "login"
                }
                if (
                    normalize(candidate) not in bad_name_words
                    and not any(w in normalize(candidate) for w in bad_name_words)
                    and any(w in rest for w in ["why", "what", "how", "fix", "help", "not working", "issue", "problem", "urgent", "asap"])
                ):
                    validated_candidate = validate_extracted_field("name", candidate.title(), category)
                    if validated_candidate:
                        value = validated_candidate

        # Safety guard:
        # If the bot is waiting for name but the user continues with project
        # details/reference apps, do NOT save that as name. The separate
        # project/requirements extractor may still store it safely.
        if looks_like_reference_product(text) or has_project_creation_context(text):
            return {}

        # If the bot accidentally asked an exploratory project question while
        # pending_field is still name, project/business answers must NOT be saved as name.
        project_or_business_words = [
            "e-commerce", "ecommerce", "website", "web site", "app", "application",
            "crm", "chatbot", "platform", "portal", "software", "store", "shop",
            "business", "landing page", "informational site", "online store",
            "mobile app", "web app", "dashboard", "automation"
        ]

        if not value and any(w in low for w in project_or_business_words):
            return {}

        non_name_words = [
            "explain", "what", "why", "how", "tell", "show", "describe", "define",
            "service", "services", "software", "development", "website", "web",
            "app", "application", "project", "budget", "timeline", "company",
            "support", "technology", "technologies", "pricing", "cost", "contact",
            "need", "want", "build", "create", "make", "hire", "quote", "proposal",
            "e-commerce", "ecommerce", "crm", "chatbot", "platform", "portal",
            "store", "shop", "business", "landing page", "online store",
            "like", "similar", "jaisa", "jaise", "type", "clone", "chahiye",
            "chaiye", "banana", "banwana", "banwani", "bana do", "design",
            "book", "booking", "meeting", "call", "schedule", "appointment"
        ]

        if not value:
            if (
                1 <= len(text.split()) <= 4
                and not any(w in low for w in non_name_words)
                and not email
                and not phone
            ):
                value = text

        return {"name": value} if value else {}

    if expected_field == "company":
        if is_booking_control_phrase(text):
            return {}

        has_company_label = any(lbl in low for lbl in ["my company", "company name", "company", "business name", "company ka naam", "business ka naam", "meri company", "hamari company", "humari company"])
        if (not has_company_label) and (
            looks_like_reference_product(text)
            or has_project_creation_context(text)
            or has_semantic_support_intent(text)
            or has_semantic_hiring_intent(text)
        ):
            return {}

        value = remove_label_prefix(text, ["my company", "company name", "company", "organization", "business name", "company ka naam", "business ka naam"])
        if not value:
            blocked = [
                "explain", "what", "why", "how", "tell", "describe",
                "software", "development", "service", "services",
                "need", "want", "budget", "timeline", "issue", "role",
                "experience", "skills", "requirements",
                "book", "booking", "meeting", "call", "schedule", "appointment",
            ]
            if 1 <= len(text.split()) <= 5 and not any(b in low for b in blocked) and not email and not phone:
                value = text
        return {"company": value} if value else {}

    if category == "client_lead":
        if expected_field == "project_type":
            value = remove_label_prefix(text, ["project type", "type", "project"])
            project_keywords = [
                "mobile app", "android", "ios", "cross-platform", "cross platform",
                "website", "web app", "e-commerce", "ecommerce", "crm", "dashboard",
                "management system", "software", "chatbot", "automation", "portal",
                "erp", "saas", "application", "app"
            ]
            if not value:
                if any(k in low for k in project_keywords):
                    value = text
                elif len(text.split()) <= 8:
                    value = text
            return {"project_type": value} if value else {}

        if expected_field == "requirements":
            value = remove_label_prefix(text, ["requirements", "requirement", "features"])
            if not value:
                value = text
            return {"requirements": value} if value else {}

        if expected_field == "budget":
            value = remove_label_prefix(text, ["budget", "amount"])
            if not value:
                m = re.search(r"(\₹|rs\.?|inr|around|approx|approximately)?\s*[\d,]+(\.\d+)?\s*(k|lakh|lakhs|crore|cr|rs|inr)?", low)
                if m:
                    value = m.group(0).strip()
            return {"budget": value} if value else {}

        if expected_field == "timeline":
            value = remove_label_prefix(text, ["timeline", "time", "deadline"])
            if not value:
                m = re.search(r"(within\s+)?\d+\s*(days|day|weeks|week|months|month)|next\s+\w+|this\s+\w+|quarter|asap", low)
                if m:
                    value = m.group(0)
                elif len(text.split()) <= 5:
                    value = text
            return {"timeline": value} if value else {}

    if category == "meeting_booking":
        if expected_field == "work_details":
            if is_booking_control_phrase(text):
                return {}

            value = remove_label_prefix(text, [
                "work details",
                "details",
                "topic",
                "discussion topic",
                "meeting topic",
                "project",
                "service",
            ])
            if not value:
                m = re.search(r"(?i)\b(?:discuss|talk about|meeting about|call about|discussion about)\s+(.+)$", text)
                if m:
                    value = m.group(1).strip()
            if not value:
                if extract_meeting_mode(text) or extract_time_slot(text):
                    return {}
                date_value = extract_meeting_date(text)
                if date_value and len(text.split()) <= 5:
                    return {}
                if len(text.split()) <= 24:
                    value = text
            return {"work_details": value} if value else {}

        if expected_field == "meeting_mode":
            mode = extract_meeting_mode(text)
            return {"meeting_mode": mode} if mode else {}

        if expected_field == "date":
            value = remove_label_prefix(text, ["meeting date", "date", "schedule date", "day"])
            date_value = extract_meeting_date(value or text)
            return {"date": date_value} if date_value else {}

        if expected_field == "time_slot":
            value = remove_label_prefix(text, ["time slot", "slot", "time", "meeting time"])
            slot = extract_time_slot(value or text)
            return {"time_slot": slot} if slot else {}

    if category == "customer_support":
        if expected_field == "issue_type":
            value = remove_label_prefix(text, ["issue type", "type", "issue"])
            if not value:
                value = text
            return {"issue_type": value} if value else {}

        if expected_field == "issue_details":
            value = remove_label_prefix(text, ["issue details", "details", "problem", "error"])
            if not value:
                value = text
            return {"issue_details": value} if value else {}

        if expected_field == "urgency":
            value = remove_label_prefix(text, ["urgency", "priority"])
            if not value and any(k in low for k in ["urgent", "high", "medium", "low", "critical"]):
                value = text
            return {"urgency": value} if value else {}

    if category == "hiring_support":
        if expected_field == "role":
            value = remove_label_prefix(text, ["role", "position", "apply for"])
            if not value:
                value = text
            return {"role": value} if value else {}

        if expected_field == "experience":
            value = remove_label_prefix(text, ["experience"])
            if not value:
                m = re.search(r"(fresher|\d+\s*(month|months|year|years))", low)
                if m:
                    value = m.group(0)
            return {"experience": value} if value else {}

        if expected_field == "skills":
            value = remove_label_prefix(text, ["skills", "skill"])
            if not value:
                value = text
            return {"skills": value} if value else {}

        if expected_field == "resume_or_portfolio":
            value = remove_label_prefix(text, ["resume link", "portfolio", "resume"])
            if not value:
                m = re.search(r"(https?://\S+|[\w.-]+\.(com|dev|io|in|net)/?\S*)", text)
                if m:
                    value = m.group(0)
                else:
                    value = text
            return {"resume_or_portfolio": value} if value else {}

    # Last-resort verifier:
    # Deterministic extraction above failed. Ask LLM only for uncertain fields.
    verified = llm_verify_uncertain_field(expected_field, text, category)
    if verified:
        return {expected_field: verified}

    return {}




def extract_semantic_compat_profile(user_text: str, category: str, expected_field: Optional[str]) -> dict:
    """
    Deterministic semantic supplement for Hinglish/new phrasing.
    It never decides flow or pending fields. It only extracts explicitly present
    values into the same existing REQUIRED_FIELDS schema.
    """
    text = str(user_text or "").strip()
    low = normalize(text)
    out = {}

    if not text or is_small_talk(text) or is_gibberish(text) or is_hard_unrelated_or_unsafe(text):
        return out

    email = extract_email(text)
    phone = extract_phone(text)
    if category in {"client_lead", "customer_support", "hiring_support", "meeting_booking"}:
        if email:
            out["email"] = email
            out["email_or_phone"] = email
        if phone:
            out["phone"] = phone
            if "email_or_phone" not in out:
                out["email_or_phone"] = phone

    # Hinglish name labels. Only labeled names are extracted here.
    name_patterns = [
        r"(?i)\b(?:my\s+name|mera\s+naam|mere\s+naam)\s+(?:hai|h|is)?\s*([a-z][a-z.'-]*(?:\s+[a-z][a-z.'-]*){0,2})\b",
        r"(?i)\b(?:naam)\s+(?:hai|h|is)?\s*([a-z][a-z.'-]*(?:\s+[a-z][a-z.'-]*){0,2})\b",
        r"(?i)\b(?:main|mai|mein)\s+([a-z][a-z.'-]*(?:\s+[a-z][a-z.'-]*){0,2})\s+(?:hu|hoon|hun)\b",
    ]
    for pattern in name_patterns:
        m = re.search(pattern, text)
        if m:
            out["name"] = m.group(1).strip()
            break

    company_patterns = [
        r"(?i)\b(?:company|business|organization|organisation)\s+(?:ka\s+naam\s+)?(?:hai|h|is|:)\s*([a-zA-Z0-9& ._-]{2,60})",
        r"(?i)\b(?:company|business|organization|organisation)\s+ka\s+naam\s+([a-zA-Z0-9& ._-]{2,60})",
        r"(?i)\b(?:meri|hamari|humari|my|our)\s+(?:company|business)\s+([a-zA-Z0-9& ._-]{2,60})",
    ]
    for pattern in company_patterns:
        m = re.search(pattern, text)
        if m:
            company = re.split(r"(?i)\b(and|aur|but|lekin|,|\.|\?)\b", m.group(1).strip())[0].strip()
            if company:
                out["company"] = company
                break

    if category == "client_lead":
        service_topic = detect_requested_service_topic(text)
        if service_topic:
            out.setdefault("project_type", service_topic)

        ref_req = extract_reference_requirement_value(text)
        if ref_req:
            out.setdefault("requirements", ref_req)
            if "project_type" not in out and any(w in low for w in ["app", "application", "android", "ios"]):
                out["project_type"] = "mobile app"

        requirement_signals = [
            "feature", "features", "payment", "gateway", "login", "signup",
            "admin", "panel", "dashboard", "tracking", "live", "notification",
            "booking", "inventory", "billing", "report", "scoring", "tournament",
            "team", "profile", "business management", "lead", "customer",
        ]
        if any(s in low for s in requirement_signals):
            out.setdefault("requirements", text)

        budget_patterns = [
            r"(?i)\b(?:budget|amount)\s*(?:hai|h|is|:)?\s*([₹$]?\s*[\d,]+(?:\.\d+)?\s*(?:rs|inr|usd|k|lakh|lakhs|crore|cr)?)",
            r"(?i)\b([₹$]?\s*[\d,]+(?:\.\d+)?\s*(?:rs|inr|usd|k|lakh|lakhs|crore|cr))\s*(?:ka|tak)?\s*(?:budget)?",
        ]
        for pattern in budget_patterns:
            m = re.search(pattern, text)
            if m:
                out["budget"] = m.group(0).strip()
                break

        timeline_patterns = [
            r"(?i)\b(?:within|in|next)\s+\d+\s*(?:day|days|week|weeks|month|months|year|years)\b",
            r"(?i)\b\d+\s*(?:day|days|week|weeks|month|months|year|years)\s*(?:me|mein|mai|ke andar)?\b",
            r"(?i)\b(?:asap|jaldi|urgent|next month|next week|is month|iss month)\b",
        ]
        for pattern in timeline_patterns:
            m = re.search(pattern, text)
            if m:
                out["timeline"] = m.group(0).strip()
                break

    elif category == "customer_support":
        if has_semantic_support_intent(text):
            if any(w in low for w in ["login", "signin", "sign in"]):
                out.setdefault("issue_type", "login issue")
            elif any(w in low for w in ["payment", "pay"]):
                out.setdefault("issue_type", "payment issue")
            elif any(w in low for w in ["website", "site", "web"]):
                out.setdefault("issue_type", "website issue")
            elif any(w in low for w in ["app", "application"]):
                out.setdefault("issue_type", "app issue")
            elif any(w in low for w in ["server", "down"]):
                out.setdefault("issue_type", "server issue")
            else:
                out.setdefault("issue_type", "technical issue")
            out.setdefault("issue_details", text)
        if any(w in low for w in ["urgent", "critical", "jaldi", "asap", "high priority"]):
            out["urgency"] = "high"
        elif any(w in low for w in ["medium", "normal"]):
            out["urgency"] = "medium"
        elif any(w in low for w in ["low", "not urgent"]):
            out["urgency"] = "low"

    elif category == "hiring_support":
        role_match = re.search(r"(?i)\b(?:role|position|apply for|job for|as a|for)\s+([a-zA-Z][a-zA-Z0-9 +#._-]{2,50})", text)
        if role_match:
            out["role"] = role_match.group(1).strip()
        else:
            generic_hiring_requests = {
                "i want internship", "want internship", "need internship",
                "mujhe internship chahiye", "internship chahiye",
                "job chahiye", "naukri chahiye", "resume submit karna hai",
                "job ke liye apply karna hai", "i want to submit my resume",
            }
            has_specific_role = bool(re.search(r"(?i)\b(python|react|node|django|fastapi|ai|ml|java|frontend|backend|full stack|designer|developer|engineer)\b", text))
            if has_specific_role and low.strip() not in generic_hiring_requests:
                out.setdefault("role", text)

        exp_match = re.search(r"(?i)\b(fresher|\d+\s*(?:month|months|year|years|saal))\b", text)
        if exp_match:
            out["experience"] = exp_match.group(0)

        has_skill_label = "skills" in low or "skill" in low
        has_skill_token = bool(re.search(r"(?i)\b(python|react|node|django|fastapi|ml|ai|java|sql|tensorflow|pytorch)\b", text))
        if has_skill_label or has_skill_token:
            out.setdefault("skills", text)

        resume_match = re.search(r"(?i)(https?://\S+)", text)
        if resume_match:
            out["resume_or_portfolio"] = resume_match.group(0)
        elif any(w in low for w in ["resume", "portfolio", "github", "linkedin"]):
            link_match = re.search(r"(?i)([\w.-]+\.(?:com|dev|io|in|net)/?\S*)", text)
            if link_match and not extract_email(link_match.group(0)):
                out["resume_or_portfolio"] = link_match.group(0)

    elif category == "meeting_booking":
        mode = extract_meeting_mode(text)
        date_value = extract_meeting_date(text)
        slot = extract_time_slot(text)

        if mode:
            out["meeting_mode"] = mode
        if date_value:
            out["date"] = date_value
        if slot:
            out["time_slot"] = slot

        service_topic = detect_requested_service_topic(text)
        if service_topic:
            out.setdefault("work_details", service_topic)

        detail_match = re.search(
            r"(?i)\b(?:discuss|talk about|meeting about|call about|discussion about)\s+(.+?)(?=[,.;]|\b(?:on|at|tomorrow|today|next|this)\b|$)",
            text,
        )
        if detail_match:
            details = detail_match.group(1).strip()
            if details:
                out.setdefault("work_details", details)

    return validate_extracted_profile(out, category)


def extract_direct_labeled_fields(user_text: str, category: str) -> dict:
    """
    Strong deterministic extraction for explicit labeled values.
    This runs before generic field-like filtering so cases like:
    - company is SalesPro
    - project type is CRM
    - budget is 50000
    are not skipped.
    """
    text = str(user_text or "").strip()
    low = normalize(text)
    out = {}

    if is_small_talk(text) or is_gibberish(text) or is_ack(text):
        return out

    email = extract_email(text)
    phone = extract_phone(text)

    if category == "client_lead":
        if email:
            out["email"] = email
            out["email_or_phone"] = email
        if phone:
            out["phone"] = phone
            if "email_or_phone" not in out:
                out["email_or_phone"] = phone

        mapping = {
            "name": ["my name", "name"],
            "company": [
                "my company",
                "company name",
                "company",
                "organization",
                "business name",
            ],
            "project_type": [
                "project type",
                "project",
                "type",
            ],
            "requirements": [
                "requirements",
                "requirement",
                "features",
            ],
            "budget": [
                "budget",
                "amount",
            ],
            "timeline": [
                "timeline",
                "deadline",
                "time",
            ],
        }

    elif category == "meeting_booking":
        if email:
            out["email"] = email
            out["email_or_phone"] = email
        if phone:
            out["phone"] = phone
            if "email_or_phone" not in out:
                out["email_or_phone"] = phone

        mapping = {
            "name": ["my name", "name"],
            "email": ["email", "email id", "email address"],
            "phone": ["phone", "phone number", "contact", "contact number", "mobile", "mobile number"],
            "company": ["my company", "company name", "company", "business name", "business"],
            "work_details": ["work details", "details", "topic", "discussion topic", "meeting topic", "project", "service"],
            "meeting_mode": ["meeting mode", "mode", "call type"],
            "date": ["meeting date", "schedule date", "date", "day"],
            "time_slot": ["time slot", "slot", "meeting time", "time"],
        }

    elif category == "customer_support":
        if email:
            out["email"] = email
            out["email_or_phone"] = email
        if phone:
            out["phone"] = phone
            if "email_or_phone" not in out:
                out["email_or_phone"] = phone

        mapping = {
            "name": ["my name", "name"],
            "issue_type": ["issue type", "issue"],
            "issue_details": ["issue details", "details", "problem", "error"],
            "urgency": ["urgency", "priority"],
        }

    elif category == "hiring_support":
        if email:
            out["email"] = email
            out["email_or_phone"] = email
        if phone:
            out["phone"] = phone
            if "email_or_phone" not in out:
                out["email_or_phone"] = phone

        mapping = {
            "name": ["my name", "name"],
            "role": ["role", "position"],
            "experience": ["experience"],
            "skills": ["skills", "skill"],
            "resume_or_portfolio": ["resume link", "portfolio", "resume"],
        }

    else:
        mapping = {}

    for key, labels in mapping.items():
        value = remove_label_prefix(text, labels)
        if not value:
            inline_values = extract_inline_labeled_values(text, labels)
            value = inline_values[0] if inline_values else None
        if value:
            out[key] = value

    return out


def extract_labeled_fields(user_text: str, category: str) -> dict:
    """Only explicit labeled values; no question inference."""
    if is_question(user_text) or is_gibberish(user_text) or is_ack(user_text):
        return {}

    text = str(user_text or "").strip()
    out = {}

    email = extract_email(text)
    phone = extract_phone(text)

    if category == "client_lead":
        if email:
            out["email"] = email
            out["email_or_phone"] = email
        if phone:
            out["phone"] = phone
            if "email_or_phone" not in out:
                out["email_or_phone"] = phone

        mapping = {
            "name": ["my name", "name"],
            "company": ["my company", "company name", "company"],
            "project_type": ["project type"],
            "requirements": ["requirements", "requirement"],
            "budget": ["budget"],
            "timeline": ["timeline"],
        }

    elif category == "meeting_booking":
        if email:
            out["email"] = email
            out["email_or_phone"] = email
        if phone:
            out["phone"] = phone
            if "email_or_phone" not in out:
                out["email_or_phone"] = phone

        mapping = {
            "name": ["my name", "name"],
            "email": ["email", "email id", "email address"],
            "phone": ["phone", "phone number", "contact", "contact number", "mobile", "mobile number"],
            "company": ["my company", "company name", "company", "business name", "business"],
            "work_details": ["work details", "details", "topic", "discussion topic", "meeting topic", "project", "service"],
            "meeting_mode": ["meeting mode", "mode", "call type"],
            "date": ["meeting date", "schedule date", "date", "day"],
            "time_slot": ["time slot", "slot", "meeting time", "time"],
        }

    elif category == "customer_support":
        if email:
            out["email"] = email
            out["email_or_phone"] = email
        if phone:
            out["phone"] = phone
            if "email_or_phone" not in out:
                out["email_or_phone"] = phone

        mapping = {
            "name": ["my name", "name"],
            "issue_type": ["issue type"],
            "issue_details": ["issue details"],
            "urgency": ["urgency", "priority"],
        }

    elif category == "hiring_support":
        if email:
            out["email"] = email
            out["email_or_phone"] = email
        if phone:
            out["phone"] = phone
            if "email_or_phone" not in out:
                out["email_or_phone"] = phone

        mapping = {
            "name": ["my name", "name"],
            "role": ["role", "position"],
            "experience": ["experience"],
            "skills": ["skills", "skill"],
            "resume_or_portfolio": ["resume link", "portfolio", "resume"],
        }

    else:
        mapping = {}

    for key, labels in mapping.items():
        for label in labels:
            value = remove_label_prefix(text, [label])
            if value:
                out[key] = value
                break

    return out


@traceable
def extract_collection_data(state: ChatState, category: str) -> dict:
    user_text = latest_user_message(state["messages"])
    current_profile = state.get("profile", {}) or {}
    required = REQUIRED_FIELDS.get(category, [])
    intro_context = state.get("intro_context") or ""
    combined_text = (intro_context + "\n" + user_text).strip() if intro_context else user_text

    if is_small_talk(user_text) or is_hard_unrelated_or_unsafe(user_text):
        synced = sync_collection_state(category, current_profile)
        return {
            "profile": current_profile,
            **synced,
            "is_field_answer": False,
        }

    missing_before = check_missing_fields(current_profile, required)
    expected_field = missing_before[0] if missing_before else None

    # IMPORTANT:
    # Company/explanation questions must be answered, not saved as field values.
    # Example:
    # - "explain software development"
    # - "what services do you provide"
    # - "what technologies do you use"
    # These should go to RAG/dynamic answer path, then ask pending field if active.
    is_info_question = (
        is_explanatory_or_company_question(user_text)
        or (
            is_company_or_business_info_query(user_text)
            and (
                is_question(user_text)
                or normalize(user_text).startswith(("explain", "tell", "describe", "define", "what ", "why ", "how "))
            )
        )
    )

    # Use buffered intro context only after a business/support/hiring flow starts.
    # Latest-message expected-field extraction still uses user_text below.
    direct_labeled = extract_direct_labeled_fields(combined_text, category)
    regex_extracted = extract_obvious_profile_regex(combined_text, category)
    semantic_compat_extracted = extract_semantic_compat_profile(combined_text, category, expected_field)

    extracted = {}
    extracted.update(direct_labeled)
    extracted.update(regex_extracted)
    extracted.update(semantic_compat_extracted)

    # Expected pending field should run even when the same message also asks a question.
    # Example: "Anurag, why is it not working?" should save name while response still answers the question.
    expected_extracted = extract_expected_field(user_text, expected_field, category)
    if expected_extracted:
        extracted.update(expected_extracted)

    if is_field_like_answer(user_text, expected_field):
        extracted.update(extract_labeled_fields(user_text, category))

    # If this is an information/explanation question and no field was extracted,
    # do not save anything; let response_generator answer the question and keep
    # asking the same pending field.
    # If a field WAS extracted (e.g. "Anurag, why is it not working?"), keep it
    # and still let response_generator answer because has_extra_question_after_field()
    # prevents the field-only shortcut.
    if is_info_question and not extracted:
        synced = sync_collection_state(category, current_profile)
        return {
            "profile": current_profile,
            **synced,
            "is_field_answer": False,
        }

    # Selective LLM extraction: deterministic first, LLM only fills important
    # missing semantic fields from rich messages. This keeps the flow stable but
    # restores dynamic extraction for project/support/hiring details.
    deterministic_clean = validate_extracted_profile(extracted, category)
    temp_profile = merge_profile(current_profile, deterministic_clean, category)
    still_missing = check_missing_fields(temp_profile, required)
    critical_fields = {
        "client_lead": ["project_type", "requirements", "budget", "timeline"],
        "customer_support": ["issue_type", "issue_details", "urgency"],
        "hiring_support": ["role", "experience", "skills", "resume_or_portfolio"],
        "meeting_booking": ["work_details", "meeting_mode", "date", "time_slot"]
    }
    low_user = normalize(user_text)
    rich_signal_words = [
        "build", "develop", "create", "proposal", "mobile app", "android", "ios",
        "cross-platform", "website", "e-commerce", "ecommerce", "crm", "software",
        "management system", "apple pay", "payment", "budget", "timeline", "within",
        "experience", "skills", "role", "issue", "error", "urgent",
        "chahiye", "chaiye", "banwana", "banwani", "banana", "bana do",
        "jaisa", "jaise", "similar", "type", "kitna", "kaise", "nahi chal", "nhi chal",
        "meet", "meeting", "call", "date", "tomorrow", "today", "slot", "time", "pm", "am"
    ]
    should_try_llm = (
        any(f in still_missing for f in critical_fields.get(category, []))
        and any(w in low_user for w in rich_signal_words)
    )
    if should_try_llm:
        llm_extracted = extract_structured_profile_llm(user_text, category, temp_profile, expected_field)
        # Do not let LLM overwrite deterministic identity/contact values; only fill/extend.
        for k, v in llm_extracted.items():
            if k not in deterministic_clean or k in {"requirements", "issue_details", "project_type", "budget", "timeline", "work_details", "meeting_mode", "date", "time_slot"}:
                extracted[k] = v

    if not extracted:
        synced = sync_collection_state(category, current_profile)
        return {
            "profile": current_profile,
            **synced,
            "is_field_answer": False,
        }

    clean = validate_extracted_profile(extracted, category)

    merged = merge_profile(current_profile, clean, category)
    synced = sync_collection_state(category, merged)

    return {
        "profile": merged,
        **synced,
        "is_field_answer": bool(clean),
        "intro_context": None,
    }


# ---------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------

@traceable
def unrelated_query_node(state: ChatState) -> dict:
    settings = get_chatbot_settings()
    company_name = settings.get("company_name", "CodeQlik")
    response = f"I can only help with {company_name}-related services, projects, support, or hiring. Please ask something related to our company."

    user_text = latest_user_message(state["messages"])
    thread_id = state.get("thread_id") or "default"
    active_collection = state.get("active_collection")
    profile = state.get("profile") or {}
    allowed = REQUIRED_FIELDS.get(active_collection or "", [])
    filtered_profile = {k: v for k, v in profile.items() if k in allowed} if allowed else {}

    return {
        "response_text": response,
        "messages": [AIMessage(content=response)],
        "intent": "unrelated_query",
        "primary_intent": "unrelated_query",
        "active_collection": active_collection,
        "pending_field": state.get("pending_field"),
        "profile": profile,
        "missing_fields": state.get("missing_fields", []),
        "qualified": state.get("qualified", False),
        "response_mode": "decline_unrelated",
    }


@traceable
def general_chat_node(state: ChatState) -> dict:
    if state.get("active_collection"):
        return {}

    user_text = latest_user_message(state["messages"])
    update = {
        "required_fields": [],
        "missing_fields": [],
        "qualified": False,
        "pending_field": None,
        "last_pending_field": None,
    }

    # Buffer intro/profile-like text only temporarily. It is not saved to profile
    # until the user starts a real client/support/hiring flow.
    if looks_like_intro_context(user_text):
        update["intro_context"] = user_text

    return update


@traceable
def client_lead_node(state: ChatState) -> dict:
    user_text = latest_user_message(state["messages"])
    data = extract_collection_data(state, "client_lead")

    context = ""
    confidence = 0.0
    sources = []

    # Keep collection path fast and deterministic. Response generator can answer general info without blocking on RAG.
    if False:
        pass

    if data["qualified"]:
        save_collection_data("client_lead", state.get("thread_id", "default"), data["profile"])

    return {
        **data,
        "retrieved_context": context,
        "company_context": context,
        "rag_confidence": confidence,
        "rag_sources": sources,
    }


@traceable
def customer_support_node(state: ChatState) -> dict:
    data = extract_collection_data(state, "customer_support")

    if data["qualified"]:
        save_collection_data("customer_support", state.get("thread_id", "default"), data["profile"])

    return data


@traceable
def hiring_support_node(state: ChatState) -> dict:
    data = extract_collection_data(state, "hiring_support")

    if data["qualified"]:
        save_collection_data("hiring_support", state.get("thread_id", "default"), data["profile"])

    return data


def repair_meeting_booking_field(state: ChatState, data: dict) -> dict:
    profile = dict(data.get("profile") or {})
    required = REQUIRED_FIELDS.get("meeting_booking", [])
    missing_before = check_missing_fields(state.get("profile", {}) or {}, required)
    expected_field = missing_before[0] if missing_before else None
    user_text = latest_user_message(state["messages"])
    patch = {}

    if expected_field == "meeting_mode" and not profile.get("meeting_mode"):
        mode = extract_meeting_mode(user_text)
        if mode:
            patch["meeting_mode"] = mode
    elif expected_field == "date" and not profile.get("date"):
        date_value = extract_meeting_date(user_text)
        if date_value:
            patch["date"] = date_value
    elif expected_field == "time_slot" and not profile.get("time_slot"):
        slot = extract_time_slot(user_text)
        if slot:
            patch["time_slot"] = slot

    if not patch:
        return data

    profile = merge_profile(profile, patch, "meeting_booking")
    synced = sync_collection_state("meeting_booking", profile)
    return {
        **data,
        "profile": profile,
        **synced,
        "is_field_answer": True,
    }


@traceable
def meeting_booking_node(state: ChatState) -> dict:
    user_text = latest_user_message(state["messages"])
    
    if is_unsupported_meeting_topic(user_text):
        return {
            "intent": "meeting_booking",
            "active_collection": None,
            "qualified": False,
            "profile": {},
            "response_text": "Sorry, hum sirf CodeQlik ke software, website, app, automation, support ya project-related meetings book kar sakte hain.",
            "response_mode": "refusal",
            "messages": [AIMessage(content="Sorry, hum sirf CodeQlik ke software, website, app, automation, support ya project-related meetings book kar sakte hain.")]
        }

    data = extract_collection_data(state, "meeting_booking")
    data = repair_meeting_booking_field(state, data)
    data = {
        **data,
        "slot_conflict": False,
        "no_slots_available": False,
    }

    if data.get("active_collection") == "meeting_booking" and data.get("pending_field") == "time_slot":
        available_slots = get_fixed_response_options(
            "meeting_booking",
            "time_slot",
            profile=data.get("profile") or {},
            thread_id=state.get("thread_id", "default"),
        )
        if not available_slots:
            profile = dict(data.get("profile") or {})
            profile.pop("date", None)
            profile.pop("time_slot", None)
            synced = sync_collection_state("meeting_booking", profile)
            return {
                **data,
                "profile": profile,
                **synced,
                "is_field_answer": False,
                "no_slots_available": True,
            }

    if data["qualified"]:
        saved = save_collection_data("meeting_booking", state.get("thread_id", "default"), data["profile"])
        if saved is False:
            profile = dict(data.get("profile") or {})
            profile.pop("time_slot", None)
            available_slots = get_fixed_response_options(
                "meeting_booking",
                "time_slot",
                profile=profile,
                thread_id=state.get("thread_id", "default"),
            )
            if not available_slots:
                profile.pop("date", None)
                synced = sync_collection_state("meeting_booking", profile)
                return {
                    **data,
                    "profile": profile,
                    **synced,
                    "is_field_answer": False,
                    "no_slots_available": True,
                }

            synced = sync_collection_state("meeting_booking", profile)
            return {
                **data,
                "profile": profile,
                **synced,
                "is_field_answer": False,
                "slot_conflict": True,
            }

    return data


def build_pending_question(
    pending_field: Optional[str],
    active_collection: Optional[str],
    soft: bool = False,
    language_hint: Optional[str] = None,
    profile: Optional[dict] = None,
    thread_id: Optional[str] = None,
) -> str:
    """
    Natural pending-field question builder.

    This does NOT change the chatbot flow.
    sync_collection_state() still decides the exact pending_field; this function
    only changes how that same field is asked.

    soft=True is used when the user asks an information question while the same
    field is still pending, so the follow-up feels less pushy/repetitive.
    """
    if not pending_field:
        return ""

    lang = language_hint or "english"
    if active_collection == "meeting_booking" and pending_field == "time_slot":
        slot_options = get_fixed_response_options(
            active_collection,
            pending_field,
            profile=profile,
            thread_id=thread_id,
        )
        if slot_options:
            slot_number_by_value = {
                "10:00 AM": "1",
                "02:00 PM": "2",
                "04:00 PM": "3",
            }
            slot_lines = "\n".join(
                f"{slot_number_by_value.get(option.get('value'), str(idx))}. {option.get('label') or option.get('value')}"
                for idx, option in enumerate(slot_options, start=1)
            )
            if lang in {"hinglish", "hindi"}:
                return f"Inme se kon sa available time slot sahi rahega:\n{slot_lines}"
            if soft:
                return f"Which of these available slots fits your schedule:\n{slot_lines}"
            return f"Which of these available slots works best for you:\n{slot_lines}"

        if lang in {"hinglish", "hindi"}:
            return "Is date par saare slots booked hain. Aap koi aur date share kar sakte ho?"
        return "All slots are booked for that date. Which other date works best for you?"

    if lang in {"hinglish", "hindi"}:
        client_questions_local = {
            "name": "Before we go ahead — aapka naam kya hai?",
            "email_or_phone": "Team follow-up ke liye best email ya phone number kya hai?",
            "email": "Team follow-up ke liye best email kya hai?",
            "phone": "Team follow-up ke liye best phone number kya hai?",
            "company": "Ye kis company ya business ke liye hai?",
            "project_type": "Aap kis type ka project plan kar rahe ho?",
            "requirements": "Is system me mainly kya-kya kaam hona chahiye?",
            "budget": "Kya aapke mind me rough budget range hai?",
            "timeline": "Aap kab tak start ya launch karna chahte ho?",
        }
        support_questions_local = {
            "name": "Before we go ahead — aapka naam kya hai?",
            "email_or_phone": "Updates ke liye best email ya phone number kya hai?",
            "email": "Updates ke liye best email kya hai?",
            "phone": "Updates ke liye best phone number kya hai?",
            "issue_type": "Aap kis type ka issue face kar rahe ho?",
            "issue_details": "Exactly kya ho raha hai?",
            "urgency": "Ye kitna urgent hai?",
        }
        hiring_questions_local = {
            "name": "Before we go ahead — aapka naam kya hai?",
            "email": "Aapka email kya hai?",
            "phone": "Aapka phone number kya hai?",
            "role": "Aap kis role ke liye interested ho?",
            "experience": "Aapke paas kitna experience hai?",
            "skills": "Aapki main skills kya hain?",
            "resume_or_portfolio": "Aap resume ya portfolio link share kar sakte ho?",
        }
        booking_questions_local = {
            "name": "Meeting confirm karne ke liye — aapka naam kya hai?",
            "email": "Aapki email ID kya hai?",
            "phone": "Aapka contact number kya hai?",
            "company": "Aapki company ya business ka naam kya hai?",
            "work_details": "Meeting me kis service ya project ke baare me discuss karna hai?",
            "meeting_mode": "Aap kis tarah discuss karna chahenge — Google Meet call ya direct Phone Call?",
            "date": "Aap kis date ko discussion schedule karna chahte ho? (e.g. today, tomorrow, ya dynamic date)",
            "time_slot": "Inme se kon sa time slot sahi rahega:\n1. 10:00 AM\n2. 02:00 PM\n3. 04:00 PM"
        }
        if active_collection == "customer_support":
            return support_questions_local.get(pending_field, f"Aap apna {pending_field.replace('_', ' ')} share kar sakte ho?")
        if active_collection == "hiring_support":
            return hiring_questions_local.get(pending_field, f"Aap apna {pending_field.replace('_', ' ')} share kar sakte ho?")
        if active_collection == "meeting_booking":
            return booking_questions_local.get(pending_field, f"Aap apna {pending_field.replace('_', ' ')} share kar sakte ho?")
        return client_questions_local.get(pending_field, f"Aap apna {pending_field.replace('_', ' ')} share kar sakte ho?")

    # Normal mode: use after the user has just provided a field/value.
    client_questions = {
        "name": "Before we go ahead — what name should I use for you?",
        "email_or_phone": "To help the team follow up — what’s the best email or phone number for you?",
        "email": "To help the team follow up — what’s the best email address for you?",
        "phone": "To help for be connected — what’s the best phone number for you?",
        "company": "Which company or business should I connect this with?",
        "project_type": "What kind of project are you planning — website, app, CRM, SaaS, or something custom?",
        "requirements": "What should this system mainly help you do?",
        "budget": "Do you have a rough budget range in mind?",
        "timeline": "When would you like to start or have this ready?",
    }

    support_questions = {
        "name": "Before I check this properly — what name should I use for you?",
        "email_or_phone": "For updates on this — what’s the best email or phone number to reach you?",
        "email": "For updates on this — what’s the best email address to reach you?",
        "phone": "For getting you updated — what’s the best phone number to reach you?",
        "issue_type": "What type of issue is it — login, payment, website, app, server, or something else?",
        "issue_details": "What exactly is happening on your side?",
        "urgency": "How urgent is this — low, medium, high, or critical?",
    }

    hiring_questions = {
        "name": "To start your application — what name should I use?",
        "email": "Which email should we use for your application updates?",
        "phone": "What phone number should the team use to contact you?",
        "role": "Which role are you interested in?",
        "experience": "How much experience do you have in this area?",
        "skills": "Which key skills should I note for you?",
        "resume_or_portfolio": "Could you share your resume or portfolio link?",
    }

    # Soft mode: use after answering an info question while the same field is still pending.
    # These lines avoid fake acknowledgements like "Got it" after the user only asked a question.
    client_soft_questions = {
        "name": "And just so I know who I’m speaking with — what name should I use?",
        "email_or_phone": "When you’re ready — what’s the best email or phone number for follow-up?",
        "email": "When you’re ready — what’s the best email address for follow-up?",
        "phone": "When you’re ready — what’s the best phone number for follow-up?",
        "company": "To place this in the right context — which company or business is this for?",
        "project_type": "If you’re planning something around this — what type of project is it?",
        "requirements": "What would you want this to handle for your business?",
        "budget": "Any rough budget range you’d like us to keep in mind?",
        "timeline": "Any timeline you’re aiming for?",
    }

    support_soft_questions = {
        "name": "And so I can track this properly — what name should I use?",
        "email_or_phone": "When you’re ready — what’s the best email or phone number for updates?",
        "email": "When you’re ready — what’s the best email address for updates?",
        "phone": "When you’re ready — what’s the best phone number for updates?",
        "issue_type": "Which area is affected — login, payment, website, app, server, or something else?",
        "issue_details": "What are you seeing exactly?",
        "urgency": "How urgent should we treat this — low, medium, high, or critical?",
    }

    hiring_soft_questions = {
        "name": "And for the application — what name should I use?",
        "email": "When you’re ready — which email should we use for updates?",
        "phone": "What phone number should the team use to contact you?",
        "role": "Which role are you looking at?",
        "experience": "How much experience do you have in that area?",
        "skills": "Which skills should I note for your profile?",
        "resume_or_portfolio": "When you’re ready — you can share your resume or portfolio link.",
    }

    booking_questions = {
        "name": "To confirm the booking — what name should I use?",
        "email": "What email address should we send the meeting invite to?",
        "phone": "What is the best phone number to reach you?",
        "company": "What is your company or business name?",
        "work_details": "What would you like to discuss in this meeting?",
        "meeting_mode": "How would you prefer to connect — Google Meet or a direct Phone Call?",
        "date": "Which date works best for you? (e.g. today, tomorrow, or any specific date)",
        "time_slot": "Which of these slots works best for you:\n1. 10:00 AM\n2. 02:00 PM\n3. 04:00 PM"
    }

    booking_soft_questions = {
        "name": "And just so we have it for the invite — what name should I use?",
        "email": "Which email address is best for the invite?",
        "phone": "Which phone number is best for follow-ups?",
        "company": "What is your company name?",
        "work_details": "What would you like to discuss in this meeting?",
        "meeting_mode": "Would you prefer Google Meet or Phone Call?",
        "date": "Which date would you prefer?",
        "time_slot": "Which of these slots fits your schedule:\n1. 10:00 AM\n2. 02:00 PM\n3. 04:00 PM"
    }

    fallback_questions = {
        "name": "What name should I use for you?",
        "email_or_phone": "What’s the best email or phone number to reach you?",
        "email": "What email should we use?",
        "phone": "What phone number should we use?",
        "company": "Which company or business is this for?",
        "project_type": "What type of project are you planning?",
        "requirements": "What should this mainly help you do?",
        "budget": "Do you have a rough budget range in mind?",
        "timeline": "What timeline are you aiming for?",
        "issue_type": "What type of issue are you facing?",
        "issue_details": "What exactly is happening?",
        "urgency": "How urgent is this?",
        "role": "Which role are you interested in?",
        "experience": "How much experience do you have?",
        "skills": "What skills should I note down?",
        "resume_or_portfolio": "Could you share your resume or portfolio link?",
        "work_details": "What would you like to discuss?",
        "meeting_mode": "Would you prefer Google Meet or a Phone Call?",
        "date": "What date works best for you?",
        "time_slot": "Which slot works best:\n1. 10:00 AM\n2. 02:00 PM\n3. 04:00 PM"
    }

    if active_collection == "customer_support":
        questions = support_soft_questions if soft else support_questions
    elif active_collection == "hiring_support":
        questions = hiring_soft_questions if soft else hiring_questions
    elif active_collection == "meeting_booking":
        questions = booking_soft_questions if soft else booking_questions
    else:
        questions = client_soft_questions if soft else client_questions

    return questions.get(
        pending_field,
        fallback_questions.get(pending_field, f"Could you share your {pending_field.replace('_', ' ')}?"),
    )



def detect_response_language(text: str) -> str:
    """
    Detect the latest user's language in a conservative way.

    Important compatibility note:
    - This only controls response wording.
    - It does NOT change intent, active_collection, pending_field, profile, or saves.
    - Avoid single-letter markers like "h" because English words such as "with"
      can accidentally trigger Hinglish.
    """
    raw = str(text or "")
    t = normalize(raw)

    if re.search(r"[\u0900-\u097F]", raw):
        return "hindi"

    hinglish_markers = [
        "mujhe", "muje", "hame", "hume", "humko",
        "chahiye", "chaiye", "chahie",
        "banwana", "banwani", "banana", "banani",
        "bana do", "bna do", "banado", "karwana", "karwa",
        "kya", "kaise", "kitna", "kitni", "kitne", "kab",
        "batao", "btao", "batado", "samjhao",
        "nahi", "nahin", "nhi", "haan",
        "mera", "meri", "naam", "aap", "aapke", "liye",
        "hoga", "karna", "kar sakte", "bana sakte",
    ]

    padded = f" {t} "
    for marker in hinglish_markers:
        if " " in marker:
            if f" {marker} " in padded:
                return "hinglish"
        else:
            if re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", t):
                return "hinglish"

    return "english"


def is_hinglish_style(text: str) -> bool:
    return detect_response_language(text) in {"hinglish", "hindi"}


def detect_conversation_language(messages: list[BaseMessage], latest_text: str = "") -> str:
    """
    Prefer the latest meaningful user message, then recent user history.
    This keeps field-only replies like "Anurag" from switching a Hinglish
    conversation back to English.
    """
    latest_lang = detect_response_language(latest_text)
    latest_words = len(normalize(latest_text).split())

    if latest_lang != "english" or latest_words >= 2 or is_question(latest_text):
        return latest_lang

    for msg in reversed(messages or []):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", "") == "human":
            txt = getattr(msg, "content", "")
            if txt == latest_text:
                continue
            lang = detect_response_language(txt)
            if lang != "english":
                return lang
            if len(normalize(txt).split()) >= 2 or is_question(txt):
                return "english"

    return latest_lang


def language_instruction(language_hint: str) -> str:
    if language_hint == "hindi":
        return (
            "Reply in Hindi only. Keep company names and technical terms like CodeQlik, CRM, API, dashboard as-is when natural."
        )
    if language_hint == "hinglish":
        return (
            "Reply in natural Hinglish only, matching the user style. Do not switch to full English unless the user switches to English."
        )
    return (
        "Reply in English only. Do not use Hindi/Hinglish words such as haan, aap, chahiye, "
        "bana sakta hai, kya, kaise, hoga, or aapke liye. Ignore previous assistant language if it conflicts."
    )


def response_violates_language(text: str, language_hint: str) -> bool:
    """Small deterministic guard for obvious language drift."""
    if language_hint != "english":
        return False
    low = normalize(text)
    english_blocklist = [
        "haan", "aap", "aapke", "chahiye", "bana sakta", "bana sakte",
        "kar sakta", "kar sakte", "hoga", "kya", "kaise", "liye",
        "me help", "ke saath", "is tarah", "samajh gaya",
    ]
    for w in english_blocklist:
        if w.isalpha():
            if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", low):
                return True
        elif w in low:
            return True
    return False


def is_client_project_detail_turn(text: str) -> bool:
    """
    True when the user is continuing to describe/refine a client project.
    This is intentionally separate from pending-field collection so project
    details are not mistaken for name/company while the lead flow is active.
    """
    t = normalize(text)
    if not t or is_small_talk(t) or is_hard_unrelated_or_unsafe(t):
        return False
    if extract_email(t) or extract_phone(t):
        return False
    if looks_like_refusal(t):
        return False
    # Explicit identity/company labels are handled by normal field extraction.
    if re.search(r"(?i)\b(my name|mera naam|naam|company name|company ka naam|my company)\b", text):
        return False
    project_words = [
        "website", "web site", "site", "web app", "mobile app", "android", "ios",
        "app", "application", "software", "portal", "platform", "system", "crm",
        "erp", "dashboard", "ecommerce", "e-commerce", "online store", "booking",
        "chatbot", "automation", "design", "develop", "build", "create", "make",
        "banwana", "banwani", "banana", "banani", "bana", "bna", "chahiye",
        "chaiye", "karwa", "karwana", "price", "cost", "estimate", "budget",
    ]
    return has_project_creation_context(text) or looks_like_reference_product(text) or any(w in t for w in project_words)


def build_client_project_detail_reply(user_text: str, profile: dict, pending_field: Optional[str], active_collection: Optional[str], language_hint: Optional[str] = None) -> str:
    """
    Deterministic response for project-detail/refinement turns while identity/contact
    fields are still pending. This prevents empty/repetitive responses like only
    asking the name after every project detail.

    Critical compatibility fix:
    - Always answer the latest user message's exact service.
    - "web app" must not be treated as generic/mobile app just because it
      contains the word "app".
    """
    t = normalize(user_text)
    lang = language_hint or detect_response_language(user_text)
    pending_q = build_pending_question(
        pending_field,
        active_collection,
        language_hint=lang,
        profile=profile,
    ) if pending_field else ""
    ref = extract_reference_requirement_value(user_text)

    if ref:
        if lang in {"hinglish", "hindi"}:
            base = f"Haan, samajh gaya — aapko {ref} type solution chahiye. CodeQlik is tarah ka custom app/software plan aur build karne me help kar sakta hai."
        else:
            base = f"Got it — you’re looking for something {ref}. CodeQlik can help plan and build that kind of custom solution."
    else:
        # Use latest-message service detector instead of old substring order.
        base = build_service_specific_capability_reply(user_text, "CodeQlik", lang)

        # If the user asks specifically about requirements, give a requirements-style answer.
        if ("requirement" in t or "requirements" in t) and detect_requested_service_topic(user_text) == "web app":
            if lang in {"hinglish", "hindi"}:
                base = "Web app requirements me usually user login, dashboard, admin panel, database, APIs, reports aur third-party integrations discuss hote hain."
            else:
                base = "For a web app, we usually discuss user login, dashboards, admin panels, databases, APIs, reports, and third-party integrations."

    if pending_q:
        return f"{base}\n\n{pending_q}"
    return base

@traceable
def response_generator_node(state: ChatState) -> dict:
    user_text = latest_user_message(state["messages"])
    current_question = state.get("current_question") or user_text
    intent = state.get("intent", "general_chat")
    primary_intent = state.get("primary_intent", "general_chat")
    active_collection = state.get("active_collection")
    pending_field = state.get("pending_field")
    profile = state.get("profile", {}) or {}
    missing_fields = state.get("missing_fields", []) or []
    retrieved_context = state.get("retrieved_context") or state.get("company_context") or ""
    rag_confidence = state.get("rag_confidence", 0.0) or 0.0
    rag_sources = state.get("rag_sources", []) or []
    conversation_summary = state.get("conversation_summary", "") or ""
    qualified = state.get("qualified", False)
    is_field_answer = state.get("is_field_answer", False)
    has_profile_context = has_saved_business_context(profile)
    is_saved_context_followup = bool(qualified and has_profile_context and is_context_followup(user_text))
    response_language = detect_conversation_language(state.get("messages", []), user_text)
    collection_context = active_collection
    if not collection_context and qualified and primary_intent in COLLECTION_INTENTS:
        collection_context = primary_intent

    settings = get_chatbot_settings()
    company_name = settings.get("company_name", "CodeQlik")
    company_desc = settings.get("company_description", "")
    fallback_message = settings.get(
        "fallback_message",
        f"I am the official {company_name} support assistant and can assist with company services, support requests, project inquiries, hiring, and company-related information.",
    )

    def _trim(text: str, max_chars: int) -> str:
        text = str(text or "")
        return text if len(text) <= max_chars else text[:max_chars] + "…"

    def _clean_response(text: str) -> str:
        text = str(text or "").strip()
        text = re.sub(r"(?im)^\s*#{1,6}\s*(current user message|answer|follow-up question|state|profile|rules).*?$", "", text)
        text = re.sub(r"(?im)^\s*(current user message|answer|follow-up question|state|profile|rules)\s*[:#-].*?$", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text

    def _split_list_items(items_text: str) -> list[str]:
        """
        Split a comma-based list into clean items without changing item meaning.
        Used only for readability formatting, not for business logic.
        """
        raw = str(items_text or "").strip().strip(".")
        raw = re.sub(r"\s+", " ", raw)
        raw = re.sub(r"\s+(?:and|&)\s+", ", ", raw, flags=re.IGNORECASE)

        items = []
        for item in raw.split(","):
            clean = item.strip(" :-–—")
            clean = re.sub(r"^(?:and|&)\s+", "", clean, flags=re.IGNORECASE).strip()
            if clean:
                items.append(clean)

        return items

    def _format_service_list_response(text: str) -> str:
        """
        Convert long service comma-paragraphs into a readable numbered list.

        Example:
        "We offer services, including software development, AI automation, web apps..."
        becomes:
        "We offer services, including:

        1. software development
        2. AI automation
        3. web apps"

        This function only changes visual layout. It does not add/remove flow fields.
        """
        text = str(text or "").strip()
        if not text:
            return ""

        # Do not touch responses that are already visibly formatted.
        if re.search(r"(?m)^\s*(?:\d+\.|[-•*])\s+", text):
            return text

        service_signal = re.search(
            r"(?i)\b(service|services|software development|ai automation|web apps?|mobile apps?|crm|saas|cloud services?|it consulting)\b",
            text,
        )
        if not service_signal:
            return text

        company_pattern = re.escape(company_name)
        pattern = re.compile(
            rf"(?is)(?P<prefix>\b(?:yeah,\s*)?(?:sure,\s*)?(?:we|{company_pattern}|our team|i)\s+"
            rf"(?:offer|provide|provides|offers|help with|can help with|specialize in|specializes in)"
            rf"[^.\n]{{0,160}}?\b(?:including|such as|like)\s+)"
            rf"(?P<items>[^.\n]+)"
            rf"(?P<end>\.)",
        )

        match = pattern.search(text)
        if not match:
            return text

        items = _split_list_items(match.group("items"))
        if len(items) < 4:
            return text

        prefix = match.group("prefix").strip()
        intro = re.sub(r"\s+", " ", prefix).strip(" ,:-–—") + ":"
        numbered = "\n".join(f"{idx}. {item}" for idx, item in enumerate(items, start=1))

        replacement = f"{intro}\n\n{numbered}"
        before = text[:match.start()].strip()
        after = text[match.end():].strip()

        pieces = []
        if before:
            pieces.append(before)
        pieces.append(replacement)
        if after:
            pieces.append(after)

        return re.sub(r"\n{3,}", "\n\n", "\n\n".join(pieces)).strip()

    def _format_readable_response(text: str) -> str:
        """
        Final readability pass for chatbot replies.

        Goals:
        - Keep the same response meaning and same flow.
        - Avoid one large paragraph.
        - Preserve numbered/bullet lists.
        - Put answer and pending-field question in separate readable blocks.
        """
        text = str(text or "").strip()
        if not text:
            return ""

        # Normalize spaces but preserve intentional newlines.
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        text = _format_service_list_response(text)

        # If the response already has line breaks/list formatting, keep that layout.
        if "\n" in text:
            return re.sub(r"\n{3,}", "\n\n", text).strip()

        # Split long plain paragraphs into short chat-style blocks.
        sentences = re.split(r"(?<=[.!?])\s+", text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if len(sentences) <= 1:
            return text

        blocks = []
        current = ""

        for sentence in sentences:
            if not current:
                current = sentence
            elif len(current) + len(sentence) <= 145:
                current += " " + sentence
            else:
                blocks.append(current)
                current = sentence

        if current:
            blocks.append(current)

        return "\n\n".join(blocks).strip()

    def _llm_reply(prompt: str, fallback: str) -> str:
        try:
            result = llm.invoke([HumanMessage(content=prompt)])
            text = _clean_response(getattr(result, "content", result))
            return text or fallback
        except Exception as e:
            print("[Response LLM] fallback used:", e)
            return fallback

    def _field_description(collection: Optional[str], field: Optional[str]) -> str:
        descriptions = {
            "client_lead": {
                "name": "the user's name",
                "email": "the user's email address",
                "phone": "the user's phone number",
                "company": "the user's company or business name",
                "project_type": "the kind of project they want to build",
                "requirements": "the main features or requirements for the project",
                "budget": "their rough budget range",
                "timeline": "when they want to start or finish the project",
            },
            "customer_support": {
                "name": "the user's name",
                "email": "the user's email address",
                "phone": "the user's phone number",
                "issue_type": "the type/category of issue",
                "issue_details": "what exactly is happening",
                "urgency": "how urgent the issue is",
            },
            "hiring_support": {
                "name": "the candidate's name",
                "email": "the candidate's email address",
                "phone": "the candidate's phone number",
                "role": "the role they are interested in",
                "experience": "their relevant experience",
                "skills": "their key skills",
                "resume_or_portfolio": "their resume or portfolio link",
            },
            "meeting_booking": {
                "name": "the user's name for the meeting booking",
                "email": "the email address for the meeting invite",
                "phone": "the best phone number for follow-up",
                "company": "the user's company or business name",
                "work_details": "what they want to discuss in the meeting",
                "meeting_mode": "whether they prefer Google Meet or Phone Call",
                "date": "the date they want for the meeting",
                "time_slot": "the available meeting time slot they prefer",
            },
        }
        return descriptions.get(collection or "", {}).get(field or "", (field or "the missing detail").replace("_", " "))

    def _dynamic_pending_question(soft: bool = False) -> str:
        fallback = build_pending_question(
            pending_field,
            active_collection,
            soft=soft,
            language_hint=response_language,
            profile=profile,
            thread_id=state.get("thread_id"),
        )
        if not (active_collection and pending_field and not qualified):
            return fallback

        fixed_options = get_fixed_response_options(
            active_collection,
            pending_field,
            profile=profile,
            thread_id=state.get("thread_id"),
        )
        option_labels = [str(o.get("label") or o.get("value") or "").strip() for o in fixed_options if o]
        option_labels = [label for label in option_labels if label]
        option_instruction = ""
        if option_labels:
            option_instruction = (
                "The user must choose from these exact options: "
                + ", ".join(option_labels)
                + ". Include these options naturally and do not add other options."
            )
        question_profile_display = {}
        context_collection = active_collection or collection_context
        if context_collection:
            allowed = REQUIRED_FIELDS.get(context_collection, [])
            question_profile_display = {k: v for k, v in profile.items() if k in allowed}

        prompt = f"""Generate ONLY the next field-collection question for {company_name}'s chatbot.

Latest user language: {response_language}
Language instruction: {language_instruction(response_language)}
Active collection: {active_collection}
Pending field to collect: {pending_field}
Meaning of this field: {_field_description(active_collection, pending_field)}
Already collected profile:
{json.dumps(question_profile_display, ensure_ascii=False)}
Latest user message:
"{current_question}"

Rules:
- Return one natural, friendly question only.
- Ask exactly for the pending field above. Do not ask for any other field.
- Do not mention internal words like "pending field", "profile", "collection", or "state".
- Do not include an acknowledgement, greeting, explanation, or extra sentence.
- Keep it short and conversational.
- Avoid repeating a fixed template; vary the wording naturally.
- {option_instruction or "If no fixed options are listed, do not invent option lists."}

Return only the question text."""

        node_name_var.set("field_question_generation")
        generated = _llm_reply(prompt, fallback).strip()
        generated = re.sub(r"\n{3,}", "\n\n", generated)
        low = normalize(generated)
        invalid = (
            not generated
            or generated in {"{}", "[]"}
            or low in {"null", "none"}
            or len(generated) > 420
            or any(marker in low for marker in ["pending field", "active collection", "profile", "state:", "rules:"])
        )
        if invalid:
            return fallback

        if option_labels:
            missing_labels = [label for label in option_labels if label.lower() not in generated.lower()]
            if missing_labels and pending_field in {"meeting_mode", "time_slot"}:
                generated = f"{generated.rstrip()}\n" + "\n".join(
                    f"{idx}. {label}" for idx, label in enumerate(option_labels, start=1)
                )

        if "?" not in generated and response_language == "english":
            generated = generated.rstrip(".! ") + "?"

        return generated.strip()

    def _enforce_pending_question(response: str) -> str:
        """
        When a collection is active, the assistant may answer the user's current
        question, but it must ask only the exact pending_field next.
        This prevents bugs like pending_field=name but the bot asking project_type.

        Formatting note:
        - The pending question wording is generated by the LLM, then appended
          after a blank line so responses stay readable and conversational.
        """
        if not (active_collection and pending_field and not qualified):
            return response

        required_question = _dynamic_pending_question()
        response = str(response or "").strip()

        # Remove any exploratory question from the main response.
        # Keep answer content, then append the LLM-generated pending question.
        kept = []

        if "\n" in response:
            for line in response.splitlines():
                clean = line.strip()
                if not clean:
                    kept.append("")
                    continue
                if "?" in clean and required_question.lower() not in clean.lower():
                    continue
                if required_question.lower() in clean.lower():
                    continue
                kept.append(clean)

            base = "\n".join(kept).strip()
        else:
            parts = re.split(r"(?<=[.!?])\s+", response)
            for part in parts:
                clean = part.strip()
                if not clean:
                    continue
                if "?" in clean and required_question.lower() not in clean.lower():
                    continue
                if required_question.lower() in clean.lower():
                    continue
                kept.append(clean)

            base = " ".join(kept).strip()

        if base:
            return f"{base}\n\n{required_question}"

        return required_question

    def build_field_ack(pending_field: Optional[str], active_collection: Optional[str], qualified: bool = False) -> str:
        if qualified:
            return "Perfect — I’ve got the details."

        client_ack_by_next_field = {
            "email_or_phone": "Nice, thanks for sharing your name.",
            "company": "Perfect, I’ll use that for follow-up.",
            "project_type": "Great, thanks for sharing the business.",
            "requirements": "Understood, that project type is noted.",
            "budget": "Makes sense, I’ve noted the main requirements.",
            "timeline": "Alright, budget noted.",
        }

        support_ack_by_next_field = {
            "email_or_phone": "Thanks, I’ve got your name.",
            "issue_type": "Perfect, I’ll use that for updates.",
            "issue_details": "Understood, issue type noted.",
            "urgency": "Thanks, that gives us more clarity.",
        }

        hiring_ack_by_next_field = {
            "email": "Nice, thanks for sharing your name.",
            "phone": "Perfect, email noted.",
            "role": "Thanks, phone number noted.",
            "experience": "Great, role noted.",
            "skills": "Understood, experience noted.",
            "resume_or_portfolio": "Nice, skills noted.",
        }

        booking_ack_by_next_field = {
            "email": "Nice, thanks for sharing your name.",
            "phone": "Perfect, email noted.",
            "company": "Thanks, phone number noted.",
            "work_details": "Got it, company noted.",
            "meeting_mode": "Understood, meeting topic noted.",
            "date": "Perfect, meeting mode noted.",
            "time_slot": "Great, date noted.",
        }

        if active_collection == "customer_support":
            return support_ack_by_next_field.get(pending_field, "Thanks, noted.")
        if active_collection == "hiring_support":
            return hiring_ack_by_next_field.get(pending_field, "Thanks, noted.")
        if active_collection == "meeting_booking":
            return booking_ack_by_next_field.get(pending_field, "Thanks, noted.")
        return client_ack_by_next_field.get(pending_field, "Thanks, noted.")

    def _dynamic_field_ack() -> str:
        fallback = build_field_ack(pending_field, active_collection, qualified)
        if not (active_collection and is_field_answer and not qualified):
            return fallback

        prompt = f"""Generate ONLY a short acknowledgement for {company_name}'s chatbot.

Latest user language: {response_language}
Language instruction: {language_instruction(response_language)}
Latest user message:
"{current_question}"

Context:
- The latest user message has just been saved as a valid answer in the current collection flow.
- The next question will be added separately.

Rules:
- Return one brief, friendly acknowledgement only.
- Do not ask any question.
- Do not mention internal state, fields, profile, or collection.
- Do not repeat fixed phrases like "Got it" every time; vary naturally.
- Keep it under 14 words.

Return only the acknowledgement text."""

        node_name_var.set("field_ack_generation")
        generated = _llm_reply(prompt, fallback).strip()
        low = normalize(generated)
        if (
            not generated
            or generated in {"{}", "[]"}
            or low in {"null", "none"}
            or len(generated) > 120
            or "?" in generated
            or any(marker in low for marker in ["pending field", "active collection", "profile", "state:", "rules:"])
        ):
            return fallback
        return generated

    def _save_and_return(response: str, rag_confidence_value=None) -> dict:
        response = _format_readable_response(response)
        thread_id = state.get("thread_id") or "default"
        allowed = REQUIRED_FIELDS.get(active_collection or primary_intent or intent or "", [])
        filtered_profile = {k: v for k, v in profile.items() if k in allowed} if allowed else {}
        # save_chat_to_mongo(thread_id, user_text, response, intent, filtered_profile)
        try:
            rag_value = float(rag_confidence_value if rag_confidence_value is not None else rag_confidence)
        except Exception:
            rag_value = 0.0         
        return {
            "response_text": response,
            "messages": [AIMessage(content=response)],
            "retrieved_context": retrieved_context,
            "rag_confidence": rag_value,
            "rag_sources": rag_sources,
        }

    # Only field-submission turns get deterministic collection response.
    # Normal greetings/questions after a completed flow must still go to dynamic LLM response.
    is_info_question = (
        is_explanatory_or_company_question(user_text)
        or (
            is_company_or_business_info_query(user_text)
            and (
                is_question(user_text)
                or normalize(user_text).startswith(("explain", "tell", "describe", "define", "what ", "why ", "how "))
            )
        )
    )

    if active_collection == "meeting_booking" and state.get("no_slots_available"):
        next_question = _dynamic_pending_question()
        if response_language in {"hinglish", "hindi"}:
            intro = "Us date ke liye abhi saare available slots booked hain."
        else:
            intro = "All available slots for that date are already booked."
        return _save_and_return(f"{intro}\n\n{next_question}", rag_confidence)

    if active_collection == "meeting_booking" and state.get("slot_conflict"):
        next_question = _dynamic_pending_question()
        if response_language in {"hinglish", "hindi"}:
            intro = "Ye slot abhi book ho gaya hai. Please available slots me se koi aur choose kar lo."
        else:
            intro = "That slot has just been booked. Please choose another available slot."
        return _save_and_return(f"{intro}\n\n{next_question}", rag_confidence)

    if active_collection == "meeting_booking" and is_field_answer and pending_field and not qualified and not has_extra_question_after_field(user_text):
        ack = _dynamic_field_ack()
        next_question = _dynamic_pending_question()
        return _save_and_return(f"{ack}\n\n{next_question}", rag_confidence)

    if collection_context == "meeting_booking" and qualified:
        mode_label = "Google Meet" if profile.get("meeting_mode") == "google_meet" else "Phone Call"
        response = (
            "Perfect, your meeting is booked.\n\n"
            f"Name: {profile.get('name', 'N/A')}\n"
            f"Mode: {mode_label}\n"
            f"Date: {profile.get('date', 'N/A')}\n"
            f"Time Slot: {profile.get('time_slot', 'N/A')}\n\n"
            "Our team will use your email/contact details for the invite or follow-up."
        )
        return _save_and_return(response, rag_confidence)

    # Optional RAG only for company/info questions. If retriever fails or is slow internally,
    # response still works because LLM fallback has company description/state.
    if (
        not retrieved_context
        and not is_small_talk(user_text)
    ):
        try:
            details = retrieve_company_context_details(user_text, intent=primary_intent)
            retrieved_context = details.get("context_text", "") or ""
            rag_confidence = details.get("confidence", 0.0) or 0.0
            rag_sources = details.get("sources", []) or []
        except Exception as e:
            print("[RAG] skipped:", e)
            retrieved_context = ""
            rag_confidence = 0.0
            rag_sources = []

    try:
        rag_confidence_float = float(rag_confidence)
    except Exception:
        rag_confidence_float = 0.0

    if rag_confidence_float < 0.55:
        retrieved_context = ""

    profile_display = {}
    if collection_context:
        allowed = REQUIRED_FIELDS.get(collection_context, [])
        profile_display = {k: v for k, v in profile.items() if k in allowed}
    elif is_saved_context_followup:
        profile_display = profile

    if active_collection and pending_field and not qualified:
        pending_instruction = (
            f"You are currently collecting the missing field: '{pending_field}'. "
            f"If the user just provided an answer to the previous question (is_field_answer={is_field_answer}), acknowledge it in a very friendly, natural, and custom way, then ask for the '{pending_field}'. "
            f"If the user is asking a question or describing project details, FIRST answer/address their input, then naturally continue the field collection by asking for '{pending_field}'. "
            f"Make sure you ask for this specific field '{pending_field}' dynamically, naturally, and conversationally in {response_language}. "
            f"Do NOT ask for any other missing fields. Keep the tone friendly and casual."
        )
    elif collection_context == "client_lead" and qualified:
        pending_instruction = "The client lead collection is complete. Thank the user for the details, and then explicitly ask: 'Aap chaho to project discussion ke liye meeting book kar sakte ho. Book karni hai?' (or in English: 'Would you like to book a meeting for project discussion?')."
    elif collection_context == "meeting_booking" and qualified:
        pending_instruction = "The meeting booking is complete. Thank the user and confirm that their meeting with CodeQlik is successfully booked. Explicitly summarize their booking: Name, Mode (Google Meet or Phone Call), Date, and Time Slot. Tell them meeting details/invites have been sent to their email."
    elif collection_context and qualified:
        pending_instruction = "The field collection is complete. Do not ask for any more profile fields. Let the user know we have received all the details and our team will get back to them."
    elif is_saved_context_followup:
        pending_instruction = "The collection is complete. Use the saved Profile as previous business context. If the user says it/this/that, assume they refer to the saved project, issue, or hiring request. Answer without asking more fields."
    else:
        pending_instruction = "No collection is active. Do not say that details were received."

    prompt = f"""You are {company_name}'s official support chatbot.
        contact details :  Email: info@codeqlik.com. Phone: +91-8949687368. Address: CodeQlik - IT Solutions, 301, 3rd Floor, 244-245, Dhruv Marg, Tilak Nagar, near Baskin-Robbins, Gurunanakpura, Raja Park, Jaipur, Rajasthan 302004.

Company:
{_trim(company_desc, 700)}

Latest user message:
"{current_question}"

Latest user language: {response_language}
Language instruction: {language_instruction(response_language)}

Recent history for context only:
{_trim(format_history(state["messages"][:-1], limit=5), 900)}

State:
Intent: {primary_intent}
Active collection: {active_collection}
Pending field: {pending_field}
Missing fields: {missing_fields}
Qualified: {qualified}
Profile / saved business context:
{json.dumps(profile_display, ensure_ascii=False)}

Company/RAG context, use only if relevant:
{_trim(retrieved_context, 1200)}

Response personality:
- Sound like a helpful human support person, not a scripted bot.
- Be friendly, polite, warm, simple, and naturally conversational and be very happy and funny friendly.
- Make the response with like a real human breaks and be the conversation little and funny nature dont be serious.
- Match the user's tone: casual with casual users, clear and professional with serious users, calm with frustrated users.
- If Latest user language is english, reply fully in English only. Never use Hinglish/Hindi words like "haan", "aap", "chahiye", "bana sakta hai", "hoga", or "aapke liye".
- If Latest user language is hinglish, reply in natural Hinglish.
- If Latest user language is hindi, reply in Hindi.but words are of english only the language can be hindi.

Readable response style:
- Do not write one big paragraph or do not create a big response ,make the answers short and crispy.
- Use short chat-style blocks with blank lines between different thoughts.
- If listing 4 or more services, features, benefits, steps, or options, use a numbered list.
- If there is a main answer and an active collection question, answer first, then put the pending-field question on a new paragraph.
- Keep each paragraph short, usually 1-2 short sentences.
- Use bullets/numbered lists only when they improve readability.
- Never mention internal state, intent, RAG, profile, pending field, or these rules.

Rules:
1. Answer the latest user message naturally and dynamically. Do not repeat the same generic line for every small-talk message.
2. Stay focused on {company_name}: services, projects, support, hiring, pricing, contact, and company information.
3. If the user asks casual small talk, reply naturally and briefly, then keep the conversation open for company help.
4. If the user asks who you are or what you can do, explain your role as {company_name}'s support assistant.
5. If exact company data is unavailable, answer generally without inventing exact facts.
6. Use Company/RAG context only if it is relevant to the latest user message. Ignore it if it is not useful.
7. {pending_instruction}
8. CRITICAL FLOW RULE: If Active collection is not None and Pending field is not None, ask ONLY that exact pending field. Ask it dynamically and naturally. Never ask for other missing fields.
9. If the user asks a question, always answer/address the user's question first (using the Company/RAG context if relevant), and then naturally ask for the pending field to continue the collection.
10. Never ask multiple fields in one reply. Never ask a field already present in Profile.
11. Keep the reply concise and useful. Prefer 1-3 short sentences ,but if the list is needed for readability then go upto 5-8 short sentences.
12. Avoid robotic lines like "Please share your name so we can guide you better", "How can I assist you today?", or "Please provide more details."
13. DO NOT include: Thinking process, Reasoning steps ,Analysis ,Internal instructions, Any text like "Here's a thinking process. Only return the final answer.



Return only the final user-facing reply."""

    fallback = fallback_message
    if active_collection and pending_field and not qualified:
        fallback = f"{fallback_message} Could you share your {pending_field.replace('_', ' ')}?"

    node_name = "rag_answer_generation" if retrieved_context and retrieved_context.strip() else "final_response"
    node_name_var.set(node_name)
    response = _llm_reply(prompt, fallback)

    # Anti-repeat / latest-service guard:
    # If LLM falls back to an older saved project_type and ignores the latest
    # service in the user's message, replace only the answer portion with a
    # deterministic latest-message capability answer. Flow/pending field remains
    # controlled by the prompt instructions.
    latest_topic = detect_requested_service_topic(user_text)
    if latest_topic and active_collection and pending_field and not qualified:
        low_response = normalize(response)
        # web app must not be answered as Android/mobile app.
        wrong_mobile_for_web = (
            latest_topic == "web app"
            and ("android" in low_response or "mobile app" in low_response or "mobile apps" in low_response)
            and "web app" not in low_response
            and "web apps" not in low_response
        )
        # If exact latest topic is missing and a conflicting old app type appears,
        # use deterministic answer to avoid repeated/wrong capability lines.
        missing_latest_topic = (
            latest_topic.lower() not in low_response
            and not (latest_topic == "Android app" and "android" in low_response)
            and not (latest_topic == "iOS app" and "ios" in low_response)
            and not (latest_topic == "mobile app" and ("mobile app" in low_response or "mobile apps" in low_response))
        )
        if wrong_mobile_for_web or ("custom android/mobile app" in low_response and latest_topic != "Android app" and latest_topic != "mobile app"):
            response = build_service_specific_capability_reply(user_text, company_name, response_language)
        elif missing_latest_topic and is_client_project_detail_turn(user_text) and len(low_response) < 260:
            # Be conservative: only replace short generic capability replies.
            generic_patterns = [
                "can help design and develop",
                "can help with this project",
                "can help you with that",
                "custom android/mobile app",
            ]
            if any(p in low_response for p in generic_patterns):
                response = build_service_specific_capability_reply(user_text, company_name, response_language)

    # Final language-drift guard for obvious service/project turns.
    # This only rewrites the answer text when language drift is obvious; it never
    # changes intent, active_collection, pending_field, profile, or save behavior.
    if response_violates_language(response, response_language):
        latest_topic_for_language_guard = detect_requested_service_topic(user_text)
        if latest_topic_for_language_guard or is_client_project_detail_turn(user_text):
            response = build_service_specific_capability_reply(user_text, company_name, response_language)

    response = _enforce_pending_question(response).strip()
    return _save_and_return(response, rag_confidence_float)


# ---------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------

checkpointer = MemorySaver()

graph = StateGraph(ChatState)

graph.add_node("intent_classifier", intent_classifier_node)
graph.add_node("client_lead", client_lead_node)
graph.add_node("customer_support", customer_support_node)
graph.add_node("hiring_support", hiring_support_node)
graph.add_node("meeting_booking", meeting_booking_node)
graph.add_node("general_chat", general_chat_node)
graph.add_node("unrelated_query", unrelated_query_node)
graph.add_node("response_generator", response_generator_node)

graph.add_edge(START, "intent_classifier")

graph.add_conditional_edges(
    "intent_classifier",
    route_by_intent,
    {
        "company_info": "client_lead",
        "client_lead": "client_lead",
        "customer_support": "customer_support",
        "hiring_support": "hiring_support",
        "meeting_booking": "meeting_booking",
        "general_chat": "general_chat",
        "unrelated_query": "unrelated_query",
    },
)

graph.add_edge("client_lead", "response_generator")
graph.add_edge("customer_support", "response_generator")
graph.add_edge("hiring_support", "response_generator")
graph.add_edge("meeting_booking", "response_generator")
graph.add_edge("general_chat", "response_generator")
graph.add_edge("unrelated_query", END)
graph.add_edge("response_generator", END)

chatbot = graph.compile(checkpointer=checkpointer)


def get_fixed_response_options(
    active_collection: Optional[str],
    pending_field: Optional[str],
    profile: Optional[dict] = None,
    thread_id: Optional[str] = None,
) -> list[dict]:
    if active_collection != "meeting_booking":
        return []

    if pending_field == "meeting_mode":
        return [
            {"label": "Google Meet", "value": "google meet"},
            {"label": "Phone Call", "value": "phone call"},
        ]

    if pending_field == "time_slot":
        profile = profile or {}
        booked_slots = get_booked_meeting_slots(profile.get("date"), exclude_thread_id=thread_id)
        return [
            option
            for option in MEETING_TIME_SLOT_OPTIONS
            if option["value"] not in booked_slots
        ]

    return []


@traceable
def send_message(user_input: str, thread_id: str = "test_user"):
    thread_id_var.set(thread_id)
    node_name_var.set("general")
    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    print("\n" + "="*80)
    print("GRAPH THREAD ID:", thread_id)
    print("USER INPUT:", user_input)

    try:
        before_state = chatbot.get_state(config)
        print("STATE BEFORE:", before_state.values.get("profile") if before_state and before_state.values else None)
    except Exception as e:
        print("STATE BEFORE ERROR:", e)

    response = chatbot.invoke(
        {
            "messages": [HumanMessage(content=user_input)],
            "thread_id": thread_id,
        },
        config=config,
    )

    print("STATE AFTER PROFILE:", response.get("profile"))

    bot_text = ""
    if response.get("messages"):
        bot_text = getattr(response["messages"][-1], "content", "")

    intent = response.get("intent") or response.get("primary_intent") or "general_chat"
    profile = response.get("profile") or {}
    try:
        save_chat_to_mongo(thread_id, user_input, bot_text, intent, profile)
    except Exception as exc:
        print(f"[database] Failed to save chat for thread={thread_id}: {exc}")

    fixed_options = get_fixed_response_options(
        response.get("active_collection"),
        response.get("pending_field"),
        profile=profile,
        thread_id=thread_id,
    )

    print("="*80 + "\n")
    return {
        "reply": bot_text,
        "intent": response.get("intent"),
        "primary_intent": response.get("primary_intent"),
        "active_collection": response.get("active_collection"),
        "pending_field": response.get("pending_field"),
        "user_goal": response.get("user_goal"),
        "profile": profile,
        "missing_fields": response.get("missing_fields"),
        "qualified": response.get("qualified"),
        "current_question": response.get("current_question"),
        "conversation_summary": response.get("conversation_summary"),
        "retrieved_context": response.get("retrieved_context"),
        "rag_confidence": response.get("rag_confidence"),
        "rag_sources": response.get("rag_sources"),
        "response_mode": response.get("response_mode"),
        "is_field_answer": response.get("is_field_answer"),
        "fixed_options": fixed_options,
        "input_locked": False,
    }
