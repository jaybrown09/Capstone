import streamlit as st
import requests
import json
import os

# run with: python -m streamlit run smartbinder.py

# Page config
st.set_page_config(
    page_title="SmartBinder",
    page_icon="🃏",
    layout="wide",
)

# CSS
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;700;900&family=Crimson+Text:ital,wght@0,400;0,600;1,400&display=swap');

html, body, [class*="css"] {
    font-family: 'Crimson Text', serif;
}

h1, h2, h3, .stMarkdown h1 {
    font-family: 'Cinzel', serif !important;
}

.stApp {
    background: #0d0d0f;
    background-image:
        radial-gradient(ellipse at 20% 20%, rgba(101, 67, 33, 0.15) 0%, transparent 50%),
        radial-gradient(ellipse at 80% 80%, rgba(26, 60, 100, 0.15) 0%, transparent 50%);
}

/* Header */
.main-title {
    font-family: 'Cinzel', serif;
    font-size: 2.8rem;
    font-weight: 900;
    letter-spacing: 0.05em;
    background: linear-gradient(135deg, #c9a84c 0%, #f0d080 50%, #c9a84c 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    text-align: center;
    margin-bottom: 0.2rem;
}

.sub-title {
    font-family: 'Crimson Text', serif;
    font-size: 1.1rem;
    color: #7a6a50;
    text-align: center;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    margin-bottom: 2rem;
}

/* Search box */
.stTextInput > div > div > input {
    background: #1a1a20 !important;
    border: 1px solid #3a3020 !important;
    border-radius: 4px !important;
    color: #e8d5a0 !important;
    font-family: 'Crimson Text', serif !important;
    font-size: 1.1rem !important;
    padding: 0.6rem 1rem !important;
}

.stTextInput > div > div > input:focus {
    border-color: #c9a84c !important;
    box-shadow: 0 0 0 2px rgba(201, 168, 76, 0.2) !important;
}

.stTextInput > label {
    color: #a08040 !important;
    font-family: 'Cinzel', serif !important;
    font-size: 0.85rem !important;
    letter-spacing: 0.08em !important;
}

/* Buttons */
.stButton > button {
    background: linear-gradient(135deg, #2a1f08, #3d2e10) !important;
    border: 1px solid #c9a84c !important;
    color: #c9a84c !important;
    font-family: 'Cinzel', serif !important;
    font-size: 0.85rem !important;
    letter-spacing: 0.08em !important;
    border-radius: 3px !important;
    padding: 0.5rem 1.5rem !important;
    transition: all 0.2s ease !important;
}

.stButton > button:hover {
    background: linear-gradient(135deg, #3d2e10, #5a4318) !important;
    box-shadow: 0 0 12px rgba(201, 168, 76, 0.3) !important;
    color: #f0d080 !important;
}

/* Card display */
.card-frame {
    background: linear-gradient(145deg, #1e1a14, #171310);
    border: 1px solid #3a3020;
    border-radius: 8px;
    padding: 1.5rem;
    box-shadow: 0 8px 32px rgba(0,0,0,0.6), inset 0 1px 0 rgba(201,168,76,0.1);
}

.card-name {
    font-family: 'Cinzel', serif;
    font-size: 1.5rem;
    font-weight: 700;
    color: #e8d5a0;
    margin-bottom: 0.2rem;
}

.card-type {
    font-family: 'Crimson Text', serif;
    font-style: italic;
    color: #8a7850;
    font-size: 1rem;
    margin-bottom: 0.8rem;
    padding-bottom: 0.8rem;
    border-bottom: 1px solid #2a2418;
}

.card-meta {
    font-family: 'Cinzel', serif;
    font-size: 0.75rem;
    color: #6a5a38;
    letter-spacing: 0.1em;
    text-transform: uppercase;
}

.card-meta span {
    color: #a08040;
}

.card-text {
    font-family: 'Crimson Text', serif;
    font-size: 1rem;
    color: #c8b878;
    line-height: 1.6;
    background: rgba(0,0,0,0.2);
    border-left: 2px solid #3a3020;
    padding: 0.8rem 1rem;
    border-radius: 0 4px 4px 0;
    margin: 0.8rem 0;
}

.flavor-text {
    font-family: 'Crimson Text', serif;
    font-style: italic;
    font-size: 0.95rem;
    color: #6a5a38;
    margin-top: 0.5rem;
}

/* Collection items */
.collection-item {
    background: linear-gradient(135deg, #151210, #1a1610);
    border: 1px solid #2a2418;
    border-radius: 6px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.6rem;
    display: flex;
    align-items: center;
    gap: 1rem;
    transition: border-color 0.2s;
}

.collection-item:hover {
    border-color: #3a3020;
}

.col-item-name {
    font-family: 'Cinzel', serif;
    font-size: 0.95rem;
    color: #e8d5a0;
}

.col-item-type {
    font-family: 'Crimson Text', serif;
    font-size: 0.85rem;
    color: #6a5a38;
    font-style: italic;
}

/* Mana cost */
.mana-cost {
    font-family: 'Cinzel', serif;
    font-size: 0.9rem;
    color: #c9a84c;
    background: rgba(201, 168, 76, 0.1);
    border: 1px solid rgba(201, 168, 76, 0.2);
    padding: 0.2rem 0.6rem;
    border-radius: 12px;
    display: inline-block;
}

/* Section headers */
.section-header {
    font-family: 'Cinzel', serif;
    font-size: 1rem;
    color: #7a6a48;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    border-bottom: 1px solid #2a2418;
    padding-bottom: 0.5rem;
    margin-bottom: 1rem;
}

/* Rarity badge */
.rarity-mythic { color: #e8562a; }
.rarity-rare { color: #c9a84c; }
.rarity-uncommon { color: #9bb5d4; }
.rarity-common { color: #aaaaaa; }

/* Selectbox styling */
.stSelectbox > div > div {
    background: #1a1a20 !important;
    border-color: #3a3020 !important;
    color: #e8d5a0 !important;
}

/* Divider */
hr {
    border-color: #2a2418 !important;
}

/* Remove Streamlit branding padding */
.block-container {
    padding-top: 2rem !important;
    max-width: 1100px !important;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: #0f0d0a !important;
    border-right: 1px solid #2a2418 !important;
}

[data-testid="stSidebar"] .stMarkdown {
    color: #c8b878 !important;
}

/* Success/info messages */
.stSuccess {
    background: rgba(40, 70, 40, 0.3) !important;
    border-color: #4a7a4a !important;
    color: #90c890 !important;
}

.stInfo {
    background: rgba(30, 50, 80, 0.3) !important;
    border-color: #3a5a8a !important;
    color: #90b0d8 !important;
}

.stWarning {
    background: rgba(80, 60, 20, 0.3) !important;
    border-color: #8a7a3a !important;
    color: #d8c870 !important;
}

.stError {
    background: rgba(80, 30, 30, 0.3) !important;
    border-color: #8a3a3a !important;
    color: #d87070 !important;
}
</style>
""", unsafe_allow_html=True)

# Collection JSON
COLLECTION_FILE = "mtg_collection.json"

def load_collection():
    if os.path.exists(COLLECTION_FILE):
        with open(COLLECTION_FILE, "r") as f:
            return json.load(f)
    return []

def save_collection(collection):
    with open(COLLECTION_FILE, "w") as f:
        json.dump(collection, f, indent=2)

# Scryfall helpers
def search_card(name: str):
    """Exact name search, fall back to fuzzy."""
    url = f"https://api.scryfall.com/cards/named?fuzzy={requests.utils.quote(name)}"
    r = requests.get(url, timeout=10)
    if r.status_code == 200:
        return r.json(), None
    data = r.json()
    return None, data.get("details", "Card not found.")

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
    # Double-faced cards
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

# Session state
if "collection" not in st.session_state:
    st.session_state.collection = load_collection()
if "current_card" not in st.session_state:
    st.session_state.current_card = None
if "search_results" not in st.session_state:
    st.session_state.search_results = []

# Header
st.markdown('<div class="main-title">SmartBinder</div>', unsafe_allow_html=True)

# Layout
left, right = st.columns([3, 2], gap="large")

# ════════════════════════════════════════════════════════════════════════════
# LEFT: Search & Card Display
# ════════════════════════════════════════════════════════════════════════════
with left:
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

    # Card display
    card = st.session_state.current_card
    if card:
        st.markdown("---")
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

            # Prices
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

            # Add to collection controls
            qty = st.number_input("Quantity", min_value=1, max_value=99, value=1, key="qty_input")
            foil = st.checkbox("Foil", key="foil_input")

            if st.button("＋ Add to Collection", use_container_width=True):
                entry = {
                    "id": card["id"],
                    "name": card["name"],
                    "type_line": card.get("type_line", ""),
                    "set_name": card.get("set_name", ""),
                    "rarity": rarity,
                    "mana_cost": mana,
                    "quantity": qty,
                    "foil": foil,
                    "image": get_card_image(card),
                    "prices": prices,
                }
                # Check if same card+foil already in collection
                found = False
                for item in st.session_state.collection:
                    if item["id"] == entry["id"] and item["foil"] == foil:
                        item["quantity"] += qty
                        found = True
                        break
                if not found:
                    st.session_state.collection.append(entry)
                save_collection(st.session_state.collection)
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
        # Filter / sort controls
        fc1, fc2 = st.columns(2)
        with fc1:
            filter_text = st.text_input("Filter by name", placeholder="Filter...", key="filter_input", label_visibility="collapsed")
        with fc2:
            sort_by = st.selectbox("Sort", ["Name", "Rarity", "Set", "Quantity"], label_visibility="collapsed")

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
                # Find actual index in full collection for removal
                actual_idx = next((j for j, c in enumerate(st.session_state.collection) if c["id"] == item["id"] and c["foil"] == item.get("foil")), None)
                if actual_idx is not None:
                    if st.button("✕", key=f"del_{item['id']}_{i}", help="Remove from collection"):
                        st.session_state.collection.pop(actual_idx)
                        save_collection(st.session_state.collection)
                        st.rerun()

        # Export
        st.markdown("---")
        if st.button("📋 Export Collection (JSON)", use_container_width=True):
            st.download_button(
                label="⬇ Download JSON",
                data=json.dumps(st.session_state.collection, indent=2),
                file_name="mtg_collection.json",
                mime="application/json",
                use_container_width=True,
            )