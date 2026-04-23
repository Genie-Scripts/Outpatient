#!/usr/bin/env bash
# docs/ 配下のみを GitHub Pages 向けに commit & push する運用スクリプト。
# 使い方: ./scripts/deploy.sh 2026-04
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "使い方: $0 YYYY-MM" >&2
  exit 1
fi

MONTH="$1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if ! git diff --quiet -- docs/ || ! git diff --cached --quiet -- docs/; then
  git add docs/
  git commit -m "Publish dashboards for ${MONTH}"
  git push
else
  echo "docs/ に変更なし。push スキップ。"
fi
