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
from PIL import Image, ImageFilter, ImageEnhance, ExifTags
import pytesseract
import os

if os.name == 'nt':
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ── Image Preprocessing ───────────────────────────────────────────────────────

def preprocess_image(image: Image.Image) -> Image.Image:
    # Fix EXIF rotation
    try:
        for orientation in ExifTags.TAGS.keys():
            if ExifTags.TAGS[orientation] == 'Orientation':
                break
        exif = image._getexif()
        if exif and orientation in exif:
            if exif[orientation] == 3:
                image = image.rotate(180, expand=True)
            elif exif[orientation] == 6:
                image = image.rotate(270, expand=True)
            elif exif[orientation] == 8:
                image = image.rotate(90, expand=True)
    except Exception:
        pass
    return image

# ── OCR Pipeline ───────────────────────────────────────────────────────

def extract_card_name(image: Image.Image) -> tuple[str, Optional[str]]:
    try:
        image = preprocess_image(image)
        w, h = image.size

        config = (
            r'--psm 7 --oem 3 '
            r'-c tessedit_char_whitelist='
            r'"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz ,\'-"'
        )

        best = ""
        # Scan 5 horizontal strips across the image
        # The name bar could be anywhere depending on how the user framed the shot
        for top_pct in [0.02, 0.10, 0.20, 0.30, 0.40]:
            strip = image.crop((
                int(w * 0.03),
                int(h * top_pct),
                int(w * 0.72),
                int(h * (top_pct + 0.10)),
            ))
            strip = strip.resize((strip.width * 4, strip.height * 4), Image.LANCZOS)
            strip = strip.convert("L")
            strip = ImageEnhance.Contrast(strip).enhance(3.0)
            strip = strip.filter(ImageFilter.SHARPEN)

            raw = pytesseract.image_to_string(strip, config=config)
            cleaned = _clean_ocr_output(raw)
            # Keep the longest result — more characters = more likely a real name
            if len(cleaned) > len(best):
                best = cleaned

        if not best:
            return "", "OCR returned no readable text. Try better lighting or a flatter angle."
        return best, None

    except pytesseract.TesseractNotFoundError:
        return "", "Tesseract is not installed or not on PATH."
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
    name, err = extract_card_name(image)
    if err:
        return None, name, err

    # Reject if OCR result looks like noise
    if len(name.strip()) < 4 or len(name.strip().split()) > 6:
        return None, name, "Couldn't read the card name clearly. Try holding it closer and flatter."

    card, err = resolve_card_name(name)
    return card, name, err