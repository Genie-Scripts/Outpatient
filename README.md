# 外来効率化ダッシュボード

東京医療センター経営企画室向け、外来の構造改革（平準化・逆紹介推進・初診増加）を
データ駆動で推進するための、全52診療科対象の月次管理ダッシュボードシステム。

## プロジェクト構成

```
outpatient-efficiency-dashboard/
├── src/
│   ├── anonymize.py           # 医師実名→匿名ID変換
│   ├── aggregate.py           # 生データ→12種の集計CSV生成
│   ├── cli.py                 # CLI統合エントリ
│   ├── llm_client.py          # LM Studio クライアント
│   ├── core/                  # 共通ロジック
│   └── dashboards/            # 各種ダッシュボード生成
├── templates/                 # Jinja2 HTML テンプレート
├── static/                    # 共通CSS/JS
├── config/                    # 設定ファイル
├── data/
│   ├── raw/                   # 【Gitignore】生データ
│   └── aggregated/YYYY-MM/    # 集計済み（コミット可）
├── docs/                      # GitHub Pages 公開物
├── scripts/                   # 運用スクリプト
└── tests/
```

## セットアップ

```bash
# Python 3.11+ と uv（または pip）を用意
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

## 月次運用フロー

```bash
# 1. 電子カルテから YYYY-MM 分のCSVをエクスポートし、以下に配置
data/raw/raw_data_2026-04.csv

# 2. 一括実行
python -m src.cli run-all --month 2026-04

# 3. docs/monthly/2026-04.html が生成される
```

### サブコマンド

| コマンド | 機能 |
|---|---|
| `anonymize --month YYYY-MM` | 医師名を匿名IDに変換 |
| `aggregate --month YYYY-MM` | 匿名化済みCSV → 12種の集計CSV |
| `build monthly --month YYYY-MM` | 月次ダッシュボード生成 |
| `run-all --month YYYY-MM` | 上記を一括 |

### オプション

- `--no-llm`：LLM未使用（定型文でハイライト生成）
- `--verbose`：詳細ログ

## セキュリティ

- **`data/raw/` は絶対にGitコミット禁止**（`.gitignore` で除外）
- **`config/master_key.csv` も Gitコミット禁止**（医師実名↔匿名ID対応表）
- コミット前に必ず `git status` で確認

## 仕様書

- `CLAUDE.md`：Claude Code 向け実装指示
- `spec/spec_v0.2.md`：プロジェクト仕様書（ローカル参照のみ）

## ライセンス

院内利用専用（非公開）。
