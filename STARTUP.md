# Telegram Claude Bot 啟動說明

## 環境設定

### 1. 設定環境變數

在啟動 Bot 之前，需要設定以下環境變數：

```bash
# Telegram Bot Token (從 @BotFather 獲取)
export TELEGRAM_BOT_TOKEN="your_telegram_bot_token_here"

# DeepSeek API 金鑰 (從 deepseek.com 獲取)
export DEEPSEEK_API_KEY="your_deepseek_api_key_here"

# 可選：提醒聊天 ID 和授權使用者 ID
export REMINDER_CHAT_ID="your_chat_id_here"
export AUTHORIZED_USER_ID="your_user_id_here"
```

建議將這些設定添加到你的 shell 配置文件中（如 `~/.bashrc`、`~/.zshrc` 或 `~/.profile`）：

```bash
echo 'export TELEGRAM_BOT_TOKEN="your_token_here"' >> ~/.bashrc
echo 'export DEEPSEEK_API_KEY="your_key_here"' >> ~/.bashrc
source ~/.bashrc
```

### 2. 設定虛擬環境（推薦）

```bash
# 創建虛擬環境
python -m venv venv_poly

# 啟用虛擬環境
source venv_poly/bin/activate

# 安裝依賴
pip install -r requirements.txt
```

## 啟動 Bot

### 方法 1：使用啟動腳本（推薦）

```bash
# 確保腳本有執行權限
chmod +x start_bot.sh

# 啟動 Bot
./start_bot.sh
```

啟動腳本會自動：
1. 檢查必要的環境變數
2. 清理舊的 Bot 進程
3. 啟用虛擬環境
4. 在背景啟動 Bot
5. 顯示 Bot PID 和操作指令

### 方法 2：手動啟動

```bash
# 啟用虛擬環境
source venv_poly/bin/activate

# 在背景啟動 Bot
nohup python main.py > bot.log 2>&1 &

# 檢查是否啟動成功
tail -f bot.log
```

## 操作指令

### 查看日誌
```bash
# 即時查看日誌
tail -f bot.log

# 查看最後 50 行
tail -50 bot.log
```

### 停止 Bot
```bash
# 優雅停止
pkill -f "python main.py"

# 強制停止
pkill -9 -f "python main.py"
```

### 重啟 Bot
```bash
./start_bot.sh
```

## 疑難排解

### Bot 啟動失敗

1. **檢查環境變數**：
   ```bash
   echo $TELEGRAM_BOT_TOKEN
   echo $DEEPSEEK_API_KEY
   ```

2. **檢查日誌**：
   ```bash
   tail -50 bot.log
   ```

3. **檢查 Python 依賴**：
   ```bash
   pip list | grep -E "openai|python-telegram-bot|httpx"
   ```

### 虛擬環境問題

如果虛擬環境不存在：
```bash
python -m venv venv_poly
source venv_poly/bin/activate
pip install -r requirements.txt
```

## 安全性注意事項

1. **永不提交金鑰**：API 金鑰和 token 永遠不要寫在程式碼中
2. **使用環境變數**：所有敏感資訊都應該從環境變數讀取
3. **保護日誌文件**：`bot.log` 可能包含敏感資訊，請妥善保護
4. **定期更新金鑰**：定期輪換 API 金鑰和 token

## 進階設定

### 使用 .env 文件（替代方案）

創建 `.env` 文件：
```bash
TELEGRAM_BOT_TOKEN=your_token_here
DEEPSEEK_API_KEY=your_key_here
REMINDER_CHAT_ID=your_chat_id_here
AUTHORIZED_USER_ID=your_user_id_here
```

然後修改 `main.py` 使用 `python-dotenv` 載入 `.env` 文件。

### 系統服務（Systemd）

對於生產環境，可以設定 systemd 服務：
```ini
# /etc/systemd/system/telegram-bot.service
[Unit]
Description=Telegram Claude Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/telegram-claude-bot
Environment="TELEGRAM_BOT_TOKEN=your_token"
Environment="DEEPSEEK_API_KEY=your_key"
ExecStart=/path/to/telegram-claude-bot/venv_poly/bin/python main.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```