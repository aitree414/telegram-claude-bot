"""Market schedule: trading hours, holidays, and session status.

Provides real-time market status for TWSE (Taiwan) and NYSE/NASDAQ (US)
with proper DST handling and holiday calendars.
"""

from __future__ import annotations

import enum
import logging
from datetime import date, datetime, timedelta, time as dtime
from typing import Optional, Union
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

TZ_TW = ZoneInfo("Asia/Taipei")     # UTC+8 fixed
TZ_US = ZoneInfo("America/New_York")  # ET with DST


class Market(enum.Enum):
    TW = "tw"
    US = "us"


# ── Trading hours ────────────────────────────────────────────────────

TW_OPEN = dtime(9, 0)
TW_CLOSE = dtime(13, 30)
US_OPEN = dtime(9, 30)
US_CLOSE = dtime(16, 0)

# ── 2026 holiday sets (date → description) ───────────────────────────

TW_HOLIDAYS_2026: dict[date, str] = {
    date(2026, 1, 1):   "元旦",
    date(2026, 2, 16):  "春節",
    date(2026, 2, 17):  "春節",
    date(2026, 2, 18):  "春節",
    date(2026, 2, 19):  "春節",
    date(2026, 2, 20):  "春節",
    date(2026, 2, 27):  "和平紀念日",
    date(2026, 4, 3):   "清明節補假",
    date(2026, 4, 4):   "清明節",
    date(2026, 6, 19):  "端午節",
    date(2026, 10, 5):  "中秋節",
    date(2026, 10, 9):  "國慶日",
}

US_HOLIDAYS_2026: dict[date, str] = {
    date(2026, 1, 1):   "New Year's Day",
    date(2026, 1, 19):  "Martin Luther King Jr. Day",
    date(2026, 2, 16):  "Presidents' Day",
    date(2026, 4, 3):   "Good Friday",
    date(2026, 5, 25):  "Memorial Day",
    date(2026, 6, 19):  "Juneteenth",
    date(2026, 7, 3):   "Independence Day (observed)",
    date(2026, 9, 7):   "Labor Day",
    date(2026, 11, 26): "Thanksgiving Day",
    date(2026, 12, 25): "Christmas Day",
}


# ── Public helpers ───────────────────────────────────────────────────

def detect_market(symbol: str) -> Market:
    """Determine which market a symbol belongs to.

    >>> detect_market("2330.TW")
    <Market.TW: 'tw'>
    >>> detect_market("AAPL")
    <Market.US: 'us'>
    """
    s = symbol.strip().upper()
    if s.endswith(".TW") or s.endswith(".TWO"):
        return Market.TW
    raw = s.replace(".TW", "").replace(".TWO", "")
    if raw.isdigit():
        return Market.TW
    return Market.US


def is_holiday(market: Market, d: Optional[date] = None) -> bool:
    """Return True if *d* is a trading holiday for *market*."""
    d = d or date.today()
    cal = TW_HOLIDAYS_2026 if market == Market.TW else US_HOLIDAYS_2026
    return d in cal


def _is_weekend(d: date) -> bool:
    return d.weekday() >= 5  # Sat=5, Sun=6


# ── Core market-status queries ───────────────────────────────────────

def is_market_open(
    symbol_or_market: Union[str, Market],
    now: Optional[datetime] = None,
) -> bool:
    """Check whether the given symbol/market is currently trading."""
    if isinstance(symbol_or_market, str):
        market = detect_market(symbol_or_market)
    else:
        market = symbol_or_market

    now = now or datetime.now()
    tz = TZ_TW if market == Market.TW else TZ_US
    local_now = now.astimezone(tz)
    local_date = local_now.date()
    local_time = local_now.time()

    if _is_weekend(local_date):
        return False
    if is_holiday(market, local_date):
        return False

    open_time = TW_OPEN if market == Market.TW else US_OPEN
    close_time = TW_CLOSE if market == Market.TW else US_CLOSE
    return open_time <= local_time < close_time


def next_market_event(
    market: Market,
    now: Optional[datetime] = None,
) -> dict:
    """Return the next market open or close event.

    Returns
    -------
    dict with keys: type ("open"|"close"), datetime, minutes_until, label.
    """
    now = now or datetime.now()
    tz = TZ_TW if market == Market.TW else TZ_US
    local_now = now.astimezone(tz)
    open_time = TW_OPEN if market == Market.TW else US_OPEN
    close_time = TW_CLOSE if market == Market.TW else US_CLOSE

    # Currently open → next event is today's close
    if is_market_open(market, now):
        close_dt = local_now.replace(
            hour=close_time.hour, minute=close_time.minute,
            second=0, microsecond=0,
        )
        mins = max(0, int((close_dt - local_now).total_seconds() / 60))
        return {
            "type": "close",
            "datetime": close_dt,
            "minutes_until": mins,
            "label": "收盤",
        }

    # Scan forward up to 14 days for next trading day
    check = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    for _ in range(14):
        check += timedelta(days=1)
        if _is_weekend(check.date()):
            continue
        if is_holiday(market, check.date()):
            continue
        open_dt = check.replace(
            hour=open_time.hour, minute=open_time.minute,
            second=0, microsecond=0,
        )
        secs = (open_dt - local_now).total_seconds()
        mins = max(0, int(secs / 60))
        label = "開盤" if market == Market.TW else "open"
        return {
            "type": "open",
            "datetime": open_dt,
            "minutes_until": mins,
            "label": label,
        }

    return {"type": "unknown", "datetime": None, "minutes_until": None, "label": "未知"}


def market_status(now: Optional[datetime] = None) -> dict:
    """Return real-time status for both TW and US markets.

    Returns
    -------
    dict with keys "tw" and "us", each containing:
        name, open_time, close_time, is_open, next_event, holiday, local_time
    """
    now = now or datetime.now()

    def _build(market: Market) -> dict:
        tz = TZ_TW if market == Market.TW else TZ_US
        ot = TW_OPEN if market == Market.TW else US_OPEN
        ct = TW_CLOSE if market == Market.TW else US_CLOSE
        local_now = now.astimezone(tz)
        d = local_now.date()

        holiday_name = None
        cal = TW_HOLIDAYS_2026 if market == Market.TW else US_HOLIDAYS_2026
        if d in cal:
            holiday_name = cal[d]

        return {
            "name": "TWSE (臺灣)"
            if market == Market.TW
            else "NYSE/NASDAQ (美國)",
            "open_time": ot.strftime("%H:%M"),
            "close_time": ct.strftime("%H:%M"),
            "timezone": "Asia/Taipei"
            if market == Market.TW
            else "America/New_York",
            "is_open": is_market_open(market, now),
            "next_event": next_market_event(market, now),
            "holiday": holiday_name,
            "local_time": local_now.strftime("%H:%M"),
        }

    return {"tw": _build(Market.TW), "us": _build(Market.US)}
