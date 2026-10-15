"""CSV・HTML・PNGエクスポート（グラフ描画を含む）"""
import base64
import html
import io
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # 画面のないサーバーで描画する
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

# グラフの色（単一系列なので1色。文字は系列色を使わずインクの色）
BAR_COLOR = "#2a78d6"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID_COLOR = "#e4e3df"

_FONT_READY = False


def setup_japanese_font():
    """
    matplotlib で日本語を表示できるようにする。
    japanize-matplotlib（Streamlit Cloud の Python 3.11 で利用）を優先し、
    使えない環境（Python 3.12 以降など）ではOSに入っている日本語フォントを探す。
    """
    global _FONT_READY
    if _FONT_READY:
        return
    try:
        import japanize_matplotlib  # noqa: F401
    except Exception:
        from matplotlib import font_manager
        installed = {f.name for f in font_manager.fontManager.ttflist}
        for name in ["IPAexGothic", "Noto Sans CJK JP", "Noto Sans JP", "Yu Gothic",
                     "Meiryo", "BIZ UDGothic", "Hiragino Sans", "MS Gothic"]:
            if name in installed:
                plt.rcParams["font.family"] = name
                break
    plt.rcParams["axes.unicode_minus"] = False
    _FONT_READY = True


def bar_chart_png(table, label_col, value_col, title, pct_col=None, note=None):
    """
    横棒グラフ（度数）を描いて PNG のバイト列を返す。
    棒の端に「度数（割合%）」を直接書く。選択肢はYAMLの順に上から並べる。
    """
    setup_japanese_font()
    labels = [str(x) for x in table[label_col]]
    values = [float(v) for v in table[value_col]]
    n_bars = max(len(labels), 1)
    fig, ax = plt.subplots(figsize=(6.4, 0.42 * n_bars + 1.1), dpi=150)
    y = list(range(n_bars))[::-1]
    ax.barh(y[:len(values)], values, height=0.62, color=BAR_COLOR, edgecolor="white", linewidth=1)
    ax.set_yticks(y[:len(labels)], labels, fontsize=9, color=TEXT_PRIMARY)
    vmax = max(values) if values and max(values) > 0 else 1
    ax.set_xlim(0, vmax * 1.28)
    for yi, (i, v) in zip(y, enumerate(values)):
        text = f"{int(v)}"
        if pct_col is not None:
            text += f"（{table[pct_col].iloc[i]:.1f}%）"
        ax.text(v + vmax * 0.015, yi, text, va="center", fontsize=8.5, color=TEXT_SECONDARY)
    ax.set_title(title, fontsize=10.5, color=TEXT_PRIMARY, loc="left")
    if note:
        ax.set_xlabel(note, fontsize=8, color=TEXT_SECONDARY, loc="left")
    ax.xaxis.grid(True, color=GRID_COLOR, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(axis="x", colors=TEXT_SECONDARY, labelsize=8)
    ax.tick_params(axis="y", length=0)
    for side in ["top", "right", "left"]:
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID_COLOR)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


# ============================================================
# CSV
# ============================================================

def tables_to_csv(sections):
    """
    複数の表を1つのCSVにまとめる（Excelで文字化けしないよう UTF-8 BOM 付き）。
    sections: [(見出し, DataFrame)]
    """
    buf = io.StringIO()
    for title, df in sections:
        buf.write(f"# {title}\n")
        if df is None or len(df) == 0:
            buf.write("（データなし）\n\n")
            continue
        df.to_csv(buf, index=_has_named_index(df))
        buf.write("\n")
    return buf.getvalue().encode("utf-8-sig")


def _has_named_index(df):
    return df.index.name is not None or not isinstance(df.index, pd.RangeIndex)


# ============================================================
# HTML レポート
# ============================================================

def html_report(title, meta_lines, sections):
    """
    HTMLレポート（1ファイルで完結。画像は埋め込み）を文字列で返す。
    sections: [{"heading": str, "text": [str], "tables": [(見出し, DataFrame)], "images": [png bytes]}]
    """
    parts = [f"<h1>{html.escape(title)}</h1>",
             "<p class='meta'>" + "<br>".join(html.escape(m) for m in meta_lines) + "</p>"]
    for s in sections:
        parts.append(f"<h2>{html.escape(s['heading'])}</h2>")
        for t in s.get("text", []):
            parts.append(f"<p>{html.escape(t)}</p>")
        for img in s.get("images", []):
            b64 = base64.b64encode(img).decode("ascii")
            parts.append(f"<img alt='' src='data:image/png;base64,{b64}'>")
        for cap, df in s.get("tables", []):
            if cap:
                parts.append(f"<h3>{html.escape(cap)}</h3>")
            if df is None or len(df) == 0:
                parts.append("<p class='muted'>（データなし）</p>")
            else:
                parts.append(df.to_html(index=_has_named_index(df), border=0,
                                        na_rep="—", classes="tbl"))
    body = "\n".join(parts)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body {{ font-family: "Hiragino Sans", "Yu Gothic", "Noto Sans JP", sans-serif; color: #0b0b0b;
       background: #fff; max-width: 860px; margin: 0 auto; padding: 16px; line-height: 1.6; }}
h1 {{ font-size: 1.4rem; }} h2 {{ font-size: 1.15rem; border-bottom: 1px solid #ddd; margin-top: 2em; }}
h3 {{ font-size: 0.95rem; margin-bottom: 4px; }}
.meta, .muted {{ color: #52514e; font-size: 0.85rem; }}
img {{ max-width: 100%; height: auto; display: block; margin: 8px 0; }}
.tbl {{ border-collapse: collapse; font-size: 0.85rem; margin: 4px 0 16px; display: block; overflow-x: auto; }}
.tbl th, .tbl td {{ border-bottom: 1px solid #e4e3df; padding: 4px 8px; text-align: right; }}
.tbl th:first-child, .tbl td:first-child {{ text-align: left; }}
</style></head><body>
{body}
<p class="muted">生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
</body></html>"""
