"""CNN-based Pokémon card recognition - fallback when no OpenAI key.

Integrates with the bot's sale flow. Uses transfer learning MobileNetV2.
Currently provides feature extraction + categorization capability.
For production use, train on a Pokémon card dataset or use a pre-trained model.

NOTE: This module provides the CNN infrastructure. Without trained weights on
Pokémon cards, it will report "model not trained" — but the framework is ready
for when you obtain/ train a card classifier.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.pokebot.services.cnn_recognition import CardRecognitionModel, log

# ─── Paths ────────────────────────────────────────────────────────────────

# ponytail: paths derived from file location; PROJECT_ROOT = /c/Users/PC/pokebot
# cnn_integration.py is at pokebot/src/pokebot/services/, so root is 3 levels up
PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = PROJECT_ROOT / "models"
CATEGORIES_PATH = MODEL_DIR / "card_categories.json"
MODEL_PATH = MODEL_DIR / "card_classifier.pt"

# Ensure model directory exists
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# ─── Default categories (placeholder) ────────────────────────────────────

# This list should be replaced with actual Pokémon card names from your dataset
DEFAULT_CATEGORIES = [
    "Charizard",
    "Blastoise",
    "Venusaur",
    "Pikachu",
    "Dragonite",
    "Mewtwo",
    "Eevee",
    "Squirtle",
    "Charmander",
    "Bulbasaur",
]

# Save default categories if none exist
if not CATEGORIES_PATH.is_file():
    with open(CATEGORIES_PATH, "w", encoding="utf-8") as f:
        json.dump({"classes": DEFAULT_CATEGORIES}, f, ensure_ascii=False, indent=2)
    log.info("Created default categories at %s", CATEGORIES_PATH)

# ─── Initialize Model ─────────────────────────────────────────────────────

# Ponytail: model will use random weights initially (no trained Pokémon card weights)
# This is expected — the CNN framework is ready, weights need to be trained/obtained
_cnn_model = None


def get_cnn_model() -> CardRecognitionModel:
    """Get or initialize the CNN card recognition model."""
    global _cnn_model
    if _cnn_model is None:
        _cnn_model = CardRecognitionModel(
            model_path=MODEL_PATH,
            categories_path=CATEGORIES_PATH,
            num_classes=len(DEFAULT_CATEGORIES),
        )
    return _cnn_model


# ─── Public API ───────────────────────────────────────────────────────────

def recognize_cards_from_image(image_path: str) -> Dict[str, any]:
    """Recognize Pokémon cards from an image file using local CNN.

    Args:
        image_path: Path to the card image file

    Returns:
        Dict with recognition results compatible with PRD validation pipeline.
        Keys: best_class, confidence, top_k, success, error
    """
    model = get_cnn_model()
    img_path = Path(image_path)

    if not img_path.is_file():
        return {
            "best_class": None,
            "confidence": None,
            "top_k": [],
            "success": False,
            "error": f"Image file not found: {image_path}",
        }

    try:
        image = Image.open(img_path).convert("RGB")
    except Exception as e:  # noqa: BLE001
        return {
            "best_class": None,
            "confidence": None,
            "top_k": [],
            "success": False,
            "error": f"Failed to open image: {e}",
        }

    result = model.predict(image)

    # Augment result with PRD-compatible structure
    if result["success"] and result["best_class"]:
        # Map the predicted class to known card names if possible
        predicted = result["best_class"]
        # Check if prediction matches any known category (case-insensitive substring)
        matched = None
        for cat in DEFAULT_CATEGORIES:
            if predicted.lower() in cat.lower() or cat.lower() in predicted.lower():
                matched = cat
                break

        return {
            "card_name": matched or predicted,
            "confidence": result["confidence"],
            "set_name": "Unknown",
            "card_number": "Unknown",
            "rarity": "Unknown",
            "database_match": False,  # CNN doesn't validate against TCG DB
            "cnn_model_used": True,
            "cnn_confidence": result["confidence"],
        }
    else:
        return {
            "card_name": None,
            "confidence": None,
            "set_name": "Unknown",
            "card_number": "Unknown",
            "rarity": "Unknown",
            "database_match": False,
            "cnn_model_used": False,
            "error": result.get("error", "Recognition failed"),
        }


def recognize_image_file(image_path: str) -> Dict[str, any]:
    """High-level wrapper: recognize cards from image file.

    Returns dict that can be directly used by the PRD validation pipeline.
    """
    return recognize_cards_from_image(image_path)


# ─── CLI Test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="CNN Pokémon card recognition (bot fallback)"
    )
    parser.add_argument("image", type=str, help="Path to card image")
    parser.add_argument(
        "--list-categories", action="store_true", help="List known card categories"
    )
    args = parser.parse_args()

    if args.list_categories:
        print("Known card categories:")
        for cat in DEFAULT_CATEGORIES:
            print(f"  - {cat}")
        sys.exit(0)

    result = recognize_image_file(args.image)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("card_name"):
        print(f"\nPredicted: {result['card_name']}")
        print(f"Confidence: {result.get('confidence', 0):.1%}")
    else:
        print("\nNo prediction available.")
        print("This CNN model needs trained weights on Pokémon card images.")
        print("To train: collect 500+ card images labeled with card names,")
        print("then run the training script or obtain a pretrained model.")