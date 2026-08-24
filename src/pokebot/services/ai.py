"""AI service for Pokémon card recognition using vision models."""

import base64
import json

from openai import AsyncOpenAI

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


async def recognize_cards(
    client: AsyncOpenAI,
    image_data: bytes,
    mime_type: str = "image/jpeg",
    model: str = "gpt-4o-mini",
) -> RecognitionResult:
    """Run vision recognition on one photo. Raises on API failure."""
    b64 = base64.b64encode(image_data).decode()
    resp = await client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": SCHEMA_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Identify all Pokemon cards."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                    },
                ],
            },
        ],
    )
    content = resp.choices[0].message.content or ""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError("Vision model returned non-JSON output")
        data = json.loads(content[start:end])

    cards = [c for c in data.get("cards", []) if _validate_card(c)]
    quality = data.get("image_quality") or {"score": 0.0, "usable": False}
    return RecognitionResult(cards=cards, image_quality=quality)