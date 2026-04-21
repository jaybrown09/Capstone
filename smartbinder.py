import streamlit as st
import requests
from PIL import Image

# run with: python -m streamlit run smartbinder.py

from auth import require_auth, current_user
from supabase_client import get_collection, add_to_collection, remove_from_collection
from ocr import scan_card_image

# Page config
st.set_page_config(
    page_title="SmartBinder",
    page_icon="🃏",
    layout="wide",
)

# CSS
def local_css(file_name):
    with open(file_name) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

local_css("css/style.css")

# ── Auth gate — nothing below renders until the user is signed in ─────────────
require_auth()
user = current_user()


# ── Scryfall helpers ──────────────────────────────────────────────────────────

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


# ── Session state ─────────────────────────────────────────────────────────────

if "current_card" not in st.session_state:
    st.session_state.current_card = None
if "search_results" not in st.session_state:
    st.session_state.search_results = []
if "scan_ocr_text" not in st.session_state:
    st.session_state.scan_ocr_text = ""
# Load collection fresh from DB on first render
if "collection" not in st.session_state:
    coll, err = get_collection(user["id"])
    st.session_state.collection = coll if not err else []


# ── Main header ───────────────────────────────────────────────────────────────
st.markdown('<div class="main-title">SmartBinder</div>', unsafe_allow_html=True)

# ── Layout ────────────────────────────────────────────────────────────────────
left, right = st.columns([3, 2], gap="large")


# ════════════════════════════════════════════════════════════════════════════
# LEFT: Search, Scan & Card Display
# ════════════════════════════════════════════════════════════════════════════
with left:

    # ── Search section ────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Card Search</div>', unsafe_allow_html=True)

    search_query = st.text_input("Card name or search query", placeholder="e.g. Black Lotus, lightning bolt, dragon...")

    col_a, col_b = st.columns([1, 1])
    with col_a:
        search_btn = st.button("🔍 Search", use_container_width=True)
    with col_b:
        random_btn = st.button("🎲 Random Card", use_container_width=True)

    # Random card
    if random_btn:
        with st.spinner("Drawing from the aether..."):
            r = requests.get("https://api.scryfall.com/cards/random", timeout=10)
            if r.status_code == 200:
                st.session_state.current_card = r.json()
                st.session_state.search_results = []

    # Search
    if search_btn and search_query.strip():
        with st.spinner("Consulting the grimoire..."):
            results, err = search_cards_list(search_query.strip())
            if err:
                st.error(err)
            elif len(results) == 1:
                st.session_state.current_card = results[0]
                st.session_state.search_results = []
            elif results:
                st.session_state.search_results = results
                st.session_state.current_card = None
            else:
                st.warning("No cards found.")

    # Multiple results → pick one
    if st.session_state.search_results:
        st.markdown('<div class="section-header" style="margin-top:1rem;">Select a Card</div>', unsafe_allow_html=True)
        names = [f"{c['name']}  ({c.get('set_name','?')} · {c.get('rarity','?')})" for c in st.session_state.search_results]
        choice = st.selectbox("", names, label_visibility="collapsed")
        if st.button("Load Selected Card"):
            idx = names.index(choice)
            st.session_state.current_card = st.session_state.search_results[idx]
            st.session_state.search_results = []

    st.markdown("---")

    # ── OCR Scan section ──────────────────────────────────────────────────────
    st.markdown('<div class="section-header">📷 Scan a Card</div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="color:#4a3a28;font-family:\'Crimson Text\',serif;font-size:0.9rem;margin-bottom:0.6rem;">'
        'Point your camera at the card — keep it flat, well-lit, and unobstructed.'
        '</div>',
        unsafe_allow_html=True,
    )

    # Camera input — returns an UploadedFile (bytes-like) or None
    camera_image = st.camera_input("Capture card", label_visibility="collapsed")

    # Fallback: upload a photo if camera isn't available
    uploaded_image = st.file_uploader(
        "Or upload a card photo",
        type=["jpg", "jpeg", "png", "webp"],
        label_visibility="visible",
    )

    scan_btn = st.button("🔎 Scan Card", use_container_width=True)

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
                # Surface raw OCR text so the user can correct and search manually
                if ocr_text:
                    st.markdown(
                        f'<div style="color:#4a3a28;font-size:0.85rem;margin-top:0.4rem;">'
                        f'OCR read: <strong>{ocr_text}</strong> — try searching for it manually above.'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.session_state.current_card = card
                st.session_state.search_results = []
                st.session_state.scan_ocr_text = ocr_text
                st.success(f'Scanned: **{card["name"]}**  _(OCR read: "{ocr_text}")_')

    st.markdown("---")

    # ── Card display ──────────────────────────────────────────────────────────
    card = st.session_state.current_card
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

            qty  = st.number_input("Quantity", min_value=1, max_value=99, value=1, key="qty_input")
            foil = st.checkbox("Foil", key="foil_input")

            if st.button("＋ Add to Collection", use_container_width=True):
                with st.spinner("Saving..."):
                    err = add_to_collection(user["id"], card, qty, foil)
                if err:
                    st.error(f"Could not add card: {err}")
                else:
                    coll, _ = get_collection(user["id"])
                    st.session_state.collection = coll
                    label = "foil " if foil else ""
                    st.success(f"Added {qty}× {label}{card['name']} to your collection!")


# ════════════════════════════════════════════════════════════════════════════
# RIGHT: Collection
# ════════════════════════════════════════════════════════════════════════════
with right:
    coll = st.session_state.collection
    total_cards = sum(c["quantity"] for c in coll)

    st.markdown(f'<div class="section-header">MTG Collection &nbsp;<span style="color:#c9a84c;font-size:0.8em;">({len(coll)} unique · {total_cards} total)</span></div>', unsafe_allow_html=True)

    if not coll:
        st.markdown('<div style="color:#4a3a28;font-family:\'Crimson Text\',serif;font-style:italic;padding:1rem 0;">Your collection is empty. Search for cards and add them above.</div>', unsafe_allow_html=True)
    else:
        fc1, fc2 = st.columns(2)
        with fc1:
            filter_text = st.text_input("Filter by name", placeholder="Filter...", key="filter_input")
        with fc2:
            sort_by = st.selectbox("Sort", ["Name", "Rarity", "Set", "Quantity"])

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
            st.markdown(f'<div class="card-meta" style="margin-bottom:0.8rem;">Estimated Value: <span>${total_value:.2f}</span></div>', unsafe_allow_html=True)

        # List items
        for i, item in enumerate(filtered):
            rarity  = item.get("rarity", "common")
            foil_tag = " ✦" if item.get("foil") else ""
            r_class  = rarity_class(rarity)

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
                if st.button("✕", key=f"del_{item['id']}_{i}", help="Remove from collection"):
                    with st.spinner("Removing..."):
                        err = remove_from_collection(item["collection_id"])
                    if err:
                        st.error(f"Could not remove card: {err}")
                    else:
                        coll2, _ = get_collection(user["id"])
                        st.session_state.collection = coll2
                        st.rerun()

        # Export
        st.markdown("---")
        if st.button("📋 Export Collection (JSON)", use_container_width=True):
            import json
            st.download_button(
                label="⬇ Download JSON",
                data=json.dumps(st.session_state.collection, indent=2),
                file_name="mtg_collection.json",
                mime="application/json",
                use_container_width=True,
            )