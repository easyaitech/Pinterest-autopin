"""AI draft validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class DraftError(ValueError):
    pass


@dataclass(frozen=True)
class PinDraft:
    title: str
    description: str
    tags: tuple[str, ...]
    alt_text: str
    risk_notes: tuple[str, ...]
    confidence: str


def validate_draft(payload: Mapping[str, Any]) -> PinDraft:
    title = _required_str(payload, "title")
    description = _required_str(payload, "description")
    alt_text = _required_str(payload, "altText")
    tags = _required_list(payload, "tags")
    risk_notes = _required_list(payload, "riskNotes")
    confidence = str(payload.get("confidence", "medium"))
    if len(title) > 100:
        raise DraftError("title is too long")
    if confidence not in {"high", "medium", "low"}:
        raise DraftError("confidence must be high, medium, or low")
    return PinDraft(
        title=title,
        description=description,
        tags=tuple(tags),
        alt_text=alt_text,
        risk_notes=tuple(risk_notes),
        confidence=confidence,
    )


def combined_description(description: str, tags: list[str] | tuple[str, ...], *, limit: int = 500) -> str:
    tag_text = " ".join(tag.strip() for tag in tags if tag.strip())
    combined = description.strip()
    if tag_text:
        combined = f"{combined}\n\n{tag_text}"
    if len(combined) <= limit:
        return combined
    return description.strip()


def _required_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DraftError(f"{key} is required")
    return value.strip()


def _required_list(payload: Mapping[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise DraftError(f"{key} must be a non-empty list")
    cleaned = [str(item).strip() for item in value if str(item).strip()]
    if not cleaned:
        raise DraftError(f"{key} must contain text")
    return cleaned
