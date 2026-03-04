#!/bin/bash

# Telegram Claude Bot 啟動腳本
# 安全版本：不包含硬編碼的金鑰，從環境變數讀取

set -e

echo "=========================================="
echo "  Telegram Claude Bot 啟動腳本"
echo "=========================================="
echo ""

# 檢查必要的環境變數
check_env_var() {
    local var_name=$1
    local var_value="${!var_name}"

    if [ -z "$var_value" ]; then
        echo "❌ 錯誤：環境變數 $var_name 未設定"
        echo ""
        echo "請設定環境變數："
        echo "  export $var_name=\"your_actual_value\""
        echo ""
        echo "或者在當前終端機中設定："
        echo "  $var_name=\"your_actual_value\" $0"
        echo ""
        exit 1
    else
        # 顯示部分金鑰（安全原因）
        local masked_value="${var_value:0:8}...${var_value: -4}"
        echo "✅ $var_name: $masked_value"
    fi
}

echo "--- [1/4] 檢查環境變數 ---"
check_env_var "TELEGRAM_BOT_TOKEN"
check_env_var "DEEPSEEK_API_KEY"

# 可選的環境變數
if [ -n "$REMINDER_CHAT_ID" ]; then
    echo "ℹ️  REMINDER_CHAT_ID: $REMINDER_CHAT_ID"
fi

if [ -n "$AUTHORIZED_USER_ID" ]; then
    echo "ℹ️  AUTHORIZED_USER_ID: $AUTHORIZED_USER_ID"
fi

echo ""
echo "--- [2/4] 清理舊進程和日誌 ---"

# 優雅地停止 bot
echo "正在停止現有的 Bot 進程..."
pkill -f "python main.py" 2>/dev/null || true
sleep 1

# 強制停止（如果優雅停止失敗）
pkill -9 -f "python main.py" 2>/dev/null || true

# 備份舊日誌（可選）
if [ -f "bot.log" ]; then
    timestamp=$(date +"%Y%m%d_%H%M%S")
    mv "bot.log" "bot.log.$timestamp" 2>/dev/null || true
    echo "✅ 已備份舊日誌：bot.log.$timestamp"
fi

echo "✅ 清理完成"
echo ""

echo "--- [3/4] 設定環境 ---"

# 檢查虛擬環境
if [ -d "venv_poly" ] && [ -f "venv_poly/bin/activate" ]; then
    echo "啟用虛擬環境：venv_poly"
    source venv_poly/bin/activate
elif [ -d ".venv" ] && [ -f ".venv/bin/activate" ]; then
    echo "啟用虛擬環境：.venv"
    source .venv/bin/activate
elif [ -d "venv" ] && [ -f "venv/bin/activate" ]; then
    echo "啟用虛擬環境：venv"
    source venv/bin/activate
else
    echo "⚠️  警告：未找到虛擬環境，使用系統 Python"
fi

# 顯示 Python 版本
python_version=$(python --version 2>&1 || echo "未知")
echo "Python 版本：$python_version"

echo "✅ 環境設定完成"
echo ""

echo "--- [4/4] 啟動 Bot ---"

echo "正在啟動 Bot..."
echo "日誌輸出：bot.log"
echo ""

# 後台啟動 Bot
nohup python main.py > bot.log 2>&1 &
BOT_PID=$!

# 等待啟動
sleep 3

# 檢查是否啟動成功
if kill -0 $BOT_PID 2>/dev/null; then
    echo "=========================================="
    echo "  ✅ Bot 啟動成功！"
    echo "  PID: $BOT_PID"
    echo ""
    echo "  操作指令："
    echo "  - 查看日誌：tail -f bot.log"
    echo "  - 停止 Bot：kill $BOT_PID"
    echo "  - 重啟 Bot：$0"
    echo ""
    echo "  請到 Telegram 測試對話"
    echo "=========================================="
else
    echo "❌ Bot 啟動失敗！"
    echo ""
    echo "檢查日誌："
    tail -20 bot.log 2>/dev/null || echo "日誌文件不存在"
    exit 1
fi