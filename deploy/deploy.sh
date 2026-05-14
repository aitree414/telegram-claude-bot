#!/usr/bin/env bash
# Telegram Claude Bot — 快速更新腳本
# 每次 git push 後在 VPS 上執行即可更新
# 用法：sudo bash deploy/deploy.sh
set -euo pipefail

INSTALL_DIR="/opt/telegram-claude-bot"
SERVICE="tg-bot"

echo "==> 拉取最新程式碼..."
cd "$INSTALL_DIR"
git fetch origin
git checkout main
git pull origin main

echo "==> 更新 Python 套件..."
source venv/bin/activate
pip install -r requirements.txt -q

echo "==> 重新啟動服務..."
systemctl restart "$SERVICE"
systemctl status "$SERVICE" --no-pager | head -10

echo ""
echo "✅ 更新完成！查看即時日誌：journalctl -u $SERVICE -f"
