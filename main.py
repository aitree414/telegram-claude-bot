import logging
import os

from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from bot.claude_client import ClaudeClient
from bot.alerts import AlertManager
from bot.watchlist import WatchlistManager
from bot.portfolio import PortfolioManager
from bot.handlers import (
    alert_command,
    alerts_command,
    analysis_command,
    buy_command,
    clear_command,
    delalert_command,
    files_command,
    handle_document,
    handle_photo,
    handle_text,
    help_command,
    history_command,
    poly_command,
    portfolio_command,
    report_command,
    scan_command,
    sell_command,
    start,
    stock_command,
    today_command,
    watch_command,
)
from bot.scheduler import setup_scheduler

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    telegram_token = os.environ["TELEGRAM_BOT_TOKEN"]
    anthropic_key = os.environ["ANTHROPIC_API_KEY"]
    try:
        reminder_chat_id = int(os.environ.get("REMINDER_CHAT_ID", "0"))
    except ValueError:
        reminder_chat_id = 0
        logger.warning("REMINDER_CHAT_ID 格式錯誤，每日提醒已停用")
    reminder_hour = int(os.environ.get("REMINDER_HOUR", "8"))

    authorized_user_id = int(os.environ.get("AUTHORIZED_USER_ID", "0"))
    claude = ClaudeClient(api_key=anthropic_key, authorized_user_id=authorized_user_id)
    alert_manager = AlertManager()
    watchlist_manager = WatchlistManager()
    portfolio_manager = PortfolioManager()

    app = Application.builder().token(telegram_token).build()
    app.bot_data["claude"] = claude
    app.bot_data["alert_manager"] = alert_manager
    app.bot_data["watchlist_manager"] = watchlist_manager
    app.bot_data["portfolio_manager"] = portfolio_manager

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("files", files_command))
    app.add_handler(CommandHandler("poly", poly_command))
    app.add_handler(CommandHandler("stock", stock_command))
    app.add_handler(CommandHandler("analysis", analysis_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(CommandHandler("watch", watch_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("sell", sell_command))
    app.add_handler(CommandHandler("portfolio", portfolio_command))
    app.add_handler(CommandHandler("alert", alert_command))
    app.add_handler(CommandHandler("alerts", alerts_command))
    app.add_handler(CommandHandler("delalert", delalert_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    if reminder_chat_id or True:  # always start scheduler for price alerts
        scheduler = setup_scheduler(app, reminder_chat_id, reminder_hour, claude, alert_manager)

        async def on_startup(application) -> None:
            scheduler.start()
            logger.info(f"每日提醒已設定：每天 {reminder_hour}:00 發送至 {reminder_chat_id}")

        app.post_init = on_startup

    logger.info("Bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
