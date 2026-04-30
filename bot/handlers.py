import logging
import os
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from .claude_client import ClaudeClient
from .constants import SUPPORTED_IMAGE_TYPES
from .alerts import AlertManager
from .horse_race import format_daily_report
from .polymarket import get_trending_markets, search_markets
from .poly_analyzer import get_ai_recommendations, get_quick_picks
from .stock import _normalize_symbol, get_stock_analysis, get_stock_info, scan_strong_stocks, get_current_price
from .watchlist import WatchlistManager
from .portfolio import PortfolioManager
from .session_manager import get_session_manager, TaskType
from .task_tracker import get_task_tracker, TaskType as TrackerTaskType, TaskStatus
from analysis.stock_analyzer import analyze_stock
from analysis.persona_agents import PERSONA_NAMES
from manager.portfolio_manager_agent import PortfolioManagerAgent
from manager.portfolio_risk import PortfolioRiskManager
from manager.real_trader_bridge import TokenMapper

logger = logging.getLogger(__name__)

FILE_SIZE_LIMIT = 20 * 1024 * 1024  # 20MB

SCAN_MODES = {"technical", "value", "momentum", "pullback"}


async def record_conversation_task(user_id: int, session_id: str) -> None:
    """
    Record a conversation as a task in the task tracker.

    Args:
        user_id: Telegram user ID
        session_id: Session ID from session manager
    """
    try:
        session_manager = get_session_manager()
        task_tracker = get_task_tracker()

        session = session_manager.get_session(session_id)
        if not session:
            logger.warning(f"Session {session_id} not found for task tracking")
            return

        # Convert TaskType enum from session manager to task tracker TaskType
        task_type_map = {
            TaskType.STOCK: TrackerTaskType.STOCK,
            TaskType.PORTFOLIO: TrackerTaskType.PORTFOLIO,
            TaskType.ALERTS: TrackerTaskType.ALERTS,
            TaskType.WATCHLIST: TrackerTaskType.WATCHLIST,
            TaskType.POLY: TrackerTaskType.POLY,
            TaskType.CHAT: TrackerTaskType.CHAT,
            TaskType.GENERAL: TrackerTaskType.GENERAL,
        }

        tracker_task_type = task_type_map.get(session.task_type, TrackerTaskType.OTHER)

        # Convert messages to list of dicts
        messages = []
        for msg in session.messages:
            messages.append({
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp
            })

        # Prepare metadata
        metadata = session.metadata.copy()
        metadata["session_id"] = session_id

        # Record task
        task_tracker.record_task(
            user_id=user_id,
            task_type=tracker_task_type,
            messages=messages,
            metadata=metadata
        )

        logger.debug(f"Recorded task for session {session_id}, user {user_id}")
    except Exception as e:
        logger.error(f"Failed to record task for session {session_id}: {e}", exc_info=True)


async def record_task_from_text(user_id: int, text: str, reply: str = None) -> None:
    """
    Record a task from a text message, using session manager to get session.
    If reply is provided, add it as assistant message.
    """
    try:
        session_manager = get_session_manager()
        session_id = session_manager.get_or_create_session(user_id, text)

        # Get session
        session = session_manager.get_session(session_id)
        if not session:
            logger.warning(f"Session {session_id} not found")
            return

        # Add user message if session has no messages
        if not session.messages:
            session_manager.add_message(session_id, "user", text)

        # Add assistant reply if provided
        if reply:
            session_manager.add_message(session_id, "assistant", reply)

        await record_conversation_task(user_id, session_id)
    except Exception as e:
        logger.error(f"Failed to record task from text for user {user_id}: {e}", exc_info=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "你好！我是 Meet Mona Lisa 展覽項目助理。\n\n"
        "我可以：\n"
        "• 回答關於 HKHM 展覽項目的問題\n"
        "• 讀取你電腦上的本地檔案\n"
        "• 傳送圖片或 PDF 讓我分析\n"
        "• 執行文件搜尋指令\n\n"
        "📈 進階分析：\n"
        "/deep 2330 - 5個AI分析師多維度評估\n"
        "/deepscan - AI深層掃描觀察清單\n"
        "/consolidated - 整合投資日報\n"
        "\n"
        "📊 傳統分析：\n"
        "/stock 2330 - 查詢股價\n"
        "/analysis 0700 - 技術+基本面分析\n"
        "/scan - 掃描強勢台股\n"
        "/scan value - 價值股模式\n"
        "/scan momentum - 動能股模式\n"
        "/scan pullback - 拉回買點模式\n"
        "\n"
        "📋 管理：\n"
        "/watch - 查看追蹤清單\n"
        "/watch add 2330 - 加入追蹤\n"
        "/watch remove 2330 - 移除\n"
        "/watch scan - 掃描追蹤清單\n"
        "/alert 0700 above 400 - 價格提醒\n"
        "/alerts - 查看提醒\n"
        "/risk - 風控狀態\n"
        "\n"
        "💰 交易記錄：\n"
        "/buy 2330 100 900 - 記錄買入\n"
        "/sell 2330 50 950 - 記錄賣出\n"
        "/portfolio - 持倉損益\n"
        "/buysim AAPL 10 200 - 模擬買入\n"
        "/sellsim AAPL 5 210 - 模擬賣出\n"
        "/simportfolio - 模擬持倉\n"
        "\n"
        "🔮 預測市場：\n"
        "/poly - Polymarket 熱門市場\n"
        "/poly <關鍵字> - 搜尋\n"
        "/poly_pick - AI 推薦\n"
        "\n"
        "🤖 自動化：\n"
        "/autotrade - 自動交易狀態\n"
        "/autotrade on - 啟用自動交易\n"
        "/autotrade off - 停用\n"
        "/autotrade run - 立即掃描一次\n"
        "/autotrade real on - 啟用鏈上真實交易\n"
        "/tokenmap - 管理代幣映射\n"
        "/consolidated - 整合投資日報\n"
        "\n"
        "⚙️ 系統：\n"
        "/today - 工作提醒\n"
        "/report - Horse Race 報告\n"
        "/new - 新對話\n"
        "/sessions - 查看對話\n"
        "/clear - 清除記憶\n"
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


async def autotrade_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    auto_trader = context.bot_data.get("auto_trader")
    if not auto_trader:
        await update.message.reply_text("自動交易系統未初始化。")
        return

    args = context.args or []

    # Sub-commands
    if args and args[0].lower() == "on":
        auto_trader.enable()
        await update.message.reply_text("🟢 自動交易已啟用")
        return

    if args and args[0].lower() == "off":
        auto_trader.disable()
        await update.message.reply_text("🔴 自動交易已停用")
        return

    # Real mode sub-command
    if args and args[0].lower() == "real":
        if len(args) > 1 and args[1].lower() == "on":
            auto_trader.enable_real_mode()
            await update.message.reply_text(
                "⛓️ 鏈上真實交易模式已啟用\n\n"
                "注意：需先設定代幣映射 (/tokenmap add)，否則交易會被跳過。\n"
                "當前網路模式：測試鏈 (可透過 .env 的 NETWORK_MODE 切換)"
            )
            return
        if len(args) > 1 and args[1].lower() == "off":
            auto_trader.disable_real_mode()
            await update.message.reply_text("⛓️ 鏈上真實交易模式已停用，僅保留模擬交易")
            return
        await update.message.reply_text(
            "用法：\n"
            "/autotrade real on — 啟用鏈上真實交易\n"
            "/autotrade real off — 停用鏈上真實交易"
        )
        return

    if args and args[0].lower() == "run":
        await update.message.reply_text("🔍 正在執行自動掃描，請稍候...")
        from .stock import TAIWAN_WATCHLIST
        symbols = [_normalize_symbol(s) for s in TAIWAN_WATCHLIST]
        actions = await auto_trader.run_cycle(symbols)
        if not actions:
            await update.message.reply_text("✅ 掃描完成，無符合條件的交易。")
        else:
            lines = ["🤖 自動交易執行結果：\n"]
            for a in actions:
                lines.append(
                    f"{'🟢' if a['action'] == 'BUY' else '🔴' if a['action'] == 'SELL' else '⛔'} "
                    f"{a['action']} {a['symbol']}"
                    f" @ {a.get('price', '?')}"
                )
                if "reason" in a and isinstance(a["reason"], str):
                    lines.append(f"   └ {a['reason']}")
            await update.message.reply_text("\n".join(lines))
        return

    # Default: show status from both orchestrator and auto-trader
    orchestrator = context.bot_data.get("orchestrator")
    at_status = auto_trader.status_text()
    parts = [at_status]

    if orchestrator:
        status = orchestrator.get_status()
        parts.append(
            "⛓️ 鏈上監控\n"
            f"錢包：{'可用' if status.get('wallet_available') else '唯讀'}\n"
            f"已處理信號：{status['stats']['total_signals_processed']}\n"
            f"成功交易：{status['stats']['successful_trades']}"
        )

    await update.message.reply_text("\n\n".join(parts))


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    claude: ClaudeClient = context.bot_data["claude"]
    await update.message.chat.send_action("typing")
    today = datetime.now().strftime("%Y年%m月%d日")
    try:
        # Use auto session for today command (task type will be determined from text)
        reply, session_id = claude.chat_with_auto_session(
            update.effective_user.id,
            f"今天是 {today}，請列出今天的重要工作事項。",
        )
        await update.message.reply_text(reply)

        # Record task after successful response
        await record_conversation_task(update.effective_user.id, session_id)
    except Exception:
        logger.exception("today_command failed")
        await update.message.reply_text("發生錯誤，請稍後再試。")


async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    claude: ClaudeClient = context.bot_data["claude"]
    await update.message.chat.send_action("typing")
    try:
        # Use auto session for files command
        reply, session_id = claude.chat_with_auto_session(
            update.effective_user.id,
            "請列出 /Users/aitree414/Documents/08/HKHM 目錄的所有一級子目錄和檔案。",
        )
        await update.message.reply_text(reply)

        # Record task after successful response
        await record_conversation_task(update.effective_user.id, session_id)
    except Exception:
        logger.exception("files_command failed")
        await update.message.reply_text("發生錯誤，請稍後再試。")


async def analysis_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("用法：/analysis <股票代碼>\n\n例如：/analysis 0700")
        return
    await update.message.chat.send_action("typing")
    results = [get_stock_analysis(symbol) for symbol in context.args]
    reply_text = "\n\n---\n\n".join(results)
    await update.message.reply_text(reply_text)
    # Record task
    try:
        await record_task_from_text(update.effective_user.id, update.message.text, reply_text)
    except Exception as e:
        logger.error(f"Failed to record analysis command task: {e}")


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
    # Record task
    try:
        await record_task_from_text(update.effective_user.id, update.message.text, result)
    except Exception as e:
        logger.error(f"Failed to record scan command task: {e}")


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
        lines = ["📋 自選觀察清單（夜間回測宇宙）：\n"]
        for i, s in enumerate(symbols, 1):
            name = wl.get_name(s)
            lines.append(f"{i}. {s} {name}".rstrip())
        lines.append("\n/watch add <代碼> [名稱] — 新增\n/watch remove <代碼> — 移除\n/watch scan — 技術掃描")
        await update.message.reply_text("\n".join(lines))
        return

    sub = args[0].lower()

    if sub == "add":
        if len(args) < 2:
            await update.message.reply_text("用法：/watch add <股票代碼> [股票名稱]")
            return
        symbol = _normalize_symbol(args[1])
        name = " ".join(args[2:]) if len(args) > 2 else ""
        if wl.add(symbol, name):
            label = f"{symbol} {name}" if name else symbol
            await update.message.reply_text(f"✅ {label} 已加入自選清單，夜間回測將包含此股。")
        else:
            await update.message.reply_text(f"{symbol} 已在自選清單中。")

    elif sub == "remove":
        if len(args) < 2:
            await update.message.reply_text("用法：/watch remove <股票代碼>")
            return
        symbol = _normalize_symbol(args[1])
        if wl.remove(symbol):
            await update.message.reply_text(f"🗑 {symbol} 已從自選清單移除。")
        else:
            await update.message.reply_text(f"{symbol} 不在自選清單中。")

    elif sub == "scan":
        symbols = wl.list_symbols()
        if not symbols:
            await update.message.reply_text("自選清單是空的，無法掃描。")
            return
        await update.message.reply_text(f"掃描自選清單 ({len(symbols)} 支)，請稍候...")
        result = scan_strong_stocks(symbols=symbols, top_n=len(symbols), mode="technical")
        await update.message.reply_text(result)

    else:
        await update.message.reply_text(
            "用法：\n"
            "/watch — 查看自選清單\n"
            "/watch add <代碼> [名稱] — 加入（例：/watch add 2454 聯發科）\n"
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
    # Record task
    try:
        await record_task_from_text(update.effective_user.id, update.message.text, result)
    except Exception as e:
        logger.error(f"Failed to record poly command task: {e}")


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
    # Record task
    try:
        await record_task_from_text(update.effective_user.id, update.message.text, result)
    except Exception as e:
        logger.error(f"Failed to record poly_pick command task: {e}")


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
    reply_text = "\n\n---\n\n".join(results)
    await update.message.reply_text(reply_text)
    # Record task
    try:
        await record_task_from_text(update.effective_user.id, update.message.text, reply_text)
    except Exception as e:
        logger.error(f"Failed to record stock command task: {e}")




async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    claude: ClaudeClient = context.bot_data["claude"]
    claude.clear_memory(update.effective_user.id)
    await update.message.reply_text("對話記憶已清除！")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    claude: ClaudeClient = context.bot_data["claude"]
    await update.message.chat.send_action("typing")
    try:
        # Use auto session for all text messages
        reply, session_id = claude.chat_with_auto_session(update.effective_user.id, update.message.text)
        await update.message.reply_text(reply)

        # Record task after successful response
        await record_conversation_task(update.effective_user.id, session_id)
    except Exception:
        logger.exception("handle_text failed")
        await update.message.reply_text("發生錯誤，請稍後再試。")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    claude: ClaudeClient = context.bot_data["claude"]

    # Get largest photo
    photo = update.message.photo[-1]

    # Check file size if available
    if photo.file_size and photo.file_size > FILE_SIZE_LIMIT:
        await update.message.reply_text("圖片太大，請上傳小於 20MB 的檔案。")
        return

    await update.message.chat.send_action("typing")
    try:
        file = await context.bot.get_file(photo.file_id)
        image_data = bytes(await file.download_as_bytearray())
        reply, session_id = claude.analyze_image(
            update.effective_user.id,
            image_data,
            "image/jpeg",
            update.message.caption or "",
        )
        await update.message.reply_text(reply)

        # Record task after successful response
        await record_conversation_task(update.effective_user.id, session_id)
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
        session_id = None

        if mime_type in SUPPORTED_IMAGE_TYPES:
            reply, session_id = claude.analyze_image(
                update.effective_user.id, file_data, mime_type, caption
            )
        else:
            reply, session_id = claude.analyze_file(
                update.effective_user.id,
                file_data,
                document.file_name or "file",
                caption,
            )
        await update.message.reply_text(reply)

        # Record task after successful response if we have a session_id
        if session_id:
            await record_conversation_task(update.effective_user.id, session_id)
    except Exception:
        logger.exception("handle_document failed")
        await update.message.reply_text("檔案分析失敗，請稍後再試。")


async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a new conversation session."""
    claude: ClaudeClient = context.bot_data["claude"]
    user_id = update.effective_user.id

    task_type = None
    if context.args:
        task_type = context.args[0].lower()

    session_id = claude.create_new_session(user_id, task_type)

    await update.message.reply_text(
        f"已建立新對話 session！\n"
        f"Session ID: `{session_id}`\n\n"
        f"用 /sessions 查看所有 session\n"
        f"用 /history 查看當前 session 摘要",
        parse_mode="Markdown"
    )


async def sessions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all sessions for the user."""
    claude: ClaudeClient = context.bot_data["claude"]
    user_id = update.effective_user.id

    include_archived = False
    if context.args and context.args[0].lower() == "all":
        include_archived = True

    sessions = claude.get_user_sessions(user_id, include_archived)

    if not sessions:
        await update.message.reply_text("你目前沒有任何 session。")
        return

    lines = ["📁 你的對話 session：\n"]
    for i, session in enumerate(sessions[:10], 1):  # Limit to 10 sessions
        task_type = session.get("task_type", "general")
        created = datetime.fromtimestamp(session.get("created_at", 0)).strftime("%m/%d")
        last_active = datetime.fromtimestamp(session.get("last_activity", 0)).strftime("%m/%d %H:%M")
        msg_count = len(session.get("messages", []))

        lines.append(
            f"{i}. `{session['session_id'][:20]}...`\n"
            f"   📝 {task_type} | 📅 {created} | 💬 {msg_count} 條 | ⏰ {last_active}"
        )

    if len(sessions) > 10:
        lines.append(f"\n...還有 {len(sessions) - 10} 個 session")

    lines.append("\n用 /new 建立新 session")
    lines.append("用 /history <session_id> 查看詳細記錄")

    await update.message.reply_text("\n".join(lines))


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show history of a session."""
    claude: ClaudeClient = context.bot_data["claude"]
    user_id = update.effective_user.id

    if context.args:
        session_id = context.args[0]
    else:
        # Get current session based on last message
        # For simplicity, we'll use the most recent session
        sessions = claude.get_user_sessions(user_id)
        if not sessions:
            await update.message.reply_text("你目前沒有任何 session。")
            return
        session_id = sessions[0]["session_id"]

    summary = claude.get_session_summary(session_id)

    if "error" in summary:
        await update.message.reply_text(f"找不到 session: {session_id}")
        return

    # Get session details
    session = claude._session_manager.get_session(session_id)
    if not session:
        await update.message.reply_text("無法讀取 session 詳細資料。")
        return

    lines = [
        f"📋 Session 摘要：",
        f"ID: `{session_id}`",
        f"類型: {summary['task_type']}",
        f"建立時間: {summary['created_at']}",
        f"最後活動: {summary['last_activity']}",
        f"訊息數量: {summary['message_count']}",
    ]

    if session.metadata:
        lines.append("\n📊 元數據:")
        for key, value in session.metadata.items():
            if key not in ["user_id", "date"]:
                lines.append(f"  {key}: {value}")

    # Show recent messages (last 5)
    recent_messages = session.get_recent_messages(max_messages=5)
    if recent_messages:
        lines.append("\n💬 最近訊息:")
        for i, msg in enumerate(recent_messages[-3:], 1):  # Last 3 messages
            role_icon = "👤" if msg["role"] == "user" else "🤖"
            content_preview = str(msg["content"])[:50]
            if len(str(msg["content"])) > 50:
                content_preview += "..."
            lines.append(f"  {role_icon} {content_preview}")

    lines.append(f"\n📁 完整記錄保存在: data/sessions/{session_id}.json")

    await update.message.reply_text("\n".join(lines))


# =====================================================================
# NEW: Priority 1 — Deep Persona Analysis (/deep, /deepscan)
# =====================================================================

async def deep_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Multi-persona AI analysis for one or more stocks."""
    if not context.args:
        await update.message.reply_text(
            "用法：/deep <股票代碼>\n\n"
            "用 5 個 AI 分析師從不同角度評估一檔股票。\n"
            "範例：/deep 2330\n"
            "      /deep AAPL"
        )
        return

    await update.message.chat.send_action("typing")
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        await update.message.reply_text("錯誤：未設定 DEEPSEEK_API_KEY")
        return

    for symbol in context.args:
        await update.message.reply_text(f"🔍 正在用 5 個 AI 分析師評估 {symbol}，請稍候...")
        from .stock import _scan_single
        data = _scan_single(symbol)
        if not data:
            await update.message.reply_text(f"❌ 無法取得 {symbol} 的數據")
            continue
        result = analyze_stock(data)
        await update.message.reply_text(result["summary"])


async def deepscan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scan watchlist using multi-persona AI analysis."""
    from .stock import _scan_single, TAIWAN_WATCHLIST

    await update.message.chat.send_action("typing")
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        await update.message.reply_text("錯誤：未設定 DEEPSEEK_API_KEY")
        return

    symbols = [_normalize_symbol(s) for s in TAIWAN_WATCHLIST]
    await update.message.reply_text(f"🧠 深層 AI 掃描 {len(symbols)} 個標的，請稍候（約 30 秒）...")

    results = []
    for s in symbols:
        data = _scan_single(s)
        if data:
            r = analyze_stock(data)
            results.append(r)

    if not results:
        await update.message.reply_text("掃描失敗，無法取得數據。")
        return

    # Sort by consensus_score descending
    results.sort(key=lambda r: r["consensus_score"], reverse=True)

    lines = ["🧠 深層 AI 掃描結果（排序：最看好 → 最看淡）\n"]
    for r in results[:10]:
        icon = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(r["consensus_rating"], "⚪")
        lines.append(
            f"{icon} {r['name']} ({r['symbol']}) "
            f"{r['consensus_rating']} "
            f"信心 {r['confidence']:.0%}"
        )
    lines.append("")
    lines.append("(分析使用 DeepSeek AI，僅供參考)")
    await update.message.reply_text("\n".join(lines))

    # Also send top BUY picks in detail
    buys = [r for r in results if r["consensus_rating"] == "BUY"][:3]
    for b in buys:
        await update.message.reply_text(b["summary"])


# =====================================================================
# NEW: Priority 2 — Consolidated Portfolio Briefing (/consolidated)
# =====================================================================

async def consolidated_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unified portfolio briefing from all subsystems."""
    await update.message.chat.send_action("typing")

    # Gather stock scan data
    from .stock import _scan_single, TAIWAN_WATCHLIST
    scan_data = []
    for s in TAIWAN_WATCHLIST:
        d = _scan_single(s)
        if d:
            scan_data.append(d)

    agent: PortfolioManagerAgent = context.bot_data.get("portfolio_manager_agent")
    if not agent:
        agent = PortfolioManagerAgent()
        context.bot_data["portfolio_manager_agent"] = agent

    orchestrator = context.bot_data.get("orchestrator")
    briefing = agent.synthesize(scan_results=scan_data, orchestrator=orchestrator)

    await update.message.reply_text(briefing)


# =====================================================================
# NEW: Priority 4 — Portfolio Risk Status (/risk)
# =====================================================================

async def risk_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show portfolio risk status."""
    pm: PortfolioRiskManager = context.bot_data.get("portfolio_risk_manager")
    if not pm:
        pm = PortfolioRiskManager()
        context.bot_data["portfolio_risk_manager"] = pm
    await update.message.reply_text(pm.text_summary())


# =====================================================================
# NEW: Priority 5 — Simulated Trading (/buysim, /sellsim, /simportfolio)
# =====================================================================

async def buysim_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Record a simulated buy."""
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text("用法：/buysim <代碼> <股數> <成本價> [備註]")
        return

    symbol = _normalize_symbol(args[0])
    try:
        shares = float(args[1])
        price = float(args[2])
    except ValueError:
        await update.message.reply_text("股數和成本價必須是數字")
        return

    note = " ".join(args[3:]) if len(args) > 3 else ""
    sim_pm = context.bot_data.get("sim_portfolio")
    if not sim_pm:
        sim_pm = PortfolioManager(simulation=True)
        context.bot_data["sim_portfolio"] = sim_pm

    trade_id = sim_pm.buy(symbol, shares, price, note)
    await update.message.reply_text(
        f"🟡 *模擬* 買入記錄已儲存！(#{trade_id})\n"
        f"{symbol}  {shares:.0f} 股  @ {price:.3f}"
        + (f"\n備註：{note}" if note else ""),
        parse_mode="Markdown",
    )


async def sellsim_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Record a simulated sell."""
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text("用法：/sellsim <代碼> <股數> <賣出價>")
        return

    symbol = _normalize_symbol(args[0])
    try:
        shares = float(args[1])
        price = float(args[2])
    except ValueError:
        await update.message.reply_text("股數和賣出價必須是數字")
        return

    sim_pm = context.bot_data.get("sim_portfolio")
    if not sim_pm:
        await update.message.reply_text("尚無模擬持倉。請先用 /buysim 建立模擬部位。")
        return

    result = sim_pm.sell(symbol, shares, price)
    if not result["ok"]:
        await update.message.reply_text(f"賣出失敗：{result['error']}")
        return

    pnl = result["realized_pnl"]
    pnl_pct = result["realized_pnl_pct"]
    arrow = "▲" if pnl >= 0 else "▼"
    await update.message.reply_text(
        f"🟡 *模擬* 賣出記錄已儲存！(#{result['trade_id']})\n"
        f"{symbol}  {shares:.0f} 股  @ {price:.3f}\n\n"
        f"均成本：{result['avg_cost']:.3f}\n"
        f"已實現損益：{arrow} {abs(pnl):.2f} ({arrow}{abs(pnl_pct):.2f}%)",
        parse_mode="Markdown",
    )


async def simportfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show simulated portfolio."""
    sim_pm = context.bot_data.get("sim_portfolio")
    if not sim_pm:
        await update.message.reply_text(
            "尚無模擬持倉。\n\n用 /buysim <代碼> <股數> <成本價> 開始模擬交易。"
        )
        return

    holdings = sim_pm.list_holdings()
    if not holdings:
        await update.message.reply_text("模擬持倉是空的。")
        return

    await update.message.chat.send_action("typing")
    lines = ["🟡 模擬持倉損益\n"]
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

    lines.append("\n🟡 模擬交易 ≠ 真實持倉，僅供參考")
    await update.message.reply_text("\n".join(lines))


# =====================================================================
# Real-mode Token Mapping (/tokenmap)
# =====================================================================

async def tokenmap_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manage on-chain token address mappings for real-mode trading."""
    mapper = TokenMapper()
    args = context.args or []

    if not args:
        await update.message.reply_text(mapper.to_text())
        return

    sub = args[0].lower()

    if sub == "add":
        if len(args) < 3:
            await update.message.reply_text(
                "用法：/tokenmap add <代碼> <chain> <合約地址>\n\n"
                "範例：/tokenmap add WETH sepolia 0xfFf9976782d46CC05630D1f6eBAb18b2324d6B14\n"
                "      /tokenmap add USDC sepolia 0x...\n\n"
                "支援的 chain：ethereum, bsc, arbitrum, polygon, avalanche, sepolia"
            )
            return
        symbol = args[1].upper()
        chain = args[2].lower()
        address = args[3] if len(args) > 3 else ""

        if not address.startswith("0x") or len(address) != 42:
            await update.message.reply_text("❌ 無效的合約地址，需為 0x + 40 位十六進位")
            return

        mapper.set(symbol, chain, address)
        await update.message.reply_text(
            f"✅ 已新增代幣映射：{symbol} → {chain}:{address[:10]}..."
        )

    elif sub == "remove":
        if len(args) < 2:
            await update.message.reply_text("用法：/tokenmap remove <代碼>\n範例：/tokenmap remove WETH")
            return
        symbol = args[1].upper()
        if mapper.remove(symbol):
            await update.message.reply_text(f"🗑 已移除 {symbol} 的映射")
        else:
            await update.message.reply_text(f"找不到 {symbol} 的映射")

    elif sub == "balance":
        """Check native token balance for a mapped symbol's chain."""
        if len(args) < 2:
            await update.message.reply_text("用法：/tokenmap balance <代碼>")
            return
        symbol = args[1].upper()
        bridge = context.bot_data.get("auto_trader")
        if bridge and hasattr(bridge, "real_trade_bridge"):
            bal = bridge.real_trade_bridge.get_balance(symbol)
            if bal is not None:
                await update.message.reply_text(f"💰 {symbol} 鏈上餘額：{bal:.6f} ETH")
            else:
                await update.message.reply_text(f"❌ 無法查詢 {symbol} 餘額（無映射或錢包未就緒）")
        else:
            await update.message.reply_text("自動交易系統未初始化")

    else:
        await update.message.reply_text(
            "用法：\n"
            "/tokenmap — 檢視所有映射\n"
            "/tokenmap add <代碼> <chain> <address> — 新增映射\n"
            "/tokenmap remove <代碼> — 移除映射\n"
            "/tokenmap balance <代碼> — 查詢鏈上餘額"
        )
