import json
import logging
import os
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .alerts import AlertManager
from .stock import get_current_price, _normalize_symbol, TAIWAN_WATCHLIST
from .poly_analyzer import get_ai_recommendations
from .session_manager import get_session_manager

logger = logging.getLogger(__name__)


def setup_scheduler(
    app, chat_id: int, hour: int, claude, alert_manager: AlertManager
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Hong_Kong")

    # Daily project reminder
    async def send_daily_reminder() -> None:
        today = datetime.now().strftime("%Y年%m月%d日（%A）")
        prompt = (
            f"今天是 {today}。"
            "請根據 Meet Mona Lisa 展覽項目時間表，"
            "簡短列出今天的重要工作事項和里程碑。"
            "如果今天不在工作期間，請說明並提示下個工作日。"
            "格式要簡潔，適合在 Telegram 閱讀。"
        )
        try:
            reply = claude.chat(0, prompt)
            await app.bot.send_message(
                chat_id=chat_id,
                text=f"早安！今日工作提醒 {datetime.now().strftime('%m/%d')}\n\n{reply}",
            )
        except Exception:
            logger.exception("每日提醒發送失敗")

    # Stock price alert checker (every 5 minutes)
    async def check_price_alerts() -> None:
        pending = alert_manager.get_pending()
        if not pending:
            return

        for alert in pending:
            try:
                price = get_current_price(alert["symbol"])
                if price is None:
                    continue

                triggered = (
                    alert["condition"] == "above" and price >= alert["target"]
                ) or (
                    alert["condition"] == "below" and price <= alert["target"]
                )

                if triggered:
                    symbol = _normalize_symbol(alert["symbol"])
                    direction = "突破" if alert["condition"] == "above" else "跌破"
                    msg = (
                        f"股價提醒！\n\n"
                        f"{symbol} 已{direction}目標價 {alert['target']}\n"
                        f"現價：{price:.3f}"
                    )
                    await app.bot.send_message(chat_id=alert["user_id"], text=msg)
                    alert_manager.mark_triggered(alert["id"])
            except Exception:
                logger.exception(f"檢查提醒失敗：{alert}")

    async def send_poly_picks() -> None:
        if not chat_id:
            return
        try:
            api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
            result = get_ai_recommendations(api_key, top_n=5)
            await app.bot.send_message(chat_id=chat_id, text=result)
        except Exception:
            logger.exception("Polymarket 每日推薦發送失敗")

    async def archive_old_sessions() -> None:
        """Archive sessions older than 30 days."""
        try:
            session_manager = get_session_manager()
            archived_count = session_manager.archive_old_sessions()
            if archived_count > 0:
                logger.info(f"已歸檔 {archived_count} 個舊 session")
        except Exception:
            logger.exception("Session 歸檔失敗")

    # AI 投資委員會每日報告推播
    COMMITTEE_FILE = Path(__file__).resolve().parent.parent / "data" / "committee" / "daily_signals.json"

        # Committee trader cycle (executes trades based on committee signals)
    async def committee_trader_cycle() -> None:
        committee_trader = app.bot_data.get("committee_trader")
        if not committee_trader:
            return
        try:
            actions = committee_trader.run_cycle()
            if actions:
                logger.info("Committee trader: %d action(s)", len(actions))
                if chat_id:
                    lines = ["📊 AI 委員會自動交易執行：\n"]
                    for a in actions:
                        if a["action"] == "BUY":
                            lines.append(f"  🟢 買入 {a['name']} ({a['symbol']}) x{a['shares']} @ {a['price']:.2f}")
                        elif a["action"] == "SELL":
                            lines.append(f"  🔴 賣出 {a['name']} ({a['symbol']}) x{a['shares']} @ {a['price']:.2f}")
                        elif a["action"] == "BLOCKED":
                            lines.append(f"  ⚠️ 阻擋 {a['name']} ({a['symbol']})：{a.get('reason', '')}")
                    await app.bot.send_message(chat_id=chat_id, text="\n".join(lines))
        except Exception:
            logger.exception("Committee trader cycle failed")

    async def send_committee_report() -> None:
        if not chat_id:
            return
        if not COMMITTEE_FILE.exists():
            logger.warning("委員會報告不存在：%s", COMMITTEE_FILE)
            return
        try:
            data = json.loads(COMMITTEE_FILE.read_text())
            summary = data.get("summary", {})
            date_str = data.get("date", "未知")

            # 分類標題與 emoji
            signals = []
            if summary.get("strong_buy_count"):
                names = [s["name"] for s in summary.get("strong_buys", [])]
                signals.append(f"🟢 強力買入 {summary['strong_buy_count']} 檔：{'、'.join(names[:5])}")
            if summary.get("buy_count"):
                names = [s["name"] for s in summary.get("buys", [])]
                signals.append(f"🔵 買入 {summary['buy_count']} 檔：{'、'.join(names[:5])}")
            if summary.get("hold_count"):
                signals.append(f"⚪ 持有 {summary['hold_count']} 檔")
            if summary.get("sell_count"):
                names = [s["name"] for s in summary.get("sells", [])]
                signals.append(f"🔴 賣出 {summary['sell_count']} 檔：{'、'.join(names[:5])}")
            if summary.get("strong_sell_count"):
                names = [s["name"] for s in summary.get("strong_sells", [])]
                signals.append(f"⛔ 強力賣出 {summary['strong_sell_count']} 檔：{'、'.join(names[:5])}")
            if summary.get("error_count"):
                signals.append(f"⚠️ 分析失敗 {summary['error_count']} 檔")

            msg = (
                f"🤖 AI 投資委員會報告 ({date_str})\n"
                f"{'─' * 20}\n"
                f"{chr(10).join(signals)}\n"
                f"{'─' * 20}\n"
                f"詳情請見 Dashboard：http://localhost:8888"
            )
            await app.bot.send_message(chat_id=chat_id, text=msg)
            logger.info("委員會報告已推播至 %s", chat_id)
        except Exception:
            logger.exception("委員會報告推播失敗")

    # Auto-trader cycle (closes the analysis→execution loop)
    async def auto_trader_cycle() -> None:
        auto_trader = app.bot_data.get("auto_trader")
        if not auto_trader or not auto_trader.is_enabled:
            return
        try:
            symbols = [_normalize_symbol(s) for s in TAIWAN_WATCHLIST]
            actions = await auto_trader.run_cycle(symbols)
            if actions:
                logger.info(f"Auto-trader: {len(actions)} action(s)")
                if chat_id:
                    lines = ["🤖 自動交易執行：\n"]
                    for a in actions:
                        lines.append(f"  {a['action']} {a['symbol']} @ {a.get('price','?')}")
                    await app.bot.send_message(chat_id=chat_id, text="\n".join(lines))
        except Exception:
            logger.exception("Auto-trader cycle failed")

    async def polymarket_heartbeat_cycle() -> None:
        heartbeat = app.bot_data.get("polymarket_heartbeat")
        if not heartbeat:
            return
        try:
            result = await heartbeat.beat()
            if result.has_events:
                logger.info("Heartbeat: %s", result.summary_log())
        except Exception:
            logger.exception("Polymarket heartbeat cycle failed")

    async def polymarket_copy_trade_cycle() -> None:
        copy_trader = app.bot_data.get("copy_trader")
        if not copy_trader or not copy_trader.is_enabled:
            return
        try:
            trades = copy_trader.run_cycle()
            if trades:
                logger.info("Copy trader: %d trade(s)", len(trades))
                if chat_id:
                    lines = ["👤 複製交易執行：\n"]
                    for t in trades[:5]:
                        lines.append(f"  {t['side']} {t['outcome']} x{t['size']} @ ${t['price']:.4f}")
                    await app.bot.send_message(chat_id=chat_id, text="\n".join(lines))
        except Exception:
            logger.exception("Copy trade cycle failed")

    if chat_id:
        scheduler.add_job(send_daily_reminder, "cron", hour=hour, minute=0)
        scheduler.add_job(send_poly_picks, "cron", hour=9, minute=30)
        scheduler.add_job(send_committee_report, "cron", hour=7, minute=35, day_of_week="mon-fri")
        scheduler.add_job(committee_trader_cycle, "cron", hour=7, minute=40, day_of_week="mon-fri")
    scheduler.add_job(check_price_alerts, "interval", minutes=5)
    scheduler.add_job(archive_old_sessions, "cron", hour=3, minute=0)  # Daily at 3 AM

    # Auto-trader (interval from config, default 60 min)
    from manager.auto_trader import AutoTraderConfig
    _ac = AutoTraderConfig()
    scheduler.add_job(auto_trader_cycle, "interval", minutes=_ac.interval_minutes)

    # Polymarket heartbeat (if enabled)
    if os.environ.get("POLYMARKET_HEARTBEAT_ENABLED", "false").lower() == "true":
        interval = int(os.environ.get("POLYMARKET_SCAN_INTERVAL", "60"))
        scheduler.add_job(polymarket_heartbeat_cycle, "interval", minutes=interval)
        logger.info("Polymarket heartbeat scheduled (every %d min)", interval)

    # Polymarket copy trading (if enabled)
    if os.environ.get("POLYCOPY_ENABLED", "false").lower() == "true":
        interval = int(os.environ.get("POLYCOPY_SCAN_INTERVAL", "15"))
        scheduler.add_job(polymarket_copy_trade_cycle, "interval", minutes=interval)
        logger.info("Polymarket copy trader scheduled (every %d min)", interval)

    return scheduler
