#!/usr/bin/env bash
# =============================================================================
# Telegram Claude Bot — VPS 一鍵部署腳本
# 適用於 Ubuntu 22.04 / Debian 12
# 用法：sudo bash deploy/vps-setup.sh
# =============================================================================
set -euo pipefail

REPO_URL="https://github.com/YOUR_USER/YOUR_REPO.git"   # ← 替換為你的 repo
BRANCH="main"
BOT_USER="tg-bot"
INSTALL_DIR="/opt/telegram-claude-bot"
PYTHON_VERSION="3.11"

echo "========================================"
echo " Telegram Claude Bot — VPS 部署"
echo "========================================"

# ── 1. 系統套件 ──────────────────────────────
echo "[1/7] 安裝系統套件..."
apt-get update -qq
apt-get install -y -qq \
    curl wget git \
    build-essential \
    python3 python3-pip python3-venv \
    libssl-dev \
    tesseract-ocr \
    poppler-utils \
    jq

# ── 2. 建立專用使用者 ────────────────────────
echo "[2/7] 建立系統使用者 $BOT_USER..."
if ! id "$BOT_USER" &>/dev/null; then
    useradd --system --create-home --shell /usr/sbin/nologin "$BOT_USER"
fi

# ── 3. 下載專案 ──────────────────────────────
echo "[3/7] 下載專案..."
if [ -d "$INSTALL_DIR" ]; then
    cd "$INSTALL_DIR"
    git fetch origin
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
else
    git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ── 4. Python 虛擬環境 ───────────────────────
echo "[4/7] 設定 Python 虛擬環境..."
python3 -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"
pip install --upgrade pip -q
pip install -r "$INSTALL_DIR/requirements.txt" -q

# ── 5. 設定檔 ────────────────────────────────
echo "[5/7] 建立 .env 設定檔..."
if [ ! -f "$INSTALL_DIR/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    echo ""
    echo " ⚠️  請編輯 $INSTALL_DIR/.env 填入你的設定："
    echo "    sudo nano $INSTALL_DIR/.env"
    echo ""
    echo "    至少需要填入："
    echo "    - TELEGRAM_BOT_TOKEN=你的 bot token（從 @BotFather）"
    echo "    - DEEPSEEK_API_KEY=你的 DeepSeek API key"
    echo "    - ALLOWED_USER_IDS=你的 Telegram user ID"
    echo "    - PRIVATE_KEY=你的錢包私鑰（用 0x 開頭）"
    echo ""
    echo "    Polymarket（透過 API 下單，不需瀏覽器）："
    echo "    - POLYMARKET_TRADER_ENABLED=true"
    echo "    - POLYMARKET_DRY_RUN=true  # 第一次先開模擬模式"
    echo ""
    read -rp "按 Enter 繼續（或 Ctrl+C 中斷去編輯）..."
else
    echo "    .env 已存在，跳過"
fi

# ── 6. 系統服務 ──────────────────────────────
echo "[6/7] 安裝 systemd 服務..."
cat > /etc/systemd/system/tg-bot.service << 'SERVICE'
[Unit]
Description=Telegram Claude Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=tg-bot
Group=tg-bot
WorkingDirectory=/opt/telegram-claude-bot
EnvironmentFile=/opt/telegram-claude-bot/.env
ExecStart=/opt/telegram-claude-bot/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=append:/var/log/tg-bot/tg-bot.log
StandardError=append:/var/log/tg-bot/tg-bot.log

# 安全強化
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true
ReadWritePaths=/opt/telegram-claude-bot /var/log/tg-bot

[Install]
WantedBy=multi-user.target
SERVICE

# 建立日誌目錄
mkdir -p /var/log/tg-bot
chown "$BOT_USER:$BOT_USER" /var/log/tg-bot

# ── 7. 日誌輪替 ──────────────────────────────
echo "[7/7] 設定 logrotate..."
cat > /etc/logrotate.d/tg-bot << 'LOGROTATE'
/var/log/tg-bot/tg-bot.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
LOGROTATE

# ── 權限修正 ──────────────────────────────────
echo "修正檔案權限..."
chown -R "$BOT_USER:$BOT_USER" "$INSTALL_DIR"
chmod -R 755 "$INSTALL_DIR"
chmod 600 "$INSTALL_DIR/.env"

# ── 啟用服務 ──────────────────────────────────
systemctl daemon-reload
systemctl enable tg-bot.service

echo ""
echo "========================================"
echo " ✅ 部署完成！"
echo "========================================"
echo ""
echo "常用指令："
echo "  sudo systemctl start tg-bot       # 啟動"
echo "  sudo systemctl stop tg-bot        # 停止"
echo "  sudo systemctl restart tg-bot     # 重啟"
echo "  sudo systemctl status tg-bot      # 查看狀態"
echo "  journalctl -u tg-bot -f          # 即時查看日誌"
echo "  tail -f /var/log/tg-bot/tg-bot.log # 查看應用日誌"
echo ""
echo "⚠️  還沒設定 .env 的話，現在去編輯："
echo "   sudo nano $INSTALL_DIR/.env"
echo "   然後 sudo systemctl start tg-bot"
echo ""
echo "💡 Polymarket 因為台灣網路封鎖："
echo "   請確認 VPS 在國外（新加坡、日本、美國皆可）"
echo "   API（clob.polymarket.com）在國外可直接存取"
echo ""
