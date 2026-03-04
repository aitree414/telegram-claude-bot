from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Tuple
from requests.exceptions import ConnectionError, Timeout

import yfinance as yf
import pandas as pd

from .retry import retry, retry_with_exponential_backoff


TAIWAN_WATCHLIST = [
    "2330", "2317", "2454", "2308", "2382", "2412", "2303", "3711",
    "2881", "2882", "2884", "2886", "1301", "1303", "2002", "3008",
    "2395", "3034", "4938", "2324",
]


def _normalize_symbol(symbol: str) -> str:
    if symbol.isdigit():
        return f"{symbol}.TW"
    return symbol.upper()


def _format_market_cap(market_cap: float, currency: str) -> str:
    if market_cap >= 1_000_000_000_000:
        return f"{currency} {market_cap / 1_000_000_000_000:.2f}T"
    if market_cap >= 1_000_000_000:
        return f"{currency} {market_cap / 1_000_000_000:.2f}B"
    return f"{currency} {market_cap / 1_000_000:.2f}M"


def _compute_indicators(hist: pd.DataFrame) -> dict:
    """Compute technical indicators from 60d history DataFrame."""
    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]
    volume = hist["Volume"]

    ma5 = close.rolling(5).mean().iloc[-1]
    ma20_series = close.rolling(20).mean()
    ma20 = ma20_series.iloc[-1]
    ma20_prev = ma20_series.iloc[-6] if len(ma20_series) >= 6 else ma20

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    # 避免除零錯誤
    rs = gain / loss.replace(0, float("nan"))
    rsi_series = 100 - 100 / (1 + rs)
    rsi_series = rsi_series.fillna(50)  # 當rs為NaN時設為中性值50
    rsi = rsi_series.iloc[-1]

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_series = ema12 - ema26
    signal_series = macd_series.ewm(span=9, adjust=False).mean()
    macd_hist_series = macd_series - signal_series
    macd_line = macd_series.iloc[-1]
    signal_line = signal_series.iloc[-1]
    macd_hist = macd_hist_series.iloc[-1]
    macd_hist_prev = macd_hist_series.iloc[-2] if len(macd_hist_series) >= 2 else macd_hist

    bb_mid = ma20
    bb_std = close.rolling(20).std().iloc[-1]
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    current_close = close.iloc[-1]
    bb_range = bb_upper - bb_lower
    bb_pct = (current_close - bb_lower) / bb_range if bb_range != 0 else 0.5

    low9 = low.rolling(9).min()
    high9 = high.rolling(9).max()
    high_low_range = high9 - low9
    rsv = ((close - low9) / high_low_range.replace(0, float("nan")) * 100).fillna(50)
    k_series = rsv.ewm(com=2, adjust=False).mean()
    d_series = k_series.ewm(com=2, adjust=False).mean()
    k = k_series.iloc[-1]
    d = d_series.iloc[-1]

    vol_20_avg = volume.rolling(20).mean().iloc[-1]
    vol_today = volume.iloc[-1]
    # 檢查是否為NaN或零
    if pd.notna(vol_20_avg) and vol_20_avg != 0:
        vol_ratio = vol_today / vol_20_avg
    else:
        vol_ratio = 1.0

    return {
        "ma5": ma5,
        "ma20": ma20,
        "ma20_prev": ma20_prev,
        "rsi": rsi,
        "macd_line": macd_line,
        "signal_line": signal_line,
        "macd_hist": macd_hist,
        "macd_hist_prev": macd_hist_prev,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "bb_pct": bb_pct,
        "k": k,
        "d": d,
        "vol_ratio": vol_ratio,
    }


def _compute_score(ind: dict, current: float, info: dict) -> Tuple[int, list]:
    """Technical score 0-8 based on 8 bullish conditions."""
    high_52 = info.get("fiftyTwoWeekHigh") or 0
    score = 0
    triggers = []

    if ind["ma5"] > ind["ma20"]:
        score += 1
        triggers.append("均線多頭(MA5>MA20)")

    if ind["ma20"] > ind["ma20_prev"]:
        score += 1
        triggers.append("MA20上揚")

    if 50 <= ind["rsi"] <= 70 or ind["rsi"] < 35:
        score += 1
        label = "RSI超賣反彈" if ind["rsi"] < 35 else f"RSI強勢({ind['rsi']:.0f})"
        triggers.append(label)

    if ind["macd_hist"] > 0:
        score += 1
        triggers.append("MACD柱>0")

    if ind["vol_ratio"] >= 1.5:
        score += 1
        triggers.append(f"量比{ind['vol_ratio']:.1f}x")

    if current > ind["ma20"]:
        score += 1
        triggers.append("現價>MA20")

    if high_52 and current >= high_52 * 0.88:
        score += 1
        triggers.append("近52週高")

    if ind["k"] > ind["d"] and ind["k"] > 50:
        score += 1
        triggers.append(f"KD黃金交叉(K:{ind['k']:.0f})")

    return score, triggers


def _get_fundamentals(info: dict) -> dict:
    """Extract fundamental data from yfinance info dict."""
    per = info.get("trailingPE") or info.get("forwardPE")
    pbr = info.get("priceToBook")
    raw_yield = info.get("dividendYield")
    raw_roe = info.get("returnOnEquity")
    raw_growth = info.get("revenueGrowth")

    return {
        "per": per,
        "pbr": pbr,
        "dividend_yield": raw_yield * 100 if raw_yield is not None else None,
        "roe": raw_roe * 100 if raw_roe is not None else None,
        "revenue_growth": raw_growth * 100 if raw_growth is not None else None,
    }


def _compute_fundamental_score(fund: dict) -> Tuple[int, list]:
    """Fundamental score 0-100 based on PER/PBR/yield/ROE/revenue growth."""
    score = 0
    triggers = []

    per = fund.get("per")
    if per is not None:
        if per < 15:
            score += 25
            triggers.append("PER極低(<15)")
        elif per < 20:
            score += 18
            triggers.append(f"PER合理({per:.1f})")
        elif per < 30:
            score += 10
            triggers.append(f"PER偏高({per:.1f})")

    pbr = fund.get("pbr")
    if pbr is not None:
        if pbr < 1:
            score += 25
            triggers.append("PBR<1(破淨)")
        elif pbr < 2:
            score += 18
            triggers.append(f"PBR合理({pbr:.1f})")
        elif pbr < 3:
            score += 10

    dy = fund.get("dividend_yield")
    if dy is not None:
        if dy > 5:
            score += 20
            triggers.append(f"高殖利率({dy:.1f}%)")
        elif dy > 3:
            score += 14
            triggers.append(f"殖利率{dy:.1f}%")
        elif dy > 1:
            score += 8

    roe = fund.get("roe")
    if roe is not None:
        if roe > 20:
            score += 15
            triggers.append(f"ROE優異({roe:.1f}%)")
        elif roe > 15:
            score += 11
            triggers.append(f"ROE良好({roe:.1f}%)")
        elif roe > 10:
            score += 7

    growth = fund.get("revenue_growth")
    if growth is not None:
        if growth > 20:
            score += 15
            triggers.append(f"營收高成長({growth:.1f}%)")
        elif growth > 10:
            score += 11
            triggers.append(f"營收成長({growth:.1f}%)")
        elif growth > 0:
            score += 6

    return score, triggers


def get_current_price(symbol: str) -> Optional[float]:
    """Return current price as float, or None if unavailable."""
    symbol = _normalize_symbol(symbol)

    # Define retryable exceptions (network errors)
    retryable_exceptions = (ConnectionError, Timeout)

    # Define the function that will be retried
    def fetch_price():
        info = yf.Ticker(symbol).info
        return info.get("currentPrice") or info.get("regularMarketPrice")

    # Try with retry for network errors
    try:
        return retry_with_exponential_backoff(
            fetch_price,
            max_retries=2,
            initial_delay=0.5,
            max_delay=5.0,
            backoff_factor=2.0,
            retryable_exceptions=retryable_exceptions,
        )
    except retryable_exceptions:
        # Network error after all retries
        return None
    except (KeyError, ValueError, TypeError):
        # Data parsing error or invalid symbol
        return None
    except Exception:
        # Other unexpected errors
        return None


def get_stock_info(symbol: str) -> str:
    symbol = _normalize_symbol(symbol)

    # Define retryable exceptions (network errors)
    retryable_exceptions = (ConnectionError, Timeout)

    def fetch_stock_data():
        """Fetch stock data with retry for network errors."""
        ticker = yf.Ticker(symbol)
        info = ticker.info

        name = info.get("longName") or info.get("shortName") or symbol
        currency = info.get("currency", "")
        current = info.get("currentPrice") or info.get("regularMarketPrice")
        prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
        volume = info.get("volume") or info.get("regularMarketVolume")
        high_52 = info.get("fiftyTwoWeekHigh")
        low_52 = info.get("fiftyTwoWeekLow")
        market_cap = info.get("marketCap")

        if not current:
            raise ValueError(f"No price data for {symbol}")

        return {
            "name": name,
            "currency": currency,
            "current": current,
            "prev_close": prev_close,
            "volume": volume,
            "high_52": high_52,
            "low_52": low_52,
            "market_cap": market_cap,
        }

    try:
        # Try with retry for network errors
        data = retry_with_exponential_backoff(
            fetch_stock_data,
            max_retries=2,
            initial_delay=0.5,
            max_delay=5.0,
            backoff_factor=2.0,
            retryable_exceptions=retryable_exceptions,
        )
    except retryable_exceptions as e:
        return f"查詢 {symbol} 時發生網路錯誤：{e}，請檢查網路連線後再試。"
    except ValueError as e:
        # No price data
        return (
            f"找不到 {symbol} 的股票資料，請確認代碼是否正確。\n\n"
            "港股範例：0700 或 0700.HK\n美股範例：AAPL、TSLA"
        )
    except (KeyError, ValueError, TypeError) as e:
        return f"查詢 {symbol} 時發生數據解析錯誤：{e}，請確認股票代碼是否有效。"
    except Exception as e:
        return f"查詢 {symbol} 時發生未預期錯誤：{e}"

    # Format the response
    name = data["name"]
    currency = data["currency"]
    current = data["current"]
    prev_close = data["prev_close"]
    volume = data["volume"]
    high_52 = data["high_52"]
    low_52 = data["low_52"]
    market_cap = data["market_cap"]

    change = current - prev_close if prev_close else 0
    change_pct = (change / prev_close * 100) if prev_close else 0
    arrow = "▲" if change >= 0 else "▼"

    lines = [
        f"{name} ({symbol})",
        "",
        f"現價：{currency} {current:.3f}",
        f"漲跌：{arrow} {abs(change):.3f} ({abs(change_pct):.2f}%)",
    ]
    if prev_close:
        lines.append(f"昨收：{currency} {prev_close:.3f}")
    if high_52 and low_52:
        lines.append(f"52週：{low_52:.3f} - {high_52:.3f}")
    if volume:
        lines.append(f"成交量：{volume:,}")
    if market_cap:
        lines.append(f"市值：{_format_market_cap(market_cap, currency)}")

    return "\n".join(lines)


def get_stock_analysis(symbol: str) -> str:
    symbol = _normalize_symbol(symbol)
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        name = info.get("longName") or info.get("shortName") or symbol
        currency = info.get("currency", "")
        current = info.get("currentPrice") or info.get("regularMarketPrice")
        prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")

        if not current:
            return f"找不到 {symbol} 的資料。"

        hist = ticker.history(period="60d")
        if hist.empty or len(hist) < 20:
            return f"{symbol}：歷史數據不足，無法計算技術指標。"

        ind = _compute_indicators(hist)
        tech_score, tech_triggers = _compute_score(ind, current, info)
        fund = _get_fundamentals(info)
        fund_score, fund_triggers = _compute_fundamental_score(fund)

        change = current - prev_close if prev_close else 0
        change_pct = (change / prev_close * 100) if prev_close else 0
        arrow = "▲" if change >= 0 else "▼"

        trend = "上升趨勢" if ind["ma5"] > ind["ma20"] else "下降趨勢"
        ma20_dir = "上揚" if ind["ma20"] > ind["ma20_prev"] else "下滑"
        rsi_signal = "超買" if ind["rsi"] > 70 else ("超賣" if ind["rsi"] < 30 else "中性")
        macd_signal = "買入信號" if ind["macd_hist"] > 0 else "賣出信號"

        lines = [
            f"{name} ({symbol}) 技術分析",
            "",
            f"現價：{currency} {current:.3f}  {arrow} {abs(change_pct):.2f}%",
            "",
            "--- 技術指標 ---",
            f"MA5：{ind['ma5']:.3f}",
            f"MA20：{ind['ma20']:.3f}  ({trend}，{ma20_dir})",
            f"RSI(14)：{ind['rsi']:.1f}  ({rsi_signal})",
            f"MACD：{ind['macd_line']:.4f}  Signal：{ind['signal_line']:.4f}  ({macd_signal})",
            f"KD：K={ind['k']:.1f}  D={ind['d']:.1f}",
            f"布林帶：%B={ind['bb_pct']:.2f}  上軌={ind['bb_upper']:.3f}  下軌={ind['bb_lower']:.3f}",
            f"量比：{ind['vol_ratio']:.2f}x",
            "",
            "--- 基本面 ---",
        ]

        per_str = f"{fund['per']:.1f}" if fund["per"] is not None else "N/A"
        pbr_str = f"{fund['pbr']:.2f}" if fund["pbr"] is not None else "N/A"
        dy_str = f"{fund['dividend_yield']:.2f}%" if fund["dividend_yield"] is not None else "N/A"
        roe_str = f"{fund['roe']:.1f}%" if fund["roe"] is not None else "N/A"
        growth_str = f"{fund['revenue_growth']:.1f}%" if fund["revenue_growth"] is not None else "N/A"

        lines += [
            f"PER：{per_str}  PBR：{pbr_str}  殖利率：{dy_str}",
            f"ROE：{roe_str}  營收成長：{growth_str}",
            f"基本面評分：{fund_score}/100",
        ]
        if fund_triggers:
            lines.append("基本面：" + "、".join(fund_triggers))

        lines += [
            "",
            "--- 技術評分 ---",
            f"強勢評分：{tech_score}/8",
        ]
        if tech_triggers:
            lines.append("觸發條件：" + "、".join(tech_triggers))

        lines.append("")
        if tech_score >= 5:
            lines.append("強勢股 (僅供參考，非投資建議)")
        elif tech_score >= 3:
            lines.append("中性偏多 (僅供參考，非投資建議)")
        else:
            lines.append("偏弱 (僅供參考，非投資建議)")

        return "\n".join(lines)

    except (ConnectionError, Timeout) as e:
        return f"分析 {symbol} 時發生網路錯誤：{e}，請檢查網路連線後再試。"
    except (KeyError, ValueError, TypeError) as e:
        return f"分析 {symbol} 時發生數據解析錯誤：{e}，可能該股票數據不完整。"
    except Exception as e:
        return f"分析 {symbol} 時發生未預期錯誤：{e}"


def _scan_single(symbol: str) -> Optional[dict]:
    """Fetch and score a single stock for scan. Returns dict or None on failure."""
    normalized = _normalize_symbol(symbol)

    # Define retryable exceptions (network errors)
    retryable_exceptions = (ConnectionError, Timeout)

    def fetch_stock_data():
        """Fetch stock data with retry for network errors."""
        ticker = yf.Ticker(normalized)
        info = ticker.info
        name = info.get("longName") or info.get("shortName") or normalized
        current = info.get("currentPrice") or info.get("regularMarketPrice")
        prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
        currency = info.get("currency", "")

        if not current:
            raise ValueError("No price data")

        hist = ticker.history(period="60d")
        if hist.empty or len(hist) < 20:
            raise ValueError("Insufficient historical data")

        ind = _compute_indicators(hist)
        tech_score, tech_triggers = _compute_score(ind, current, info)
        fund = _get_fundamentals(info)
        fund_score, fund_triggers = _compute_fundamental_score(fund)

        change_pct = ((current - prev_close) / prev_close * 100) if prev_close else 0
        return {
            "symbol": normalized,
            "name": name,
            "current": current,
            "currency": currency,
            "change_pct": change_pct,
            "tech_score": tech_score,
            "tech_triggers": tech_triggers,
            "fund_score": fund_score,
            "fund_triggers": fund_triggers,
            "ind": ind,
            "fund": fund,
        }

    try:
        # Try with retry for network errors
        return retry_with_exponential_backoff(
            fetch_stock_data,
            max_retries=1,  # One retry (total 2 attempts)
            initial_delay=0.5,
            max_delay=2.0,
            backoff_factor=2.0,
            retryable_exceptions=retryable_exceptions,
        )
    except retryable_exceptions:
        # Network error after all retries
        return None
    except ValueError:
        # No price data or insufficient history
        return None
    except (KeyError, ValueError, TypeError):
        # Data error or invalid symbol
        return None
    except Exception:
        # Other unexpected errors
        return None


def _matches_mode(r: dict, mode: str) -> bool:
    """Filter logic per scan mode."""
    ind = r["ind"]
    fund = r["fund"]
    current = r["current"]
    ma20 = ind["ma20"]

    if mode == "value":
        per = fund.get("per")
        pbr = fund.get("pbr")
        dy = fund.get("dividend_yield")
        return (
            (per is None or per < 25)
            and (pbr is None or pbr < 3)
            and (dy is None or dy > 1)
        )

    if mode == "momentum":
        return (
            r["tech_score"] >= 4
            and 50 <= ind["rsi"] <= 70
            and ind["ma20"] > ind["ma20_prev"]
            and ind["vol_ratio"] >= 1.5
        )

    if mode == "pullback":
        near_ma20 = ma20 != 0 and abs(current - ma20) / ma20 <= 0.05
        return (
            35 <= ind["rsi"] <= 55
            and near_ma20
            and ind["macd_hist"] > 0
        )

    return True  # "technical" — no extra filter


def _sort_key(r: dict, mode: str):
    if mode == "value":
        return (r["fund_score"], r["change_pct"])
    return (r["tech_score"], r["change_pct"])


def scan_strong_stocks(
    symbols: Optional[list] = None,
    top_n: int = 5,
    mode: str = "technical",
) -> str:
    """Parallel scan of stocks. mode: technical / value / momentum / pullback."""
    try:
        if symbols:
            target = [_normalize_symbol(s) for s in symbols]
        else:
            target = [_normalize_symbol(s) for s in TAIWAN_WATCHLIST]

        results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_scan_single, s): s for s in target}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    results.append(result)

        filtered = [r for r in results if _matches_mode(r, mode)]

        if not filtered:
            return f"掃描完成，{mode} 模式下無符合條件的股票。"

        filtered.sort(key=lambda r: _sort_key(r, mode), reverse=True)
        top = filtered[:top_n]

        mode_label = {"technical": "技術", "value": "價值", "momentum": "動能", "pullback": "拉回買點"}.get(mode, mode)
        lines = [f"強勢股掃描 [{mode_label}模式] Top {top_n}", ""]

        for i, r in enumerate(top, 1):
            arrow = "▲" if r["change_pct"] >= 0 else "▼"
            if mode == "value":
                score_str = f"基本面{r['fund_score']}/100"
                triggers = r["fund_triggers"][:3]
            else:
                score_str = f"技術{r['tech_score']}/8"
                triggers = r["tech_triggers"][:3]
            trigger_str = "、".join(triggers) if triggers else "無"
            lines.append(
                f"{i}. {r['name']} ({r['symbol']})\n"
                f"   {score_str}  現價：{r['currency']} {r['current']:.3f}  {arrow}{abs(r['change_pct']):.2f}%\n"
                f"   [{trigger_str}]"
            )

        lines.append("")
        lines.append("(僅供參考，非投資建議)")
        return "\n".join(lines)

    except (ConnectionError, Timeout) as e:
        return f"掃描股票時發生網路錯誤：{e}，請檢查網路連線後再試。"
    except (KeyError, ValueError, TypeError) as e:
        return f"掃描股票時發生數據錯誤：{e}，請確認輸入的股票代碼是否有效。"
    except Exception as e:
        return f"掃描股票時發生未預期錯誤：{e}"
