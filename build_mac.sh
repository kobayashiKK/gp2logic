#!/bin/bash
# GP2Logic — macOS .app ビルドスクリプト
# 使い方: ./build_mac.sh
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

VENV="$DIR/.venv"
PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"
PYINSTALLER="$VENV/bin/pyinstaller"

# ── PyInstaller のインストール確認 ──────────────────────────────────────────
if ! "$PYTHON" -c "import PyInstaller" 2>/dev/null; then
    echo "📦 PyInstaller をインストールしています..."
    "$PIP" install pyinstaller
fi

# ── ビルド ─────────────────────────────────────────────────────────────────
echo ""
echo "🔨 GP2Logic.app をビルドしています..."
"$PYINSTALLER" GP2Logic.spec --noconfirm

APP="$DIR/dist/GP2Logic.app"

if [ ! -d "$APP" ]; then
    echo "❌ ビルドに失敗しました。"
    exit 1
fi

echo ""
echo "✅ ビルド完了: $APP"
echo ""

# ── ZIP アーカイブの作成（配布用）─────────────────────────────────────────
read -p "ZIP を作成しますか？ (y/N): " CREATE_ZIP
if [[ "$CREATE_ZIP" =~ ^[Yy]$ ]]; then
    ZIP="$DIR/dist/GP2Logic.zip"
    echo "📦 ZIP を作成しています: $ZIP"
    cd "$DIR/dist"
    zip -r --symlinks "GP2Logic.zip" "GP2Logic.app"
    cd "$DIR"
    echo "✅ ZIP 作成完了: $ZIP"
fi

echo ""
echo "── 使い方 ─────────────────────────────────────────────────────────────"
echo "  Finder で開く:     open \"$APP\""
echo "  Gatekeeper を通過: 初回は右クリック → 「開く」を選択してください"
echo "  Applications へ:  cp -r \"$APP\" /Applications/"
echo "──────────────────────────────────────────────────────────────────────"
