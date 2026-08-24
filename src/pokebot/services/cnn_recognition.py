"""Local CNN-based Pokémon card recognition - zero API dependencies.

Uses transfer learning with PyTorch MobileNetV2 for card classification.
Complete offline operation - no OpenAI, no API keys, no internet required after download.

Design:
- MobileNetV2 (pretrained on ImageNet) for feature extraction
- Custom classifier head for card categories
- Save/load model weights
- Batch prediction with confidence scores
- Integration-ready: returns structured dict compatible with PRD validation pipeline
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch
import torch.nn as nn
import torchvision.models as models
import torchvision.transforms as transforms
from PIL import Image


# ─── Configuration ───────────────────────────────────────────────────────

MODEL_NAME = "mobilenet_v2"
DEFAULT_WEIGHTS_PATH = Path("models") / "card_classifier.pt"
CARD_CATEGORIES_PATH = Path("models") / "card_categories.json"

# Input image size expected by MobileNetV2
IMG_SIZE = 224

# ─── Transform: normalize + resize as MobileNetV2 expects ──────────────────

_transform = transforms.Compose(
    [
        transforms.Resize((IMG_SIZE, IMG_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],  # ImageNet mean
            std=[0.229, 0.224, 0.225],   # ImageNet std
        ),
    ]
)


# ─── Model Definition ─────────────────────────────────────────────────────

class CardClassifier(nn.Module):
    """CNN classifier for Pokémon cards using MobileNetV2 feature extractor."""

    def __init__(self, num_classes: int, dropout: float = 0.5) -> None:
        super().__init__()

        # Use pretrained MobileNetV2 without the original classifier
        self.backbone = models.mobilenet_v2(weights=models.MobileNet_V2_Weights.IMAGENET1K_V1)
        # Freeze backbone weights for feature extraction (optional - uncomment to freeze)
        # for param in self.backbone.parameters():
        #     param.requires_grad = False

        # Get the number of input features to the original classifier
        last_channel = self.backbone.last_channel  # typically 1280 for mobilenet_v2

        # New classifier head
        self.classifier = nn.Sequential(
            nn.Dropout(p=dropout),
            nn.Linear(last_channel, 512),
            nn.ReLU(inplace=True),
            nn.Dropout(p=dropout),
            nn.Linear(512, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # MobileNetV2 features
        x = self.backbone.features(x)
        # Global average pooling (already included in features output shape)
        x = torch.mean(x, dim=[2, 3])  # adaptive avg pooling effectively
        x = self.classifier(x)
        return x


# ─── Model Manager ────────────────────────────────────────────────────────

class CardRecognitionModel:
    """Load, save, and run local CNN card classifier."""

    def __init__(
        self,
        model_path: Path = DEFAULT_WEIGHTS_PATH,
        categories_path: Path = CARD_CATEGORIES_PATH,
        num_classes: int = 10,  # default; will be updated from categories file
        device: str | None = None,
    ) -> None:
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        log.info("Using device: %s", self.device)

        self.model_path = model_path
        self.categories_path = categories_path
        self.num_classes = num_classes
        self.model: Optional[CardClassifier] = None
        self.class_names: List[str] = []
        self._load_classes()
        self._load_model()

    def _load_classes(self) -> None:
        """Load card category names from JSON file."""
        if self.categories_path.is_file():
            with open(self.categories_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.class_names = data.get("classes", [])
            self.num_classes = len(self.class_names)
            log.info("Loaded %d card classes from %s", self.num_classes, self.categories_path)
        else:
            log.warning(
                "Categories file not found at %s — using empty class list",
                self.categories_path,
            )
            self.class_names = []
            self.num_classes = 0

    def _load_model(self) -> None:
        """Load the CNN model weights if available."""
        if self.model_path.is_file():
            try:
                self.model = CardClassifier(num_classes=self.num_classes)
                checkpoint = torch.load(
                    self.model_path,
                    map_location=self.device,
                    weights_only=True,
                )
                # Handle both full state_dict and just the model dict
                if isinstance(checkpoint, dict) and "state_dict" in checkpoint:
                    state_dict = checkpoint["state_dict"]
                else:
                    state_dict = checkpoint

                self.model.load_state_dict(state_dict)
                self.model.to(self.device)
                self.model.eval()
                log.info("Model loaded from %s", self.model_path)
            except Exception as e:  # noqa: BLE001
                log.error("Failed to load model: %s", e)
                self.model = CardClassifier(num_classes=self.num_classes)
                self.model.to(self.device)
                self.model.eval()
                log.warning("Using randomly initialized model as fallback")
        else:
            log.warning("Model weights not found at %s — using randomly initialized model", self.model_path)
            self.model = CardClassifier(num_classes=self.num_classes)
            self.model.to(self.device)
            self.model.eval()

    def save_classes(self, classes: List[str], path: Path | None = None) -> None:
        """Save card category names to JSON file."""
        path = Path(path or self.categories_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"classes": classes}, f, ensure_ascii=False, indent=2)
        log.info("Saved %d classes to %s", len(classes), path)

    def predict(self, image: Image.Image) -> Dict[str, any]:
        """Run classification on a PIL Image.

        Returns dict with:
            - best_class: str or None
            - confidence: float (0-1) or None
            - top_k: list of (class_name, probability) tuples
            - success: bool
        """
        if self.model is None or not self.class_names:
            return {
                "best_class": None,
                "confidence": None,
                "top_k": [],
                "success": False,
                "error": "Model not loaded or no classes defined",
            }

        try:
            # Transform image
            tensor = _transform(image).unsqueeze(0).to(self.device)  # type: ignore

            # Predict
            with torch.no_grad():
                logits = self.model(tensor)
                probs = torch.softmax(logits, dim=1).squeeze().cpu()

            # Get top predictions
            top_k_vals, top_k_idx = torch.topk(probs, min(5, len(self.class_names)))

            top_k: List[Tuple[str, float]] = [
                (self.class_names[idx], float(val))
                for idx, val in zip(top_k_idx.tolist(), top_k_vals.tolist())
            ]

            best_class = top_k[0][0] if top_k else None
            best_confidence = top_k[0][1] if top_k else None

            return {
                "best_class": best_class,
                "confidence": best_confidence,
                "top_k": top_k,
                "success": True,
            }

        except Exception as e:  # noqa: BLE001
            log.error("Prediction failed: %s", e)
            return {
                "best_class": None,
                "confidence": None,
                "top_k": [],
                "success": False,
                "error": str(e),
            }


# ─── Logging ──────────────────────────────────────────────────────────────

import logging

log = logging.getLogger("card_cnn")


# ─── CLI Test ─────────────────────────────────────────────────────────────

def main() -> None:
    """CLI: predict card from image file."""
    import argparse

    parser = argparse.ArgumentParser(description="Local CNN Pokémon card recognition")
    parser.add_argument("image_path", type=str, help="Path to card image file")
    parser.add_argument(
        "--model", type=Path, default=DEFAULT_WEIGHTS_PATH, help="Model weights path"
    )
    parser.add_argument(
        "--categories", type=Path, default=CARD_CATEGORIES_PATH, help="Classes JSON path"
    )
    args = parser.parse_args()

    # Load model
    model = CardRecognitionModel(model_path=args.model, categories_path=args.categories)

    # Load image
    img_path = Path(args.image_path)
    if not img_path.is_file():
        log.error("Image file not found: %s", img_path)
        sys.exit(1)

    try:
        image = Image.open(img_path).convert("RGB")
    except Exception as e:  # noqa: BLE001
        log.error("Failed to open image: %s", e)
        sys.exit(1)

    # Predict
    result = model.predict(image)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result["success"] and result["best_class"]:
        print(f"\nTop prediction: {result['best_class']} ({result['confidence']:.1%} confidence)")
    else:
        print("\nNo reliable prediction — the model hasn't been trained on Pokémon cards yet.")
        print("This is expected for a fresh model. You need to:")
        print("  1. Collect card images with labels")
        print("  2. Train the model (or use a pre-trained Pokémon card classifier)")
        print("  3. Replace the model weights and categories JSON")


if __name__ == "__main__":
    # Minimal logging config for CLI
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()