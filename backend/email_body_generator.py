import json
import re
import html as html_lib
from typing import Dict, Tuple, Any

from llm_client import FailoverChatGroq
from langchain_core.messages import HumanMessage


email_llm = FailoverChatGroq(
    model="llama-3.1-8b-instant",
    temperature=0.2
)


DEFAULT_COMPANY_NAME = "CodeQlik"


# -----------------------------
# Helpers
# -----------------------------

def _clean_value(value: Any, default: str = "") -> str:
    if value is None:
        return default
    value = str(value).strip()
    return value if value else default


def _limit(value: str, max_len: int) -> str:
    value = _clean_value(value)
    return value[:max_len].strip()


def _looks_like_email(value: str) -> bool:
    value = _clean_value(value)
    return bool(re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", value))


def _looks_like_phone(value: str) -> bool:
    value = _clean_value(value)
    digits = re.sub(r"\D", "", value)
    return len(digits) >= 8


def _extract_email_phone(profile: Dict[str, Any]) -> Tuple[str, str]:
    email = _clean_value(profile.get("email"))
    phone = _clean_value(profile.get("phone"))

    email_or_phone = _clean_value(profile.get("email_or_phone"))

    if not email and _looks_like_email(email_or_phone):
        email = email_or_phone

    if not phone and _looks_like_phone(email_or_phone) and not _looks_like_email(email_or_phone):
        phone = email_or_phone

    return email, phone


def _normalize_profile(profile: Dict[str, Any]) -> Dict[str, str]:
    profile = profile or {}

    email, phone = _extract_email_phone(profile)

    normalized = {
        "name": _clean_value(
            profile.get("name")
            or profile.get("customer_name")
            or profile.get("full_name")
            or "Visitor"
        ),
        "email": email,
        "phone": phone,
        "company": _clean_value(profile.get("company") or profile.get("company_name")),
        "project_type": _clean_value(profile.get("project_type") or profile.get("service") or profile.get("intent")),
        "requirements": _clean_value(profile.get("requirements") or profile.get("requirement") or profile.get("message")),
        "budget": _clean_value(profile.get("budget")),
        "timeline": _clean_value(profile.get("timeline")),
        "role": _clean_value(profile.get("role")),
        "experience": _clean_value(profile.get("experience")),
        "education": _clean_value(profile.get("education")),
        "issue_details": _clean_value(profile.get("issue_details")),
        "website_url": _clean_value(profile.get("website_url")),
    }

    # Keep extra useful fields, but avoid overwriting normalized clean fields with empty values.
    for key, value in profile.items():
        if key not in normalized and value not in [None, ""]:
            normalized[key] = _clean_value(value)

    return normalized


def _safe_json(data: Dict[str, Any]) -> str:
    return json.dumps(data or {}, indent=2, ensure_ascii=False)


def _escape(value: Any) -> str:
    return html_lib.escape(_clean_value(value, "N/A"))


def _profile_summary_text(profile: Dict[str, str]) -> str:
    lines = []

    fields = [
        ("Name", profile.get("name")),
        ("Email", profile.get("email")),
        ("Phone", profile.get("phone")),
        ("Company", profile.get("company")),
        ("Project Type", profile.get("project_type")),
        ("Requirements", profile.get("requirements")),
        ("Budget", profile.get("budget")),
        ("Timeline", profile.get("timeline")),
        ("Issue Details", profile.get("issue_details")),
        ("Website URL", profile.get("website_url")),
    ]

    for label, value in fields:
        value = _clean_value(value)
        if value:
            lines.append(f"{label}: {value}")

    return "\n".join(lines) if lines else "No profile details captured yet."


def _profile_summary_html(profile: Dict[str, str]) -> str:
    rows = []

    fields = [
        ("Name", profile.get("name")),
        ("Email", profile.get("email")),
        ("Phone", profile.get("phone")),
        ("Company", profile.get("company")),
        ("Project Type", profile.get("project_type")),
        ("Requirements", profile.get("requirements")),
        ("Budget", profile.get("budget")),
        ("Timeline", profile.get("timeline")),
        ("Issue Details", profile.get("issue_details")),
        ("Website URL", profile.get("website_url")),
    ]

    for label, value in fields:
        value = _clean_value(value)
        if value:
            rows.append(
                f"<tr>"
                f"<td style='padding:6px 10px;border:1px solid #ddd;'><strong>{_escape(label)}</strong></td>"
                f"<td style='padding:6px 10px;border:1px solid #ddd;'>{_escape(value)}</td>"
                f"</tr>"
            )

    if not rows:
        return "<p>No profile details captured yet.</p>"

    return (
        "<table style='border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:14px;'>"
        + "".join(rows)
        + "</table>"
    )


# -----------------------------
# Prompt
# -----------------------------

def _event_context(event_type: str) -> Dict[str, str]:
    if event_type == "new_chat_start":
        return {
            "audience": "admin",
            "purpose": "Notify company management that a new website visitor has started a chatbot conversation.",
            "tone": "short, clear, action-oriented",
            "must_include": "first visitor message, thread ID, and instruction to open admin panel",
            "must_avoid": "do not call it a completed lead; do not invent contact details",
        }

    if event_type == "lead_complete_admin":
        return {
            "audience": "admin",
            "purpose": "Notify company management that a new qualified lead has been captured by the chatbot.",
            "tone": "professional, concise, business-focused",
            "must_include": "lead name, contact, requirement, project type, budget, timeline if available",
            "must_avoid": "do not write a long marketing email; do not hide important lead details",
        }

    if event_type == "lead_complete_user":
        return {
            "audience": "user",
            "purpose": "Send a polite confirmation email to the visitor after their lead details were captured.",
            "tone": "friendly, reassuring, simple",
            "must_include": "thank the visitor, confirm the request was received, say the team will contact them shortly",
            "must_avoid": "do not include internal thread IDs, admin notes, raw JSON, or technical details",
        }

    if event_type.endswith("_complete_admin"):
        label = event_type.replace("_complete_admin", "").replace("_", " ").title()
        return {
            "audience": "admin",
            "purpose": f"Notify company management that a {label} workflow was completed in the chatbot.",
            "tone": "professional, concise, action-oriented",
            "must_include": "captured profile details and contact information if available",
            "must_avoid": "do not write unnecessary marketing text",
        }

    if event_type.endswith("_complete_user"):
        return {
            "audience": "user",
            "purpose": "Send a polite confirmation email to the visitor after their details were submitted.",
            "tone": "friendly, simple, reassuring",
            "must_include": "thank the visitor and mention the team will contact them shortly",
            "must_avoid": "do not include internal details, raw JSON, or thread ID",
        }

    return {
        "audience": "admin",
        "purpose": "Send a short chatbot notification email.",
        "tone": "clear and professional",
        "must_include": "important available details",
        "must_avoid": "do not invent missing information",
    }


def _build_prompt(
    event_type: str,
    thread_id: str,
    profile: Dict[str, str],
    user_message: str,
    company_name: str,
) -> str:
    context = _event_context(event_type)
    audience = context["audience"]

    public_profile = {
        "name": profile.get("name"),
        "email": profile.get("email"),
        "phone": profile.get("phone"),
        "company": profile.get("company"),
        "project_type": profile.get("project_type"),
        "requirements": profile.get("requirements"),
        "budget": profile.get("budget"),
        "timeline": profile.get("timeline"),
        "issue_details": profile.get("issue_details"),
        "website_url": profile.get("website_url"),
    }

    return f"""
You are an email writer for a company website chatbot.

Generate ONE email.

Return ONLY valid JSON.
No markdown.
No code fences.
No explanation.

JSON schema:
{{
  "subject": "short email subject",
  "text": "plain text email body",
  "html": "simple HTML email body"
}}

Company name:
{company_name}

Event type:
{event_type}

Audience:
{audience}

Purpose:
{context["purpose"]}

Tone:
{context["tone"]}

Must include:
{context["must_include"]}

Must avoid:
{context["must_avoid"]}

Thread ID:
{thread_id}

Latest visitor message:
{user_message or "N/A"}

Captured profile:
{_safe_json(public_profile)}

Writing rules:
- Keep the email short and useful.
- Do not invent missing values.
- If a value is missing, omit it instead of writing "unknown" many times.
- Subject must be under 90 characters.
- Text body should be plain text only.
- HTML body should use only simple tags: <p>, <strong>, <br/>, <ul>, <li>, <table>, <tr>, <td>.
- No script tags.
- No external images.
- No fake links.
- No placeholders like [Company Name].
- For user emails, do not mention admin panel or thread ID.
- For admin emails, make the next action clear.
""".strip()


# -----------------------------
# LLM Response Parsing
# -----------------------------

def _extract_json_object(text: str) -> str:
    text = _clean_value(text)

    if text.startswith("```json"):
        text = text.replace("```json", "", 1).strip()

    if text.startswith("```"):
        text = text.replace("```", "", 1).strip()

    if text.endswith("```"):
        text = text[:-3].strip()

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]

    return text


def _parse_llm_response(response_text: str) -> Dict[str, str]:
    cleaned = _extract_json_object(response_text)
    parsed = json.loads(cleaned)

    if not isinstance(parsed, dict):
        raise ValueError("LLM response is not a JSON object")

    subject = _limit(parsed.get("subject"), 120)
    text = _limit(parsed.get("text"), 4000)
    html = _limit(parsed.get("html"), 8000)

    if not subject:
        raise ValueError("Email subject missing")

    if not text and html:
        text = re.sub(r"<[^>]+>", "", html).strip()

    if not html and text:
        escaped_text = html_lib.escape(text).replace("\n", "<br/>")
        html = f"<p>{escaped_text}</p>"

    if not text:
        raise ValueError("Email body missing")

    if "<script" in html.lower():
        raise ValueError("Unsafe HTML generated")

    return {
        "subject": subject,
        "text": text,
        "html": html,
    }


# -----------------------------
# Fallback Emails
# -----------------------------

def _fallback_new_chat_start(
    thread_id: str,
    profile: Dict[str, str],
    user_message: str,
    company_name: str,
) -> Tuple[str, str, str]:
    subject = f"New website chat started - {company_name}"

    text = f"""
New visitor started a chat on your website.

Company: {company_name}
Thread ID: {thread_id}
First message: {user_message or "No message provided."}

Open the admin panel to view and monitor the conversation.
""".strip()

    html = f"""
<p><strong>New visitor started a chat on your website.</strong></p>
<p><strong>Company:</strong> {_escape(company_name)}</p>
<p><strong>Thread ID:</strong> {_escape(thread_id)}</p>
<p><strong>First message:</strong> {_escape(user_message or "No message provided.")}</p>
<p>Open the admin panel to view and monitor the conversation.</p>
""".strip()

    return subject, text, html


def _fallback_admin_complete(
    event_type: str,
    thread_id: str,
    profile: Dict[str, str],
    company_name: str,
) -> Tuple[str, str, str]:
    if event_type == "lead_complete_admin":
        subject = f"New lead captured - {company_name}"
        intro = "A new qualified lead has been captured from the chatbot."
    else:
        workflow_label = (
            event_type
            .replace("_complete_admin", "")
            .replace("_", " ")
            .title()
        )
        subject = f"{workflow_label} completed - {company_name}"
        intro = f"A new {workflow_label.lower()} workflow has been completed in the chatbot."

    profile_text = _profile_summary_text(profile)
    profile_html = _profile_summary_html(profile)

    text = f"""
{intro}

Company: {company_name}
Thread ID: {thread_id}

Details:
{profile_text}

Open the admin panel for the full conversation.
""".strip()

    html = f"""
<p><strong>{_escape(intro)}</strong></p>
<p><strong>Company:</strong> {_escape(company_name)}</p>
<p><strong>Thread ID:</strong> {_escape(thread_id)}</p>
<p><strong>Details:</strong></p>
{profile_html}
<p>Open the admin panel for the full conversation.</p>
""".strip()

    return subject, text, html


def _fallback_user_complete(
    profile: Dict[str, str],
    company_name: str,
) -> Tuple[str, str, str]:
    name = profile.get("name") or "there"
    requirement = profile.get("requirements") or profile.get("project_type")

    subject = f"Thanks for contacting {company_name}"

    text = f"""
Hi {name},

Thank you for contacting {company_name}. We have received your request.

Our team will review your details and contact you shortly.
""".strip()

    if requirement:
        text += f"\n\nYour request:\n{requirement}"

    text += f"\n\nBest regards,\n{company_name} Team"

    html = f"""
<p>Hi {_escape(name)},</p>
<p>Thank you for contacting <strong>{_escape(company_name)}</strong>. We have received your request.</p>
<p>Our team will review your details and contact you shortly.</p>
"""

    if requirement:
        html += f"<p><strong>Your request:</strong><br/>{_escape(requirement)}</p>"

    html += f"<p>Best regards,<br/>{_escape(company_name)} Team</p>"

    return subject, text, html.strip()


def _fallback_email(
    event_type: str,
    thread_id: str,
    profile: Dict[str, str],
    user_message: str,
    company_name: str,
) -> Tuple[str, str, str]:
    if event_type == "new_chat_start":
        return _fallback_new_chat_start(thread_id, profile, user_message, company_name)

    if event_type.endswith("_complete_user"):
        return _fallback_user_complete(profile, company_name)

    if event_type.endswith("_complete_admin") or event_type == "lead_complete_admin":
        return _fallback_admin_complete(event_type, thread_id, profile, company_name)

    subject = f"Chatbot notification - {company_name}"
    text = "This is an automated notification from your chatbot."
    html = "<p>This is an automated notification from your chatbot.</p>"
    return subject, text, html


# -----------------------------
# Main Function
# -----------------------------

def build_email_content(
    event_type: str,
    thread_id: str,
    profile: Dict[str, str] = None,
    user_message: str = "",
    company_name: str = DEFAULT_COMPANY_NAME,
) -> Tuple[str, str, str]:
    profile = _normalize_profile(profile or {})
    company_name = _clean_value(company_name, DEFAULT_COMPANY_NAME)

    prompt = _build_prompt(
        event_type=event_type,
        thread_id=thread_id,
        profile=profile,
        user_message=user_message,
        company_name=company_name,
    )

    try:
        result = email_llm.invoke([HumanMessage(content=prompt)])
        raw = getattr(result, "content", str(result)).strip()

        parsed = _parse_llm_response(raw)

        subject = parsed["subject"]
        text = parsed["text"]
        html = parsed["html"]

        return subject, text, html

    except Exception as e:
        print(f"[EmailGenerator] LLM fallback used for {event_type}: {e}")
        return _fallback_email(
            event_type=event_type,
            thread_id=thread_id,
            profile=profile,
            user_message=user_message,
            company_name=company_name,
        )