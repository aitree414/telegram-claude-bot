# PROJECT
Name: telegram-claude-bot
Purpose: 這個專案採用「三層分離」架構來解決 Claude Code Router 和 DeepSeek API 的 Token 限制問題，確保系統的穩定性和可維護性。
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
2026-06-29
- Created Pui Ching Entrance Display quotation (HKD $1,231,700) from 27-page technical drawing set for 裘槎科學週
- Generated PuiChing_EntranceDisplay_Quotation.xlsx — 9 categories, 30+ line items, professional format

2026-06-25
- Created dxf_detail_fab.py — DXF detail drawing generator using ezdxf for Layout-compatible output with proper layers (A-FURN-OUTL, A-FURN-HIDD, A-DIMS, A-ANNO-CALLOUT, A-FURN-SECT, etc.), dimensions, hatch patterns, and title block
- Generated 3 production DXF files: plinth (G0304_1F_3000), bench (G05_1F_3003), table (G0304_1F_3001) — importable into SketchUp Layout

2026-06-25
- Created drawing_detail_fab.py — new DETAIL fabrication drawing generator with multi-view support (Elevation A/B/C, Plan, Section, Detail), FI_xx finish references, material callouts, professional title block matching Museum Studio format, revision history, BOM, and component generators for plinth/bench/table
- Created cad_plinth_detail.py — generated G0304_1F_3000-00_SW.02-PLINTH DETAILS_v2.svg (production detail drawing for Meet Mona Lisa project plinth with Elevation A, Plan, Section A-A, Detail B, finish schedule, BOM, title block)
- Created cad_bench_detail.py — generated G05_1F_3003-05_SW.11-CURVE BENCH_v2.svg (curve bench detail drawing with elevation, plan showing arc geometry, section, cushion fixing detail)

2026-06-25
- Created drawing_cad.py — CAD-style production drawing generator (white bg, black linework, title block, multi-view, matching 08 Collective fabrication standard)
- Created cad_guitar_truss.py — Guitar Truss v3 A3 production drawing with front/side views, section A-A, detail B/C, BOM, notes, rigging detail
- Generated Guitar_Truss_工程圖_v3.svg (46KB, XML valid) and 製作圖_v3.html wrapper
- Generated Zoe_Taiwan_Guitar_Truss_Quotation_v2.xlsx — 6 categories, 30+ line items
- Added xml_escape() to drawing_cad.py for proper XML special character handling

2026-06-22
- Updated 木作生產圖_v2.html → v3.0 with designer CAD cross-reference
- Added 28-item material index (PT/LM/VT/GL/MT/WP) from 貝貝 P-02
- Updated Zone 1 entry display to D1-02 specs (LM 07, GL 01/03, ⌀400)
- Updated Zone 2 counter to D1-01 specs (LM 02/03, PT 02, POS position)
- Updated Zone 5 apparel cabinets to D1-05 specs (LM 08, metal framing)
- Updated Zone 6 window display to D1-09 specs (LM 05, ⌀40 tubes, 3mm acrylic)
- Updated Zone 7/8 tennis/badminton to D1-10 specs (LM 03 surface, PT 03 paint, MT 02/03 pegboards)
- Added Zone 7 tennis seating from D1-11 (drawer cabinets + foam cushion)
- Added CAD drawing index table (D1-01~D1-11, P-02) mapping to all items
- Updated fitting room to WP 01 gray wallpaper FE76657

2026-06-06
- SketchUp 自動化匯出：成功從 yonex_260604.skp (620MB) 匯出 56 個 Scene + 7 個標準視角共 63 張 PNG 到木作/skp_exports/
- 解決 SketchUp 2023 macOS RubyStartup/Plugin/GUI 自動化問題，最終通過 Ruby Console load 指令完成匯出
- 修正 Camera up vector 平行錯誤，更新標準視角定義

2026-06-01
- Updated dashboard_server.py (8890): serve v3 wife_portfolio.html at /, proxy /api/* and /db/* to backend on 8888
- Updated cloudflared config: vivian.08creative.cc → localhost:8890

2026-06-01
- Add yonex_electrical_designer.py on port 8893 — interactive LIGHT + OUTLET floor plan editor with drag-drop palette, pre-populated positions from quotation/equipment analysis, circuit grouping, and PDF generation

2026-06-01
- Fix CCTV designer PDF download: Content-Disposition header with Chinese characters corrupted HTTP response (RFC 6266), changed to ASCII-only + UTF-8 encoding syntax

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

# 視覺處理規範 (Vision SOP)
- ⚠️ 本開發環境已安裝 Tesseract OCR 工具。
- 只要使用者要求讀取圖片（.jpg, .png 等）或解析圖片內的文字，**絕對禁止**回答「我無法看圖片」。
- 遇到圖片時，你必須主動使用終端機指令：`tesseract [圖片路徑] stdout` 來獲取文字，並根據輸出的純文字結果來完成後續任務。

# HOW CLAUDE SHOULD OPERATE
- Preserve existing architecture patterns and folder structure
- Avoid introducing duplicate logic — check existing utilities first
- Update CLAUDE.md after significant architectural changes

# CLAUDE PREFERENCES
_Auto-learned from 1 observation. Last updated: 2026-05-24_

## Workflow
- Use conventional commits format (feat:, fix:, chore:, etc.) _(weak signal)_

# CURRENT TASK
Completed fabrication detail drawing module (drawing_detail_fab.py) and two production drawings. Awaiting user review.
