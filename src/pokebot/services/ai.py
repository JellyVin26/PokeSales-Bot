"""AI service for Pokemon card recognition with OpenAI + Gemini + manual fallback."""

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
    """Extract JSON from model response, handling markdown code blocks."""
    import re
    cleaned = re.sub(r"```(?:json)?\s*", "", content).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError("Model returned non-JSON output")
        data = json.loads(cleaned[start:end])
    if isinstance(data, str):
        data = json.loads(data)
    return data


def _to_result(data) -> RecognitionResult:
    if isinstance(data, str):
        data = _parse_response(data)
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
    return _to_result(_parse_response(resp.choices[0].message.content or ""))


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
    return _to_result(_parse_response(resp.text or ""))


# ---- Local perceptual hash fallback ----

_hash_db: dict[str, str] = {}  # card_id -> card_name
_hashes_loaded = False

async def _load_hash_db():
    """Fetch card images from Pokemon TCG API and compute perceptual hashes."""
    global _hash_db, _hashes_loaded
    if _hashes_loaded:
        return
    try:
        import imagehash
        from PIL import Image
        from io import BytesIO
        import httpx

        page = 1
        total = 9999
        async with httpx.AsyncClient(timeout=15) as client:
            while (page - 1) * 250 < total and page <= 20:  # max ~5000 cards
                try:
                    resp = await client.get(
                        "https://api.pokemontcg.io/v2/cards",
                        params={"pageSize": 250, "page": page},
                    )
                    data = resp.json()
                    total = data.get("totalCount", 0)
                    for card in data.get("data", []):
                        name = card.get("name", "")
                        img_url = card.get("images", {}).get("small", "")
                        if not img_url or not name:
                            continue
                        try:
                            img_resp = await client.get(img_url, follow_redirects=True)
                            img = Image.open(BytesIO(img_resp.content)).convert("RGB").resize((128, 128))
                            h = imagehash.phash(img)
                            _hash_db[str(h)] = name
                        except Exception:
                            pass
                except Exception as e:
                    log.warning("Hash DB page %d failed: %s", page, e)
                    break
                page += 1
        _hashes_loaded = True
        log.info("Loaded %d card hashes", len(_hash_db))
    except ImportError as e:
        log.warning("imagehash not installed: %s", e)
        _hashes_loaded = True
    except Exception as e:
        log.warning("Failed to load hash DB: %s", e)
        _hashes_loaded = True


async def _try_local_hash(image_data: bytes, mime_type: str) -> RecognitionResult:
    """Match photo against precomputed card hashes."""
    await _load_hash_db()
    if not _hash_db:
        raise ValueError("No card hashes loaded")
    import imagehash
    from PIL import Image
    from io import BytesIO

    img = Image.open(BytesIO(image_data)).convert("RGB").resize((128, 128))
    query_hash = imagehash.phash(img)

    # Find closest matches
    matches = []
    for stored_hash_str, name in _hash_db.items():
        stored_hash = imagehash.hex_to_hash(stored_hash_str)
        distance = query_hash - stored_hash
        if distance < 20:  # threshold
            confidence = max(0, 1 - distance / 20)
            matches.append({"name": name, "confidence": round(confidence, 2)})

    if not matches:
        raise ValueError("No matching cards found")

    # Deduplicate by name, keep best confidence
    seen = {}
    for m in matches:
        if m["name"] not in seen or m["confidence"] > seen[m["name"]]["confidence"]:
            seen[m["name"]] = m
    cards = sorted(seen.values(), key=lambda x: -x["confidence"])[:10]
    for c in cards:
        c["quantity"] = 1

    return RecognitionResult(
        cards=cards,
        image_quality={"score": 0.5, "usable": True},
    )


# ---- Main entry: try all providers in order ----

async def recognize_cards(
    image_data: bytes,
    mime_type: str = "image/jpeg",
) -> RecognitionResult:
    """Try OpenAI -> Gemini -> local hash. Raises if all fail."""
    errors = []
    for name, fn in [("OpenAI", _try_openai), ("Gemini", _try_gemini), ("Local", _try_local_hash)]:
        try:
            result = await fn(image_data, mime_type)
            log.info("Card recognition via %s: %d cards found", name, len(result.cards))
            return result
        except Exception as e:
            log.warning("%s failed: %s", name, e)
            errors.append(f"{name}: {e}")
    raise RuntimeError("All recognition methods failed: " + "; ".join(errors))
