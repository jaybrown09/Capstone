"""
supabase_client.py
------------------
All database interactions for SmartBinder.
Import `db` from this module anywhere you need data access.
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
        "id":          card["id"],
        "name":        card["name"],
        "type_line":   card.get("type_line", ""),
        "set_name":    card.get("set_name", ""),
        "rarity":      card.get("rarity", "common"),
        "mana_cost":   card.get("mana_cost", ""),
        "image_url":   _image(card),
        "oracle_text": card.get("oracle_text", ""),
        "power":       card.get("power"),
        "toughness":   card.get("toughness"),
        "cmc":         card.get("cmc"),
        "prices":      card.get("prices", {}),
    }

    try:
        supabase.table("cards").upsert(payload).execute()
        return None
    except Exception as e:
        return str(e)


# ── Collection ────────────────────────────────────────────────────────────────

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
                "quantity":      row["quantity"],
                "foil":          row["foil"],
                "added_at":      row["added_at"],
                # Flatten card fields for easy access in the UI
                "id":            card.get("id"),
                "name":          card.get("name"),
                "type_line":     card.get("type_line"),
                "set_name":      card.get("set_name"),
                "rarity":        card.get("rarity"),
                "mana_cost":     card.get("mana_cost"),
                "image":         card.get("image_url"),
                "prices":        card.get("prices", {}),
            })
        return items, None
    except Exception as e:
        return [], str(e)


def add_to_collection(user_id: str, card: dict, quantity: int, foil: bool) -> Optional[str]:
    """
    Add a card to the user's collection.
    If the (user, card, foil) row already exists, increments quantity atomically.
    Returns an error string, or None on success.
    """
    # 1. Ensure the card is cached in the shared cards table
    err = upsert_card(card)
    if err:
        return err

    card_id = card["id"]

    try:
        # 2. Check if the row already exists
        existing = (
            supabase.table("collection")
            .select("id, quantity")
            .eq("user_id", user_id)
            .eq("card_id", card_id)
            .eq("foil", foil)
            .execute()
        )

        if existing.data:
            # Atomic increment via stored procedure
            supabase.rpc(
                "increment_quantity",
                {
                    "p_user_id": user_id,
                    "p_card_id": card_id,
                    "p_foil":    foil,
                    "p_amount":  quantity,
                },
            ).execute()
        else:
            # New row
            supabase.table("collection").insert({
                "user_id":  user_id,
                "card_id":  card_id,
                "quantity": quantity,
                "foil":     foil,
            }).execute()

        return None
    except Exception as e:
        return str(e)


def remove_from_collection(collection_id: int) -> Optional[str]:
    """
    Delete a specific collection row by its primary key.
    Returns an error string, or None on success.
    """
    try:
        supabase.table("collection").delete().eq("id", collection_id).execute()
        return None
    except Exception as e:
        return str(e)


def update_quantity(collection_id: int, new_quantity: int) -> Optional[str]:
    """
    Set an absolute quantity on a collection row.
    Returns an error string, or None on success.
    """
    try:
        supabase.table("collection").update({"quantity": new_quantity}).eq("id", collection_id).execute()
        return None
    except Exception as e:
        return str(e)