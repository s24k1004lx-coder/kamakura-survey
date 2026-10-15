"""回答入力の途中状態を session_state に保持する"""
import streamlit as st

# 回答入力ウィザードの状態を持つウィジェットキーの接頭辞
INPUT_WIDGET_PREFIXES = ("q_", "conformity_", "flag_", "flagmemo_", "rmode_")


def keep_input_state():
    """
    Streamlit は「その回の実行で描画されなかったウィジェット」の値を session_state から消す。
    入力画面は1画面1設問なので、そのままだと前の設問の回答が消えてしまう。
    ウィジェットを描画する前に値を再代入すると消去の対象外になる（Streamlit公式の回避策）。
    ページ切り替え時にも消えないよう、app.py と入力画面の両方の先頭で呼ぶ。
    """
    for k in list(st.session_state.keys()):
        if k.startswith(INPUT_WIDGET_PREFIXES):
            st.session_state[k] = st.session_state[k]
