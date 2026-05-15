# Telegram Claude Bot - 三層分離系統

## 🎯 系統概述

這個專案採用「三層分離」架構來解決 Claude Code Router 和 DeepSeek API 的 Token 限制問題，確保系統的穩定性和可維護性。

## 📋 三層分離架構

### 第一層：任務檔案分離
- 每個功能模組有獨立的 Markdown 檔案
- 減少單次對話的上下文大小
- 提高開發專注度

### 第二層：狀態快照
- 自動記錄系統狀態
- 便於恢復和追蹤進度
- 定期創建系統快照

### 第三層：對話隔離
- 不同類型的任務使用不同的對話
- 測試對話 vs 生產對話
- 避免上下文污染

## 🚀 快速開始

### 初始化系統
```bash
python3 task_based_development_system.py
```

### 使用任務管理器
```bash
# 列出所有任務
./task_manager.py list

# 顯示任務詳細資訊
./task_manager.py show task_01_api_auth

# 更新任務狀態
./task_manager.py status task_01_api_auth in_progress

# 顯示下一個建議處理的任務
./task_manager.py next

# 顯示系統統計
./task_manager.py stats

# 創建系統快照
./task_manager.py snapshot
```

## 📁 目錄結構

```
docs/
├── tasks/              # 任務檔案 (第一層)
│   ├── task_01_api_auth.md
│   ├── task_02_market_data.md
│   └── ...
├── status/             # 狀態檔案 (第二層)
│   ├── project_status.json
│   ├── development_plan.md
│   └── task_*_status.json
├── snapshots/          # 系統快照 (第二層)
│   └── snapshot_YYYYMMDD_HHMMSS/
├── sessions/           # 對話記錄 (第三層)
└── modules/           # 模組化程式碼
```

## 🎯 任務定義

| 任務 ID | 名稱 | 狀態 | 優先級 | 依賴 |
|---------|------|------|--------|------|
| task_01_api_auth | API 認證與金鑰管理 | pending | high | - |
| task_02_market_data | 市場數據抓取與處理 | pending | high | task_01 |
| task_03_trading_logic | 交易策略與下單邏輯 | pending | high | task_01, task_02 |
| task_04_hyperliquid_grid | Hyperliquid 網格交易 | in_progress | critical | task_01, task_03 |
| task_05_telegram_bot | Telegram 機器人處理 | pending | medium | task_01 |
| task_06_web_services | 網頁服務與監控 | completed | low | - |
| task_07_self_healing | 自我修復系統 | completed | medium | - |

## 🔄 工作流程

### 標準工作流程
1. **檢查狀態**：使用 `./task_manager.py next` 查看下一個任務
2. **專注處理**：只讀取相關任務的檔案（減少上下文）
3. **更新狀態**：完成後使用 `./task_manager.py status` 更新
4. **創建快照**：重要里程碑後創建快照

### 最佳實踐
- 每次只專注一個任務
- 定期創建系統快照
- 按照依賴順序處理任務
- 使用對話隔離策略

## 🛠️ 主要工具

### 1. 任務分離開發系統
```bash
python3 task_based_development_system.py
```
- 初始化三層分離系統
- 創建任務檔案和狀態檔案
- 生成開發計劃

### 2. 任務管理器 CLI
```bash
./task_manager.py [command]
```
- 管理任務狀態
- 查看系統統計
- 創建系統快照

### 3. Claude Router 自我修復系統
```bash
./claude_router_daemon.sh [start|stop|status|repair]
```
- 監控 Claude Code Router 錯誤
- 自動切換 API 模型
- 確保系統高可用性

## 🔒 出國前準備

### 必須完成的步驟
1. **創建最終快照**
   ```bash
   ./task_manager.py snapshot
   ```

2. **更新所有任務狀態**
   ```bash
   ./task_manager.py list
   ```

3. **備份重要檔案**
   ```bash
   cp -r docs/ ~/backup/telegram-bot-docs/
   ```

4. **記錄當前狀態**
   ```bash
   ./task_manager.py stats > ~/backup/system_status.txt
   ```

### 緊急恢復流程
如果對話中斷或 API 錯誤：
1. 從最新快照恢復
2. 使用 `./task_manager.py next` 查看進度
3. 繼續處理下一個任務

## 📞 支援

### 常用命令速查
```bash
# 查看幫助
./task_manager.py --help

# 查看系統狀態
./task_manager.py stats

# 查看開發計劃
cat docs/status/development_plan.md

# 查看任務詳細資訊
./task_manager.py show <task_id>
```

### 重要檔案位置
- 任務檔案：`docs/tasks/`
- 狀態檔案：`docs/status/`
- 系統快照：`docs/snapshots/`
- 開發計劃：`docs/status/development_plan.md`

---

**記住：每次只專注一個任務，定期創建快照，按照依賴順序工作。**