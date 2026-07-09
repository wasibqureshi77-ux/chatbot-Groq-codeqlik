import json
import re
from typing import List, Optional, Union, Dict
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from llm_client import FailoverChatGroq

class SuggestionMessage(BaseModel):
    role: str
    content: str

class WidgetSuggestionRequest(BaseModel):
    latest_bot_message: str
    latest_user_message: Optional[str] = None
    recent_messages: Optional[Union[List[SuggestionMessage], List[str], List[Dict[str, str]]]] = None
    company_name: Optional[str] = "CodeQlik"
    assistant_name: Optional[str] = "Ray"
    business_context: Optional[str] = (
        "software development, websites, mobile apps, AI automation, CRM, SaaS, cloud, IT consulting"
    )
    language_hint: Optional[str] = "auto"
    max_suggestions: Optional[int] = 4
    thread_id: Optional[str] = None

class WidgetSuggestionResponse(BaseModel):
    suggestions: List[str]

# Create a dedicated LLM instance for suggestions to avoid circular imports
llm_suggestions = FailoverChatGroq(
    model="llama-3.1-8b-instant",
    temperature=0.2,
)

def sanitize_suggestions(
    raw_suggestions: List[str],
    latest_user_message: Optional[str],
    latest_bot_message: str,
    max_suggestions: int = 4
) -> List[str]:
    """
    Sanitize suggestion items to match strictly the conversion, safety, and formatting rules.
    """
    # 1. Check if bot asks for name, email, phone, contact number or private details
    # Only block if it is a short, direct contact request (less than 120 characters)
    bot_low = (latest_bot_message or "").lower()
    contact_cues = [
        "your name", "what name", "email", "phone", "contact", "number",
        "reach you", "best email", "best phone", "email address", "phone number",
        "mobile number", "call you", "contact number"
    ]
    if len(latest_bot_message) < 120 and any(cue in bot_low for cue in contact_cues):
        return []

    # 2. Filtering negative/refusal phrases
    negative_phrases = [
        "skip", "i don't want", "i don't want to", "why do you need", "don't ask me",
        "no thanks", "nothing else", "i'm not interested", "private", "not share",
        "refuse", "not telling", "no", "not now", "later", "why do you need this"
    ]

    cleaned = []
    seen = set()

    for s in raw_suggestions:
        if not isinstance(s, str):
            continue
        s_stripped = s.strip().strip('"').strip("'").strip()
        if not s_stripped:
            continue

        s_low = s_stripped.lower()

        # Check negative phrases
        if any(neg in s_low for neg in negative_phrases):
            continue

        # Check length
        if len(s_stripped) > 80:
            continue

        # Check duplicates case-insensitively
        if s_low in seen:
            continue

        # Ensure it's not identical to the latest user message
        if latest_user_message and s_low == latest_user_message.strip().lower():
            continue

        # Remove email-like/phone-like text
        if "@" in s_stripped or re.search(r"\b\d{5,}\b", s_stripped):
            continue

        # Strip emojis/quotes/markdown/numbering prefix if any
        # Remove numbers like "1. ", "2) "
        s_clean = re.sub(r"^\d+[\s.)-]+\s*", "", s_stripped)
        s_clean = s_clean.strip('"').strip("'").strip()

        # Check unsafe categories (adult, political, hack, religious, advisory)
        unsafe_keywords = [
            "hack", "politics", "religion", "sex", "adult", "porn", "medical", "legal", "financial advisor"
        ]
        if any(u in s_clean.lower() for u in unsafe_keywords):
            continue

        if not s_clean:
            continue

        seen.add(s_clean.lower())
        cleaned.append(s_clean)

    return cleaned[:max_suggestions]

def generate_widget_suggestions(req: WidgetSuggestionRequest) -> List[str]:
    # Normalize recent messages format
    formatted_history = []
    if req.recent_messages:
        for msg in req.recent_messages:
            if isinstance(msg, str):
                formatted_history.append(msg)
            elif isinstance(msg, dict):
                role = msg.get("role", "user")
                content = msg.get("content", "")
                formatted_history.append(f"{role.capitalize()}: {content}")
            elif hasattr(msg, "role") and hasattr(msg, "content"):
                formatted_history.append(f"{msg.role.capitalize()}: {msg.content}")

    history_str = "\n".join(formatted_history[-8:]) if formatted_history else "No history"

    prompt = f"""You generate positive, business-friendly quick reply suggestions representing what the USER can reply to the chatbot.
The suggestions must be written strictly from the USER'S perspective (e.g., what the user wants to ask next, how the user answers the bot's question) and NEVER from the bot/assistant's perspective.

Company: {req.company_name}
Assistant: {req.assistant_name}
Business context: {req.business_context}

Recent conversation:
{history_str}

Latest user message:
{req.latest_user_message or ""}

Latest bot message:
{req.latest_bot_message}

Rules:
- Return JSON only.
- Return 0 to {req.max_suggestions} suggestions.
- All suggestions MUST be written from the USER'S perspective (e.g., "I want to discuss website development", "Can you show me your portfolio?"), NEVER from the assistant's perspective (e.g., do NOT suggest "How can I help you?").
- If the latest bot message asks a question with choices or options (e.g. asking for project type, budget range, timeline, features), the suggestions MUST be direct options answering that question from the user's side (e.g. "Website", "Mobile app", "CRM system" or "Under ₹50,000", "₹50,000 - ₹1 lakh" or "As soon as possible").
- Suggestions must be short messages the user can click and send directly.
- Suggestions must help the user continue the conversation positively.
- Suggestions must be useful for a software/service company.
- Do not generate fake names, emails, phone numbers, addresses, or private data.
- If the latest bot message is ONLY asking for name, email, phone, or contact details, return an empty list. However, if the bot message also lists options or services (even if it ends with a contact request), you should suggest those options or services with understanding the conversation and give the meaningful suggestions not useless suggestions.
- Do not include negative or refusal-style options.
- Do not include "skip", "I don't want to share", or "why do you need this".
- Match the user's language style: English, or Hinglish.
- Avoid repeating recently used messages.
- Do not change chatbot flow or mention internal state.

Return this exact JSON shape:
{{
  "suggestions": ["...", "..."]
}}
"""
    try:
        json_llm = llm_suggestions.bind(response_format={"type": "json_object"})
        result = json_llm.invoke([HumanMessage(content=prompt)]).content
        
        parsed = json.loads(result)
        raw_suggs = parsed.get("suggestions", [])
        if not isinstance(raw_suggs, list):
            return []
            
        return sanitize_suggestions(
            raw_suggs,
            req.latest_user_message,
            req.latest_bot_message,
            req.max_suggestions or 4
        )
    except Exception as e:
        print(f"[Widget Suggestions] Error in generation: {e}")
        return []
