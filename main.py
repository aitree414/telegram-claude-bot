import asyncio
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
    autotrade_command,
    buy_command,
    buysim_command,
    clear_command,
    consolidated_command,
    deep_command,
    deepscan_command,
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
    risk_command,
    scan_command,
    sell_command,
    sellsim_command,
    simportfolio_command,
    start,
    stock_command,
    today_command,
    tokenmap_command,
    watch_command,
)
from bot.scheduler import setup_scheduler
from bot.repair import get_repair_manager
from onchain.orchestrator import TradeOrchestrator
from bot.config import get_config
from manager.portfolio_manager_agent import PortfolioManagerAgent
from manager.portfolio_risk import PortfolioRiskManager
from manager.auto_trader import AutoTrader
from manager.real_trader_bridge import RealTradeBridge

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
    orchestrator = TradeOrchestrator()

    app = Application.builder().token(config.telegram_bot_token).build()
    app.bot_data["claude"] = claude
    app.bot_data["alert_manager"] = alert_manager
    app.bot_data["watchlist_manager"] = watchlist_manager
    app.bot_data["portfolio_manager"] = portfolio_manager
    app.bot_data["orchestrator"] = orchestrator

    # New components (Priority 2 & 4)
    portfolio_manager_agent = PortfolioManagerAgent()
    portfolio_risk_manager = PortfolioRiskManager()
    sim_portfolio = PortfolioManager(simulation=True)
    app.bot_data["portfolio_manager_agent"] = portfolio_manager_agent
    app.bot_data["portfolio_risk_manager"] = portfolio_risk_manager
    app.bot_data["sim_portfolio"] = sim_portfolio

    # Auto-trader (Priority 6 — closes the analysis→execution loop)
    real_trade_bridge = RealTradeBridge(orchestrator=orchestrator)
    auto_trader = AutoTrader(
        sim_portfolio=sim_portfolio,
        risk_manager=portfolio_risk_manager,
        real_trade_bridge=real_trade_bridge,
    )
    app.bot_data["auto_trader"] = auto_trader

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
    app.add_handler(CommandHandler("autotrade", autotrade_command))
    app.add_handler(CommandHandler("tokenmap", tokenmap_command))

    # New commands (Priority 1 — Deep Persona Analysis)
    app.add_handler(CommandHandler("deep", deep_command))
    app.add_handler(CommandHandler("deepscan", deepscan_command))

    # New command (Priority 2 — Consolidated Portfolio)
    app.add_handler(CommandHandler("consolidated", consolidated_command))

    # New command (Priority 4 — Risk Status)
    app.add_handler(CommandHandler("risk", risk_command))

    # New commands (Priority 5 — Simulated Trading)
    app.add_handler(CommandHandler("buysim", buysim_command))
    app.add_handler(CommandHandler("sellsim", sellsim_command))
    app.add_handler(CommandHandler("simportfolio", simportfolio_command))

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

        # Start auto-trade orchestrator in background (read-only monitoring)
        asyncio.create_task(
            orchestrator.start_continuous_processing(),
            name="orchestrator"
        )
        logger.info("自動交易監控引擎已啟動（唯讀模式，BSC 鏈）")
        if auto_trader.is_enabled:
            logger.info(f"🤖 自動交易引擎已啟用（間隔：{auto_trader.config.interval_minutes} 分鐘）")

    async def on_shutdown(application) -> None:
        await orchestrator.stop_continuous_processing()
        logger.info("自動交易監控引擎已停止")

    app.post_init = on_startup
    app.post_shutdown = on_shutdown

    logger.info("Bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
