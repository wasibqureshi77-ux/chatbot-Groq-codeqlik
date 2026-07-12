from __future__ import annotations

import json
import os
import re
from typing import Any

from rag.chunker import detect_risk_flags, extract_keywords_from_text

PROMPT = """You are a factual knowledge-base restructuring component.

Convert the SOURCE into one concise, self-contained RAG knowledge record.

Strict rules:
- Use only facts explicitly present in SOURCE.
- Do not add outside knowledge, assumptions, recommendations, names, numbers, dates, prices,
  certifications, partnerships, clients, outcomes, guarantees, or totals.
- Preserve every number, date, email, phone number, URL, and named product exactly.
- Selected examples are not a complete total.
- Remove sales filler and repeated calls to action, but preserve factual service capabilities.
- Return valid JSON only with this schema:
  {"title":"...","content":"...","sample_questions":["..."],"keywords":["..."]}

SOURCE TITLE:
{title}

SOURCE CONTENT:
{content}
"""

STOPWORDS = {
    "the", "and", "or", "to", "of", "in", "on", "for", "with", "a", "an", "is", "are",
    "we", "our", "you", "your", "this", "that", "from", "can", "company", "service", "services",
}


def _tokens(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9][a-z0-9+./_-]*", (text or "").lower())
        if token not in STOPWORDS and len(token) > 1
    }


def _facts(text: str) -> set[str]:
    patterns = [
        r"\b\d+(?:\.\d+)?%?\+?\b",
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        r"https?://[^\s)]+",
        r"(?:₹|\$|€|£)\s*\d[\d,]*(?:\.\d+)?",
        r"\+?\d[\d\s()-]{7,}\d",
    ]
    values: set[str] = set()
    for pattern in patterns:
        values.update(re.findall(pattern, text or "", flags=re.I))
    return {str(value).strip().lower() for value in values}


def _safe_json(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except Exception:
        match = re.search(r"\{.*\}", text or "", flags=re.DOTALL)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
        except Exception:
            return None


def _supported(source: str, output: str) -> bool:
    source_facts = _facts(source)
    output_facts = _facts(output)
    if not output_facts.issubset(source_facts):
        return False

    source_tokens = _tokens(source)
    output_tokens = _tokens(output)
    if not output_tokens:
        return False
    support_ratio = len(source_tokens & output_tokens) / max(1, len(output_tokens))
    return support_ratio >= float(os.getenv("RAG_REFINER_MIN_SUPPORT", "0.58"))


def _default_llm(prompt: str) -> str:
    from langchain_core.messages import HumanMessage
    from llm_client import FailoverChatGroq

    model = os.getenv("RAG_REFINER_MODEL", "llama-3.1-8b-instant")
    llm = FailoverChatGroq(model=model, temperature=0.0)
    response = llm.bind(response_format={"type": "json_object"}).invoke([HumanMessage(content=prompt)])
    return response.content


def refine_chunks(chunks: list[dict], llm_callable=None) -> list[dict]:
    """Safely rewrite chunks without changing their evidence metadata.

    Any invalid, unsupported, or failed LLM output falls back to the original chunk.
    """
    if os.getenv("RAG_LLM_REFINER", "false").lower() != "true":
        return chunks

    caller = llm_callable or _default_llm
    maximum = max(0, int(os.getenv("RAG_LLM_REFINER_MAX_CHUNKS", "100")))
    refined: list[dict] = []

    for index, original in enumerate(chunks):
        if index >= maximum:
            refined.append(original)
            continue
        source_content = str(original.get("content") or original.get("chunk_text") or "").strip()
        if len(source_content) < 80 or len(source_content) > 6000:
            refined.append(original)
            continue
        try:
            raw = caller(PROMPT.format(title=original.get("title", "Knowledge"), content=source_content))
            parsed = _safe_json(raw)
        except Exception:
            parsed = None
        if not parsed:
            refined.append(original)
            continue

        new_content = str(parsed.get("content") or "").strip()
        new_title = str(parsed.get("title") or original.get("title") or "Knowledge").strip()
        if not new_content or not _supported(source_content, new_content):
            refined.append(original)
            continue
        if set(detect_risk_flags(new_content)) - set(detect_risk_flags(source_content)):
            refined.append(original)
            continue

        copy = dict(original)
        copy["title"] = new_title[:180]
        copy["content"] = new_content
        copy["chunk_text"] = new_content
        provided_questions = [str(value).strip() for value in parsed.get("sample_questions", []) if str(value).strip()]
        provided_keywords = [str(value).strip() for value in parsed.get("keywords", []) if str(value).strip()]
        if provided_questions:
            copy["sample_questions"] = provided_questions[:4]
        if provided_keywords:
            copy["keywords"] = provided_keywords[:12]
        else:
            copy["keywords"] = extract_keywords_from_text(f"{new_title} {new_content}")
        copy["summary"] = new_content.split(".", 1)[0].strip() + ("." if "." in new_content else "")
        copy["chunk_summary"] = copy["summary"]
        copy["retrieval_text"] = (
            f"Title: {copy['title']}\nCategory: {copy.get('category', 'general')}\n"
            f"Topic: {copy.get('topic', 'general')}\nContent: {new_content}\n"
            f"Questions: {' | '.join(copy.get('sample_questions', []))}\n"
            f"Keywords: {', '.join(copy.get('keywords', []))}"
        )
        metadata = dict(copy.get("metadata") or {})
        metadata["llm_refined"] = True
        copy["metadata"] = metadata
        refined.append(copy)
    return refined
