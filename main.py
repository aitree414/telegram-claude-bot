import asyncio
import logging
import os
import ssl
import sys
from pathlib import Path

# Fix SSL for macOS LibreSSL (Polymarket CLOB, etc.)
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except Exception:
    pass

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
    committee_command,
    consolidated_command,
    cookies_command,
    copy_command,
    deep_command,
    deepscan_command,
    delalert_command,
    fetch_command,
    files_command,
    handle_document,
    handle_photo,
    handle_text,
    health_command,
    help_command,
    history_command,
    new_command,
    sessions_command,
    poly_command,
    poly_pick_command,
    polymarket_command,
    portfolio_command,
    read_command,
    ls_command,
    report_command,
    risk_command,
    scan_command,
    sell_command,
    sellsim_command,
    simportfolio_command,
    daybuy_command,
    daysell_command,
    daytrade_command,
    dayideas_command,
    dayautotrade_command,
    dayreview_command,
    start,
    research_command,
    stock_command,
    today_command,
    tokenmap_command,
    market_command,
    performance_command,
    watch_command,
)
from bot.scheduler import setup_scheduler
from bot.repair import get_repair_manager
from onchain.orchestrator import TradeOrchestrator
from bot.config import get_config
from manager.portfolio_manager_agent import PortfolioManagerAgent
from broker.sino_bridge import SinoBridge
from broker.options_trader import OptionsTrader
from manager.portfolio_risk import PortfolioRiskManager
from manager.auto_trader import AutoTrader
from manager.committee_trader import CommitteeTrader
from manager.crypto_committee_trader import CryptoCommitteeTrader
from manager.real_trader_bridge import RealTradeBridge
from manager.polymarket_trader import PolymarketTrader
from manager.polymarket_heartbeat import PolymarketHeartbeat
from manager.copy_trader import CopyTrader
from manager.poly_whale_watcher import WhaleWatcher
from manager.day_trader_sim import DayTraderSim
from manager.day_auto_trader import DayAutoTrader

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
    claude = ClaudeClient(api_key=config.api_key, authorized_user_id=config.authorized_user_id)
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

    # 當沖模擬 (Day Trading Simulation, separate fund)
    day_trader_sim = DayTraderSim()
    app.bot_data["day_trader_sim"] = day_trader_sim
    logger.info("⚡ 當沖模擬系統已載入（資金 NT$%.0f）", day_trader_sim.get_cash())

    # 當沖自動交易引擎 (Day Auto-Trader) — 獨立 risk manager 狀態檔
    day_risk_dir = Path(__file__).resolve().parent / "data" / "day_risk"
    day_risk_dir.mkdir(parents=True, exist_ok=True)
    day_risk_manager = PortfolioRiskManager(data_dir=day_risk_dir)
    day_auto_trader = DayAutoTrader(
        day_trader_sim=day_trader_sim,
        risk_manager=day_risk_manager,
    )
    app.bot_data["day_auto_trader"] = day_auto_trader
    if day_auto_trader.is_enabled:
        logger.info("⚡ 當沖自動交易引擎已啟用（間隔：%d 分鐘）", day_auto_trader.config.interval_minutes)

    # 永豐金證券 broker bridge (simulation mode until API key is set)
    sino_bridge = SinoBridge(simulation=True)
    app.bot_data["sino_bridge"] = sino_bridge
    logger.info(f"🏦 永豐金證券橋接器已載入（模式：{'模擬' if sino_bridge.simulation else '正式'}）")

    # Auto-trader (Priority 6 — closes the analysis→execution loop)
    real_trade_bridge = RealTradeBridge(orchestrator=orchestrator)
    auto_trader = AutoTrader(
        sim_portfolio=sim_portfolio,
        risk_manager=portfolio_risk_manager,
        real_trade_bridge=real_trade_bridge,
        broker=sino_bridge,
    )
    app.bot_data["auto_trader"] = auto_trader

    # 台指選擇權交易員（獨立 10 萬模擬帳戶）
    options_trader = OptionsTrader(initial_capital=100_000)
    app.bot_data["options_trader"] = options_trader
    logger.info(f"📊 台指選擇權交易員已載入（NT$100,000 模擬帳戶）")

    # AI 投資委員會自動交易
    committee_trader = CommitteeTrader(
        sim_portfolio=sim_portfolio,
        risk_manager=portfolio_risk_manager,
    )
    app.bot_data["committee_trader"] = committee_trader
    logger.info("AI 委員會自動交易引擎已載入")

    # Web3 加密貨幣委員會自動交易（透過 RealTradeBridge 執行鏈上交易）
    crypto_committee_trader = CryptoCommitteeTrader(
        real_trade_bridge=real_trade_bridge,
    )
    app.bot_data["crypto_committee_trader"] = crypto_committee_trader
    logger.info("Web3 加密貨幣委員會自動交易引擎已載入")

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
    app.add_handler(CommandHandler("research", research_command))
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
    app.add_handler(CommandHandler("performance", performance_command))
    app.add_handler(CommandHandler("market", market_command))

    # Polymarket auto-trader (Phase 1: CLOB execution + NEH + PairArb)
    polymarket_trader = PolymarketTrader(risk_manager=portfolio_risk_manager)
    app.bot_data["polymarket_trader"] = polymarket_trader

    # PolymarketHeartbeat (Phase 3a — scheduled scanning + price alerts)
    polymarket_heartbeat = PolymarketHeartbeat(
        trader=polymarket_trader,
        app=app,
        chat_id=config.reminder_chat_id,
    )
    app.bot_data["polymarket_heartbeat"] = polymarket_heartbeat

    # CopyTrader — mirrors Polymarket trades from leader wallets
    app.bot_data["copy_trader"] = CopyTrader()

    app.add_handler(CommandHandler("polymarket", polymarket_command))
    app.add_handler(CommandHandler("copy", copy_command))

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
    app.add_handler(CommandHandler("daybuy", daybuy_command))
    app.add_handler(CommandHandler("daysell", daysell_command))
    app.add_handler(CommandHandler("daytrade", daytrade_command))
    app.add_handler(CommandHandler("dayideas", dayideas_command))
    app.add_handler(CommandHandler("dayautotrade", dayautotrade_command))
    app.add_handler(CommandHandler("dayreview", dayreview_command))
    app.add_handler(CommandHandler("committee", committee_command))
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(CommandHandler("fetch", fetch_command))
    app.add_handler(CommandHandler("cookies", cookies_command))
    app.add_handler(CommandHandler("read", read_command))
    app.add_handler(CommandHandler("ls", ls_command))

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

        # Whale watcher — discover Polymarket whales on startup
        async def _startup_whale_discovery():
            try:
                watcher = WhaleWatcher()
                whales = await watcher.discover()
                logger.info("Whale watcher startup: discovered %d whales", len(whales))
            except Exception as e:
                logger.warning("Whale watcher startup discovery skipped: %s", e)

        asyncio.create_task(_startup_whale_discovery(), name="whale-discovery")

        # Committee trader: fire an immediate scan FIRST (concrete signals take priority)
        async def _committee_startup_scan():
            try:
                ct = app.bot_data.get("committee_trader")
                if ct:
                    actions = ct.run_cycle()
                    if actions:
                        logger.info("Committee startup: %d action(s)", len(actions))
                    else:
                        logger.info("Committee startup: no trades triggered")
            except Exception as e:
                logger.warning("Committee startup scan skipped: %s", e)
        asyncio.create_task(_committee_startup_scan(), name="committee-startup-scan")

        # Auto-trader: fire an immediate scan after committee (uses remaining budget)
        if auto_trader.is_enabled:
            async def _startup_scan():
                try:
                    from bot.stock import TAIWAN_WATCHLIST, US_WATCHLIST, resolve_stock_symbol
                    symbols = [resolve_stock_symbol(s) for s in TAIWAN_WATCHLIST + US_WATCHLIST]
                    actions = await auto_trader.run_cycle(symbols)
                    if actions:
                        logger.info("Startup scan: %d action(s)", len(actions))
                    else:
                        logger.info("Startup scan: no trades triggered")

                    # Also feed results to options trader
                    o_trader = app.bot_data.get("options_trader")
                    if o_trader:
                        import yfinance as yf
                        twii = yf.Ticker("^TWII")
                        hist = twii.history(period="1d")
                        idx = float(hist["Close"].iloc[-1]) if not hist.empty else 0.0
                        o_msgs = o_trader.evaluate_and_trade(actions or [], idx)
                        if o_msgs:
                            logger.info("Options trader startup: %d action(s)", len(o_msgs))
                except Exception as e:
                    logger.warning("Startup scan skipped: %s", e)
            asyncio.create_task(_startup_scan(), name="auto-trader-startup-scan")

    async def on_shutdown(application) -> None:
        await orchestrator.stop_continuous_processing()
        logger.info("自動交易監控引擎已停止")

    app.post_init = on_startup
    app.post_shutdown = on_shutdown

    logger.info("Bot started!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
