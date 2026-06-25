from typing import Annotated, Optional
from typing_extensions import TypedDict
import json
import re

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from database import save_chat_to_mongo, save_collection_data, get_chatbot_settings
from rag.retriever import retrieve_company_context_details
from llm_client import FailoverChatGroq
from langsmith import traceable


llm = FailoverChatGroq(
    model="llama-3.1-8b-instant",
    temperature=0.2,
)


REQUIRED_FIELDS = {
    "client_lead": [
        "name",
        "email_or_phone",
        "company",
        "project_type",
        "requirements",
        "budget",
        "timeline",
    ],
    "customer_support": [
        "name",
        "email_or_phone",
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
}

COLLECTION_INTENTS = {"client_lead", "customer_support", "hiring_support"}

VALID_INTENTS = [
    "company_info",
    "client_lead",
    "customer_support",
    "hiring_support",
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


def is_question(text: str) -> bool:
    t = normalize(text)
    return (
        "?" in t
        or t.startswith(("what ", "why ", "how ","have" ,"when ", "where ", "who ", "which "))
        or t.startswith(("can you", "do you", "does ", "did ", "are you", "is there", "tell me about", "could you", "would you", "should "))
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
        "skills", "resume", "portfolio",
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
    return any(k in t for k in keywords) or has_business_domain_keyword(t)


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
    """
    t = normalize(text)
    hard_blocks = [
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
    return any(k in t for k in hard_blocks)


def is_unrelated_query(text: str) -> bool:
    t = normalize(text)

    if is_small_talk(t):
        return False

    if is_company_or_business_info_query(t):
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
        "crm", "automation", "chatbot", "support"
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

    return any(cue in t for cue in buying_cues) and any(term in t for term in service_terms)


def has_hiring_info_intent(text: str) -> bool:
    t = normalize(text)
    return any(k in t for k in [
        "opening", "openings", "available role", "available roles",
        "roles available", "vacancy", "vacancies", "hiring",
        "career", "internship", "job"
    ])


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
  "intent": "client_lead|customer_support|hiring_support|company_info|general_chat|unrelated_query",
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
    - LLM semantic classifier only for unclear no-active cases.
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
    if any(k in t for k in clear_support_phrases):
        return "customer_support"

    clear_hiring_phrases = [
        "i want internship", "want internship", "need internship",
        "apply", "apply for", "want to apply", "i want to apply",
        "job", "internship", "fresher", "resume", "cv",
        "career", "hiring", "vacancy", "opening", "openings",
        "available role", "available roles", "roles available",
        "python developer job", "ai intern", "ml intern"
    ]
    if any(k in t for k in clear_hiring_phrases):
        return "hiring_support"

    clear_client_phrases = [
        "i need", "i want", "build", "develop", "create", "make",
        "quote", "proposal", "need website", "need app", "need crm",
        "need chatbot", "want website", "want app", "want crm",
        "website for my business", "for my business", "can you make",
        "can you build", "ecommerce", "e-commerce", "software for my business"
    ]
    if any(k in t for k in clear_client_phrases) or has_client_buying_intent(t):
        return "client_lead"

    # During an active collection, do not reject broad project/company questions
    # just because keyword matching is imperfect. Only hard unrelated/unsafe topics
    # should break the flow.
    if active_collection:
        if is_hard_unrelated_or_unsafe(t):
            return "unrelated_query"
        return active_collection

    # Broad service/domain informational questions should be answered, not refused.
    # Example: "tell me about e commerce", "explain ERP", "what is payment gateway integration".
    if is_company_or_business_info_query(t) or (is_question(t) and has_business_domain_keyword(t)):
        return "company_info"

    # Ambiguous questions get RAG first, then LLM fallback before refusing.
    # Hard unrelated/unsafe topics were already handled above and still remain blocked.
    if is_unrelated_query(t):
        if is_question(t) and (rag_suggests_company_relevance(t) or llm_suggests_company_relevance(t)):
            return "general_chat"
        return "unrelated_query"

    if is_plain_value_without_context(t):
        return "general_chat"

    # Company/service info should answer and then continue the client lead flow.
    # Greeting/small-talk is already handled above, so it will not start lead collection.
    if is_company_or_business_info_query(t):
        if has_hiring_info_intent(t):
            return "hiring_support"
        return "company_info"

    # Avoid slow/unstable LLM classification in production flow tests.
    # Rules cover company/client/support/hiring/general/unrelated cases.
    return classify_intent_rules_fallback(user_text, active_collection)

def is_clear_flow_switch(user_text: str, current_active: Optional[str], new_intent: str) -> bool:
    if not current_active:
        return True

    if new_intent == current_active:
        return True

    if new_intent == "unrelated_query":
        return True

    t = normalize(user_text)

    if new_intent == "customer_support":
        return any(k in t for k in ["actually", "existing", "bug", "issue", "problem", "not working", "not opening", "crashing", "error", "downtime", "server error", "login issue", "after login", "keeps failing", "failing"])

    if new_intent == "hiring_support":
        return any(k in t for k in ["actually", "apply", "internship", "job", "resume", "career", "hiring"])

    if new_intent == "client_lead":
        return any(k in t for k in [
            "actually", "i need", "i want", "we need", "we want",
            "build", "develop", "create", "quote", "hire your company",
            "for my business", "need website", "need app", "need crm",
            "can you make", "can you build", "help me with", "looking for",
            "interested in", "require", "solution for", "erp", "odoo",
            "crm", "management system", "cost for", "price for", "estimate for"
        ]) or has_client_buying_intent(t)

    return False


@traceable
def intent_classifier_node(state: ChatState) -> dict:
    user_text = latest_user_message(state["messages"])
    current_active = state.get("active_collection")
    current_profile = state.get("profile", {}) or {}
    summary = state.get("conversation_summary", "")

    primary_intent = classify_intent_rules(user_text, current_active)

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

    return {
        "intent": primary_intent,
        "primary_intent": primary_intent,
        "active_collection": synced["active_collection"],
        "user_goal": state.get("user_goal") or primary_intent,
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
        forbidden = [
            "product manager", "manager at", "company", "solutions", "project",
            "requirement", "requirements", "mobile app", "application", "platform",
            "development", "dashboard", "invoice", "export", "support", "details",
            "we're", "we are", "looking", "build", "create", "proposal", "email",
            "phone", "budget", "timeline",
            "e-commerce", "ecommerce", "website", "web site", "app",
            "application", "crm", "chatbot", "platform", "portal",
            "software", "store", "shop", "business", "landing page",
            "informational site", "online store"
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
        forbidden_exact = {"details", "project", "requirements", "mobile app", "app", "website", "crm", "yes", "no", "ok"}
        if low in forbidden_exact:
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

    if key in {"requirements", "issue_type", "issue_details", "role", "skills"}:
        if low in {"details", "yes", "no", "ok"} and key != "issue_type":
            return None
        return text

    return text


def validate_extracted_profile(raw: dict, category: str) -> dict:
    allowed = set(REQUIRED_FIELDS.get(category, [])) | {"email", "phone"}
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
- For pure explanation/company questions like "explain software development", return all fields null.

Return JSON only:
{json.dumps(schema_hint, indent=2)}
"""

    try:
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

    if category in {"client_lead", "customer_support"}:
        if email:
            out["email_or_phone"] = email
        elif phone:
            out["email_or_phone"] = phone
    elif category == "hiring_support":
        if email:
            out["email_or_phone"] = email
            out["email"] = email
        if phone:
            out["email_or_phone"] = phone
            out["phone"] = phone

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
        if any(k in low for k in project_markers):
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
        value = remove_label_prefix(text, ["my name", "name", "i am", "i'm", "myself", "this is"])

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
            "store", "shop", "business", "landing page", "online store"
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
        value = remove_label_prefix(text, ["my company", "company name", "company", "organization", "business name"])
        if not value:
            blocked = [
                "explain", "what", "why", "how", "tell", "describe",
                "software", "development", "service", "services",
                "need", "want", "budget", "timeline", "issue", "role",
                "experience", "skills", "requirements",
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
            out["email_or_phone"] = email
            out["email"] = email
        if phone:
            out["email_or_phone"] = phone
            out["phone"] = phone

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

    elif category == "customer_support":
        if email:
            out["email_or_phone"] = email
            out["email"] = email
        if phone:
            out["email_or_phone"] = phone
            out["phone"] = phone

        mapping = {
            "name": ["my name", "name"],
            "issue_type": ["issue type", "issue"],
            "issue_details": ["issue details", "details", "problem", "error"],
            "urgency": ["urgency", "priority"],
        }

    elif category == "hiring_support":
        if email:
            out["email_or_phone"] = email
            out["email"] = email
        if phone:
            out["email_or_phone"] = phone
            out["phone"] = phone

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
            out["email_or_phone"] = email
            out["email"] = email
        if phone:
            out["email_or_phone"] = phone
            out["phone"] = phone

        mapping = {
            "name": ["my name", "name"],
            "company": ["my company", "company name", "company"],
            "project_type": ["project type"],
            "requirements": ["requirements", "requirement"],
            "budget": ["budget"],
            "timeline": ["timeline"],
        }

    elif category == "customer_support":
        if email:
            out["email_or_phone"] = email
            out["email"] = email
        if phone:
            out["email_or_phone"] = phone
            out["phone"] = phone

        mapping = {
            "name": ["my name", "name"],
            "issue_type": ["issue type"],
            "issue_details": ["issue details"],
            "urgency": ["urgency", "priority"],
        }

    elif category == "hiring_support":
        if email:
            out["email_or_phone"] = email
            out["email"] = email
        if phone:
            out["email_or_phone"] = phone
            out["phone"] = phone

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

    extracted = {}
    extracted.update(direct_labeled)
    extracted.update(regex_extracted)

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
    }
    low_user = normalize(user_text)
    rich_signal_words = [
        "build", "develop", "create", "proposal", "mobile app", "android", "ios",
        "cross-platform", "website", "e-commerce", "ecommerce", "crm", "software",
        "management system", "apple pay", "payment", "budget", "timeline", "within",
        "experience", "skills", "role", "issue", "error", "urgent"
    ]
    should_try_llm = (
        any(f in still_missing for f in critical_fields.get(category, []))
        and any(w in low_user for w in rich_signal_words)
    )
    if should_try_llm:
        llm_extracted = extract_structured_profile_llm(user_text, category, temp_profile, expected_field)
        # Do not let LLM overwrite deterministic identity/contact values; only fill/extend.
        for k, v in llm_extracted.items():
            if k not in deterministic_clean or k in {"requirements", "issue_details", "project_type", "budget", "timeline"}:
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


def build_pending_question(pending_field: Optional[str], active_collection: Optional[str]) -> str:
    if not pending_field:
        return ""

    labels = {
        "name": "your name",
        "email_or_phone": "your email or phone number",
        "email": "your email address",
        "phone": "your phone number",
        "company": "your company name",
        "project_type": "the project type",
        "requirements": "your main requirements",
        "budget": "your estimated budget",
        "timeline": "your expected timeline",
        "issue_type": "the issue type",
        "issue_details": "more details about the issue",
        "urgency": "the urgency level",
        "role": "the role you want to apply for",
        "experience": "your experience",
        "skills": "your key skills",
        "resume_or_portfolio": "your resume or portfolio link",
    }

    label = labels.get(pending_field, pending_field.replace("_", " "))

    if active_collection == "customer_support":
        return f"Please share {label} so our support team can help."
    if active_collection == "hiring_support":
        return f"Please share {label}."
    return f"Please share {label} so we can guide you better."


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

    def _llm_reply(prompt: str, fallback: str) -> str:
        try:
            result = llm.invoke([HumanMessage(content=prompt)])
            text = _clean_response(getattr(result, "content", result))
            return text or fallback
        except Exception as e:
            print("[Response LLM] fallback used:", e)
            return fallback

    def _enforce_pending_question(response: str) -> str:
        """
        When a collection is active, the assistant may answer the user's current
        question, but it must ask only the exact pending_field next.
        This prevents bugs like pending_field=name but the bot asking project_type.
        """
        if not (active_collection and pending_field and not qualified):
            return response

        required_question = build_pending_question(pending_field, active_collection)
        response = str(response or "").strip()

        # Remove any LLM-generated exploratory question.
        # Keep non-question answer sentences, then append the deterministic pending question.
        parts = re.split(r"(?<=[.!?])\s+", response)
        kept = []
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
            return f"{base} {required_question}"
        return required_question

    def _save_and_return(response: str, rag_confidence_value=None) -> dict:
        thread_id = state.get("thread_id") or "default"
        allowed = REQUIRED_FIELDS.get(active_collection or primary_intent or intent or "", [])
        filtered_profile = {k: v for k, v in profile.items() if k in allowed} if allowed else {}
        save_chat_to_mongo(thread_id, user_text, response, intent, filtered_profile)
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

    # If the latest message only submits a field, keep the fast deterministic response.
    # If it submits a field AND asks a question, answer the question dynamically first,
    # then _enforce_pending_question() will append the exact next pending field.
    if is_field_answer and not is_info_question and not has_extra_question_after_field(user_text):
        if active_collection and qualified:
            response = "Thanks, I’ve received the required details. Our team can follow up with you shortly. Is there anything else you’d like to know?"
        else:
            response = f"Thanks. {build_pending_question(pending_field, active_collection)}"
        return _save_and_return(response)

    dynamic_fallback = f"I can only help with {company_name}-related services, projects, support, or hiring. Please ask something related to our company."

    if (
        is_hard_unrelated_or_unsafe(user_text)
        or (
            not active_collection
            and is_unrelated_query(user_text)
            and not is_saved_context_followup
            and not has_business_domain_keyword(user_text)
            and not rag_suggests_company_relevance(user_text)
            and not llm_suggests_company_relevance(user_text)
        )
    ):
        return _save_and_return(dynamic_fallback)

    # Optional RAG only for company/info questions. If retriever fails or is slow internally,
    # response still works because LLM fallback has company description/state.
    if (
        not retrieved_context
        and not is_small_talk(user_text)
        and (not is_field_answer or has_extra_question_after_field(user_text))
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
    if active_collection:
        allowed = REQUIRED_FIELDS.get(active_collection, [])
        profile_display = {k: v for k, v in profile.items() if k in allowed}
    elif is_saved_context_followup:
        profile_display = profile

    if active_collection and pending_field and not qualified:
        pending_instruction = f"After answering the current message, ask exactly this one follow-up: {build_pending_question(pending_field, active_collection)}"
    elif active_collection and qualified:
        pending_instruction = "The collection is complete. Do not ask more fields unless the user starts a new request."
    elif is_saved_context_followup:
        pending_instruction = "The collection is complete. Use the saved Profile as previous business context. If the user says it/this/that, assume they refer to the saved project, issue, or hiring request. Answer without asking more fields."
    else:
        pending_instruction = "No collection is active. Do not say that details were received."

    prompt = f"""You are {company_name}'s official support chatbot.
Company: {_trim(company_desc, 700)}

Latest user message:
"{current_question}"

Recent history for context only:
{_trim(format_history(state["messages"][:-1], limit=5), 900)}

State:
Intent: {primary_intent}
Active collection: {active_collection}
Pending field: {pending_field}
Missing fields: {missing_fields}
Qualified: {qualified}
Profile / saved business context: {json.dumps(profile_display, ensure_ascii=False)}

Company/RAG context, use only if relevant:
{_trim(retrieved_context, 1200)}

Response nature:
- friendly and happy conversational

Rules:
1. Answer the latest user message naturally and dynamically. Do not repeat the same generic line for every small-talk message.
2. Stay focused on {company_name}: services, projects, support, hiring, pricing, contact, and company information.
3. If the user asks casual small talk, reply naturally and briefly, then keep the conversation open for company help.
4. If the user asks who you are or what you can do, explain your role as {company_name}'s support assistant.
5. If exact company data is unavailable, answer generally without inventing exact facts.
6. {pending_instruction}
7. CRITICAL FLOW RULE: If Active collection is not None and Pending field is not None, ask ONLY that exact pending field. Never ask exploratory questions, never change the collection order, and never ask for project type/company/budget/timeline unless that exact field is pending.
8. If the latest user message contains both a field value and a company/service question, answer the question first, then continue with the exact pending field.
9. Never ask multiple fields in one reply. Never ask a field already present in Profile.
10. Keep the reply concise: 1-3 sentences.
11. Response nature: - friendly , polite , funny and happy conversational
Return only the final user-facing reply."""

    fallback = fallback_message
    if active_collection and pending_field and not qualified:
        fallback = f"{fallback_message} {build_pending_question(pending_field, active_collection)}"

    response = _llm_reply(prompt, fallback)
    response = _enforce_pending_question(response)
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
        "general_chat": "general_chat",
        "unrelated_query": "unrelated_query",
    },
)

graph.add_edge("client_lead", "response_generator")
graph.add_edge("customer_support", "response_generator")
graph.add_edge("hiring_support", "response_generator")
graph.add_edge("general_chat", "response_generator")
graph.add_edge("unrelated_query", END)
graph.add_edge("response_generator", END)

chatbot = graph.compile(checkpointer=checkpointer)


@traceable
def send_message(user_input: str, thread_id: str = "test_user"):
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
    }
