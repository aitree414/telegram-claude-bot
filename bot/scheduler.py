import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .alerts import AlertManager
from .stock import get_current_price, _normalize_symbol

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

    if chat_id:
        scheduler.add_job(send_daily_reminder, "cron", hour=hour, minute=0)
    scheduler.add_job(check_price_alerts, "interval", minutes=5)
    return scheduler
