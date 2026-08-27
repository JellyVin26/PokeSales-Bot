"""AI service for Pokemon card recognition with OpenAI + Gemini fallback."""

import base64
import json
import logging
import os

log = logging.getLogger(__name__)

SCHEMA_PROMPT = (
    "You are a Pokemon TCG card identifier. Look at the image and list every "
    "Pokemon card visible. Return ONLY JSON, no prose, matching exactly:\n"
    '{"cards": [{"name": str, "quantity": int, "confidence": float (0-1), '
    '"set": str|null, "card_number": str|null}], '
    '"image_quality": {"score": float (0-1), "usable": bool}}\n'
    "Rules: name is the card name as printed (e.g. \"Dusknoir\", "
    "\"Dragapult ex\"). confidence reflects how sure you are the card name is "
    "correct. If no cards visible or image unreadable, return empty cards list "
    "and usable=false."
)


class RecognitionResult:
    def __init__(self, cards: list[dict], image_quality: dict):
        self.cards = cards
        self.image_quality = image_quality


def _validate_card(c: dict) -> bool:
    return (
        isinstance(c, dict)
        and isinstance(c.get("name"), str)
        and bool(c["name"].strip())
        and isinstance(c.get("quantity", 1), int)
        and 0 <= float(c.get("confidence", 0)) <= 1
    )


def _parse_response(content: str) -> dict:
    """Extract JSON from model response."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError("Model returned non-JSON output")
        return json.loads(content[start:end])


def _to_result(data: dict) -> RecognitionResult:
    cards = [c for c in data.get("cards", []) if _validate_card(c)]
    quality = data.get("image_quality") or {"score": 0.0, "usable": False}
    return RecognitionResult(cards=cards, image_quality=quality)


# ---- OpenAI ----

async def _try_openai(image_data: bytes, mime_type: str) -> RecognitionResult:
    from openai import AsyncOpenAI
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("No OPENAI_API_KEY")
    client = AsyncOpenAI(api_key=api_key)
    b64 = base64.b64encode(image_data).decode()
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[
            {"role": "system", "content": SCHEMA_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Identify all Pokemon cards."},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                ],
            },
        ],
    )
    return _to_result(resp.choices[0].message.content or "")


# ---- Gemini ----

async def _try_gemini(image_data: bytes, mime_type: str) -> RecognitionResult:
    import google.generativeai as genai
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("No GEMINI_API_KEY")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    resp = await model.generate_content_async(
        [
            SCHEMA_PROMPT,
            {"mime_type": mime_type, "data": image_data},
        ],
        generation_config=genai.GenerationConfig(temperature=0),
    )
    return _to_result(resp.text or "")


# ---- Main entry: try OpenAI, fallback to Gemini ----

async def recognize_cards(
    image_data: bytes,
    mime_type: str = "image/jpeg",
) -> RecognitionResult:
    """Try OpenAI first, fallback to Gemini. Raises if both fail."""
    errors = []
    for name, fn in [("OpenAI", _try_openai), ("Gemini", _try_gemini)]:
        try:
            result = await fn(image_data, mime_type)
            log.info("Card recognition via %s: %d cards found", name, len(result.cards))
            return result
        except Exception as e:
            log.warning("%s failed: %s", name, e)
            errors.append(f"{name}: {e}")
    raise RuntimeError("All AI providers failed: " + "; ".join(errors))
