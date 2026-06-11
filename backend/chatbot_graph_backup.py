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
        or t.startswith(("what ", "why ", "how ", "when ", "where ", "who ", "which "))
        or t.startswith(("can you", "do you", "are you", "is there", "tell me about"))
    )


def is_ack(text: str) -> bool:
    return normalize(text) in {"ok", "okay", "yes", "yeah", "yep", "sure", "go ahead", "fine", "hmm"}


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
        "nice to meet you",
    ]

    return any(p in t for p in smalltalk_patterns)


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

    if any(w in t for w in info_words) and not any(x in t for x in ["i need", "i want", "build", "create", "hire", "quote"]):
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

    if is_sensitive_or_unsafe(t) or is_unrelated_query(t):
        return False

    if is_explanatory_or_company_question(t):
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
            "qualified": True,
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

        # Do not overwrite valid old values with accidental later values.
        old_value = merged.get(key)
        if is_answered(old_value, key) and normalize(value) not in DECLINED_VALUES:
            # If explicitly same, no need to update.
            if normalize(old_value) == normalize(value):
                continue
            # Do not overwrite name/company/role/project unless value was explicitly labeled by extractor.
            # The deterministic extractor only sends expected/labeled fields, so overwrite is usually safe.
            # Still protect name from being overwritten after first valid value.
            if key == "name":
                continue

        merged[key] = value

    return merged


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
    ]
    return any(k in t for k in keywords)


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


def is_unrelated_query(text: str) -> bool:
    t = normalize(text)

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

def classify_intent_rules(user_text: str, active_collection: Optional[str]) -> str:
    t = normalize(user_text)

    # Small talk must be allowed before unrelated-question detection.
    # Without this, "how are you" becomes unrelated because it is a question.
    if is_small_talk(t):
        if active_collection:
            return active_collection
        return "general_chat"

    if is_sensitive_or_unsafe(t) or is_unrelated_query(t):
        return "unrelated_query"

    # If hiring collection is active, normal non-question answers like
    # "python developer" must stay inside hiring flow as role/experience/skills.
    if active_collection == "hiring_support" and not is_question(t):
        return "hiring_support"

    # Support must be checked BEFORE active-flow field-answer locking.
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
    if any(k in t for k in client_keywords):
        return "client_lead"

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
        # Existing logic: company_info merged into client_lead.
        return "client_lead"

    # Only now keep active flow for short/non-question field answers.
    # This prevents topic-switch messages from being trapped in the old flow.
    if active_collection and not is_question(t):
        return active_collection

    if t in {"hi", "hello", "hey", "thanks", "thank you", "bye", "good morning", "good evening"}:
        return "general_chat"

    if active_collection:
        return active_collection

    return "general_chat"

def is_clear_flow_switch(user_text: str, current_active: Optional[str], new_intent: str) -> bool:
    if not current_active:
        return True

    if new_intent == current_active:
        return True

    if new_intent == "unrelated_query":
        return True

    t = normalize(user_text)

    if new_intent == "customer_support":
        return any(k in t for k in ["actually", "existing", "bug", "issue", "problem", "not working", "not opening", "crashing", "error", "downtime", "server error", "login issue"])

    if new_intent == "hiring_support":
        return any(k in t for k in ["actually", "apply", "internship", "job", "resume", "career", "hiring"])

    if new_intent == "client_lead":
        return any(k in t for k in ["actually", "i need", "i want", "build", "develop", "create", "quote", "hire your company"])

    return False


@traceable
def intent_classifier_node(state: ChatState) -> dict:
    user_text = latest_user_message(state["messages"])
    current_active = state.get("active_collection")
    current_profile = state.get("profile", {}) or {}
    summary = state.get("conversation_summary", "")

    primary_intent = classify_intent_rules(user_text, current_active)

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

def remove_label_prefix(text: str, labels: list[str]) -> Optional[str]:
    raw = str(text or "").strip()

    for label in labels:
        # Supports:
        # company is SalesPro
        # company: SalesPro
        # company - SalesPro
        # project type is CRM
        # my company is ABC
        pattern = rf"(?i)^\s*{re.escape(label)}\s*(?:is|:|-)?\s+(.+?)\s*$"
        match = re.match(pattern, raw)
        if match:
            value = match.group(1).strip()
            if value:
                return value

    return None


def extract_expected_field(user_text: str, expected_field: Optional[str], category: str) -> dict:
    text = str(user_text or "").strip()
    low = normalize(text)

    if not expected_field:
        return {}

    if is_gibberish(text) or is_ack(text):
        return {}

    if is_sensitive_or_unsafe(text) or is_unrelated_query(text):
        return {}

    if is_question(text):
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
        value = remove_label_prefix(text, ["my name", "name", "i am", "i'm"])

        non_name_words = [
            "explain", "what", "why", "how", "tell", "show", "describe", "define",
            "service", "services", "software", "development", "website", "web",
            "app", "application", "project", "budget", "timeline", "company",
            "support", "technology", "technologies", "pricing", "cost", "contact",
            "need", "want", "build", "create", "make", "hire", "quote", "proposal",
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
            if not value and len(text.split()) <= 8:
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
            "issue_type": ["issue type", "issue"],
            "issue_details": ["issue details", "details", "problem", "error"],
            "urgency": ["urgency", "priority"],
        }

    elif category == "hiring_support":
        if email:
            out["email"] = email
        if phone:
            out["phone"] = phone

        mapping = {
            "role": ["role", "position"],
            "experience": ["experience"],
            "skills": ["skills", "skill"],
            "resume_or_portfolio": ["resume link", "portfolio", "resume"],
        }

    else:
        mapping = {}

    for key, labels in mapping.items():
        value = remove_label_prefix(text, labels)
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
            "issue_type": ["issue type"],
            "issue_details": ["issue details"],
            "urgency": ["urgency", "priority"],
        }

    elif category == "hiring_support":
        if email:
            out["email"] = email
        if phone:
            out["phone"] = phone

        mapping = {
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

    if is_small_talk(user_text) or is_sensitive_or_unsafe(user_text) or is_unrelated_query(user_text):
        synced = sync_collection_state(category, current_profile)
        return {
            "profile": current_profile,
            **synced,
            "is_field_answer": False,
        }

    missing_before = check_missing_fields(current_profile, required)
    expected_field = missing_before[0] if missing_before else None

    # First extract explicit labeled values.
    # This must happen before the generic field-like gate.
    direct_labeled = extract_direct_labeled_fields(user_text, category)

    # Normal company/explanation questions should be answered, but not saved into profile.
    # Example: "explain software development" must not become name/company/project_type.
    if not direct_labeled and not is_field_like_answer(user_text, expected_field):
        synced = sync_collection_state(category, current_profile)
        return {
            "profile": current_profile,
            **synced,
            "is_field_answer": False,
        }

    extracted = {}
    extracted.update(extract_expected_field(user_text, expected_field, category))
    extracted.update(extract_labeled_fields(user_text, category))
    extracted.update(direct_labeled)

    clean = {}
    allowed = set(required + ["email", "phone"])
    for key, value in extracted.items():
        if key not in allowed:
            continue
        if normalize(value) in DECLINED_VALUES:
            clean[key] = "declined"
        elif is_valid_field_value(value, key):
            clean[key] = value

    merged = merge_profile(current_profile, clean, category)
    synced = sync_collection_state(category, merged)

    return {
        "profile": merged,
        **synced,
        "is_field_answer": bool(clean),
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

    save_chat_to_mongo(thread_id, user_text, response, "unrelated_query", filtered_profile)

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
    return {
        "required_fields": [],
        "missing_fields": [],
        "qualified": True,
        "pending_field": None,
        "last_pending_field": None,
    }


@traceable
def client_lead_node(state: ChatState) -> dict:
    user_text = latest_user_message(state["messages"])
    data = extract_collection_data(state, "client_lead")

    context = ""
    confidence = 0.0
    sources = []

    if not data.get("is_field_answer") and not is_small_talk(user_text) and not is_sensitive_or_unsafe(user_text) and not is_unrelated_query(user_text):
        details = retrieve_company_context_details(user_text)
        context = details.get("context_text", "")
        confidence = details.get("confidence", 0.0)
        sources = details.get("sources", [])

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

    # Deterministic response for field answers.
    # This prevents old history/RAG answer from being repeated after user provides name/email/company/etc.
    if is_field_answer:
        if qualified:
            response = "Thanks, I’ve received the required details. Our team can follow up with you shortly. Is there anything else you’d like to know?"
        else:
            response = f"Thanks. {build_pending_question(pending_field, active_collection)}"

        thread_id = state.get("thread_id") or "default"
        allowed = REQUIRED_FIELDS.get(active_collection or primary_intent or intent or "", [])
        filtered_profile = {k: v for k, v in profile.items() if k in allowed} if allowed else {}
        save_chat_to_mongo(thread_id, user_text, response, intent, filtered_profile)

        return {
            "response_text": response,
            "messages": [AIMessage(content=response)],
            "retrieved_context": retrieved_context,
            "rag_confidence": rag_confidence,
            "rag_sources": rag_sources,
        }

    # RAG only for non-field company questions.
    if not retrieved_context and not is_small_talk(user_text) and not is_sensitive_or_unsafe(user_text) and not is_unrelated_query(user_text):
        details = retrieve_company_context_details(user_text)
        retrieved_context = details.get("context_text", "")
        rag_confidence = details.get("confidence", 0.0) or 0.0
        rag_sources = details.get("sources", []) or []

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

    pending_instruction = ""
    if active_collection and pending_field and not qualified:
        pending_instruction = f"After answering, ask exactly this one follow-up: {build_pending_question(pending_field, active_collection)}"
    elif qualified:
        pending_instruction = "The collection is complete. Confirm that details are received and do not ask more fields."

    dynamic_fallback = f"I can only help with {company_name}-related services, projects, support, or hiring. Please ask something related to our company."

    prompt = f"""You are {company_name}'s official support chatbot.
Company: {_trim(company_desc, 500)}

### CURRENT USER MESSAGE — answer this only ###
"{current_question}"

### HISTORY — background only, do not re-answer old turns ###
{_trim(format_history(state["messages"][:-1], limit=5), 900)}

### SUMMARY ###
{_trim(conversation_summary, 300)}

### STATE ###
Intent: {primary_intent}
Active collection: {active_collection}
Pending field: {pending_field}
Missing fields: {missing_fields}
Qualified: {qualified}
Profile: {json.dumps(profile_display)}

### COMPANY/RAG CONTEXT ###
{_trim(retrieved_context, 900)}

### RULES ###
1. Answer the latest user message first.
2. Do not repeat previous answers unless user asks for recap.
3. If the latest message is casual small talk, reply politely and briefly, then optionally mention you can help with company services/support/hiring.
4. If the latest message is unrelated, unsafe, political, hacking, adult, internal prompt/system/API/model related, respond only with: "{dynamic_fallback}"
4. If active collection exists, answer first, then ask only the pending field.
5. {pending_instruction}
6. Do not ask any field already present in Profile.
7. Do not invent facts. If exact data is not available, answer generally within company scope.
8. Keep it concise: 1-3 sentences. No meta-text."""

    response = llm.invoke([HumanMessage(content=prompt)]).content

    thread_id = state.get("thread_id") or "default"
    allowed = REQUIRED_FIELDS.get(active_collection or primary_intent or intent or "", [])
    filtered_profile = {k: v for k, v in profile.items() if k in allowed} if allowed else {}
    save_chat_to_mongo(thread_id, user_text, response, intent, filtered_profile)

    return {
        "response_text": response,
        "messages": [AIMessage(content=response)],
        "retrieved_context": retrieved_context,
        "rag_confidence": rag_confidence_float,
        "rag_sources": rag_sources,
    }


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

    response = chatbot.invoke(
        {
            "messages": [HumanMessage(content=user_input)],
            "thread_id": thread_id,
        },
        config=config,
    )

    return {
        "reply": response["messages"][-1].content,
        "intent": response.get("intent"),
        "primary_intent": response.get("primary_intent"),
        "active_collection": response.get("active_collection"),
        "pending_field": response.get("pending_field"),
        "user_goal": response.get("user_goal"),
        "profile": response.get("profile"),
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
