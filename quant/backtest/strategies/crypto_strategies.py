"""Web3 / 加密貨幣專用策略模板。

加密貨幣市場特性：
- 24/7 交易，無跳空缺口
- 高波動（5-10x 股票）
- 趨勢持續性強
- 受消息面/鏈上數據影響大

策略列表：
1. TrendFollowing — EMA 趨勢跟蹤 + ADX 過濾（適合 COIN, MSTR）
2. GridRecovery — 波動區間網格低買高賣（適合 BITO）
3. VolatilityBreakout — ATR 波動突破（適合 RIOT, CLSK）
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

from .base_strategies import BaseStrategy, compute_indicators_for_backtest

import logging
logger = logging.getLogger(__name__)


class TrendFollowingStrategy(BaseStrategy):
    """EMA 趨勢跟蹤策略（加密貨幣專用）。

    適合：COIN, MSTR 等趨勢型標的
    邏輯：
    - 快線 EMA12 上穿慢線 EMA26 → 買入
    - 快線 EMA12 下穿慢線 EMA26 → 賣出
    - ADX > 25 才進場（過濾盤整）
    """

    def __init__(self, fast_period: int = 12, slow_period: int = 26, adx_threshold: float = 25.0):
        params = {"fast_period": fast_period, "slow_period": slow_period, "adx_threshold": adx_threshold}
        super().__init__(params)
        self.name = f"TrendFollowing_EMA{fast_period}_{slow_period}_ADX{int(adx_threshold)}"

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()

        # EMA
        ema_fast = df["Close"].ewm(span=self.params["fast_period"], adjust=False).mean()
        ema_slow = df["Close"].ewm(span=self.params["slow_period"], adjust=False).mean()

        # ADX (Average Directional Index)
        high, low, close = df["High"], df["Low"], df["Close"]
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()

        plus_dm = high.diff()
        minus_dm = low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm > 0] = 0
        minus_dm = minus_dm.abs()

        plus_di = 100 * (plus_dm.ewm(span=14).mean() / atr.replace(0, np.nan))
        minus_di = 100 * (minus_dm.ewm(span=14).mean() / atr.replace(0, np.nan))
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
        adx = dx.rolling(14).mean()

        # 考慮加密貨幣高波動：用 2.5x ATR 止損
        df["atr_stop"] = df["Close"] - atr * 2.5

        # 買入：EMA 黃金交叉 + ADX > 門檻（趨勢確認）
        ema_cross_up = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
        trend_strong = adx > self.params["adx_threshold"]
        df["buy"] = ema_cross_up & trend_strong.shift(1).fillna(False)

        # 賣出：EMA 死亡交叉
        ema_cross_down = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))
        df["sell"] = ema_cross_down
        df["hold"] = ~(df["buy"] | df["sell"])

        df["buy_price"] = np.where(df["buy"], df["Close"], np.nan)
        df["sell_price"] = np.where(df["sell"], df["Close"], np.nan)

        return df


class GridRecoveryStrategy(BaseStrategy):
    """波動區間網格策略（加密貨幣專用）。

    適合：BITO 等區間震盪型 ETF
    邏輯：
    - 價格跌破 Bollinger 下軌 → 買入（超賣）
    - 價格突破 Bollinger 上軌 → 賣出（超買）
    - RSI 過濾極端行情
    - 加密貨幣版使用更寬的標準差 (2.5x)
    """

    def __init__(self, bb_period: int = 20, bb_std: float = 2.5, rsi_oversold: float = 25, rsi_overbought: float = 75):
        params = {"bb_period": bb_period, "bb_std": bb_std, "rsi_oversold": rsi_oversold, "rsi_overbought": rsi_overbought}
        super().__init__(params)
        self.name = f"GridRecovery_BB{bb_period}_{bb_std}_RSI{int(rsi_oversold)}_{int(rsi_overbought)}"

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()

        # Bollinger Bands (加密貨幣版：2.5x 標準差)
        middle = df["Close"].rolling(self.params["bb_period"]).mean()
        std = df["Close"].rolling(self.params["bb_period"]).std()
        upper = middle + std * self.params["bb_std"]
        lower = middle - std * self.params["bb_std"]

        # RSI
        if "RSI" not in df.columns:
            delta = df["Close"].diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, float("nan"))
            df["RSI"] = 100 - 100 / (1 + rs)
            df["RSI"] = df["RSI"].fillna(50)

        # 買入：價格觸及下軌 + RSI 不極端超買
        touch_lower = (df["Close"] <= lower) & (df["Close"].shift(1) > lower.shift(1))
        not_overbought = df["RSI"] < self.params["rsi_overbought"]
        df["buy"] = touch_lower & not_overbought

        # 賣出：價格觸及上軌 + RSI 不極端超賣
        touch_upper = (df["Close"] >= upper) & (df["Close"].shift(1) < upper.shift(1))
        not_oversold = df["RSI"] > self.params["rsi_oversold"]
        df["sell"] = touch_upper & not_oversold
        df["hold"] = ~(df["buy"] | df["sell"])

        df["buy_price"] = np.where(df["buy"], df["Close"], np.nan)
        df["sell_price"] = np.where(df["sell"], df["Close"], np.nan)

        return df


class VolatilityBreakoutStrategy(BaseStrategy):
    """ATR 波動突破策略（加密貨幣專用）。

    適合：RIOT, CLSK 等高波動標的
    邏輯：
    - 收盤價突破前 N 日高點 + ATR 確認 → 買入
    - 收盤價跌破前 N 日低點 - ATR 確認 → 賣出
    - 使用 3x ATR 作為動態止損
    """

    def __init__(self, lookback: int = 20, atr_multiplier: float = 1.5, atr_period: int = 14):
        params = {"lookback": lookback, "atr_multiplier": atr_multiplier, "atr_period": atr_period}
        super().__init__(params)
        self.name = f"VolatilityBreakout_LB{lookback}_ATR{atr_multiplier}"

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()

        # ATR
        high, low, close = df["High"], df["Low"], df["Close"]
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(self.params["atr_period"]).mean()

        lookback = self.params["lookback"]
        atr_mult = self.params["atr_multiplier"]

        # 前 N 日最高/最低
        rolling_high = high.rolling(lookback).max().shift(1)
        rolling_low = low.rolling(lookback).min().shift(1)

        # 買入：收盤突破前高 + 足夠波動
        df["buy"] = (close > rolling_high) & (close - rolling_high > atr * atr_mult * 0.5)
        # 賣出：收盤跌破前低
        df["sell"] = close < rolling_low
        df["hold"] = ~(df["buy"] | df["sell"])

        df["buy_price"] = np.where(df["buy"], df["Close"], np.nan)
        df["sell_price"] = np.where(df["sell"], df["Close"], np.nan)

        # 動態止損價（3x ATR）
        df["stop_loss"] = df["Close"] - atr * 3.0

        return df
