"""DBなしで画面を確認するためのプレビュー用エントリポイント（ダミーデータ・認証なし）

実行: streamlit run tests/preview_app.py
本番の Supabase には一切接続しない。入力した内容はメモリ上にだけ残り、再起動で消える。
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st  # noqa: E402

from tests import fake_db  # noqa: E402

# Streamlit は再実行ごとにこのファイルを実行し直すので、差し替えは最初の1回だけ
if not getattr(sys.modules.get("lib.db"), "FAKE", False):
    fake_db.install(n_groups=100)

from lib.session import keep_input_state  # noqa: E402

st.set_page_config(page_title="鎌倉アンケート（プレビュー）", layout="centered")
st.caption("プレビュー（ダミーデータ・DB未接続）")
keep_input_state()
st.navigation([
    st.Page(os.path.join(ROOT, "pages", "1_input.py"), title="回答入力"),
    st.Page(os.path.join(ROOT, "pages", "3_aggregate.py"), title="集計"),
]).run()
