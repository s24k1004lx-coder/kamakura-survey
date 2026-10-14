"""パスワード認証"""
import streamlit as st
import hmac


def check_password():
    """認証済みなら True。未認証ならログインフォームを表示して False。"""
    if st.session_state.get("authenticated"):
        return True

    st.title("鎌倉アンケートシステム")
    st.markdown("---")
    password = st.text_input("パスワード", type="password", key="login_pw")

    if st.button("ログイン", use_container_width=True):
        if hmac.compare_digest(password, st.secrets["auth"]["password"]):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("パスワードが違います")
    return False
