"""Pinterest draft generation focused on Etsy conversion."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class DraftQualityError(ValueError):
    pass


@dataclass(frozen=True)
class ImageSignals:
    width: int = 0
    height: int = 0
    orientation: str = ""
    filename_terms: tuple[str, ...] = ()
    product_terms: tuple[str, ...] = ()
    style_terms: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PinDraft:
    title: str
    description: str
    tags: str
    alt_text: str
    search_intent: str
    quality_score: int
    quality_notes: tuple[str, ...]
    image_signals: ImageSignals


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "product",
    "the",
    "this",
    "to",
    "with",
    "your",
}

PRODUCT_ALIASES = {
    "mug": {"mug", "cup", "tumbler"},
    "print": {"print", "poster", "wall", "art", "illustration"},
    "shirt": {"shirt", "tee", "tshirt", "sweatshirt"},
    "jewelry": {"necklace", "ring", "bracelet", "earrings", "jewelry"},
    "candle": {"candle"},
    "sticker": {"sticker", "decal"},
    "planner": {"planner", "template", "calendar", "journal"},
    "invitation": {"invitation", "invite", "wedding", "bridal"},
    "ornament": {"ornament", "christmas"},
    "bag": {"bag", "tote", "pouch"},
    "pillow": {"pillow", "cushion", "cover"},
    "lamp": {"lamp", "light"},
    "shelf": {"shelf", "rack"},
    "jar": {"jar", "storage"},
}

PRODUCT_LABELS = {
    "mug": "Mug",
    "print": "Wall Art Print",
    "shirt": "Shirt",
    "jewelry": "Jewelry",
    "candle": "Candle",
    "sticker": "Sticker",
    "planner": "Planner",
    "invitation": "Invitation",
    "ornament": "Ornament",
    "bag": "Tote Bag",
    "pillow": "Pillow Cover",
    "lamp": "Table Lamp",
    "shelf": "Floating Shelf",
    "jar": "Storage Jar",
}

STYLE_TERMS = {
    "boho",
    "cozy",
    "custom",
    "farmhouse",
    "floral",
    "funny",
    "handmade",
    "minimal",
    "minimalist",
    "modern",
    "personalized",
    "rustic",
    "vintage",
}

MATERIAL_TERMS = {
    "ceramic",
    "cotton",
    "glass",
    "gold",
    "leather",
    "linen",
    "oak",
    "silver",
    "wood",
    "wooden",
}

AUDIENCE_HINTS = {
    "cat": "Cat Lovers",
    "dog": "Dog Lovers",
    "coffee": "Coffee Lovers",
    "teacher": "Teachers",
    "mom": "Mom",
    "dad": "Dad",
    "bride": "Brides",
    "baby": "New Parents",
    "book": "Book Lovers",
    "plant": "Plant Lovers",
}

OCCASION_TERMS = {
    "anniversary",
    "birthday",
    "bridal",
    "christmas",
    "graduation",
    "holiday",
    "mother",
    "teacher",
    "wedding",
}


def generate_pin_draft(fields: Mapping[str, Any], image_path: str | Path) -> PinDraft:
    product_name = _clean_text(
        fields.get("draft_title")
        or fields.get("product_name")
        or fields.get("title")
        or fields.get("source_title")
        or ""
    )
    description_source = _clean_text(
        fields.get("product_description")
        or fields.get("source_description")
        or fields.get("draft_description")
        or fields.get("notes")
        or ""
    )
    brand = _clean_text(fields.get("brand_name") or "")
    explicit_keywords = _keywords(fields.get("keywords") or fields.get("tags") or fields.get("draft_tags") or "")
    notes = _clean_text(fields.get("notes") or "")
    image = analyze_image(image_path)
    text_terms = _terms(" ".join([product_name, description_source, brand, notes, " ".join(explicit_keywords)]))
    all_terms = _unique([*text_terms, *image.filename_terms, *image.product_terms, *image.style_terms])
    product_key = _product_key(all_terms)
    product_label = _product_label(product_name, product_key)
    audience = _audience(all_terms, product_key)
    intent = _search_intent(all_terms, product_key)
    title = _title(product_name, brand, product_label, all_terms, intent, audience)
    description = _description(product_label, description_source, all_terms, intent, audience, image)
    tags = _tags(product_label, all_terms, intent, audience)
    alt_text = _alt_text(product_label, title, all_terms, image)
    score, quality_notes = quality_gate(
        {
            "title": title,
            "description": description,
            "tags": tags,
            "alt_text": alt_text,
        },
        product_terms={*text_terms, product_key},
    )
    if score < 80:
        raise DraftQualityError("draft quality gate failed: " + "; ".join(quality_notes))
    return PinDraft(
        title=title,
        description=description,
        tags=tags,
        alt_text=alt_text,
        search_intent=intent,
        quality_score=score,
        quality_notes=quality_notes,
        image_signals=image,
    )


def analyze_image(image_path: str | Path) -> ImageSignals:
    path = Path(image_path)
    filename_terms = _terms(path.stem)
    width, height = _image_dimensions(path)
    orientation = ""
    notes: list[str] = []
    if width and height:
        if height > width:
            orientation = "portrait"
        elif width > height:
            orientation = "landscape"
        else:
            orientation = "square"
        ratio = height / width if width else 0
        if ratio and not 1.35 <= ratio <= 1.7:
            notes.append("image is not close to Pinterest 2:3 ratio")
    else:
        notes.append("image dimensions unavailable")
    product_terms = tuple(term for term in filename_terms if _product_key([term]) != "find")
    style_terms = tuple(term for term in filename_terms if term in STYLE_TERMS or term in MATERIAL_TERMS)
    return ImageSignals(
        width=width,
        height=height,
        orientation=orientation,
        filename_terms=filename_terms,
        product_terms=_unique(product_terms),
        style_terms=_unique(style_terms),
        notes=tuple(notes),
    )


def quality_gate(draft: Mapping[str, str], *, product_terms: set[str]) -> tuple[int, tuple[str, ...]]:
    title = draft.get("title", "").strip()
    description = draft.get("description", "").strip()
    tags = _split_tags(draft.get("tags", ""))
    alt_text = draft.get("alt_text", "").strip()
    score = 100
    notes: list[str] = []

    if not 28 <= len(title) <= 95:
        score -= 15
        notes.append("title should be 28-95 characters")
    if not _has_any(_terms(title), product_terms):
        score -= 20
        notes.append("title must include a product/search term")
    if not 90 <= len(description) <= 500:
        score -= 15
        notes.append("description should be 90-500 characters")
    if "etsy" not in description.lower():
        score -= 15
        notes.append("description must include an Etsy click cue")
    if len(tags) < 4:
        score -= 12
        notes.append("at least 4 tags are required")
    if not any(tag.lower() == "#etsyfinds" for tag in tags):
        score -= 8
        notes.append("#EtsyFinds is required")
    if not alt_text:
        score -= 10
        notes.append("alt text is required")
    return max(score, 0), tuple(notes or ("quality gate passed",))


def _title(
    product_name: str,
    brand: str,
    product_label: str,
    terms: tuple[str, ...],
    intent: str,
    audience: str,
) -> str:
    source_label = _title_case(product_name) if product_name else product_label
    if brand and brand.lower() not in source_label.lower():
        source_label = f"{_title_case(brand)} {source_label}"
    descriptor = _first([term for term in terms if term in STYLE_TERMS or term in MATERIAL_TERMS])
    if descriptor and descriptor not in source_label.lower():
        source_label = f"{_title_case(descriptor)} {source_label}"
    if intent == "personalized_gift":
        title = f"Personalized {product_label} Gift for {audience}"
    elif intent == "occasion_gift":
        occasion = _first([term for term in terms if term in OCCASION_TERMS]) or "Holiday"
        title = f"{source_label} for {_title_case(occasion)} Gift Ideas"
    elif intent == "home_decor":
        title = f"{source_label} for Cozy Home Decor"
    elif intent == "printable":
        title = f"{source_label} for Easy Etsy Download"
    else:
        title = f"{source_label} Gift for {audience}"
    return _trim_title(title)


def _description(
    product_label: str,
    source_description: str,
    terms: tuple[str, ...],
    intent: str,
    audience: str,
    image: ImageSignals,
) -> str:
    scenario = _scenario(intent, audience, terms)
    fact = _sentence(source_description) or f"A {product_label.lower()} made for everyday gifting and Etsy shoppers."
    visual = _visual_phrase(image, terms)
    first = f"{scenario} {visual}".strip()
    second = fact
    cta = "Tap through to the Etsy listing to see options, details, and availability."
    return _limit_text(" ".join([first, second, cta]), 500)


def _tags(product_label: str, terms: tuple[str, ...], intent: str, audience: str) -> str:
    candidates = [
        product_label,
        f"{audience} Gift",
        "Etsy Finds",
    ]
    if intent == "home_decor":
        candidates.append("Home Decor")
    if intent in {"personalized_gift", "occasion_gift"}:
        candidates.append("Gift Ideas")
    candidates.extend(_title_case(term) for term in terms if term in STYLE_TERMS or term in MATERIAL_TERMS)
    candidates.extend(_title_case(term) for term in terms if term in OCCASION_TERMS)
    tags = []
    for candidate in candidates:
        tag = "#" + re.sub(r"[^A-Za-z0-9]", "", _title_case(candidate))
        if len(tag) > 2 and tag not in tags:
            tags.append(tag)
        if len(tags) >= 7:
            break
    if "#EtsyFinds" not in tags:
        tags.insert(min(2, len(tags)), "#EtsyFinds")
    return " ".join(tags[:7])


def _alt_text(product_label: str, title: str, terms: tuple[str, ...], image: ImageSignals) -> str:
    style = _first([term for term in terms if term in STYLE_TERMS or term in MATERIAL_TERMS])
    detail = f"{style} " if style else ""
    orientation = f" in a {image.orientation} product photo" if image.orientation else " in a product photo"
    return _limit_text(f"{detail}{product_label} shown{orientation} for {title}", 180)


def _search_intent(terms: tuple[str, ...], product_key: str) -> str:
    if {"personalized", "custom", "monogram", "name"} & set(terms):
        return "personalized_gift"
    if OCCASION_TERMS & set(terms):
        return "occasion_gift"
    if product_key in {"print", "pillow", "lamp", "shelf", "jar", "candle"} or "decor" in terms:
        return "home_decor"
    if {"download", "printable", "template", "planner"} & set(terms):
        return "printable"
    return "gift"


def _scenario(intent: str, audience: str, terms: tuple[str, ...]) -> str:
    if intent == "home_decor":
        return "A save-worthy home decor idea for cozy rooms, shelves, and personal spaces."
    if intent == "printable":
        return "A practical Etsy download idea for planning, gifting, or quick creative projects."
    occasion = _first([term for term in terms if term in OCCASION_TERMS])
    if occasion:
        return f"A thoughtful {_title_case(occasion)} gift idea for {audience}."
    return f"A thoughtful gift idea for {audience}."


def _visual_phrase(image: ImageSignals, terms: tuple[str, ...]) -> str:
    visible = [term for term in [*image.product_terms, *image.style_terms] if term in terms]
    if visible:
        return "The image highlights " + ", ".join(_title_case(term).lower() for term in visible[:3]) + "."
    if image.orientation:
        return f"The {image.orientation} image keeps the product easy to understand on mobile."
    return ""


def _product_key(terms: tuple[str, ...] | list[str]) -> str:
    term_set = set(terms)
    for key, aliases in PRODUCT_ALIASES.items():
        if aliases & term_set:
            return key
    return "find"


def _product_label(product_name: str, product_key: str) -> str:
    if product_key != "find":
        return PRODUCT_LABELS[product_key]
    words = _terms(product_name)
    useful = [word for word in words if word not in STYLE_TERMS and word not in MATERIAL_TERMS]
    if useful:
        return _title_case(" ".join(useful[-2:]))
    return "Etsy Find"


def _audience(terms: tuple[str, ...], product_key: str) -> str:
    for term, label in AUDIENCE_HINTS.items():
        if term in terms:
            return label
    if product_key == "mug":
        return "Coffee Lovers"
    if product_key in {"print", "pillow", "lamp", "shelf", "jar", "candle"}:
        return "Home Decor Fans"
    if product_key == "jewelry":
        return "Jewelry Lovers"
    return "Etsy Shoppers"


def _keywords(value: Any) -> tuple[str, ...]:
    if isinstance(value, list):
        raw = " ".join(str(item) for item in value)
    else:
        raw = str(value or "")
    return _unique(_terms(raw))


def _terms(value: str) -> tuple[str, ...]:
    split = re.findall(r"[a-z0-9]+", str(value or "").lower())
    return _unique(word for word in split if word and word not in STOPWORDS)


def _split_tags(value: str) -> tuple[str, ...]:
    return tuple(part for part in str(value or "").split() if part.startswith("#"))


def _has_any(terms: tuple[str, ...], candidates: set[str]) -> bool:
    return bool(set(terms) & {candidate for candidate in candidates if candidate})


def _unique(values) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip().lower()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return tuple(result)


def _first(values) -> str:
    for value in values:
        text = str(value).strip()
        if text:
            return text
    return ""


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _sentence(value: str) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if text[-1] not in ".!?":
        text += "."
    return text


def _title_case(value: str) -> str:
    return " ".join(part.capitalize() for part in re.findall(r"[A-Za-z0-9]+", str(value)))


def _trim_title(value: str) -> str:
    clean = _clean_text(value)
    if len(clean) <= 95:
        return clean
    return clean[:95].rsplit(" ", 1)[0].strip()


def _limit_text(value: str, limit: int) -> str:
    clean = _clean_text(value)
    if len(clean) <= limit:
        return clean
    return clean[:limit].rsplit(" ", 1)[0].strip()


def _image_dimensions(path: Path) -> tuple[int, int]:
    try:
        data = path.read_bytes()
    except OSError:
        return 0, 0
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return struct.unpack(">II", data[16:24])
    if len(data) >= 10 and data[:6] in {b"GIF87a", b"GIF89a"}:
        return struct.unpack("<HH", data[6:10])
    if data.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(data)
    return 0, 0


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            break
        length = struct.unpack(">H", data[index : index + 2])[0]
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if index + 7 <= len(data):
                height = struct.unpack(">H", data[index + 3 : index + 5])[0]
                width = struct.unpack(">H", data[index + 5 : index + 7])[0]
                return width, height
        index += max(length, 2)
    return 0, 0
