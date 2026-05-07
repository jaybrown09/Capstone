"""
ocr.py
------
Tesseract OCR pipeline for SmartBinder card scanning.
Handles image preprocessing, OCR extraction, and Scryfall/PokéWallet
fuzzy resolution. Supports both MTG and Pokémon cards.
"""

from __future__ import annotations

import re
import requests
import numpy as np
import cv2

from typing import Optional
from PIL import Image, ImageFilter, ImageEnhance, ExifTags
import pytesseract
import os

if os.name == 'nt':
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


# ── Card Detection ────────────────────────────────────────────────────────────
def find_card_crop(pil_image: Image.Image) -> Image.Image:
    img = np.array(pil_image.convert("RGB"))
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    kernel = np.ones((3, 3), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    img_area = pil_image.width * pil_image.height
    best = None
    best_score = float('inf')

    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        area = w * h
        # Must be between 10% and 85% of image
        if not (img_area * 0.10 < area < img_area * 0.85):
            continue
        # Score by how close the aspect ratio is to 5:7 (0.714)
        ratio = w / h if h > 0 else 0
        score = abs(ratio - 0.714)
        if score < best_score:
            best_score = score
            best = (x, y, w, h)

    # Only accept if ratio is within 20% of expected
    if best and best_score < 0.20:
        x, y, w, h = best
        return pil_image.crop((x, y, x + w, y + h))
    return pil_image


# ── Glare Removal ─────────────────────────────────────────────────────────────
def remove_glare(img: Image.Image) -> Image.Image:
    """
    Clip very bright pixels to reduce specular hotspots on foil/glossy cards.
    Works on a greyscale PIL image.
    """
    arr = np.array(img)
    arr = np.clip(arr, 0, 220)
    return Image.fromarray(arr.astype(np.uint8))


# ── EXIF rotation (shared helper) ─────────────────────────────────────────────
def _fix_exif_rotation(image: Image.Image) -> Image.Image:
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


# ── MTG Image Preprocessing (unchanged) ───────────────────────────────────────
def preprocess_image(image: Image.Image) -> Image.Image:
    image = _fix_exif_rotation(image)

    # Step 1: Detect and crop to just the card itself
    image = find_card_crop(image)

    w, h = image.size

    # Step 2: Crop the name strip from the detected card region.
    # Push left boundary in to avoid left-edge decoration bleeding in.
    # Pull right boundary back to avoid mana cost symbols on the right.
    name_strip = image.crop((
        int(w * 0.10),
        int(h * 0.03),
        int(w * 0.75),
        int(h * 0.10),
    ))

    return _process_name_strip(name_strip)


# ── Pokémon Image Preprocessing (new) ─────────────────────────────────────────
def preprocess_pokemon_image(image: Image.Image) -> Image.Image:
    """
    Pokémon cards put the name in a banner across the very top, with HP
    in the upper-right corner and an evolution badge sometimes in the
    upper-left. We crop a horizontal strip biased toward the centre-left
    to skip the badge but include the full name, and stop before HP.
    """
    image = _fix_exif_rotation(image)
    image = find_card_crop(image)

    w, h = image.size

    # Pokémon name banner: roughly the top 4–9% of the card height,
    # 12–70% across (skip the evolution circle on the left, stop before HP).
    name_strip = image.crop((
        int(w * 0.12),
        int(h * 0.04),
        int(w * 0.70),
        int(h * 0.10),
    ))

    return _process_name_strip(name_strip)


# ── Shared name-strip processing (extracted from preprocess_image) ────────────
def _process_name_strip(name_strip: Image.Image) -> Image.Image:
    # Step 3: Upscale for better OCR resolution
    scale = 4
    name_strip = name_strip.resize(
        (name_strip.width * scale, name_strip.height * scale),
        Image.LANCZOS,
    )

    # Step 4: Convert to greyscale
    name_strip = name_strip.convert("L")

    # Step 5: Remove glare before contrast adjustment
    name_strip = remove_glare(name_strip)

    # Step 6: Boost contrast
    name_strip = ImageEnhance.Contrast(name_strip).enhance(3.0)

    # Step 7: Sharpen
    name_strip = name_strip.filter(ImageFilter.SHARPEN)

    # Step 8: Binarize — 100 is less aggressive than 140, preserves letter structure
    name_strip = name_strip.point(lambda x: 0 if x < 100 else 255, '1')

    # Convert back to 'L' mode — pytesseract doesn't accept mode '1' reliably
    name_strip = name_strip.convert("L")

    return name_strip


# ── OCR Extraction ────────────────────────────────────────────────────────────
def _run_ocr(processed: Image.Image) -> str:
    """Run two-pass Tesseract (normal + inverted) and return whichever
    pass produced more text. Shared between MTG and Pokémon."""
    config = "--psm 7 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789\\ "

    raw1 = pytesseract.image_to_string(processed, config=config)
    inverted = Image.fromarray(255 - np.array(processed))
    raw2 = pytesseract.image_to_string(inverted, config=config)

    return raw1 if len(raw1.strip()) >= len(raw2.strip()) else raw2


def extract_card_name(image: Image.Image) -> tuple[str, Optional[str]]:
    """
    Run Tesseract on a raw MTG card image.
    Returns (extracted_name, error_message).
    """
    try:
        processed = preprocess_image(image)
        raw = _run_ocr(processed)
        cleaned = _clean_ocr_output(raw)
        if not cleaned:
            return "", "OCR returned no readable text. Try better lighting or a flatter angle."
        return cleaned, None
    except pytesseract.TesseractNotFoundError:
        return "", _tesseract_install_msg()
    except Exception as e:
        return "", f"OCR error: {e}"


def extract_pokemon_card_name(image: Image.Image) -> tuple[str, Optional[str]]:
    """
    Run Tesseract on a raw Pokémon card image.
    Returns (extracted_name, error_message).
    """
    try:
        processed = preprocess_pokemon_image(image)
        raw = _run_ocr(processed)
        cleaned = _clean_ocr_output(raw)
        if not cleaned:
            return "", "OCR returned no readable text. Try better lighting or a flatter angle."
        return cleaned, None
    except pytesseract.TesseractNotFoundError:
        return "", _tesseract_install_msg()
    except Exception as e:
        return "", f"OCR error: {e}"


def _tesseract_install_msg() -> str:
    return (
        "Tesseract is not installed or not on PATH. "
        "Install it with: sudo apt install tesseract-ocr (Linux) "
        "or brew install tesseract (macOS). "
        "On Streamlit Cloud, add 'tesseract-ocr' to packages.txt."
    )


def _clean_ocr_output(raw: str) -> str:
    """Strip noise from Tesseract output and return a normalised card name."""
    text = raw.strip()
    # Keep only characters that appear in real card names (including digits)
    text = re.sub(r"[^A-Za-z0-9 ,'\-]", "", text)
    # Collapse multiple spaces
    text = re.sub(r" +", " ", text).strip()
    # Take only the first line — name is always the first line
    text = text.splitlines()[0].strip() if text else ""
    # Title-case so fuzzy matching gets a clean signal
    return text.title()


# ── Scryfall Fuzzy Resolution (MTG, unchanged) ────────────────────────────────
def resolve_card_name(name: str) -> tuple[Optional[dict], Optional[str]]:
    """
    Resolve an OCR'd card name to a full Scryfall card object.
    1. Tries /cards/named?fuzzy= first (built for typos/noise).
    2. Falls back to /cards/search if fuzzy returns nothing.
    Returns (card_dict, error_message).
    """
    if not name:
        return None, "No name to resolve."

    # Attempt 1: fuzzy named lookup
    try:
        r = requests.get(
            "https://api.scryfall.com/cards/named",
            params={"fuzzy": name},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json(), None
        if r.status_code != 404:
            return None, r.json().get("details", "Scryfall error.")
    except requests.RequestException as e:
        return None, f"Network error: {e}"

    # Attempt 2: full-text search fallback
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


# ── Public entry points ───────────────────────────────────────────────────────
def scan_card_image(image: Image.Image) -> tuple[Optional[dict], str, Optional[str]]:
    """MTG scan entry point. Returns (card, ocr_text, error)."""
    name, err = extract_card_name(image)
    if err:
        return None, name, err
    if len(name.strip()) < 3 or len(name.strip().split()) > 8:
        return None, name, "Couldn't read the card name clearly. Try holding it closer and flatter."
    card, err = resolve_card_name(name)
    return card, name, err


def scan_pokemon_card_image(image: Image.Image) -> tuple[Optional[dict], str, Optional[str]]:
    """Pokémon scan entry point. Returns (card, ocr_text, error)."""
    # Imported here to avoid a hard dependency cycle if pokewallet.py is
    # ever loaded before streamlit secrets are available.
    from pokewalletHelpers import resolve_pokemon_name

    name, err = extract_pokemon_card_name(image)
    if err:
        return None, name, err
    if len(name.strip()) < 3 or len(name.strip().split()) > 8:
        return None, name, "Couldn't read the card name clearly. Try holding it closer and flatter."
    card, err = resolve_pokemon_name(name)
    return card, name, err