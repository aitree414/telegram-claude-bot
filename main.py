import logging
import os
import sys

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
    new_command,
    sessions_command,
    poly_command,
    poly_pick_command,
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
from bot.repair import get_repair_manager
from bot.config import get_config

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    # Load configuration
    try:
        config = get_config()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    # Ensure required directories exist
    if not config.ensure_directories():
        logger.warning("Failed to create some directories, continuing anyway")

    # Create components
    claude = ClaudeClient(api_key=config.deepseek_api_key, authorized_user_id=config.authorized_user_id)
    alert_manager = AlertManager()
    watchlist_manager = WatchlistManager()
    portfolio_manager = PortfolioManager()

    app = Application.builder().token(config.telegram_bot_token).build()
    app.bot_data["claude"] = claude
    app.bot_data["alert_manager"] = alert_manager
    app.bot_data["watchlist_manager"] = watchlist_manager
    app.bot_data["portfolio_manager"] = portfolio_manager

    # Run automatic repair checks on startup
    repair_manager = get_repair_manager()
    if not repair_manager.run_startup_checks():
        logger.warning("Some startup checks failed, but continuing operation")

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("files", files_command))
    app.add_handler(CommandHandler("poly", poly_command))
    app.add_handler(CommandHandler("poly_pick", poly_pick_command))
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
    app.add_handler(CommandHandler("new", new_command))
    app.add_handler(CommandHandler("sessions", sessions_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Always start scheduler for price alerts (daily reminders only if chat_id > 0)
    scheduler = setup_scheduler(app, config.reminder_chat_id, config.reminder_hour, claude, alert_manager)

    async def on_startup(application) -> None:
        scheduler.start()
        if config.reminder_chat_id:
            logger.info(f"每日提醒已設定：每天 {config.reminder_hour}:00 發送至 {config.reminder_chat_id}")
        logger.info("價格提醒檢查已啟動（每5分鐘）")

    app.post_init = on_startup

    logger.info("Bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
