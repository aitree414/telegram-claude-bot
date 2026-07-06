# PROJECT
Name: telegram-Codex-bot
Purpose: 這個專案採用「三層分離」架構來解決 Codex Router 和 DeepSeek API 的 Token 限制問題，確保系統的穩定性和可維護性。
Stage: development

# STACK
Language: Python

# FOLDER STRUCTURE
accounting/ — Application code
ai_quant/ — Application code
analysis/ — Application code
bot/ — Application code
broker/ — Application code
contracts/ — Application code
data/ — Application code
deploy/ — Application code
docs/ — Documentation
logs/ — Application code
manager/ — Application code
onchain/ — Application code

# CONVENTIONS
- kebab-case file naming
- Async/await pattern for async operations

# RECENT CHANGES
2026-05-27
- Add DayTraderSim (manager/day_trader_sim.py) — 獨立當沖模擬系統，30k TWD 資金，支援 buy/sell/position tracking/committee signal integration
- Add 4 Telegram commands: /daybuy, /daysell, /daytrade, /dayideas
- Wire into main.py — DayTraderSim instance + handler registration

2026-05-25
- Add news sentiment analysis to committee_service.py (Google News RSS + Chinese keyword scoring)
- Enhanced chat endpoint: committee data + DeepSeek NLG for natural language responses with news context

2026-05-25
- Replace DeepSeek API with AI committee data for chat analysis questions in wife portfolio dashboard

2026-05-16
- Added add SL/TP, dividend calendar, rebalancing, charts, performance reports, alert system
- Added consolidate project directory, add 400k sim portfolio, fix PM2 deployment

2026-05-15
- [fix] 修復圖片分析失敗和DSML洩露
- Added add committee-based auto-trading and Telegram push notification
- Added add Telegram push notification and /committee command for AI committee
- Added integrate AI investment committee with daily analysis pipeline and dashboard

2026-05-14
- Initial commit: AI Quant Workspace structure and docs
- Added add Polymarket integration, strategy engine, crypto backtest, and project documentation

2026-04-30
- Added implement multi-persona AI analysis, auto-trader, and real on-chain execution

2026-04-28
- Added implement accounting system enhancements - year dashboard, suppliers, OCR, exchange rates, backup

# HOW Codex SHOULD OPERATE
- Preserve existing architecture patterns and folder structure
- Avoid introducing duplicate logic — check existing utilities first
- Update AGENTS.md after significant architectural changes

# Codex PREFERENCES
_Auto-learned from 1 observation. Last updated: 2026-05-24_

## Workflow
- Use conventional commits format (feat:, fix:, chore:, etc.) _(weak signal)_
