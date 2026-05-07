"""
pokewallet.py
-------------
PokéWallet API helpers for SmartBinder. Mirrors the structure of the
Scryfall helpers in smartbinder.py so the UI can call symmetric functions
for MTG and Pokémon flows.

API key is read from Streamlit secrets as POKEWALLET_API_KEY.
Docs: https://www.pokewallet.io/api-docs
"""

from __future__ import annotations

import difflib
from typing import Optional

import requests
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL = "https://api.pokewallet.io"


def _headers() -> dict:
    """Build auth headers. Reads the key fresh each call so secrets edits
    take effect without a restart."""
    try:
        key = st.secrets["POKEWALLET_API_KEY"]
    except (KeyError, FileNotFoundError):
        key = ""
    return {"X-API-Key": key} if key else {}


# ── Search ────────────────────────────────────────────────────────────────────
def search_pokemon_list(query: str) -> tuple[list[dict], Optional[str]]:
    """
    Full-text search returning up to 10 results.
    Equivalent of search_cards_list() for Scryfall.
    Returns (results, error_message).
    """
    try:
        r = requests.get(
            f"{BASE_URL}/search",
            params={"q": query, "limit": 10},
            headers=_headers(),
            timeout=10,
        )
    except requests.RequestException as e:
        return [], f"Network error: {e}"

    if r.status_code == 401:
        return [], "PokéWallet API key is missing or invalid. Check Streamlit secrets."
    if r.status_code == 429:
        return [], "PokéWallet rate limit hit. Try again in a minute."
    if r.status_code != 200:
        try:
            return [], r.json().get("message", "PokéWallet search failed.")
        except Exception:
            return [], f"PokéWallet search failed (HTTP {r.status_code})."

    data = r.json().get("results", [])
    return data[:10], None


def get_random_pokemon() -> tuple[Optional[dict], Optional[str]]:
    """
    PokéWallet has no /random endpoint, so we simulate one by searching a
    random common name and picking the first result. Cheap, single API call.
    """
    import random
    seeds = ["pikachu", "charizard", "bulbasaur", "eevee", "mewtwo", "snorlax",
             "gengar", "lucario", "gyarados", "dragonite", "blastoise", "venusaur",
             "alakazam", "machamp", "rayquaza", "garchomp", "umbreon", "sylveon"]
    results, err = search_pokemon_list(random.choice(seeds))
    if err:
        return None, err
    if not results:
        return None, "Couldn't draw a random card."
    return random.choice(results), None


# ── Field accessors (mirror Scryfall helpers) ────────────────────────────────
def get_pokemon_image(card: dict) -> Optional[str]:
    """
    Return a URL Streamlit can render with st.image().
    PokéWallet's /images/:id endpoint requires the API key as a header,
    which st.image() can't send. So we use the TCGPlayer or CardMarket
    product page image if the card response embeds one — otherwise fall
    back to fetching bytes through our authenticated proxy below.

    Equivalent of get_card_image() for Scryfall.
    """
    # PokéWallet doesn't return direct image URLs in /search responses.
    # The only authenticated way is /images/:id. We surface the card ID
    # so the caller can pass it to fetch_pokemon_image_bytes().
    return None


def fetch_pokemon_image_bytes(card_id: str, size: str = "high") -> tuple[Optional[bytes], Optional[str]]:
    """
    Authenticated image fetch. Returns raw image bytes that st.image() accepts.
    Should be cached by the caller (Supabase storage) because every call
    counts against the rate limit.
    """
    try:
        r = requests.get(
            f"{BASE_URL}/images/{card_id}",
            params={"size": size},
            headers=_headers(),
            timeout=15,
        )
    except requests.RequestException as e:
        return None, f"Network error: {e}"

    if r.status_code == 200:
        return r.content, None
    if r.status_code == 401:
        return None, "PokéWallet API key is missing or invalid."
    if r.status_code == 429:
        return None, "PokéWallet rate limit hit."
    return None, f"Image fetch failed (HTTP {r.status_code})."


def format_attacks(card: dict) -> str:
    """
    Pokémon equivalent of format_oracle() — flattens attacks + ability text
    into a multi-line string the UI can split on '\\n'.
    """
    info = card.get("card_info", {}) or {}
    lines = []

    attacks = info.get("attacks") or []
    for atk in attacks:
        if atk:
            lines.append(atk)

    text = info.get("card_text")
    if text:
        lines.append(text)

    return "\n".join(lines)


def get_pokemon_name(card: dict) -> str:
    return (card.get("card_info", {}) or {}).get("name", "Unknown")


def get_pokemon_rarity(card: dict) -> str:
    return (card.get("card_info", {}) or {}).get("rarity") or "Common"


def get_pokemon_set_name(card: dict) -> str:
    return (card.get("card_info", {}) or {}).get("set_name") or ""


def get_pokemon_type_line(card: dict) -> str:
    """Build a 'type line' analogous to MTG's type_line.
    Format: '<stage> <card_type> · HP <hp>'."""
    info = card.get("card_info", {}) or {}
    parts = []
    stage = info.get("stage")
    ctype = info.get("card_type")
    hp = info.get("hp")
    if stage:
        parts.append(str(stage).strip())
    if ctype:
        parts.append(str(ctype).strip())
    line = " ".join(parts).strip()
    if hp:
        # hp comes as "200.0" — clean it up
        try:
            hp_int = int(float(hp))
            line = f"{line} · HP {hp_int}".strip(" ·")
        except (ValueError, TypeError):
            pass
    return line


def get_pokemon_market_price(card: dict) -> tuple[Optional[float], Optional[float]]:
    """
    Returns (normal_market_price_usd, holo_market_price_usd) from TCGPlayer.
    Falls back to CardMarket EUR if TCGPlayer is missing.
    """
    normal = None
    holo = None

    tcg = card.get("tcgplayer") or {}
    for p in tcg.get("prices", []) or []:
        sub = (p.get("sub_type_name") or "").lower()
        mp = p.get("market_price")
        if mp is None:
            continue
        if "holo" in sub or "foil" in sub:
            holo = float(mp) if holo is None else holo
        else:
            normal = float(mp) if normal is None else normal

    if normal is None and holo is None:
        cm = card.get("cardmarket") or {}
        for p in cm.get("prices", []) or []:
            vt = (p.get("variant_type") or "").lower()
            avg = p.get("avg") or p.get("trend") or p.get("low")
            if avg is None:
                continue
            if "holo" in vt:
                holo = float(avg) if holo is None else holo
            else:
                normal = float(avg) if normal is None else normal

    return normal, holo


def rarity_class(rarity: str) -> str:
    """Map a Pokémon rarity to a CSS class. Pokémon has way more rarity
    tiers than MTG, so we collapse them into the four MTG-style buckets the
    existing CSS already styles."""
    r = (rarity or "").lower()
    if any(x in r for x in ("ultra", "secret", "special", "hyper", "rainbow")):
        return "rarity-mythic"
    if any(x in r for x in ("holo rare", "double rare", "art rare", "super", "amazing", "promo")):
        return "rarity-rare"
    if "rare" in r:
        return "rarity-rare"
    if "uncommon" in r:
        return "rarity-uncommon"
    return "rarity-common"


# ── Fuzzy resolution (for OCR) ───────────────────────────────────────────────
def resolve_pokemon_name(name: str) -> tuple[Optional[dict], Optional[str]]:
    """
    Resolve an OCR'd card name to a full PokéWallet card object.
    PokéWallet has no fuzzy endpoint, so we search and rank results by
    string similarity. Equivalent of resolve_card_name() for Scryfall.
    """
    if not name:
        return None, "No name to resolve."

    results, err = search_pokemon_list(name)
    if err:
        return None, err
    if not results:
        return None, f'No Pokémon card found for "{name}".'

    # Rank by similarity to the OCR'd name
    target = name.lower().strip()

    def score(card: dict) -> float:
        clean = (card.get("card_info", {}) or {}).get("clean_name") or get_pokemon_name(card)
        return difflib.SequenceMatcher(None, target, clean.lower()).ratio()

    results.sort(key=score, reverse=True)
    best = results[0]

    # Reject very weak matches
    if score(best) < 0.45:
        return None, f'No close match for "{name}". Try searching manually.'

    return best, None