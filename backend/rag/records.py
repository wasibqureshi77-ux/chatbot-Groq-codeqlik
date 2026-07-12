from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

RECORD_START = "=== RAG_RECORD ==="
RECORD_END = "=== END_RAG_RECORD ==="


@dataclass
class RawRecord:
    title: str
    text: str
    source_type: str
    source_locator: dict[str, Any] = field(default_factory=dict)
    record_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def serialize_records(records: Iterable[RawRecord]) -> str:
    blocks: list[str] = []
    for record in records:
        payload = asdict(record)
        payload["title"] = _clean_text(payload.get("title")) or "Untitled record"
        payload["text"] = _clean_text(payload.get("text"))
        if not payload["text"]:
            continue
        blocks.append(
            f"{RECORD_START}\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            + f"\n{RECORD_END}"
        )
    return "\n\n".join(blocks)


def parse_records(content: str) -> list[RawRecord]:
    if not content or RECORD_START not in content:
        return []

    records: list[RawRecord] = []
    for segment in content.split(RECORD_START)[1:]:
        if RECORD_END not in segment:
            continue
        raw_payload = segment.split(RECORD_END, 1)[0].strip()
        try:
            payload = json.loads(raw_payload)
        except Exception:
            continue
        text = _clean_text(payload.get("text"))
        if not text:
            continue
        records.append(
            RawRecord(
                title=_clean_text(payload.get("title")) or "Untitled record",
                text=text,
                source_type=_clean_text(payload.get("source_type")) or "text",
                source_locator=dict(payload.get("source_locator") or {}),
                record_id=(
                    _clean_text(payload.get("record_id"))
                    if payload.get("record_id") is not None
                    else None
                ),
                metadata=dict(payload.get("metadata") or {}),
            )
        )
    return records
