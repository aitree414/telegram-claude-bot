import json
import logging
import os
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .alerts import AlertManager
from .stock import get_current_price, _normalize_symbol, TAIWAN_WATCHLIST, US_WATCHLIST
from .poly_analyzer import get_ai_recommendations
from .session_manager import get_session_manager
from analysis.persona_tracker import PersonaTracker

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

    # Stop-loss / take-profit auto-check (every 5 minutes)
    async def check_stop_loss_alerts() -> None:
        try:
            pm = app.bot_data.get("sim_portfolio")
            if not pm:
                return
            sl_mgr = pm.stop_loss_manager
            active = sl_mgr.list_active()
            if not active:
                return

            symbols = list({i["symbol"] for i in active})
            prices = {}
            for sym in symbols:
                price = get_current_price(sym)
                if price is not None:
                    prices[sym] = price

            triggered = sl_mgr.check(prices)
            for t in triggered:
                sym = t["symbol"]
                tp = t["_triggered_price"]
                tp_label = "停損" if t["type"] == "sl" else "停利"
                shares = t["shares"]
                # Auto-sell the triggered position
                result = pm.sell(sym, shares, tp)
                if result.get("ok"):
                    # Notify risk manager so P&L tracking is accurate
                    risk_mgr = app.bot_data.get("risk_manager")
                    if risk_mgr:
                        risk_mgr.record_trade(is_stock=True, pnl=result.get("realized_pnl", 0))
                    msg = (
                        f"⚠️ {tp_label}自動執行！\n\n"
                        f"{sym} @ {tp:.2f} x {shares} 股\n"
                        f"已實現損益：{result['realized_pnl']:+.2f} ({result['realized_pnl_pct']:+.2f}%)"
                    )
                else:
                    msg = (
                        f"⚠️ {tp_label}觸發但賣出失敗：{result.get('error', '')}\n\n"
                        f"{sym} 觸發價 {t['trigger_price']}，現價 {tp:.2f}"
                    )
                # Notify via Telegram if chat_id available
                if chat_id:
                    await app.bot.send_message(chat_id=chat_id, text=msg)
        except Exception:
            logger.exception("停損/停利檢查失敗")

    # Daily portfolio performance snapshot + integrity check (every day at 16:30)
    async def record_daily_performance() -> None:
        try:
            pm = app.bot_data.get("sim_portfolio")
            if not pm or pm.get_initial_capital() <= 0:
                return

            holdings = pm.list_holdings()
            total_holdings_value = 0.0
            for h in holdings:
                price = get_current_price(h["symbol"])
                if price is not None:
                    total_holdings_value += h["net_shares"] * price

            futures_list = pm.list_futures()
            futures_upnl = sum(f.get("unrealized_pnl", 0) for f in futures_list)

            cash = pm.get_cash()
            # realized_pnl = total pnl from closed positions (already in cash)
            holdings_cost = sum(h["net_shares"] * h["avg_cost"] for h in holdings)
            realized_pnl = cash + holdings_cost - pm.get_initial_capital()

            # Record performance snapshot
            pm.performance_tracker.record_snapshot(
                initial_capital=pm.get_initial_capital(),
                cash=cash,
                holdings_value=total_holdings_value,
                realized_pnl=realized_pnl,
                futures_upnl=futures_upnl,
            )

            # Portfolio integrity check
            integrity = pm.verify_integrity()
            if not integrity["ok"]:
                logger.error("❌ 組合 integrity 異常:\n" + "\n".join(f"  - {i}" for i in integrity["issues"]))
            else:
                logger.info("✅ 組合 integrity 通過")

            # Daily reconciliation report
            concentration_pct = integrity.get("holdings_concentration", {})
            top3 = sorted(concentration_pct.items(), key=lambda x: -x[1])[:3]
            concentration_str = ", ".join(f"{s}={p}%" for s, p in top3) if top3 else "無"

            logger.info(
                "📊 每日對帳 ──────────────────\n"
                f"   initial_capital: ${integrity['equity'] - integrity['realized_pnl']:>10,.2f}\n"
                f"   equity:          ${integrity['equity']:>10,.2f}\n"
                f"   cash:            ${integrity['cash']:>10,.2f}\n"
                f"   holdings:        ${integrity['holdings_value']:>10,.2f} ({integrity['holdings_count']}檔)\n"
                f"   realized_pnl:    ${integrity['realized_pnl']:>+10,.2f}\n"
                f"   trades_total:    {integrity['total_trades']:>10}\n"
                f"   top3集中度:       {concentration_str}\n"
                f"   integrity:       {'✅ OK' if integrity['ok'] else '❌ 異常'}\n"
                f"  ────────────────────────────"
            )
        except Exception:
            logger.exception("記錄績效快照失敗")

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

            # Feed to options trader
            options_trader = app.bot_data.get("options_trader")
            if options_trader:
                try:
                    import yfinance as yf
                    twii = yf.Ticker("^TWII")
                    hist = twii.history(period="1d")
                    if not hist.empty:
                        idx = float(hist["Close"].iloc[-1])
                    else:
                        idx = 0.0
                    o_msgs = options_trader.evaluate_and_trade(actions or [], idx)
                    if o_msgs:
                        logger.info("Options trader: %d signal(s) from committee", len(o_msgs))
                        if chat_id:
                            await app.bot.send_message(
                                chat_id=chat_id,
                                text="📊 期權訊號（委員會）：\n" + "\n".join(o_msgs)
                            )
                except Exception:
                    logger.exception("Committee options trader cycle failed")
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
            symbols = [_normalize_symbol(s) for s in TAIWAN_WATCHLIST + US_WATCHLIST]
            actions = await auto_trader.run_cycle(symbols)
            if actions:
                logger.info(f"Auto-trader: {len(actions)} action(s)")
                if chat_id:
                    lines = ["🤖 自動交易執行：\n"]
                    for a in actions:
                        lines.append(f"  {a['action']} {a['symbol']} @ {a.get('price','?')}")
                    await app.bot.send_message(chat_id=chat_id, text="\n".join(lines))

            # Feed results to options trader for market sentiment
            options_trader = app.bot_data.get("options_trader")
            if options_trader:
                try:
                    import yfinance as yf
                    twii = yf.Ticker("^TWII")
                    hist = twii.history(period="1d")
                    if not hist.empty:
                        idx = float(hist["Close"].iloc[-1])
                    else:
                        idx = 0.0
                    msgs = options_trader.evaluate_and_trade(actions or [], idx)
                    if msgs:
                        logger.info(f"Options trader: {len(msgs)} action(s)")
                        if chat_id:
                            await app.bot.send_message(
                                chat_id=chat_id,
                                text="📊 期權訊號：\n" + "\n".join(msgs)
                            )
                except Exception:
                    logger.exception("Options trader cycle failed")
        except Exception:
            logger.exception("Auto-trader cycle failed")

    async def check_prediction_outcomes() -> None:
        """Daily: compare unverified persona predictions against current prices."""
        auto_trader = app.bot_data.get("auto_trader")
        if not auto_trader:
            return
        tracker = auto_trader.persona_tracker
        if tracker.verified_predictions == tracker.total_predictions:
            logger.debug("No unverified predictions to check")
            return

        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        checked = 0
        for r in tracker._records:
            if r.outcome_checked:
                continue
            # Only check predictions older than 1 day
            try:
                ts = datetime.fromisoformat(r.timestamp)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if (now - ts).total_seconds() < 86400:
                continue

            price = get_current_price(r.symbol)
            if price is None or price <= 0 or r.price <= 0:
                continue

            change = (price - r.price) / r.price
            correct = False
            if r.rating == "BUY":
                correct = change > 0.015  # need > 1.5% up
            elif r.rating == "SELL":
                correct = change < -0.015  # need > 1.5% down
            elif r.rating == "HOLD":
                correct = abs(change) < 0.02  # within ±2%

            tracker.record_outcome(
                r.persona, r.symbol,
                "correct" if correct else "wrong",
                price,
            )
            checked += 1

        if checked:
            weights = tracker.get_weights()
            logger.info(
                f"Prediction check: {checked} verified, "
                f"weights: {weights}"
            )

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

    # Daily market news briefing (週一至五 8:30 AM)
    async def send_market_news_briefing() -> None:
        """Fetch top market news and send a concise briefing."""
        import urllib.request
        import urllib.parse
        import xml.etree.ElementTree as ET

        queries = ["台股 今日 重點", "美股 行情", "台股 盤前"]
        headlines: list[str] = []
        seen: set[str] = set()
        for q in queries:
            try:
                url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
                    {"q": q, "hl": "zh-TW", "gl": "TW"}
                )
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    root = ET.fromstring(resp.read())
                for item in root.iter("item"):
                    title = item.findtext("title", "")
                    if title and title not in seen:
                        seen.add(title)
                        headlines.append(title)
            except Exception:
                continue

        if not headlines:
            return

        lines = ["📰 盤前新聞重點\n"]
        for h in headlines[:10]:
            lines.append(f"• {h}")
        text = "\n".join(lines)
        try:
            # Try to send in chunks if too long
            if len(text) > 4000:
                text = text[:4000] + "\n\n...(truncated)"
            await app.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception("盤前新聞發送失敗")

    if chat_id:
        scheduler.add_job(send_daily_reminder, "cron", hour=hour, minute=0)
        scheduler.add_job(send_poly_picks, "cron", hour=9, minute=30)
        scheduler.add_job(send_committee_report, "cron", hour=7, minute=35, day_of_week="mon-fri")
        scheduler.add_job(send_market_news_briefing, "cron", hour=8, minute=30, day_of_week="mon-fri")
        scheduler.add_job(committee_trader_cycle, "cron", hour=9, minute=30, day_of_week="mon-fri")

        # Web3 加密貨幣委員會自動交易（7:45 AM，股票之後）
        async def crypto_committee_trader_cycle() -> None:
            crypto_trader = app.bot_data.get("crypto_committee_trader")
            if not crypto_trader:
                return
            try:
                actions = await crypto_trader.run_cycle()
                if actions:
                    logger.info("Crypto committee trader: %d action(s)", len(actions))
                    if chat_id:
                        lines = ["🔮 Web3 加密貨幣委員會自動交易執行：\n"]
                        for a in actions:
                            if a["action"] == "BUY":
                                lines.append(f"  🟢 買入 {a['name']} ({a['symbol']}) {a.get('amount_eth', '?')} ETH")
                            elif a["action"] == "SELL":
                                lines.append(f"  🔴 賣出 {a['name']} ({a['symbol']})")
                            elif a["action"] == "BLOCKED":
                                lines.append(f"  ⚠️ 阻擋 {a['name']} ({a['symbol']})：{a.get('reason', '')}")
                            elif a["action"] == "FAILED":
                                lines.append(f"  ❌ 失敗 {a['name']} ({a['symbol']})：{a.get('reason', '')}")
                        await app.bot.send_message(chat_id=chat_id, text="\n".join(lines))
            except Exception:
                logger.exception("Crypto committee trader cycle failed")

        scheduler.add_job(crypto_committee_trader_cycle, "cron", hour=7, minute=45, day_of_week="mon-fri")
    # ── 鏈上持倉停損/停利監控 (每 15 分鐘) ──────────────────────────────────
    async def check_onchain_sl_tp() -> None:
        """Monitor open on-chain positions for stop-loss/take-profit triggers."""
        try:
            from onchain.database import get_onchain_database, Trade, TradeStatus
            from web3 import Web3
            from web3.middleware import ExtraDataToPOAMiddleware
            from onchain.dex_client import DEXClientFactory
            from bot.config_web3 import get_web3_config
            from manager.real_trader_bridge import TokenMapper

            config = get_web3_config()
            db = get_onchain_database()
            session = db.get_session()

            # Open positions = COMPLETED BUY trades
            trades = session.query(Trade).filter(
                Trade.status == TradeStatus.COMPLETED,
                Trade.trade_type == 'BUY',
            ).all()
            if not trades:
                session.close()
                return

            w3 = Web3(Web3.HTTPProvider(config.get_rpc_url('polygon') or 'https://polygon.drpc.org'))
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

            dex = DEXClientFactory.create_client('quickswap', w3, config)
            if not dex:
                session.close()
                return

            token_map = TokenMapper()
            usdc = '0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359'
            usdc_decimals = 6

            triggered = []
            for trade in trades:
                token_addr = trade.token_address
                amt_token = trade.amount_token or 0
                amt_spent = trade.amount_eth or 0
                if not token_addr or amt_token <= 0 or amt_spent <= 0:
                    continue

                # Look up output token decimals from token_map
                sym = trade.token_symbol or ''
                mapping = token_map.get(sym)
                out_decimals = (mapping.get('decimals', 18) if mapping else 18)

                # Get current price via DEX: how much token 1 USDC buys
                output_amount, _ = dex.get_price(
                    usdc, token_addr, 1.0,
                    token_in_decimals=usdc_decimals,
                    token_out_decimals=out_decimals,
                )
                if output_amount is None or output_amount <= 0:
                    continue

                # output_amount = WBTC per 1 USDC → WBTC price in USDC = 1 / output_amount
                current_price_per_token = 1.0 / output_amount

                # Effective entry price per token (USDC per token)
                entry_price_per_token = amt_spent / amt_token

                if entry_price_per_token <= 0:
                    continue

                # P&L percent
                pnl_pct = (current_price_per_token - entry_price_per_token) / entry_price_per_token * 100

                # SL/TP thresholds from trade record or config defaults
                sl_threshold = (abs(trade.stop_loss) if trade.stop_loss else config.stop_loss_pct) * 100
                tp_threshold = (trade.take_profit if trade.take_profit else config.take_profit_pct) * 100

                if pnl_pct <= -sl_threshold:
                    triggered.append({
                        'trade_id': trade.id,
                        'symbol': trade.token_symbol or '?',
                        'type': 'stop_loss',
                        'entry': entry_price_per_token,
                        'current': current_price_per_token,
                        'pnl_pct': round(pnl_pct, 1),
                        'threshold': sl_threshold,
                    })
                elif pnl_pct >= tp_threshold:
                    triggered.append({
                        'trade_id': trade.id,
                        'symbol': trade.token_symbol or '?',
                        'type': 'take_profit',
                        'entry': entry_price_per_token,
                        'current': current_price_per_token,
                        'pnl_pct': round(pnl_pct, 1),
                        'threshold': tp_threshold,
                    })

                # Update current_price and pnl in DB
                trade.current_price = current_price_per_token
                trade.pnl_eth = (current_price_per_token - entry_price_per_token) * amt_token
                trade.pnl_percent = pnl_pct / 100
                session.commit()

            session.close()

            if triggered and chat_id:
                lines = ["⚠️ 鏈上持倉警報！\n"]
                for t in triggered:
                    direction = "🔴 停損" if t['type'] == 'stop_loss' else "🟢 停利"
                    lines.append(f"{direction} {t['symbol']}")
                    lines.append(f"  買入 ${t['entry']:.2f} → 現價 ${t['current']:.2f}")
                    lines.append(f"  損益 {t['pnl_pct']:.1f}% (閾值 {t['threshold']:.0f}%)")
                    lines.append("")
                await app.bot.send_message(chat_id=chat_id, text="\n".join(lines))

        except Exception:
            logger.exception("On-chain SL/TP check failed")

    scheduler.add_job(check_onchain_sl_tp, "interval", minutes=15)
    scheduler.add_job(check_price_alerts, "interval", minutes=5)
    scheduler.add_job(check_stop_loss_alerts, "interval", minutes=5)
    scheduler.add_job(archive_old_sessions, "cron", hour=3, minute=0)  # Daily at 3 AM
    scheduler.add_job(record_daily_performance, "cron", hour=16, minute=30)  # Daily snapshot
    scheduler.add_job(check_prediction_outcomes, "cron", hour=18, minute=0)   # 收盤後驗證預測

    # Auto-tuner: weekly threshold adjustment based on prediction accuracy
    async def auto_tuner_cycle() -> None:
        auto_trader = app.bot_data.get("auto_trader")
        if not auto_trader:
            return
        try:
            from analysis.auto_tuner import AutoTuner
            tuner = AutoTuner(auto_trader.persona_tracker)
            result = tuner.tune(
                current_buy_threshold=auto_trader.config.buy_threshold,
                current_sell_threshold=auto_trader.config.sell_threshold,
                current_min_confidence=auto_trader.config.min_confidence,
            )
            if result["adjusted"]:
                logger.info(f"AutoTuner: {result['reasoning']}")
        except Exception:
            logger.exception("Auto-tuner cycle failed")

    scheduler.add_job(auto_tuner_cycle, "cron", day_of_week="sun", hour=20, minute=0)

    # Auto-trader (interval from config, default 60 min)
    from manager.auto_trader import AutoTraderConfig
    _ac = AutoTraderConfig()
    scheduler.add_job(auto_trader_cycle, "interval", minutes=_ac.interval_minutes,
                      misfire_grace_time=120, coalesce=True)

    # Committee trader: cron only (7:40 AM Mon-Fri above), NOT interval.
    # Running both would cause double-execution race conditions.

    # Day auto-trader (interval from config, default 5 min)
    async def day_auto_trader_cycle() -> None:
        day_auto_trader = app.bot_data.get("day_auto_trader")
        if not day_auto_trader or not day_auto_trader.is_enabled:
            return
        try:
            actions = day_auto_trader.run_cycle()
            if actions:
                logger.info("Day auto-trader: %d action(s)", len(actions))
                if chat_id:
                    lines = ["⚡ 當沖自動交易執行：\n"]
                    for a in actions:
                        action = a["action"]
                        sym = a["symbol"]
                        if action == "PROBE_BUY":
                            fees = a.get("est_fees_twd", 0)
                            lines.append(
                                f"  🔍 試單 {sym} x{a.get('shares', '?')} @ ${a['price']:.2f}"
                                f" (信心 {a.get('confidence', 0):.0%})"
                                f" | 預估來回手續費 TWD{fees:.0f}"
                            )
                        elif action == "PYRAMID_ADD":
                            lines.append(
                                f"  🚀 加碼 {sym} +{a.get('shares', '?')} @ ${a['price']:.2f}"
                                f" → 共 {a.get('total_shares', '?')} 股"
                            )
                        elif action == "AUTO_BUY":
                            lines.append(
                                f"  🟢 買入 {sym} x{a.get('shares', '?')} @ ${a['price']:.2f}"
                                f" (信心 {a.get('confidence', 0):.0%})"
                            )
                        elif action in ("SL_SELL", "TP_SELL", "FORCE_CLOSE"):
                            label = {"SL_SELL": "停損", "TP_SELL": "停利", "FORCE_CLOSE": "強制平倉"}
                            net = a.get("net_pnl_twd", 0)
                            fees = a.get("fees_twd", 0)
                            lines.append(
                                f"  🔴 {label[action]} {sym} x{a.get('shares', '?')}"
                                f" @ ${a['price']:.2f}"
                                f" | PnL {a.get('pnl_pct', 0):+.2f}%"
                                f" (net TWD{net:+,.0f}, fees TWD{fees:.0f})"
                            )
                        elif action == "HALTED":
                            lines.append(f"  ⛔ 交易暫停：{a.get('reason', '')}")
                    await app.bot.send_message(chat_id=chat_id, text="\n".join(lines))
        except Exception:
            logger.exception("Day auto-trader cycle failed")

    from manager.day_auto_trader import DayAutoTraderConfig
    _dac = DayAutoTraderConfig()
    scheduler.add_job(
        day_auto_trader_cycle, "interval", minutes=_dac.interval_minutes,
        misfire_grace_time=60, coalesce=True,
    )
    if _dac.enabled:
        logger.info("Day auto-trader scheduled (every %d min)", _dac.interval_minutes)

    # Day trade post-market review (巨𪿳傑: 盤後檢討)
    # 美東 16:30 = 台灣隔天 4:30 AM
    async def day_trade_review() -> None:
        day_auto_trader = app.bot_data.get("day_auto_trader")
        if not day_auto_trader or not day_auto_trader.is_enabled:
            return
        try:
            report = day_auto_trader.review_text()
            review_path = day_auto_trader.generate_review_file()
            if review_path:
                logger.info("Day trade review saved: %s", review_path)
            if chat_id:
                await app.bot.send_message(chat_id=chat_id, text=report)
        except Exception:
            logger.exception("Day trade review failed")

    scheduler.add_job(day_trade_review, "cron", hour=4, minute=30, day_of_week="mon-fri")
    logger.info("Day trade review scheduled (daily 4:30 AM)")

    # Polymarket heartbeat (if enabled)
    if os.environ.get("POLYMARKET_HEARTBEAT_ENABLED", "false").lower() == "true":
        interval = int(os.environ.get("POLYMARKET_SCAN_INTERVAL", "60"))
        scheduler.add_job(polymarket_heartbeat_cycle, "interval", minutes=interval)
        logger.info("Polymarket heartbeat scheduled (every %d min)", interval)

    # Polymarket copy trading (if enabled)
    if os.environ.get("POLYCOPY_ENABLED", "false").lower() == "true":
        interval = int(os.environ.get("POLYCOPY_SCAN_INTERVAL", "15"))
        scheduler.add_job(
            polymarket_copy_trade_cycle, "interval", minutes=interval,
            misfire_grace_time=120, coalesce=True,
        )
        logger.info("Polymarket copy trader scheduled (every %d min)", interval)

    # Polymarket whale watcher (auto-discover wallets, every 6 hours)
    async def whale_watcher_cycle() -> None:
        from manager.poly_whale_watcher import WhaleWatcher
        try:
            watcher = WhaleWatcher()
            whales = await watcher.discover()
            logger.info("Whale watcher: discovered %d whales", len(whales))
        except Exception:
            logger.exception("Whale watcher cycle failed")

    scheduler.add_job(whale_watcher_cycle, "interval", hours=6)
    logger.info("Whale watcher scheduled (every 6 hours)")

    # Startup performance snapshot (delayed by 30s)
    from datetime import timedelta, timezone
    startup_time = datetime.now(timezone.utc).astimezone() + timedelta(seconds=30)
    scheduler.add_job(record_daily_performance, "date", run_date=startup_time)

    return scheduler
