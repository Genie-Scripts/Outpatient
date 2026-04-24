#!/bin/bash
# deploy.sh — 作業終了時: Ollama起動 → run-all ビルド → コミット → プッシュ
# 使い方:
#   ./scripts/deploy.sh             # 月引数なし（cli.py の run-all が自動検出）
#   ./scripts/deploy.sh 2026-04     # 明示指定
set -euo pipefail

# Homebrew（Apple Silicon）のパスを明示的に追加
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# ログ出力先
LOG="/tmp/outpatient_deploy.log"
echo "=== $(date '+%Y/%m/%d %H:%M:%S') deploy 開始 ===" >> "$LOG"

# 通知関数
notify() {
  osascript -e "display notification \"$1\" with title \"外来効率化ダッシュボード\" subtitle \"$2\"" 2>/dev/null || true
}

# エラーダイアログ関数
error_dialog() {
  osascript -e "display dialog \"$1\" buttons {\"OK\"} with title \"エラー\" with icon caution" 2>/dev/null || true
  echo "❌ $1" >> "$LOG"
}

# 予期せぬエラー時に実行
trap 'error_dialog "予期せぬエラーで停止しました。詳細は $LOG を確認してください。"' ERR

# ── 0a. Ollama サーバー起動（インストール済みの場合のみ） ──
if command -v ollama > /dev/null 2>&1; then
  if ! pgrep -x "ollama" > /dev/null 2>&1; then
    echo "🦙 Ollama を起動中..." >> "$LOG"
    ollama serve >> "$LOG" 2>&1 &
    OLLAMA_PID=$!
    # 起動完了を待つ（最大10秒）
    for i in $(seq 1 10); do
      if ollama list > /dev/null 2>&1; then
        echo "✅ Ollama 起動完了 (PID: $OLLAMA_PID)" >> "$LOG"
        break
      fi
      sleep 1
    done
  else
    echo "✅ Ollama はすでに起動中" >> "$LOG"
  fi
else
  echo "ℹ️ Ollama 未インストール。LM Studio または フォールバックで動作。" >> "$LOG"
fi

# ── 0b. リポジトリルートへ移動 & 仮想環境有効化 ──
cd "$(dirname "$0")/.."

if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  error_dialog "仮想環境(.venv)が見つかりません。python -m venv .venv で作成してください。"
  exit 1
fi

# ── 1. run-all（匿名化 → 集計 → 月次 → 深掘り → index）──
echo "🔨 ビルド中..." >> "$LOG"
notify "ビルド中..." "run-all"

if [ $# -ge 1 ]; then
  if ! python -m src.cli run-all --month "$1" >> "$LOG" 2>&1; then
    error_dialog "run-all に失敗しました。$LOG を確認してください。"
    exit 1
  fi
else
  if ! python -m src.cli run-all >> "$LOG" 2>&1; then
    error_dialog "run-all に失敗しました。$LOG を確認してください。"
    exit 1
  fi
fi
echo "✅ ビルド完了" >> "$LOG"

# ── 2. 生成物と設定の変更のみステージ（生データ/医師実名は絶対に除外）──
# ホワイトリスト方式: .gitignore でも data/raw と master_key.csv は弾かれるが、二重防御で明示
git add \
  docs/ \
  templates/ \
  static/ \
  src/ \
  scripts/ \
  tests/ \
  config/dept_classification.csv \
  config/dept_targets.csv \
  config/llm_config.yaml \
  pyproject.toml \
  .gitignore \
  README.md \
  CLAUDE.md 2>/dev/null || true

# ── 2b. 禁止ファイルがステージされていないか最終検査 ──
FORBIDDEN=$(git diff --cached --name-only | grep -E '^(data/raw/|config/master_key\.csv)' || true)
if [ -n "$FORBIDDEN" ]; then
  error_dialog "禁止ファイルがステージされました: $FORBIDDEN"
  git reset HEAD -- $FORBIDDEN >> "$LOG" 2>&1 || true
  exit 1
fi

# ── 3. 変更がなければスキップ ──
if git diff --cached --quiet; then
  echo "⚠️  変更なし。スキップ。" >> "$LOG"
  notify "変更なし。スキップしました。" "deploy"
  exit 0
fi

# ── 4. コミット ──
MONTH_TAG="${1:-auto}"
MSG="Dashboard update (${MONTH_TAG}): $(date '+%Y/%m/%d %H:%M')"
git commit -m "$MSG" >> "$LOG" 2>&1
echo "✅ コミット: $MSG" >> "$LOG"

# ── 5. プッシュ（現在のブランチへ）──
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if ! git push origin "$CURRENT_BRANCH" >> "$LOG" 2>&1; then
  error_dialog "GitHubへのpushに失敗しました (branch: $CURRENT_BRANCH)。SSH接続を確認してください。"
  exit 1
fi

echo "✅ push 完了 (branch: $CURRENT_BRANCH)" >> "$LOG"
notify "GitHubへの保存が完了しました ($CURRENT_BRANCH)。" "✅ deploy 完了"
