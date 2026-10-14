# 鎌倉コミュニティ通貨アンケートシステム

鎌倉市のコミュニティ通貨「まちのコイン鎌倉（クルッポ）」の利用・非利用要因を調査する卒業研究用のアンケート入力・集計・分類Webアプリケーション。

## 機能

- **回答入力**: スマートフォンから街頭で対面アンケートを入力（一人客・グループ客対応）
- **集計・分析**: 単純集計・クロス集計・カイ二乗検定・感度分析をワンクリックで実行
- **自由記述分類**: コードブックに基づく手動分類
- **データ管理**: CSVエクスポート・バックアップ

## 技術構成

| 要素 | 技術 |
|---|---|
| アプリ | Streamlit |
| データベース | Supabase (PostgreSQL) |
| デプロイ | Streamlit Community Cloud |

## セットアップ

### 1. 依存ライブラリのインストール
```bash
pip install -r requirements.txt
```

### 2. Supabase の設定
1. [Supabase](https://supabase.com) でプロジェクトを作成
2. `docs/setup_tables.sql` を Supabase の SQL Editor で実行
3. `.streamlit/secrets.toml` を作成:
```toml
[supabase]
url = "https://your-project.supabase.co"
key = "your-anon-key"

[auth]
password = "your-app-password"
```

### 3. ローカル実行
```bash
streamlit run app.py
```

## 設問の変更方法

`config/questions.yaml` を編集してください。アプリの再起動（またはページのリロード）で反映されます。

## 論文「方法」記載用情報

### 使用ライブラリ
| ライブラリ | バージョン | 用途 |
|---|---|---|
| Streamlit | >=1.38 | Webアプリケーション |
| Supabase (PostgreSQL) | — | データベース |
| pandas | >=2.0 | データ整形 |
| matplotlib | >=3.8 | グラフ描画 |
| scipy | >=1.11 | 統計検定 |
| japanize-matplotlib | >=1.1 | 日本語フォント対応 |

### 統計検定手法
- **カイ二乗検定**: クロス集計表の独立性検定に使用
- **フィッシャーの正確確率検定**: 期待度数が5未満のセルが存在する場合に自動切替

### グループ回答の扱いと感度分析
- グループ客の各メンバーを個別の回答者として記録
- 回答の独立性を検証するため、以下の感度分析を実施:
  1. **全回答者集計**: グループメンバー全員を含む集計
  2. **グループ代表1人集計**: 各グループからメンバー番号1（または乱数シード固定のランダム抽出）を代表として選出した集計
- 両集計の結果を並列比較し、グループ回答が結果に与える影響を評価
- 「同調の可能性」フラグが付いた回答を除外した集計も実施可能

### 自由記述の分類方法
- コードブック（`config/codebook.yaml`）に基づく手動分類
- 1つの回答に複数カテゴリの付与が可能
- 分類者間の一致率はコーエンのκ係数で評価（Phase 5で実装予定）

## ディレクトリ構成

```
kamakura-survey/
├── .streamlit/          テーマ設定・secrets
├── config/              設問・コードブック定義（YAML）
├── docs/                要件定義書・SQLスクリプト
├── pages/               Streamlit各画面
├── lib/                 共通ロジック
├── tests/               テスト・ダミーデータ生成
├── app.py               エントリポイント
├── requirements.txt     依存ライブラリ
└── README.md            本ファイル
```
