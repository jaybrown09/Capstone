"""
ocr.py
------
Tesseract OCR pipeline for SmartBinder card scanning.
Handles image preprocessing, OCR extraction, and Scryfall fuzzy resolution.
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
    """
    Use OpenCV edge detection to find the largest rectangular contour
    (the card) in the photo and crop to it. Falls back to the original
    image if no suitable contour is found.
    """
    img = np.array(pil_image.convert("RGB"))
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)

    # Dilate edges slightly to close small gaps in the card border
    kernel = np.ones((3, 3), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        # Find the largest contour by area — almost always the card
        largest = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(largest)

        # Sanity check: the bounding box should be at least 10% of the image
        img_area = pil_image.width * pil_image.height
        if w * h > img_area * 0.10:
            return pil_image.crop((x, y, x + w, y + h))

    # Fallback: return the original image unchanged
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


# ── Image Preprocessing ───────────────────────────────────────────────────────

def preprocess_image(image: Image.Image) -> Image.Image:
    # Fix EXIF rotation (iPhone photos are often sideways)
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

    # Step 1: Detect and crop to just the card itself
    image = find_card_crop(image)

    w, h = image.size

    # Step 2: Crop the name strip from the detected card region
    # MTG name bar sits roughly in the top 10% of the card, left ~85% of width
    name_strip = image.crop((
        int(w * 0.03),
        int(h * 0.02),
        int(w * 0.85),   # wider — was 0.70, which cut off long names
        int(h * 0.11),
    ))

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

    # Step 8: Binarize — converts to clean black-and-white for Tesseract
    # Threshold of 140 works well for most cards; foils may need lower (~120)
    name_strip = name_strip.point(lambda x: 0 if x < 100 else 255, '1')

    # Convert back to 'L' mode — pytesseract doesn't accept mode '1' reliably
    name_strip = name_strip.convert("L")

    return name_strip


# ── OCR Extraction ────────────────────────────────────────────────────────────

def extract_card_name(image: Image.Image) -> tuple[str, Optional[str]]:
    """
    Run Tesseract on a raw card image.
    Returns (extracted_name, error_message).
    """
    try:
        processed = preprocess_image(image)
        config = (
        "--psm 7 --oem 3 "
        "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 "
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
    # Keep only characters that appear in real MTG card names (including digits)
    text = re.sub(r"[^A-Za-z0-9 ,'\-]", "", text)
    # Collapse multiple spaces
    text = re.sub(r" +", " ", text).strip()
    # Take only the first line — PSM 6 may return multiple lines; the name is always first
    text = text.splitlines()[0].strip() if text else ""
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

    # ── Attempt 2: full-text search fallback ─────────────────────────────────
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
    if len(name.strip()) < 3 or len(name.strip().split()) > 8:
        return None, name, "Couldn't read the card name clearly. Try holding it closer and flatter."

    card, err = resolve_card_name(name)
    return card, name, err