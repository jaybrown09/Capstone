"""
supabase_client.py
------------------
All database interactions for SmartBinder.
Supports both MTG (Scryfall) and Pokémon (PokéWallet) collections.
"""

from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()


# ── Singleton client ──────────────────────────────────────────────────────────
def _init_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise EnvironmentError(
            "SUPABASE_URL and SUPABASE_KEY must be set in your .env file."
        )
    return create_client(url, key)


supabase: Client = _init_client()


# ── Auth helpers ──────────────────────────────────────────────────────────────
def sign_up(email: str, password: str):
    """Register a new user. Returns (user, error_message)."""
    try:
        res = supabase.auth.sign_up({"email": email, "password": password})
        return res.user, None
    except Exception as e:
        return None, str(e)


def sign_in(email: str, password: str):
    """Sign in an existing user. Returns (session, error_message)."""
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        return res.session, None
    except Exception as e:
        return None, str(e)


def sign_out():
    """Sign out the current user."""
    try:
        supabase.auth.sign_out()
    except Exception:
        pass


def set_session(access_token: str, refresh_token: str):
    """Restore a session from stored tokens (called on page reload)."""
    try:
        supabase.auth.set_session(access_token, refresh_token)
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════════════
# MTG (Scryfall) — existing
# ════════════════════════════════════════════════════════════════════════════

# ── Card cache (shared across all users) ─────────────────────────────────────
def upsert_card(card: dict) -> Optional[str]:
    """
    Insert or update a card in the shared cards table.
    `card` is the raw Scryfall API response dict.
    Returns an error string, or None on success.
    """
    def _image(c: dict) -> Optional[str]:
        imgs = c.get("image_uris", {})
        if imgs:
            return imgs.get("normal") or imgs.get("large")
        faces = c.get("card_faces", [])
        if faces and "image_uris" in faces[0]:
            return faces[0]["image_uris"].get("normal")
        return None

    payload = {
        "id": card["id"],
        "name": card["name"],
        "type_line": card.get("type_line", ""),
        "set_name": card.get("set_name", ""),
        "rarity": card.get("rarity", "common"),
        "mana_cost": card.get("mana_cost", ""),
        "image_url": _image(card),
        "oracle_text": card.get("oracle_text", ""),
        "power": card.get("power"),
        "toughness": card.get("toughness"),
        "cmc": card.get("cmc"),
        "prices": card.get("prices", {}),
    }
    try:
        supabase.table("cards").upsert(payload).execute()
        return None
    except Exception as e:
        return str(e)


# ── MTG Collection ────────────────────────────────────────────────────────────
def get_collection(user_id: str) -> tuple[list[dict], Optional[str]]:
    """
    Fetch all collection rows for a user, joined with card data.
    Returns ([enriched_items], error_message).
    """
    try:
        res = (
            supabase.table("collection")
            .select("id, quantity, foil, added_at, cards(*)")
            .eq("user_id", user_id)
            .execute()
        )
        items = []
        for row in res.data:
            card = row.get("cards", {})
            items.append({
                "collection_id": row["id"],
                "quantity": row["quantity"],
                "foil": row["foil"],
                "added_at": row["added_at"],
                "id": card.get("id"),
                "name": card.get("name"),
                "type_line": card.get("type_line"),
                "set_name": card.get("set_name"),
                "rarity": card.get("rarity"),
                "mana_cost": card.get("mana_cost"),
                "image": card.get("image_url"),
                "prices": card.get("prices", {}),
            })
        return items, None
    except Exception as e:
        return [], str(e)


def add_to_collection(user_id: str, card: dict, quantity: int, foil: bool) -> Optional[str]:
    """
    Add an MTG card to the user's collection.
    Returns an error string, or None on success.
    """
    err = upsert_card(card)
    if err:
        return err

    card_id = card["id"]

    try:
        existing = (
            supabase.table("collection")
            .select("id, quantity")
            .eq("user_id", user_id)
            .eq("card_id", card_id)
            .eq("foil", foil)
            .execute()
        )

        if existing.data:
            supabase.rpc(
                "increment_quantity",
                {
                    "p_user_id": user_id,
                    "p_card_id": card_id,
                    "p_foil": foil,
                    "p_amount": quantity,
                },
            ).execute()
        else:
            supabase.table("collection").insert({
                "user_id": user_id,
                "card_id": card_id,
                "quantity": quantity,
                "foil": foil,
            }).execute()
        return None
    except Exception as e:
        return str(e)


def remove_from_collection(collection_id: int) -> Optional[str]:
    try:
        supabase.table("collection").delete().eq("id", collection_id).execute()
        return None
    except Exception as e:
        return str(e)


def update_quantity(collection_id: int, new_quantity: int) -> Optional[str]:
    try:
        supabase.table("collection").update({"quantity": new_quantity}).eq("id", collection_id).execute()
        return None
    except Exception as e:
        return str(e)


# ════════════════════════════════════════════════════════════════════════════
# Pokémon (PokéWallet) — new, parallel to MTG above
# ════════════════════════════════════════════════════════════════════════════

POKEMON_IMAGE_BUCKET = "pokemon-images"


def _cache_pokemon_image(card_id: str) -> Optional[str]:
    """
    On first sight of a Pokémon card, fetch its image bytes from PokéWallet
    (which costs an API call) and store them in Supabase Storage. Returns
    a public URL we can hand to st.image() forever after.

    Returns the public URL on success, or None on any failure (caller
    falls back to a placeholder).
    """
    from pokewallet import fetch_pokemon_image_bytes

    # Sanitise — Supabase storage paths can't have certain chars
    safe_name = f"{card_id}.jpg"

    try:
        # Check if it already exists by attempting to get the public URL.
        # If the file is missing the URL still returns, but we'll trust
        # the upsert below to be idempotent.
        existing = supabase.storage.from_(POKEMON_IMAGE_BUCKET).get_public_url(safe_name)
        # Cheap probe: try to list this file. If list works and includes it,
        # skip the upload.
        try:
            files = supabase.storage.from_(POKEMON_IMAGE_BUCKET).list(
                "", {"search": safe_name}
            )
            if any(f.get("name") == safe_name for f in (files or [])):
                return existing
        except Exception:
            pass

        # Not cached — fetch from PokéWallet and upload
        img_bytes, err = fetch_pokemon_image_bytes(card_id, size="high")
        if err or not img_bytes:
            return None

        try:
            supabase.storage.from_(POKEMON_IMAGE_BUCKET).upload(
                safe_name,
                img_bytes,
                {"content-type": "image/jpeg", "upsert": "true"},
            )
        except Exception:
            # Bucket might not exist yet — caller should run the SQL migration
            return None

        return supabase.storage.from_(POKEMON_IMAGE_BUCKET).get_public_url(safe_name)
    except Exception:
        return None


def upsert_pokemon_card(card: dict) -> Optional[str]:
    """
    Insert/update a Pokémon card in the shared `pokemon_cards` table.
    `card` is the raw PokéWallet API response dict.
    Caches the card image in Supabase Storage on first sight.
    """
    info = card.get("card_info", {}) or {}
    card_id = card.get("id")
    if not card_id:
        return "PokéWallet card is missing an id."

    # Cache image (best-effort — failure shouldn't block adding to collection)
    image_url = _cache_pokemon_image(card_id)

    # HP comes as a string like "200.0" — normalise to int
    hp_raw = info.get("hp")
    try:
        hp = int(float(hp_raw)) if hp_raw not in (None, "") else None
    except (ValueError, TypeError):
        hp = None

    payload = {
        "id": card_id,
        "name": info.get("name", "Unknown"),
        "set_name": info.get("set_name") or "",
        "set_code": info.get("set_code") or "",
        "card_number": info.get("card_number") or "",
        "rarity": info.get("rarity") or "Common",
        "card_type": info.get("card_type") or "",
        "stage": info.get("stage") or "",
        "hp": hp,
        "card_text": info.get("card_text") or "",
        "attacks": info.get("attacks") or [],
        "weakness": info.get("weakness") or "",
        "resistance": info.get("resistance") or "",
        "retreat_cost": info.get("retreat_cost") or "",
        "image_url": image_url,
        "tcgplayer": card.get("tcgplayer") or {},
        "cardmarket": card.get("cardmarket") or {},
    }
    try:
        supabase.table("pokemon_cards").upsert(payload).execute()
        return None
    except Exception as e:
        return str(e)


def get_pokemon_collection(user_id: str) -> tuple[list[dict], Optional[str]]:
    """Fetch a user's Pokémon collection, joined with card data."""
    try:
        res = (
            supabase.table("pokemon_collection")
            .select("id, quantity, holo, added_at, pokemon_cards(*)")
            .eq("user_id", user_id)
            .execute()
        )
        items = []
        for row in res.data:
            card = row.get("pokemon_cards") or {}
            items.append({
                "collection_id": row["id"],
                "quantity": row["quantity"],
                "holo": row["holo"],
                "added_at": row["added_at"],
                "id": card.get("id"),
                "name": card.get("name"),
                "set_name": card.get("set_name"),
                "set_code": card.get("set_code"),
                "card_number": card.get("card_number"),
                "rarity": card.get("rarity"),
                "card_type": card.get("card_type"),
                "stage": card.get("stage"),
                "hp": card.get("hp"),
                "image": card.get("image_url"),
                "tcgplayer": card.get("tcgplayer") or {},
                "cardmarket": card.get("cardmarket") or {},
            })
        return items, None
    except Exception as e:
        return [], str(e)


def add_to_pokemon_collection(user_id: str, card: dict, quantity: int, holo: bool) -> Optional[str]:
    """Add a Pokémon card to the user's collection. Increments quantity if
    the (user, card, holo) row already exists."""
    err = upsert_pokemon_card(card)
    if err:
        return err

    card_id = card.get("id")

    try:
        existing = (
            supabase.table("pokemon_collection")
            .select("id, quantity")
            .eq("user_id", user_id)
            .eq("card_id", card_id)
            .eq("holo", holo)
            .execute()
        )

        if existing.data:
            # Manual increment (no RPC — cheaper to just update directly)
            row = existing.data[0]
            new_qty = row["quantity"] + quantity
            supabase.table("pokemon_collection").update(
                {"quantity": new_qty}
            ).eq("id", row["id"]).execute()
        else:
            supabase.table("pokemon_collection").insert({
                "user_id": user_id,
                "card_id": card_id,
                "quantity": quantity,
                "holo": holo,
            }).execute()
        return None
    except Exception as e:
        return str(e)


def remove_from_pokemon_collection(collection_id: int) -> Optional[str]:
    try:
        supabase.table("pokemon_collection").delete().eq("id", collection_id).execute()
        return None
    except Exception as e:
        return str(e)


def update_pokemon_quantity(collection_id: int, new_quantity: int) -> Optional[str]:
    try:
        supabase.table("pokemon_collection").update(
            {"quantity": new_quantity}
        ).eq("id", collection_id).execute()
        return None
    except Exception as e:
        return str(e)