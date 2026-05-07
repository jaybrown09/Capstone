import streamlit as st
import requests
from PIL import Image

# run with: python -m streamlit run smartbinder.py

from auth import require_auth, current_user
from supabase_client import (
    # MTG
    get_collection, add_to_collection, remove_from_collection,
    # Pokémon
    get_pokemon_collection, add_to_pokemon_collection, remove_from_pokemon_collection,
)
from ocr import scan_card_image, scan_pokemon_card_image
import pokewalletHelpers

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SmartBinder",
    page_icon="🃏",
    layout="wide",
)


# ── CSS ──────────────────────────────────────────────────────────────────────
def local_css(file_name):
    with open(file_name) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


local_css("css/style.css")

# ── Auth gate — nothing below renders until the user is signed in ────────────
require_auth()
user = current_user()


# ════════════════════════════════════════════════════════════════════════════
# Scryfall helpers (MTG)
# ════════════════════════════════════════════════════════════════════════════
def search_cards_list(query: str):
    """Full-text search returning up to 10 results."""
    url = f"https://api.scryfall.com/cards/search?q={requests.utils.quote(query)}&order=name&unique=cards"
    r = requests.get(url, timeout=10)
    if r.status_code == 200:
        return r.json().get("data", [])[:10], None
    return [], r.json().get("details", "Search failed.")


def get_card_image(card: dict) -> str | None:
    imgs = card.get("image_uris", {})
    if imgs:
        return imgs.get("normal") or imgs.get("large")
    faces = card.get("card_faces", [])
    if faces and "image_uris" in faces[0]:
        return faces[0]["image_uris"].get("normal")
    return None


def format_oracle(card: dict) -> str:
    text = card.get("oracle_text", "")
    if not text:
        faces = card.get("card_faces", [])
        if faces:
            text = "\n//\n".join(f.get("oracle_text", "") for f in faces)
    return text


def rarity_class(rarity: str) -> str:
    return f"rarity-{rarity.lower()}"


# ── Session state ────────────────────────────────────────────────────────────
# MTG state
if "mtg_current_card" not in st.session_state:
    st.session_state.mtg_current_card = None
if "mtg_search_results" not in st.session_state:
    st.session_state.mtg_search_results = []
if "mtg_scan_ocr_text" not in st.session_state:
    st.session_state.mtg_scan_ocr_text = ""
if "mtg_collection" not in st.session_state:
    coll, err = get_collection(user["id"])
    st.session_state.mtg_collection = coll if not err else []

# Pokémon state
if "pkm_current_card" not in st.session_state:
    st.session_state.pkm_current_card = None
if "pkm_search_results" not in st.session_state:
    st.session_state.pkm_search_results = []
if "pkm_scan_ocr_text" not in st.session_state:
    st.session_state.pkm_scan_ocr_text = ""
if "pkm_collection" not in st.session_state:
    coll, err = get_pokemon_collection(user["id"])
    st.session_state.pkm_collection = coll if not err else []


# ── Main header + tabs ───────────────────────────────────────────────────────
st.markdown('<div class="main-title">SmartBinder</div>', unsafe_allow_html=True)

tab_mtg, tab_pkm = st.tabs(["🪄  Magic: The Gathering", "⚡  Pokémon"])


# ════════════════════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════════════════
# MTG TAB
# ════════════════════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════════════════
with tab_mtg:
    left, right = st.columns([3, 2], gap="large")

    # ─────────────────────────────────────────────────────────────────────────
    # LEFT: Search, Scan & Card Display
    # ─────────────────────────────────────────────────────────────────────────
    with left:
        # ── Search section ──────────────────────────────────────────────────
        st.markdown('<div class="section-header">Card Search</div>', unsafe_allow_html=True)
        search_query = st.text_input(
            "Card name or search query",
            placeholder="e.g. Black Lotus, lightning bolt, dragon...",
            key="mtg_search_input",
        )

        col_a, col_b = st.columns([1, 1])
        with col_a:
            search_btn = st.button("🔍 Search", use_container_width=True, key="mtg_search_btn")
        with col_b:
            random_btn = st.button("🎲 Random Card", use_container_width=True, key="mtg_random_btn")

        # Random card
        if random_btn:
            with st.spinner("Drawing from the aether..."):
                r = requests.get("https://api.scryfall.com/cards/random", timeout=10)
                if r.status_code == 200:
                    st.session_state.mtg_current_card = r.json()
                    st.session_state.mtg_search_results = []

        # Search
        if search_btn and search_query.strip():
            with st.spinner("Consulting the grimoire..."):
                results, err = search_cards_list(search_query.strip())
                if err:
                    st.error(err)
                elif len(results) == 1:
                    st.session_state.mtg_current_card = results[0]
                    st.session_state.mtg_search_results = []
                elif results:
                    st.session_state.mtg_search_results = results
                    st.session_state.mtg_current_card = None
                else:
                    st.warning("No cards found.")

        # Multiple results → pick one
        if st.session_state.mtg_search_results:
            st.markdown('<div class="section-header" style="margin-top:1rem;">Select a Card</div>', unsafe_allow_html=True)
            names = [f"{c['name']} ({c.get('set_name','?')} · {c.get('rarity','?')})" for c in st.session_state.mtg_search_results]
            choice = st.selectbox("", names, label_visibility="collapsed", key="mtg_choice")
            if st.button("Load Selected Card", key="mtg_load_btn"):
                idx = names.index(choice)
                st.session_state.mtg_current_card = st.session_state.mtg_search_results[idx]
                st.session_state.mtg_search_results = []

        st.markdown("---")

        # ── OCR Scan section ────────────────────────────────────────────────
        st.markdown('<div class="section-header">📷 Scan a Card</div>', unsafe_allow_html=True)
        st.markdown(
            '<div style="color:#4a3a28;font-family:\'Crimson Text\',serif;font-size:0.9rem;margin-bottom:0.6rem;">'
            'Point your camera at the card — keep it flat, well-lit, and unobstructed.'
            '</div>',
            unsafe_allow_html=True,
        )

        camera_image = st.camera_input("Capture card", label_visibility="collapsed", key="mtg_camera")
        uploaded_image = st.file_uploader(
            "Or upload a card photo",
            type=["jpg", "jpeg", "png", "webp"],
            label_visibility="visible",
            key="mtg_uploader",
        )

        scan_btn = st.button("🔎 Scan Card", use_container_width=True, key="mtg_scan_btn")
        if scan_btn:
            raw_image = camera_image or uploaded_image
            if raw_image is None:
                st.warning("Capture or upload a card photo first.")
            else:
                with st.spinner("Reading the runes..."):
                    pil_image = Image.open(raw_image)
                    card, ocr_text, err = scan_card_image(pil_image)
                    if err:
                        st.error(err)
                        if ocr_text:
                            st.markdown(
                                f'<div style="color:#4a3a28;font-size:0.85rem;margin-top:0.4rem;">'
                                f'OCR read: <strong>{ocr_text}</strong> — try searching for it manually above.'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
                    else:
                        st.session_state.mtg_current_card = card
                        st.session_state.mtg_search_results = []
                        st.session_state.mtg_scan_ocr_text = ocr_text
                        st.success(f'Scanned: **{card["name"]}** _(OCR read: "{ocr_text}")_')

        st.markdown("---")

        # ── Card display ────────────────────────────────────────────────────
        card = st.session_state.mtg_current_card
        if card:
            img_col, info_col = st.columns([1, 1.3], gap="medium")

            with img_col:
                img_url = get_card_image(card)
                if img_url:
                    st.image(img_url, use_container_width=True)

            with info_col:
                st.markdown(f'<div class="card-name">{card["name"]}</div>', unsafe_allow_html=True)

                mana = card.get("mana_cost", "")
                if mana:
                    st.markdown(f'<span class="mana-cost">{mana}</span>', unsafe_allow_html=True)

                st.markdown(f'<div class="card-type">{card.get("type_line","")}</div>', unsafe_allow_html=True)

                oracle = format_oracle(card)
                if oracle:
                    for line in oracle.split("\n"):
                        if line.strip():
                            st.markdown(f'<div class="card-text">{line}</div>', unsafe_allow_html=True)

                flavor = card.get("flavor_text", "")
                if not flavor:
                    faces = card.get("card_faces", [])
                    if faces:
                        flavor = faces[0].get("flavor_text", "")
                if flavor:
                    st.markdown(f'<div class="flavor-text">"{flavor}"</div>', unsafe_allow_html=True)

                rarity = card.get("rarity", "common")
                set_name = card.get("set_name", "")
                power = card.get("power")
                tough = card.get("toughness")
                pt = f" · {power}/{tough}" if power and tough else ""
                cmc = card.get("cmc")
                cmc_str = f" · CMC {int(cmc)}" if cmc is not None else ""

                st.markdown(f"""
                    <div class="card-meta" style="margin-top:1rem;">
                        Rarity: <span class="{rarity_class(rarity)}">{rarity.title()}</span>
                        &nbsp;·&nbsp; Set: <span>{set_name}</span>
                        {cmc_str}{pt}
                    </div>
                """, unsafe_allow_html=True)

                prices = card.get("prices", {})
                usd = prices.get("usd")
                usd_foil = prices.get("usd_foil")
                if usd or usd_foil:
                    price_parts = []
                    if usd:
                        price_parts.append(f"${usd}")
                    if usd_foil:
                        price_parts.append(f"${usd_foil} foil")
                    st.markdown(f'<div class="card-meta" style="margin-top:0.4rem;">Price: <span>{" · ".join(price_parts)}</span></div>', unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)
                qty = st.number_input("Quantity", min_value=1, max_value=99, value=1, key="mtg_qty_input")
                foil = st.checkbox("Foil", key="mtg_foil_input")

                if st.button("＋ Add to Collection", use_container_width=True, key="mtg_add_btn"):
                    with st.spinner("Saving..."):
                        err = add_to_collection(user["id"], card, qty, foil)
                        if err:
                            st.error(f"Could not add card: {err}")
                        else:
                            coll, _ = get_collection(user["id"])
                            st.session_state.mtg_collection = coll
                            label = "foil " if foil else ""
                            st.success(f"Added {qty}× {label}{card['name']} to your collection!")

    # ─────────────────────────────────────────────────────────────────────────
    # RIGHT: MTG Collection
    # ─────────────────────────────────────────────────────────────────────────
    with right:
        coll = st.session_state.mtg_collection
        total_cards = sum(c["quantity"] for c in coll)

        st.markdown(
            f'<div class="section-header">MTG Collection &nbsp;<span style="color:#c9a84c;font-size:0.8em;">'
            f'({len(coll)} unique · {total_cards} total)</span></div>',
            unsafe_allow_html=True,
        )

        if not coll:
            st.markdown(
                '<div style="color:#4a3a28;font-family:\'Crimson Text\',serif;font-style:italic;padding:1rem 0;">'
                'Your collection is empty. Search for cards and add them above.</div>',
                unsafe_allow_html=True,
            )
        else:
            fc1, fc2 = st.columns(2)
            with fc1:
                filter_text = st.text_input("Filter by name", placeholder="Filter...", key="mtg_filter_input")
            with fc2:
                sort_by = st.selectbox("Sort", ["Name", "Rarity", "Set", "Quantity"], key="mtg_sort")

            filtered = [c for c in coll if filter_text.lower() in c["name"].lower()] if filter_text else coll[:]

            rarity_order = {"mythic": 0, "rare": 1, "uncommon": 2, "common": 3, "special": 4, "bonus": 5}

            if sort_by == "Name":
                filtered.sort(key=lambda c: c["name"])
            elif sort_by == "Rarity":
                filtered.sort(key=lambda c: rarity_order.get(c.get("rarity", "common"), 9))
            elif sort_by == "Set":
                filtered.sort(key=lambda c: c.get("set_name", ""))
            elif sort_by == "Quantity":
                filtered.sort(key=lambda c: -c["quantity"])

            # Collection value estimate
            total_value = 0.0
            for c in coll:
                p = c.get("prices", {})
                price_key = "usd_foil" if c.get("foil") else "usd"
                try:
                    total_value += float(p.get(price_key) or p.get("usd") or 0) * c["quantity"]
                except (ValueError, TypeError):
                    pass

            if total_value > 0:
                st.markdown(
                    f'<div class="card-meta" style="margin-bottom:0.8rem;">Estimated Value: <span>${total_value:.2f}</span></div>',
                    unsafe_allow_html=True,
                )

            for i, item in enumerate(filtered):
                rarity = item.get("rarity", "common")
                foil_tag = " ✦" if item.get("foil") else ""
                r_class = rarity_class(rarity)

                col1, col2 = st.columns([4, 1])
                with col1:
                    st.markdown(f"""
                        <div class="collection-item">
                            <div>
                                <div class="col-item-name">{item['name']}{foil_tag}</div>
                                <div class="col-item-type">{item['type_line']} &nbsp;·&nbsp; <span class="{r_class}">{rarity.title()}</span> &nbsp;·&nbsp; {item.get('set_name','')}</div>
                            </div>
                            <div style="margin-left:auto;font-family:'Cinzel',serif;color:#c9a84c;font-size:1.1rem;white-space:nowrap;">×{item['quantity']}</div>
                        </div>
                    """, unsafe_allow_html=True)
                with col2:
                    if st.button("✕", key=f"mtg_del_{item['id']}_{i}", help="Remove from collection"):
                        with st.spinner("Removing..."):
                            err = remove_from_collection(item["collection_id"])
                            if err:
                                st.error(f"Could not remove card: {err}")
                            else:
                                coll2, _ = get_collection(user["id"])
                                st.session_state.mtg_collection = coll2
                                st.rerun()

            # Export
            st.markdown("---")
            if st.button("📋 Export Collection (JSON)", use_container_width=True, key="mtg_export_btn"):
                import json
                st.download_button(
                    label="⬇ Download JSON",
                    data=json.dumps(st.session_state.mtg_collection, indent=2),
                    file_name="mtg_collection.json",
                    mime="application/json",
                    use_container_width=True,
                    key="mtg_download_btn",
                )


# ════════════════════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════════════════
# POKÉMON TAB
# ════════════════════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════════════════
with tab_pkm:
    left, right = st.columns([3, 2], gap="large")

    # ─────────────────────────────────────────────────────────────────────────
    # LEFT: Pokémon Search, Scan & Card Display
    # ─────────────────────────────────────────────────────────────────────────
    with left:
        # ── Search section ──────────────────────────────────────────────────
        st.markdown('<div class="section-header">Card Search</div>', unsafe_allow_html=True)
        pkm_search_query = st.text_input(
            "Card name, set code, or card number",
            placeholder="e.g. Charizard ex, Pikachu, SV1...",
            key="pkm_search_input",
        )

        col_a, col_b = st.columns([1, 1])
        with col_a:
            pkm_search_btn = st.button("🔍 Search", use_container_width=True, key="pkm_search_btn")
        with col_b:
            pkm_random_btn = st.button("🎲 Random Card", use_container_width=True, key="pkm_random_btn")

        # Random card
        if pkm_random_btn:
            with st.spinner("Catching one in the tall grass..."):
                rand_card, err = pokewallet.get_random_pokemon()
                if err:
                    st.error(err)
                elif rand_card:
                    st.session_state.pkm_current_card = rand_card
                    st.session_state.pkm_search_results = []

        # Search
        if pkm_search_btn and pkm_search_query.strip():
            with st.spinner("Searching the Pokédex..."):
                results, err = pokewallet.search_pokemon_list(pkm_search_query.strip())
                if err:
                    st.error(err)
                elif len(results) == 1:
                    st.session_state.pkm_current_card = results[0]
                    st.session_state.pkm_search_results = []
                elif results:
                    st.session_state.pkm_search_results = results
                    st.session_state.pkm_current_card = None
                else:
                    st.warning("No cards found.")

        # Multiple results → pick one
        if st.session_state.pkm_search_results:
            st.markdown(
                '<div class="section-header" style="margin-top:1rem;">Select a Card</div>',
                unsafe_allow_html=True,
            )
            names = [
                f"{pokewallet.get_pokemon_name(c)} "
                f"({pokewallet.get_pokemon_set_name(c) or '?'} · {pokewallet.get_pokemon_rarity(c)})"
                for c in st.session_state.pkm_search_results
            ]
            choice = st.selectbox("", names, label_visibility="collapsed", key="pkm_choice")
            if st.button("Load Selected Card", key="pkm_load_btn"):
                idx = names.index(choice)
                st.session_state.pkm_current_card = st.session_state.pkm_search_results[idx]
                st.session_state.pkm_search_results = []

        st.markdown("---")

        # ── OCR Scan section ────────────────────────────────────────────────
        st.markdown('<div class="section-header">📷 Scan a Card</div>', unsafe_allow_html=True)
        st.markdown(
            '<div style="color:#4a3a28;font-family:\'Crimson Text\',serif;font-size:0.9rem;margin-bottom:0.6rem;">'
            'Point your camera at the card — keep it flat, well-lit, and unobstructed.'
            '</div>',
            unsafe_allow_html=True,
        )

        pkm_camera_image = st.camera_input("Capture card", label_visibility="collapsed", key="pkm_camera")
        pkm_uploaded_image = st.file_uploader(
            "Or upload a card photo",
            type=["jpg", "jpeg", "png", "webp"],
            label_visibility="visible",
            key="pkm_uploader",
        )

        pkm_scan_btn = st.button("🔎 Scan Card", use_container_width=True, key="pkm_scan_btn")
        if pkm_scan_btn:
            raw_image = pkm_camera_image or pkm_uploaded_image
            if raw_image is None:
                st.warning("Capture or upload a card photo first.")
            else:
                with st.spinner("Reading the card..."):
                    pil_image = Image.open(raw_image)
                    card, ocr_text, err = scan_pokemon_card_image(pil_image)
                    if err:
                        st.error(err)
                        if ocr_text:
                            st.markdown(
                                f'<div style="color:#4a3a28;font-size:0.85rem;margin-top:0.4rem;">'
                                f'OCR read: <strong>{ocr_text}</strong> — try searching for it manually above.'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
                    else:
                        st.session_state.pkm_current_card = card
                        st.session_state.pkm_search_results = []
                        st.session_state.pkm_scan_ocr_text = ocr_text
                        st.success(
                            f'Scanned: **{pokewallet.get_pokemon_name(card)}** _(OCR read: "{ocr_text}")_'
                        )

        st.markdown("---")

        # ── Card display ────────────────────────────────────────────────────
        card = st.session_state.pkm_current_card
        if card:
            img_col, info_col = st.columns([1, 1.3], gap="medium")

            with img_col:
                # Fetch image bytes through the authenticated proxy
                card_id = card.get("id", "")
                if card_id:
                    img_bytes, img_err = pokewallet.fetch_pokemon_image_bytes(card_id, size="high")
                    if img_bytes:
                        st.image(img_bytes, use_container_width=True)
                    else:
                        st.markdown(
                            '<div style="color:#4a3a28;font-style:italic;padding:1rem;">'
                            'Image unavailable.</div>',
                            unsafe_allow_html=True,
                        )

            with info_col:
                name = pokewallet.get_pokemon_name(card)
                st.markdown(f'<div class="card-name">{name}</div>', unsafe_allow_html=True)

                type_line = pokewallet.get_pokemon_type_line(card)
                if type_line:
                    st.markdown(f'<div class="card-type">{type_line}</div>', unsafe_allow_html=True)

                # Attacks + abilities (mirrors oracle text loop)
                body = pokewallet.format_attacks(card)
                if body:
                    for line in body.split("\n"):
                        if line.strip():
                            st.markdown(f'<div class="card-text">{line}</div>', unsafe_allow_html=True)

                # Weakness / Resistance / Retreat — Pokémon-specific footer
                info = card.get("card_info", {}) or {}
                wkn = info.get("weakness") or ""
                res = info.get("resistance") or ""
                retreat = info.get("retreat_cost") or ""
                footer_parts = []
                if wkn:
                    footer_parts.append(f"Weakness: {wkn}")
                if res:
                    footer_parts.append(f"Resistance: {res}")
                if retreat:
                    try:
                        rc = int(float(retreat))
                        footer_parts.append(f"Retreat: {rc}")
                    except (ValueError, TypeError):
                        footer_parts.append(f"Retreat: {retreat}")
                if footer_parts:
                    st.markdown(
                        f'<div class="flavor-text">{" · ".join(footer_parts)}</div>',
                        unsafe_allow_html=True,
                    )

                rarity = pokewallet.get_pokemon_rarity(card)
                set_name = pokewallet.get_pokemon_set_name(card)
                card_number = info.get("card_number", "")
                num_str = f" · #{card_number}" if card_number else ""

                st.markdown(f"""
                    <div class="card-meta" style="margin-top:1rem;">
                        Rarity: <span class="{pokewallet.rarity_class(rarity)}">{rarity}</span>
                        &nbsp;·&nbsp; Set: <span>{set_name or '—'}</span>
                        {num_str}
                    </div>
                """, unsafe_allow_html=True)

                # Prices (TCGPlayer USD with CardMarket EUR fallback)
                normal_price, holo_price = pokewallet.get_pokemon_market_price(card)
                if normal_price or holo_price:
                    price_parts = []
                    if normal_price:
                        price_parts.append(f"${normal_price:.2f}")
                    if holo_price:
                        price_parts.append(f"${holo_price:.2f} holo")
                    st.markdown(
                        f'<div class="card-meta" style="margin-top:0.4rem;">Price: <span>{" · ".join(price_parts)}</span></div>',
                        unsafe_allow_html=True,
                    )

                st.markdown("<br>", unsafe_allow_html=True)
                pkm_qty = st.number_input("Quantity", min_value=1, max_value=99, value=1, key="pkm_qty_input")
                pkm_holo = st.checkbox("Holo", key="pkm_holo_input")

                if st.button("＋ Add to Collection", use_container_width=True, key="pkm_add_btn"):
                    with st.spinner("Saving..."):
                        err = add_to_pokemon_collection(user["id"], card, pkm_qty, pkm_holo)
                        if err:
                            st.error(f"Could not add card: {err}")
                        else:
                            coll, _ = get_pokemon_collection(user["id"])
                            st.session_state.pkm_collection = coll
                            label = "holo " if pkm_holo else ""
                            st.success(f"Added {pkm_qty}× {label}{name} to your collection!")

    # ─────────────────────────────────────────────────────────────────────────
    # RIGHT: Pokémon Collection
    # ─────────────────────────────────────────────────────────────────────────
    with right:
        coll = st.session_state.pkm_collection
        total_cards = sum(c["quantity"] for c in coll)

        st.markdown(
            f'<div class="section-header">Pokémon Collection &nbsp;<span style="color:#c9a84c;font-size:0.8em;">'
            f'({len(coll)} unique · {total_cards} total)</span></div>',
            unsafe_allow_html=True,
        )

        if not coll:
            st.markdown(
                '<div style="color:#4a3a28;font-family:\'Crimson Text\',serif;font-style:italic;padding:1rem 0;">'
                'Your collection is empty. Search for cards and add them above.</div>',
                unsafe_allow_html=True,
            )
        else:
            fc1, fc2 = st.columns(2)
            with fc1:
                pkm_filter_text = st.text_input("Filter by name", placeholder="Filter...", key="pkm_filter_input")
            with fc2:
                pkm_sort_by = st.selectbox("Sort", ["Name", "Rarity", "Set", "Quantity"], key="pkm_sort")

            filtered = [c for c in coll if pkm_filter_text.lower() in (c.get("name") or "").lower()] \
                if pkm_filter_text else coll[:]

            # Pokémon rarity ordering — collapse the many tiers into buckets
            def pkm_rarity_rank(c):
                r = (c.get("rarity") or "").lower()
                if any(x in r for x in ("ultra", "secret", "special", "hyper", "rainbow")):
                    return 0
                if any(x in r for x in ("holo rare", "double rare", "art rare", "super", "amazing", "promo")):
                    return 1
                if "rare" in r:
                    return 2
                if "uncommon" in r:
                    return 3
                return 4

            if pkm_sort_by == "Name":
                filtered.sort(key=lambda c: c.get("name") or "")
            elif pkm_sort_by == "Rarity":
                filtered.sort(key=pkm_rarity_rank)
            elif pkm_sort_by == "Set":
                filtered.sort(key=lambda c: c.get("set_name") or "")
            elif pkm_sort_by == "Quantity":
                filtered.sort(key=lambda c: -c["quantity"])

            # Collection value estimate (TCGPlayer USD, CardMarket EUR fallback)
            total_value = 0.0
            for c in coll:
                tcg = c.get("tcgplayer") or {}
                cm = c.get("cardmarket") or {}
                want_holo = c.get("holo")

                price = None
                # Try TCGPlayer first
                for p in tcg.get("prices", []) or []:
                    sub = (p.get("sub_type_name") or "").lower()
                    is_holo = "holo" in sub or "foil" in sub
                    if want_holo == is_holo and p.get("market_price") is not None:
                        price = float(p["market_price"])
                        break
                # Fall back to any TCGPlayer price
                if price is None:
                    for p in tcg.get("prices", []) or []:
                        if p.get("market_price") is not None:
                            price = float(p["market_price"])
                            break
                # Fall back to CardMarket
                if price is None:
                    for p in cm.get("prices", []) or []:
                        avg = p.get("avg") or p.get("trend") or p.get("low")
                        if avg is not None:
                            price = float(avg)
                            break

                if price is not None:
                    total_value += price * c["quantity"]

            if total_value > 0:
                st.markdown(
                    f'<div class="card-meta" style="margin-bottom:0.8rem;">Estimated Value: <span>${total_value:.2f}</span></div>',
                    unsafe_allow_html=True,
                )

            for i, item in enumerate(filtered):
                rarity = item.get("rarity") or "Common"
                holo_tag = " ✦" if item.get("holo") else ""
                r_class = pokewallet.rarity_class(rarity)

                # Build the type line for the collection list
                type_bits = []
                if item.get("stage"):
                    type_bits.append(item["stage"])
                if item.get("card_type"):
                    type_bits.append(item["card_type"])
                if item.get("hp"):
                    type_bits.append(f"HP {item['hp']}")
                type_line = " · ".join(type_bits) if type_bits else "—"

                col1, col2 = st.columns([4, 1])
                with col1:
                    st.markdown(f"""
                        <div class="collection-item">
                            <div>
                                <div class="col-item-name">{item['name']}{holo_tag}</div>
                                <div class="col-item-type">{type_line} &nbsp;·&nbsp; <span class="{r_class}">{rarity}</span> &nbsp;·&nbsp; {item.get('set_name','') or '—'}</div>
                            </div>
                            <div style="margin-left:auto;font-family:'Cinzel',serif;color:#c9a84c;font-size:1.1rem;white-space:nowrap;">×{item['quantity']}</div>
                        </div>
                    """, unsafe_allow_html=True)
                with col2:
                    if st.button("✕", key=f"pkm_del_{item['id']}_{i}", help="Remove from collection"):
                        with st.spinner("Removing..."):
                            err = remove_from_pokemon_collection(item["collection_id"])
                            if err:
                                st.error(f"Could not remove card: {err}")
                            else:
                                coll2, _ = get_pokemon_collection(user["id"])
                                st.session_state.pkm_collection = coll2
                                st.rerun()

            # Export
            st.markdown("---")
            if st.button("📋 Export Collection (JSON)", use_container_width=True, key="pkm_export_btn"):
                import json
                st.download_button(
                    label="⬇ Download JSON",
                    data=json.dumps(st.session_state.pkm_collection, indent=2),
                    file_name="pokemon_collection.json",
                    mime="application/json",
                    use_container_width=True,
                    key="pkm_download_btn",
                )