import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from .claude_client import ClaudeClient, SUPPORTED_IMAGE_TYPES
from .alerts import AlertManager
from .horse_race import format_daily_report
from .polymarket import get_trending_markets, search_markets
from .poly_analyzer import get_ai_recommendations, get_quick_picks
from .stock import _normalize_symbol, get_stock_analysis, get_stock_info, scan_strong_stocks, get_current_price
from .watchlist import WatchlistManager
from .portfolio import PortfolioManager

logger = logging.getLogger(__name__)

FILE_SIZE_LIMIT = 20 * 1024 * 1024  # 20MB

SCAN_MODES = {"technical", "value", "momentum", "pullback"}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "你好！我是 Meet Mona Lisa 展覽項目助理。\n\n"
        "我可以：\n"
        "• 回答關於 HKHM 展覽項目的問題\n"
        "• 讀取你電腦上的本地檔案\n"
        "• 傳送圖片或 PDF 讓我分析\n"
        "• 執行文件搜尋指令\n\n"
        "指令：\n"
        "/today - 今日工作提醒\n"
        "/files - 查看專案文件目錄\n"
        "/poly - Polymarket 熱門市場\n"
        "/poly <關鍵字> - 搜尋預測市場\n"
        "/stock 2330 - 查詢股價\n"
        "/analysis 0700 - 技術+基本面分析\n"
        "/report - 今日 Horse Race 報告\n"
        "/report 2026-02-25 - 指定日期報告\n"
        "/scan - 掃描強勢台股 Top5\n"
        "/scan value - 價值股模式\n"
        "/scan momentum - 動能股模式\n"
        "/scan pullback - 拉回買點模式\n"
        "/watch - 查看追蹤清單\n"
        "/watch add 2330 - 加入追蹤\n"
        "/watch remove 2330 - 移除追蹤\n"
        "/watch scan - 掃描追蹤清單\n"
        "/buy 2330 100 900 - 記錄買入\n"
        "/sell 2330 50 950 - 記錄賣出\n"
        "/portfolio - 查看持倉損益\n"
        "/alert 0700 above 400 - 設定價格提醒\n"
        "/alerts - 查看提醒清單\n"
        "/clear - 清除對話記憶\n"
        "/help - 顯示幫助"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "使用方式：\n\n"
        "直接提問 - 詢問展覽項目相關問題\n"
        "傳圖片 - 分析設計圖或現場照片\n"
        "傳 PDF - 分析設計規格文件\n\n"
        "指令：\n"
        "/today - 今日工作提醒\n"
        "/files - 查看專案文件目錄\n"
        "/clear - 清除對話記憶"
    )


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    claude: ClaudeClient = context.bot_data["claude"]
    await update.message.chat.send_action("typing")
    today = datetime.now().strftime("%Y年%m月%d日")
    try:
        reply = claude.chat(
            update.effective_user.id,
            f"今天是 {today}，請列出今天的重要工作事項。",
        )
        await update.message.reply_text(reply)
    except Exception:
        logger.exception("today_command failed")
        await update.message.reply_text("發生錯誤，請稍後再試。")


async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    claude: ClaudeClient = context.bot_data["claude"]
    await update.message.chat.send_action("typing")
    try:
        reply = claude.chat(
            update.effective_user.id,
            "請列出 /Users/aitree414/Documents/08/HKHM 目錄的所有一級子目錄和檔案。",
        )
        await update.message.reply_text(reply)
    except Exception:
        logger.exception("files_command failed")
        await update.message.reply_text("發生錯誤，請稍後再試。")


async def analysis_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("用法：/analysis <股票代碼>\n\n例如：/analysis 0700")
        return
    await update.message.chat.send_action("typing")
    results = [get_stock_analysis(symbol) for symbol in context.args]
    await update.message.reply_text("\n\n---\n\n".join(results))


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    top_n = 5
    mode = "technical"
    symbols = None

    if len(args) == 1 and args[0].lower() in SCAN_MODES:
        mode = args[0].lower()
    elif len(args) == 1 and args[0].isdigit() and len(args[0]) <= 2:
        top_n = max(1, min(int(args[0]), 20))
    elif args:
        symbols = list(args)

    mode_label = {"technical": "技術", "value": "價值", "momentum": "動能", "pullback": "拉回買點"}.get(mode, mode)
    await update.message.reply_text(f"掃描中（{mode_label}模式），請稍候...")
    result = scan_strong_stocks(symbols=symbols, top_n=top_n, mode=mode)
    await update.message.reply_text(result)


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    report_date = args[0] if args else None
    await update.message.chat.send_action("typing")
    try:
        text = format_daily_report(report_date)
        await update.message.reply_text(text, parse_mode="HTML")
    except Exception:
        logger.exception("report_command failed")
        await update.message.reply_text("無法讀取報告，請稍後再試。")


async def watch_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    wl: WatchlistManager = context.bot_data["watchlist_manager"]
    args = context.args or []

    if not args:
        symbols = wl.list_symbols()
        if not symbols:
            await update.message.reply_text(
                "追蹤清單是空的。\n\n用 /watch add <代碼> 加入股票。"
            )
            return
        lines = ["追蹤清單：\n"]
        for i, s in enumerate(symbols, 1):
            lines.append(f"{i}. {s}")
        lines.append("\n/watch scan — 掃描全部\n/watch remove <代碼> — 移除")
        await update.message.reply_text("\n".join(lines))
        return

    sub = args[0].lower()

    if sub == "add":
        if len(args) < 2:
            await update.message.reply_text("用法：/watch add <股票代碼>")
            return
        symbol = _normalize_symbol(args[1])
        if wl.add(symbol):
            await update.message.reply_text(f"{symbol} 已加入追蹤清單。")
        else:
            await update.message.reply_text(f"{symbol} 已在追蹤清單中。")

    elif sub == "remove":
        if len(args) < 2:
            await update.message.reply_text("用法：/watch remove <股票代碼>")
            return
        symbol = _normalize_symbol(args[1])
        if wl.remove(symbol):
            await update.message.reply_text(f"{symbol} 已從追蹤清單移除。")
        else:
            await update.message.reply_text(f"{symbol} 不在追蹤清單中。")

    elif sub == "scan":
        symbols = wl.list_symbols()
        if not symbols:
            await update.message.reply_text("追蹤清單是空的，無法掃描。")
            return
        await update.message.reply_text(f"掃描追蹤清單 ({len(symbols)} 支)，請稍候...")
        result = scan_strong_stocks(symbols=symbols, top_n=len(symbols), mode="technical")
        await update.message.reply_text(result)

    else:
        await update.message.reply_text(
            "用法：\n"
            "/watch — 查看清單\n"
            "/watch add <代碼> — 加入\n"
            "/watch remove <代碼> — 移除\n"
            "/watch scan — 技術掃描全部"
        )


async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text(
            "用法：/buy <代碼> <股數> <成本價> [備註]\n\n"
            "例如：/buy 2330 100 900\n"
            "      /buy AAPL 10 180 長期持有"
        )
        return

    symbol = _normalize_symbol(args[0])
    try:
        shares = float(args[1])
        price = float(args[2])
    except ValueError:
        await update.message.reply_text("股數和成本價必須是數字")
        return

    note = " ".join(args[3:]) if len(args) > 3 else ""
    pm: PortfolioManager = context.bot_data["portfolio_manager"]
    trade_id = pm.buy(symbol, shares, price, note)
    await update.message.reply_text(
        f"買入記錄已儲存！(#{trade_id})\n"
        f"{symbol}  {shares:.0f} 股  @ {price:.3f}"
        + (f"\n備註：{note}" if note else "")
    )


async def sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text(
            "用法：/sell <代碼> <股數> <賣出價>\n\n"
            "例如：/sell 2330 50 950"
        )
        return

    symbol = _normalize_symbol(args[0])
    try:
        shares = float(args[1])
        price = float(args[2])
    except ValueError:
        await update.message.reply_text("股數和賣出價必須是數字")
        return

    pm: PortfolioManager = context.bot_data["portfolio_manager"]
    result = pm.sell(symbol, shares, price)

    if not result["ok"]:
        await update.message.reply_text(f"賣出失敗：{result['error']}")
        return

    pnl = result["realized_pnl"]
    pnl_pct = result["realized_pnl_pct"]
    arrow = "▲" if pnl >= 0 else "▼"
    await update.message.reply_text(
        f"賣出記錄已儲存！(#{result['trade_id']})\n"
        f"{symbol}  {shares:.0f} 股  @ {price:.3f}\n\n"
        f"均成本：{result['avg_cost']:.3f}\n"
        f"已實現損益：{arrow} {abs(pnl):.2f}  ({arrow}{abs(pnl_pct):.2f}%)"
    )


async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pm: PortfolioManager = context.bot_data["portfolio_manager"]
    holdings = pm.list_holdings()

    if not holdings:
        await update.message.reply_text(
            "持倉記錄是空的。\n\n用 /buy <代碼> <股數> <成本價> 記錄買入。"
        )
        return

    await update.message.chat.send_action("typing")
    lines = ["持倉損益\n"]
    total_cost = 0.0
    total_value = 0.0

    for h in holdings:
        current = get_current_price(h["symbol"])
        cost_total = h["avg_cost"] * h["net_shares"]
        if current:
            value = current * h["net_shares"]
            pnl = value - cost_total
            pnl_pct = pnl / cost_total * 100 if cost_total else 0
            arrow = "▲" if pnl >= 0 else "▼"
            lines.append(
                f"{h['symbol']}\n"
                f"  股數：{h['net_shares']:.0f}  均成本：{h['avg_cost']:.3f}  現價：{current:.3f}\n"
                f"  損益：{arrow} {abs(pnl):.2f} ({arrow}{abs(pnl_pct):.2f}%)"
            )
            total_cost += cost_total
            total_value += value
        else:
            lines.append(
                f"{h['symbol']}\n"
                f"  股數：{h['net_shares']:.0f}  均成本：{h['avg_cost']:.3f}  現價：無法取得"
            )
            total_cost += cost_total

    if total_cost > 0:
        total_pnl = total_value - total_cost
        total_pnl_pct = total_pnl / total_cost * 100
        arrow = "▲" if total_pnl >= 0 else "▼"
        lines.append(
            f"\n總計\n"
            f"  成本：{total_cost:.2f}  現值：{total_value:.2f}\n"
            f"  總損益：{arrow} {abs(total_pnl):.2f} ({arrow}{abs(total_pnl_pct):.2f}%)"
        )

    lines.append("\n(僅供參考，非投資建議)")
    await update.message.reply_text("\n".join(lines))


async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or len(context.args) < 3:
        await update.message.reply_text(
            "用法：/alert <股票代碼> <above|below> <目標價>\n\n"
            "例如：\n"
            "/alert 0700 above 400  (升破400提醒)\n"
            "/alert AAPL below 200  (跌破200提醒)"
        )
        return

    symbol, condition, target_str = context.args[0], context.args[1].lower(), context.args[2]

    if condition not in ("above", "below"):
        await update.message.reply_text("條件只支援 above 或 below")
        return

    try:
        target = float(target_str)
    except ValueError:
        await update.message.reply_text("目標價必須是數字")
        return

    alert_manager: AlertManager = context.bot_data["alert_manager"]
    alert_id = alert_manager.add(update.effective_user.id, symbol, condition, target)
    normalized = _normalize_symbol(symbol)
    direction = "升破" if condition == "above" else "跌破"
    await update.message.reply_text(
        f"提醒已設定！(ID: {alert_id})\n{normalized} {direction} {target} 時通知你"
    )


async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    alert_manager: AlertManager = context.bot_data["alert_manager"]
    alerts = alert_manager.list_alerts(update.effective_user.id)

    if not alerts:
        await update.message.reply_text("目前沒有設定任何價格提醒。\n\n用 /alert 設定提醒。")
        return

    lines = ["你的價格提醒：\n"]
    for a in alerts:
        direction = "升破" if a["condition"] == "above" else "跌破"
        lines.append(f"[{a['id']}] {_normalize_symbol(a['symbol'])} {direction} {a['target']}")
    lines.append("\n用 /delalert <ID> 刪除提醒")
    await update.message.reply_text("\n".join(lines))


async def delalert_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("用法：/delalert <ID>")
        return
    try:
        alert_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID 必須是數字")
        return

    alert_manager: AlertManager = context.bot_data["alert_manager"]
    if alert_manager.remove(update.effective_user.id, alert_id):
        await update.message.reply_text(f"提醒 #{alert_id} 已刪除")
    else:
        await update.message.reply_text(f"找不到提醒 #{alert_id}")


async def poly_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.chat.send_action("typing")
    if context.args:
        query = " ".join(context.args)
        result = search_markets(query)
    else:
        result = get_trending_markets()
    await update.message.reply_text(result)


async def poly_pick_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """AI-powered Polymarket recommendations."""
    import os
    await update.message.chat.send_action("typing")
    await update.message.reply_text("正在分析 Polymarket 市場，請稍候（約 15 秒）...")
    mode = context.args[0].lower() if context.args else "ai"
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if mode == "quick":
        result = get_quick_picks(api_key)
    else:
        result = get_ai_recommendations(api_key, top_n=5)
    await update.message.reply_text(result)


async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "用法：/stock <股票代碼>\n\n"
            "港股範例：/stock 0700\n"
            "美股範例：/stock AAPL\n"
            "多隻股票：/stock 0700 AAPL TSLA"
        )
        return

    await update.message.chat.send_action("typing")
    results = [get_stock_info(symbol) for symbol in context.args]
    await update.message.reply_text("\n\n---\n\n".join(results))


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    claude: ClaudeClient = context.bot_data["claude"]
    stats = claude._memory.get_stats(update.effective_user.id)
    total = stats["total_messages"]
    await update.message.reply_text(
        f"對話記錄統計\n\n"
        f"累計訊息：{total} 條\n"
        f"儲存位置：本機 SQLite 資料庫\n"
        f"重啟後不會消失\n\n"
        f"用 /clear 可清除所有記錄"
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    claude: ClaudeClient = context.bot_data["claude"]
    claude.clear_memory(update.effective_user.id)
    await update.message.reply_text("對話記憶已清除！")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    claude: ClaudeClient = context.bot_data["claude"]
    await update.message.chat.send_action("typing")
    try:
        reply = claude.chat(update.effective_user.id, update.message.text)
        await update.message.reply_text(reply)
    except Exception:
        logger.exception("handle_text failed")
        await update.message.reply_text("發生錯誤，請稍後再試。")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    claude: ClaudeClient = context.bot_data["claude"]
    await update.message.chat.send_action("typing")
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_data = bytes(await file.download_as_bytearray())
        reply = claude.analyze_image(
            update.effective_user.id,
            image_data,
            "image/jpeg",
            update.message.caption or "",
        )
        await update.message.reply_text(reply)
    except Exception:
        logger.exception("handle_photo failed")
        await update.message.reply_text("圖片分析失敗，請稍後再試。")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    claude: ClaudeClient = context.bot_data["claude"]
    document = update.message.document

    if document.file_size > FILE_SIZE_LIMIT:
        await update.message.reply_text("檔案太大，請上傳小於 20MB 的檔案。")
        return

    await update.message.chat.send_action("typing")
    try:
        file = await context.bot.get_file(document.file_id)
        file_data = bytes(await file.download_as_bytearray())
        mime_type = document.mime_type or ""
        caption = update.message.caption or ""

        if mime_type in SUPPORTED_IMAGE_TYPES:
            reply = claude.analyze_image(
                update.effective_user.id, file_data, mime_type, caption
            )
        else:
            reply = claude.analyze_file(
                update.effective_user.id,
                file_data,
                document.file_name or "file",
                caption,
            )
        await update.message.reply_text(reply)
    except Exception:
        logger.exception("handle_document failed")
        await update.message.reply_text("檔案分析失敗，請稍後再試。")
