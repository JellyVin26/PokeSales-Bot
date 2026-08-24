"""Card database validation via pokemontcg.io API (free, no key required)."""

import httpx

API_BASE = "https://api.pokemontcg.io/v2/cards"


async def search_card(name: str) -> list[dict] | None:
    """Search Pokémon TCG API for a card by name.

    Returns list of matches: [{official_name, set_name, set_id, card_number,
    rarity, image_url}], or None on network/API failure.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                API_BASE, params={"q": f'name:"{name}"', "pageSize": 5}
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
    except httpx.HTTPError:
        return None

    results = []
    for c in data.get("data", []):
        images = c.get("images", {}) or {}
        results.append(
            {
                "official_name": c.get("name"),
                "set_name": (c.get("set") or {}).get("name"),
                "set_id": (c.get("set") or {}).get("id"),
                "card_number": c.get("number"),
                "rarity": c.get("rarity"),
                "image_url": images.get("small"),
            }
        )
    return results


async def validate_detection(detected_name: str) -> dict | None:
    """Validate one AI-detected name against the card API.

    Returns best match with official fields + database_match flag,
    or None if the API is unreachable.
    """
    matches = await search_card(detected_name)
    if matches is None:
        return None  # API failure - caller decides (save as draft)
    if not matches:
        return {
            "official_name": detected_name,
            "set_name": None,
            "set_id": None,
            "card_number": None,
            "rarity": None,
            "image_url": None,
            "database_match": False,
        }
    best = matches[0]
    best["database_match"] = True
    return best