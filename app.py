"""エントリポイント: 認証 → 全ページ共通ヘッダ → ページルーティング"""
import streamlit as st
from lib.auth import check_password
from lib.db import get_counts

st.set_page_config(page_title="鎌倉アンケート", layout="centered")

# --- モバイル向けCSS ---
st.markdown("""
<style>
/* ボタンを大きく */
.stButton > button { min-height: 48px; font-size: 1.05rem; }
/* ラジオ・チェックボックスのタップ領域を広げる */
div[data-testid="stRadio"] label > div { min-height: 28px; }
div[data-testid="stCheckbox"] label { padding: 6px 0; }
</style>
""", unsafe_allow_html=True)

# --- 認証ゲート ---
if not check_password():
    st.stop()

# --- 入力済み件数（全ページ共通） ---
gc, rc = get_counts()
st.caption(f"入力済み: {gc} グループ / {rc} 人")

# --- ページナビゲーション ---
pg = st.navigation([
    st.Page("pages/1_input.py", title="回答入力"),
    st.Page("pages/2_review.py", title="確認・修正"),
])
pg.run()
