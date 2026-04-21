"""
auth.py
-------
Streamlit auth UI and session management for SmartBinder.
Call `require_auth()` at the top of smartbinder.py before any other rendering.
"""

import streamlit as st
from supabase_client import sign_in, sign_up, sign_out, set_session


# ── Session state keys ────────────────────────────────────────────────────────
_USER_KEY          = "sb_user"
_ACCESS_TOKEN_KEY  = "sb_access_token"
_REFRESH_TOKEN_KEY = "sb_refresh_token"


def _restore_session():
    """Re-hydrate the Supabase client session from stored tokens on page reload."""
    access  = st.session_state.get(_ACCESS_TOKEN_KEY)
    refresh = st.session_state.get(_REFRESH_TOKEN_KEY)
    if access and refresh:
        set_session(access, refresh)


def is_logged_in() -> bool:
    return bool(st.session_state.get(_USER_KEY))


def current_user() -> dict | None:
    return st.session_state.get(_USER_KEY)


def require_auth():
    """
    Gate the entire app behind auth.
    Call this at the very top of smartbinder.py.
    If the user is not logged in, renders the login/signup form and stops execution.
    """
    _restore_session()

    if is_logged_in():
        _render_topbar()
        return  # User is authenticated — let the rest of the app render

    _render_auth_form()
    st.stop()  # Halt rendering of the main app


# ── Internal UI ───────────────────────────────────────────────────────────────

def _render_topbar():
    """Small logout control shown when the user is signed in."""
    user = current_user()
    col1, col2 = st.columns([5, 1])
    with col2:
        st.markdown(
            f'<div style="text-align:right;color:#c9a84c;font-family:Cinzel,serif;'
            f'font-size:0.8rem;padding-top:0.3rem;">{user["email"]}</div>',
            unsafe_allow_html=True,
        )
        if st.button("Sign out", use_container_width=True):
            _do_logout()


def _render_auth_form():
    """Login / Sign-up form. Shown when the user is not authenticated."""
    st.markdown('<div class="main-title">SmartBinder</div>', unsafe_allow_html=True)
    st.markdown("---")

    tab_login, tab_signup = st.tabs(["Sign In", "Create Account"])

    with tab_login:
        email    = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        if st.button("Sign In", use_container_width=True, key="login_btn"):
            if email and password:
                with st.spinner("Signing in..."):
                    session, err = sign_in(email, password)
                if err:
                    st.error(f"Login failed: {err}")
                else:
                    _store_session(session)
                    st.rerun()
            else:
                st.warning("Please enter your email and password.")

    with tab_signup:
        new_email    = st.text_input("Email", key="signup_email")
        new_password = st.text_input("Password (min 6 chars)", type="password", key="signup_password")
        new_confirm  = st.text_input("Confirm Password", type="password", key="signup_confirm")
        if st.button("Create Account", use_container_width=True, key="signup_btn"):
            if not new_email or not new_password:
                st.warning("Please fill in all fields.")
            elif new_password != new_confirm:
                st.error("Passwords do not match.")
            elif len(new_password) < 6:
                st.error("Password must be at least 6 characters.")
            else:
                with st.spinner("Creating account..."):
                    user, err = sign_up(new_email, new_password)
                if err:
                    st.error(f"Sign-up failed: {err}")
                else:
                    st.success("Account created! Check your email to confirm, then sign in.")


def _store_session(session):
    """Persist session tokens and user info in Streamlit session state."""
    st.session_state[_USER_KEY]          = {"id": session.user.id, "email": session.user.email}
    st.session_state[_ACCESS_TOKEN_KEY]  = session.access_token
    st.session_state[_REFRESH_TOKEN_KEY] = session.refresh_token


def _do_logout():
    sign_out()
    for key in (_USER_KEY, _ACCESS_TOKEN_KEY, _REFRESH_TOKEN_KEY, "collection"):
        st.session_state.pop(key, None)
    st.rerun()