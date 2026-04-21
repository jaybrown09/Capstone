"""
ocr.py
------
Tesseract OCR pipeline for SmartBinder card scanning.
Handles image preprocessing, OCR extraction, and Scryfall fuzzy resolution.
"""

from __future__ import annotations

import re
import requests
from typing import Optional
from PIL import Image, ImageFilter, ImageEnhance
import pytesseract

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ── Image Preprocessing ───────────────────────────────────────────────────────

def preprocess_image(image: Image.Image) -> Image.Image:
    """
    Prepare a raw card photo for OCR.
    Steps: crop name strip → grayscale → contrast boost → sharpen.
    """
    w, h = image.size

    # Crop to the top ~14% of the card where the name bar lives.
    # MTG cards follow a consistent layout so this is reliable.
    name_strip = image.crop((
        int(w * 0.05),   # left  — skip border
        int(h * 0.03),   # top   — skip border
        int(w * 0.75),   # right — stop before mana cost symbols (top-right)
        int(h * 0.14),   # bottom
    ))

    # Scale up — Tesseract performs significantly better on larger images
    scale = 3
    name_strip = name_strip.resize(
        (name_strip.width * scale, name_strip.height * scale),
        Image.LANCZOS,
    )

    # Grayscale
    name_strip = name_strip.convert("L")

    # Boost contrast so the text pops against the card's textured background
    name_strip = ImageEnhance.Contrast(name_strip).enhance(2.5)

    # Sharpen edges
    name_strip = name_strip.filter(ImageFilter.SHARPEN)

    return name_strip


# ── OCR Extraction ────────────────────────────────────────────────────────────

def extract_card_name(image: Image.Image) -> tuple[str, Optional[str]]:
    """
    Run Tesseract on a raw card image.
    Returns (extracted_name, error_message).
    """
    try:
        processed = preprocess_image(image)

        # psm 7 = treat image as a single text line (the name bar)
        # Whitelist: characters that appear in real MTG card names
        config = (
            r'--psm 7 --oem 3 '
            r'-c tessedit_char_whitelist='
            r'"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz ,\'-"'
        )
        raw = pytesseract.image_to_string(processed, config=config)

        cleaned = _clean_ocr_output(raw)
        if not cleaned:
            return "", "OCR returned no readable text. Try better lighting or a flatter angle."

        return cleaned, None

    except pytesseract.TesseractNotFoundError:
        return "", (
            "Tesseract is not installed or not on PATH. "
            "Install it with: sudo apt install tesseract-ocr  (Linux) "
            "or brew install tesseract  (macOS). "
            "On Streamlit Cloud, add 'tesseract-ocr' to packages.txt."
        )
    except Exception as e:
        return "", f"OCR error: {e}"


def _clean_ocr_output(raw: str) -> str:
    """Strip noise from Tesseract output and return a normalised card name."""
    text = raw.strip()
    # Keep only characters that appear in real MTG card names
    text = re.sub(r"[^A-Za-z ,'\-]", "", text)
    # Collapse multiple spaces
    text = re.sub(r" +", " ", text).strip()
    # Title-case so Scryfall fuzzy matching gets a clean signal
    return text.title()


# ── Scryfall Fuzzy Resolution ─────────────────────────────────────────────────

def resolve_card_name(name: str) -> tuple[Optional[dict], Optional[str]]:
    """
    Resolve an OCR'd card name to a full Scryfall card object.
    1. Tries /cards/named?fuzzy= first (built for typos/noise).
    2. Falls back to /cards/search if fuzzy returns nothing.
    Returns (card_dict, error_message).
    """
    if not name:
        return None, "No name to resolve."

    # ── Attempt 1: fuzzy named lookup ────────────────────────────────────────
    try:
        r = requests.get(
            "https://api.scryfall.com/cards/named",
            params={"fuzzy": name},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json(), None
        # 404 = no fuzzy match — fall through to search
        if r.status_code != 404:
            return None, r.json().get("details", "Scryfall error.")

    except requests.RequestException as e:
        return None, f"Network error: {e}"

    # ── Attempt 2: full-text search fallback ──────────────────────────────────
    try:
        r = requests.get(
            "https://api.scryfall.com/cards/search",
            params={"q": name, "order": "name", "unique": "cards"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                return data[0], None
        return None, f'No card found for "{name}". Try adjusting the scan or search manually.'

    except requests.RequestException as e:
        return None, f"Network error: {e}"


# ── Public entry point ────────────────────────────────────────────────────────

def scan_card_image(image: Image.Image) -> tuple[Optional[dict], str, Optional[str]]:
    """
    Full pipeline: PIL image → Scryfall card object.
    Returns (card_dict, ocr_raw_text, error_message).
    card_dict is None on any failure.
    """
    name, err = extract_card_name(image)
    if err:
        return None, name, err

    card, err = resolve_card_name(name)
    return card, name, err