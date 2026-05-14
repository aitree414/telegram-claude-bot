"""Heartbeat system for Polymarket — scheduled scanning, price tracking,
and Telegram notifications.

Replaces purely manual triggering with automatic periodic cycles.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from bot.polymarket_clob import PolymarketCLOB, MarketData
from manager.polymarket_trader import PolymarketTrader, CycleResult

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD_PCT = 15.0
DEFAULT_COOLDOWN_MIN = 60


# ── Price Tracker ───────────────────────────────


class PriceTracker:
    """Tracks Polymarket outcome prices and alerts on significant moves.

    State persists to ``data/price_tracker.json`` so alerts survive
    bot restarts.
    """

    def __init__(self, data_dir: Optional[Path] = None):
        self._file = (data_dir or Path(__file__).parent.parent / "data") / "price_tracker.json"
        self._state = self._load()

    # ── Config ──────────────────────────────────

    @property
    def threshold_pct(self) -> float:
        return float(os.environ.get("POLY_PRICE_ALERT_THRESHOLD_PCT",
                                     str(self._state.get("_threshold", DEFAULT_THRESHOLD_PCT))))

    @property
    def cooldown_minutes(self) -> int:
        return int(os.environ.get("POLY_PRICE_ALERT_COOLDOWN",
                                   str(self._state.get("_cooldown", DEFAULT_COOLDOWN_MIN))))

    # ── State ───────────────────────────────────

    def _default_state(self) -> dict:
        return {
            "_threshold": DEFAULT_THRESHOLD_PCT,
            "_cooldown": DEFAULT_COOLDOWN_MIN,
            "markets": {},
        }

    def _load(self) -> dict:
        try:
            if self._file.exists():
                return json.loads(self._file.read_text())
        except Exception as e:
            logger.warning("Failed to load price_tracker.json: %s", e)
        return self._default_state()

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps(self._state, indent=2))
        except Exception as e:
            logger.warning("Failed to save price_tracker.json: %s", e)

    # ── Update ──────────────────────────────────

    def update(self, markets: list[MarketData]) -> None:
        """Record current prices for all scanned markets."""
        now = datetime.now(timezone.utc).isoformat()
        for m in markets:
            slug = m.slug
            if slug not in self._state["markets"]:
                self._state["markets"][slug] = {
                    "slug": slug,
                    "question": m.question,
                    "outcomes": m.outcomes,
                    "first_seen": now,
                }

            entry = self._state["markets"][slug]
            entry["updated_at"] = now

            # Shift current → previous
            if "last_prices" in entry:
                entry["previous_prices"] = entry["last_prices"]
            else:
                entry["previous_prices"] = dict(zip(m.outcomes, m.outcome_prices))

            entry["last_prices"] = dict(zip(m.outcomes, m.outcome_prices))

        self._save()

    # ── Alerts ──────────────────────────────────

    def check_alerts(self) -> list[dict]:
        """Check for significant price movements since last update.

        Returns
        -------
        list of alert dicts with keys:
            slug, question, outcome, old_price, new_price, change_pct
        """
        alerts: list[dict] = []
        now_ts = datetime.now(timezone.utc).timestamp()
        cooldown_sec = self.cooldown_minutes * 60
        threshold = self.threshold_pct
        changed = False

        for slug, entry in list(self._state["markets"].items()):
            last = entry.get("last_prices", {})
            prev = entry.get("previous_prices", {})

            if not last or not prev:
                continue

            for outcome in last:
                if outcome not in prev:
                    continue

                old_p = prev[outcome]
                new_p = last[outcome]
                if old_p <= 0:
                    continue

                change_pct = abs((new_p - old_p) / old_p * 100)

                if change_pct < threshold:
                    continue

                # Cooldown check
                last_alert = entry.get("last_alert_time")
                if last_alert:
                    try:
                        elapsed = now_ts - datetime.fromisoformat(last_alert).timestamp()
                        if elapsed < cooldown_sec:
                            continue
                    except (ValueError, TypeError):
                        pass

                alert = {
                    "slug": slug,
                    "question": entry.get("question", slug),
                    "outcome": outcome,
                    "old_price": round(old_p, 4),
                    "new_price": round(new_p, 4),
                    "change_pct": round(change_pct, 1),
                }
                alerts.append(alert)
                entry["last_alert_time"] = datetime.now(timezone.utc).isoformat()
                changed = True

        if changed:
            self._save()

        return alerts


# ── Heartbeat Result ─────────────────────────────


class HeartbeatResult:
    """Result of one heartbeat cycle."""

    def __init__(self, cycle_result: Optional[CycleResult] = None,
                 price_alerts: Optional[list[dict]] = None):
        self.cycle_result = cycle_result
        self.price_alerts = price_alerts or []

    @property
    def has_events(self) -> bool:
        return bool(self.price_alerts) or (self.cycle_result and self.cycle_result.has_signals)

    def summary_log(self) -> str:
        parts = []
        if self.cycle_result and self.cycle_result.executed:
            parts.append(f"{len(self.cycle_result.executed)} trade(s)")
        if self.price_alerts:
            parts.append(f"{len(self.price_alerts)} price alert(s)")
        return ", ".join(parts) if parts else "no events"

    def telegram_text(self) -> str:
        lines = []
        if self.cycle_result and self.cycle_result.executed:
            for e in self.cycle_result.executed[:5]:
                icon = "🧪" if e.get("dry_run") else "⚡"
                lines.append(
                    f"{icon} {e['strategy']}: {e['side']} {e['outcome']} "
                    f"x{e['size']} @ ${e['price']:.4f}"
                )

        if self.price_alerts:
            if lines:
                lines.append("")
            lines.append("📈 價格警報：")
            for a in self.price_alerts[:5]:
                direction = "▲" if a["new_price"] > a["old_price"] else "▼"
                lines.append(
                    f"  {a['question'][:50]}...\n"
                    f"    {a['outcome']}: ${a['old_price']} {direction} ${a['new_price']} "
                    f"({a['change_pct']:+.1f}%)"
                )

        return "\n".join(lines) if lines else ""


# ── Heartbeat Orchestrator ──────────────────────


class PolymarketHeartbeat:
    """Orchestrates one cycle: strategies → execution → price tracking.

    Meant to be called by APScheduler at a regular interval.

    Usage
    -----
    >>> heartbeat = PolymarketHeartbeat(trader, app=app, chat_id=123)
    >>> result = await heartbeat.beat()
    """

    def __init__(self, trader: PolymarketTrader,
                 price_tracker: Optional[PriceTracker] = None,
                 clob: Optional[PolymarketCLOB] = None,
                 app=None, chat_id: int = 0):
        self.trader = trader
        self.price_tracker = price_tracker or PriceTracker()
        self.clob = clob or PolymarketCLOB()
        self.app = app
        self.chat_id = chat_id

    async def beat(self) -> HeartbeatResult:
        """Run one full heartbeat cycle.

        1. Run trader cycle (if enabled)
        2. Update price tracker (always)
        3. Check for price alerts (always)
        4. Send Telegram notifications (if app + chat_id configured)
        """
        # 1. Run strategies
        cycle_result = None
        if self.trader.is_enabled:
            try:
                cycle_result = self.trader.run_cycle()
            except Exception as e:
                logger.exception("Heartbeat trader cycle failed: %s", e)

        # 2. Fetch markets for price tracking
        try:
            markets = PolymarketCLOB.fetch_active_markets(limit=50)
            if markets:
                self.price_tracker.update(markets)
        except Exception as e:
            logger.warning("Heartbeat market fetch failed: %s", e)
            markets = []

        # 3. Price alerts
        price_alerts = []
        try:
            price_alerts = self.price_tracker.check_alerts()
        except Exception as e:
            logger.warning("Heartbeat price check failed: %s", e)

        result = HeartbeatResult(
            cycle_result=cycle_result,
            price_alerts=price_alerts,
        )

        # 4. Notifications
        if result.has_events and self.app and self.chat_id:
            try:
                text = result.telegram_text()
                if text:
                    await self.app.bot.send_message(chat_id=self.chat_id, text=text[:4096])
            except Exception as e:
                logger.warning("Heartbeat notification failed: %s", e)

        return result
