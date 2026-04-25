"""基礎量化策略模板。

提供標準化的策略接口和常見技術指標策略實現。
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
import logging

logger = logging.getLogger(__name__)


def compute_indicators_for_backtest(data: pd.DataFrame) -> pd.DataFrame:
    """為回測計算技術指標（整個時間序列）。

    Args:
        data: 包含 OHLCV 的 DataFrame

    Returns:
        添加了技術指標的 DataFrame
    """
    df = data.copy()

    # 移動平均線
    df["MA5"] = df["Close"].rolling(window=5).mean()
    df["MA20"] = df["Close"].rolling(window=20).mean()
    df["MA60"] = df["Close"].rolling(window=60).mean()

    # RSI (14天)
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = (-delta.clip(upper=0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, float("nan"))
    df["RSI"] = 100 - 100 / (1 + rs)
    df["RSI"] = df["RSI"].fillna(50)  # 中性值

    # MACD
    df["EMA12"] = df["Close"].ewm(span=12, adjust=False).mean()
    df["EMA26"] = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = df["EMA12"] - df["EMA26"]
    df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]

    # 布林帶
    df["BB_Middle"] = df["Close"].rolling(window=20).mean()
    bb_std = df["Close"].rolling(window=20).std()
    df["BB_Upper"] = df["BB_Middle"] + 2 * bb_std
    df["BB_Lower"] = df["BB_Middle"] - 2 * bb_std
    bb_range = df["BB_Upper"] - df["BB_Lower"]
    df["BB_Percent"] = (df["Close"] - df["BB_Lower"]) / bb_range.replace(0, float("nan"))
    df["BB_Percent"] = df["BB_Percent"].fillna(0.5)

    # KD 指標
    low9 = df["Low"].rolling(window=9).min()
    high9 = df["High"].rolling(window=9).max()
    high_low_range = high9 - low9
    rsv = ((df["Close"] - low9) / high_low_range.replace(0, float("nan"))) * 100
    rsv = rsv.fillna(50)
    df["K"] = rsv.ewm(com=2, adjust=False).mean()
    df["D"] = df["K"].ewm(com=2, adjust=False).mean()

    # 成交量比率
    df["Volume_MA20"] = df["Volume"].rolling(window=20).mean()
    df["Volume_Ratio"] = df["Volume"] / df["Volume_MA20"].replace(0, float("nan"))
    df["Volume_Ratio"] = df["Volume_Ratio"].fillna(1.0)

    return df


class BaseStrategy:
    """策略基類，定義標準接口"""

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        """初始化策略。

        Args:
            params: 策略參數字典
        """
        self.params = params or {}
        self.name = self.__class__.__name__

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """生成交易信號。

        Args:
            data: 包含技術指標的 DataFrame

        Returns:
            添加了信號列的 DataFrame
        """
        raise NotImplementedError("子類必須實現此方法")

    def __call__(self, data: pd.DataFrame) -> pd.DataFrame:
        """使策略對象可調用。

        Args:
            data: 原始 OHLCV DataFrame

        Returns:
            添加了信號的 DataFrame
        """
        # 計算技術指標
        data_with_indicators = compute_indicators_for_backtest(data)

        # 生成信號
        signals = self.generate_signals(data_with_indicators)

        return signals


class MovingAverageCrossover(BaseStrategy):
    """雙移動平均線交叉策略"""

    def __init__(self, fast_period: int = 5, slow_period: int = 20):
        """初始化 MA 交叉策略。

        Args:
            fast_period: 快線週期
            slow_period: 慢線週期
        """
        params = {"fast_period": fast_period, "slow_period": slow_period}
        super().__init__(params)
        self.name = f"MA_Crossover_{fast_period}_{slow_period}"

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """生成 MA 交叉信號。"""
        df = data.copy()

        # 計算移動平均線
        fast_ma = df["Close"].rolling(window=self.params["fast_period"]).mean()
        slow_ma = df["Close"].rolling(window=self.params["slow_period"]).mean()

        # 生成信號
        df["buy"] = (fast_ma > slow_ma) & (fast_ma.shift(1) <= slow_ma.shift(1))
        df["sell"] = (fast_ma < slow_ma) & (fast_ma.shift(1) >= slow_ma.shift(1))
        df["hold"] = ~(df["buy"] | df["sell"])

        # 記錄價格用於後續計算
        df["buy_price"] = np.where(df["buy"], df["Close"], np.nan)
        df["sell_price"] = np.where(df["sell"], df["Close"], np.nan)

        return df


class BollingerBandsStrategy(BaseStrategy):
    """布林帶突破策略"""

    def __init__(self, period: int = 20, std_dev: float = 2.0):
        """初始化布林帶策略。

        Args:
            period: 布林帶週期
            std_dev: 標準差倍數
        """
        params = {"period": period, "std_dev": std_dev}
        super().__init__(params)
        self.name = f"BollingerBands_{period}_{std_dev}"

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """生成布林帶信號。"""
        df = data.copy()

        # 計算布林帶（如果數據中不存在）
        if "BB_Upper" not in df.columns or "BB_Lower" not in df.columns:
            middle_band = df["Close"].rolling(window=self.params["period"]).mean()
            std = df["Close"].rolling(window=self.params["period"]).std()
            df["BB_Upper"] = middle_band + (std * self.params["std_dev"])
            df["BB_Lower"] = middle_band - (std * self.params["std_dev"])

        # 生成信號：價格突破下軌買入，突破上軌賣出
        df["buy"] = (df["Close"] <= df["BB_Lower"]) & (df["Close"].shift(1) > df["BB_Lower"].shift(1))
        df["sell"] = (df["Close"] >= df["BB_Upper"]) & (df["Close"].shift(1) < df["BB_Upper"].shift(1))
        df["hold"] = ~(df["buy"] | df["sell"])

        df["buy_price"] = np.where(df["buy"], df["Close"], np.nan)
        df["sell_price"] = np.where(df["sell"], df["Close"], np.nan)

        return df


class RSIStrategy(BaseStrategy):
    """RSI 超買超賣策略"""

    def __init__(self, period: int = 14, overbought: float = 70, oversold: float = 30):
        """初始化 RSI 策略。

        Args:
            period: RSI 週期
            overbought: 超買閾值
            oversold: 超賣閾值
        """
        params = {"period": period, "overbought": overbought, "oversold": oversold}
        super().__init__(params)
        self.name = f"RSI_{period}_{overbought}_{oversold}"

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """生成 RSI 信號。"""
        df = data.copy()

        # 計算 RSI（如果數據中不存在）
        if "RSI" not in df.columns:
            delta = df["Close"].diff()
            gain = delta.clip(lower=0).rolling(window=self.params["period"]).mean()
            loss = (-delta.clip(upper=0)).rolling(window=self.params["period"]).mean()
            rs = gain / loss.replace(0, float("nan"))
            df["RSI"] = 100 - 100 / (1 + rs)
            df["RSI"] = df["RSI"].fillna(50)

        # 生成信號：超賣買入，超買賣出
        df["buy"] = (df["RSI"] < self.params["oversold"]) & (df["RSI"].shift(1) >= self.params["oversold"])
        df["sell"] = (df["RSI"] > self.params["overbought"]) & (df["RSI"].shift(1) <= self.params["overbought"])
        df["hold"] = ~(df["buy"] | df["sell"])

        df["buy_price"] = np.where(df["buy"], df["Close"], np.nan)
        df["sell_price"] = np.where(df["sell"], df["Close"], np.nan)

        return df


class MACDStrategy(BaseStrategy):
    """MACD 動能策略"""

    def __init__(self, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9):
        """初始化 MACD 策略。

        Args:
            fast_period: 快線週期
            slow_period: 慢線週期
            signal_period: 信號線週期
        """
        params = {
            "fast_period": fast_period,
            "slow_period": slow_period,
            "signal_period": signal_period
        }
        super().__init__(params)
        self.name = f"MACD_{fast_period}_{slow_period}_{signal_period}"

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """生成 MACD 信號。"""
        df = data.copy()

        # 計算 MACD（如果數據中不存在）
        if "MACD" not in df.columns or "MACD_Signal" not in df.columns:
            df["EMA_Fast"] = df["Close"].ewm(span=self.params["fast_period"], adjust=False).mean()
            df["EMA_Slow"] = df["Close"].ewm(span=self.params["slow_period"], adjust=False).mean()
            df["MACD"] = df["EMA_Fast"] - df["EMA_Slow"]
            df["MACD_Signal"] = df["MACD"].ewm(span=self.params["signal_period"], adjust=False).mean()
            df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]

        # 生成信號：MACD 上穿信號線買入，下穿信號線賣出
        df["buy"] = (df["MACD"] > df["MACD_Signal"]) & (df["MACD"].shift(1) <= df["MACD_Signal"].shift(1))
        df["sell"] = (df["MACD"] < df["MACD_Signal"]) & (df["MACD"].shift(1) >= df["MACD_Signal"].shift(1))
        df["hold"] = ~(df["buy"] | df["sell"])

        df["buy_price"] = np.where(df["buy"], df["Close"], np.nan)
        df["sell_price"] = np.where(df["sell"], df["Close"], np.nan)

        return df


class CombinedStrategy(BaseStrategy):
    """綜合策略：結合多個技術指標"""

    def __init__(self, ma_fast: int = 5, ma_slow: int = 20, rsi_period: int = 14):
        """初始化綜合策略。

        Args:
            ma_fast: 快速 MA 週期
            ma_slow: 慢速 MA 週期
            rsi_period: RSI 週期
        """
        params = {
            "ma_fast": ma_fast,
            "ma_slow": ma_slow,
            "rsi_period": rsi_period
        }
        super().__init__(params)
        self.name = f"Combined_MA{ma_fast}_{ma_slow}_RSI{rsi_period}"

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """生成綜合策略信號。"""
        df = data.copy()

        # 計算指標
        fast_ma = df["Close"].rolling(window=self.params["ma_fast"]).mean()
        slow_ma = df["Close"].rolling(window=self.params["ma_slow"]).mean()

        if "RSI" not in df.columns:
            delta = df["Close"].diff()
            gain = delta.clip(lower=0).rolling(window=self.params["rsi_period"]).mean()
            loss = (-delta.clip(upper=0)).rolling(window=self.params["rsi_period"]).mean()
            rs = gain / loss.replace(0, float("nan"))
            df["RSI"] = 100 - 100 / (1 + rs)
            df["RSI"] = df["RSI"].fillna(50)

        # 多條件買入信號：
        # 1. 快速 MA 上穿慢速 MA
        # 2. RSI 在 40-60 健康區間
        # 3. 價格在 MA20 之上
        ma_cross_buy = (fast_ma > slow_ma) & (fast_ma.shift(1) <= slow_ma.shift(1))
        rsi_healthy = (df["RSI"] > 40) & (df["RSI"] < 60)
        price_above_ma20 = df["Close"] > df["Close"].rolling(window=20).mean()

        # 賣出信號：
        # 1. 快速 MA 下穿慢速 MA
        # 2. RSI > 70 超買
        ma_cross_sell = (fast_ma < slow_ma) & (fast_ma.shift(1) >= slow_ma.shift(1))
        rsi_overbought = df["RSI"] > 70

        df["buy"] = ma_cross_buy & rsi_healthy & price_above_ma20
        df["sell"] = ma_cross_sell | rsi_overbought
        df["hold"] = ~(df["buy"] | df["sell"])

        df["buy_price"] = np.where(df["buy"], df["Close"], np.nan)
        df["sell_price"] = np.where(df["sell"], df["Close"], np.nan)

        return df


# 策略工廠函數
def create_strategy(strategy_name: str, **params) -> BaseStrategy:
    """創建策略實例。

    Args:
        strategy_name: 策略名稱
        **params: 策略參數

    Returns:
        策略實例

    Raises:
        ValueError: 未知策略名稱
    """
    strategy_map = {
        "ma_crossover": MovingAverageCrossover,
        "bollinger_bands": BollingerBandsStrategy,
        "rsi": RSIStrategy,
        "macd": MACDStrategy,
        "combined": CombinedStrategy,
    }

    if strategy_name not in strategy_map:
        raise ValueError(f"未知策略: {strategy_name}。可用策略: {list(strategy_map.keys())}")

    strategy_class = strategy_map[strategy_name]
    return strategy_class(**params)