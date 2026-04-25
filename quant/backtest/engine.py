"""專業夜間回測引擎核心模組。

此模組提供完整的回測框架，支持多策略、多標的、真實交易成本，
並與現有的數據管理器無縫整合。
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Callable
import pandas as pd
import numpy as np

from quant.data.manager import get_data_manager

logger = logging.getLogger(__name__)


class BacktestResult:
    """回測結果容器類"""

    def __init__(self):
        self.trades = []
        self.equity_curve = []
        self.metrics = {}
        self.signals = []

    def add_trade(self, trade: Dict[str, Any]) -> None:
        """添加交易記錄"""
        self.trades.append(trade)

    def add_equity_point(self, timestamp: datetime, equity: float) -> None:
        """添加權益曲線點"""
        self.equity_curve.append({
            "timestamp": timestamp,
            "equity": equity
        })

    def add_signal(self, signal: Dict[str, Any]) -> None:
        """添加交易信號"""
        self.signals.append(signal)

    def calculate_metrics(self) -> Dict[str, float]:
        """計算績效指標"""
        if not self.trades:
            return {}

        # 計算基礎指標
        trades_df = pd.DataFrame(self.trades)
        winning_trades = trades_df[trades_df["pnl"] > 0]
        losing_trades = trades_df[trades_df["pnl"] < 0]

        total_trades = len(trades_df)
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0

        # 平均盈虧
        avg_win = winning_trades["pnl"].mean() if len(winning_trades) > 0 else 0
        avg_loss = abs(losing_trades["pnl"].mean()) if len(losing_trades) > 0 else 0
        profit_factor = (avg_win * len(winning_trades)) / (avg_loss * len(losing_trades)) if avg_loss > 0 else float('inf')

        # 最大回撤
        equity_df = pd.DataFrame(self.equity_curve)
        if not equity_df.empty:
            equity_df["peak"] = equity_df["equity"].cummax()
            equity_df["drawdown"] = (equity_df["equity"] - equity_df["peak"]) / equity_df["peak"]
            max_drawdown = equity_df["drawdown"].min()
        else:
            max_drawdown = 0

        # 夏普比率（簡化版）
        if len(self.equity_curve) >= 2:
            returns = []
            for i in range(1, len(self.equity_curve)):
                ret = (self.equity_curve[i]["equity"] - self.equity_curve[i-1]["equity"]) / self.equity_curve[i-1]["equity"]
                returns.append(ret)
            if returns:
                avg_return = np.mean(returns)
                std_return = np.std(returns)
                sharpe_ratio = avg_return / std_return * np.sqrt(252) if std_return > 0 else 0
            else:
                sharpe_ratio = 0
        else:
            sharpe_ratio = 0

        self.metrics = {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe_ratio,
            "total_pnl": trades_df["pnl"].sum(),
            "avg_pnl_per_trade": trades_df["pnl"].mean(),
        }

        return self.metrics


class BacktestEngine:
    """專業回測引擎"""

    def __init__(
        self,
        initial_capital: float = 100000.0,
        commission_rate: float = 0.001,  # 0.1%
        slippage_rate: float = 0.0005,   # 0.05%
        use_cache: bool = True
    ):
        """初始化回測引擎。

        Args:
            initial_capital: 初始資金
            commission_rate: 手續費率
            slippage_rate: 滑點率
            use_cache: 是否使用緩存數據
        """
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self.data_manager = get_data_manager(use_cache=use_cache)
        self.results = {}

    def run_strategy(
        self,
        symbol: str,
        strategy_func: Callable,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: str = "180d",  # 預設回測 180 天
        **strategy_params
    ) -> BacktestResult:
        """對單一標的運行策略回測。

        Args:
            symbol: 標的代碼
            strategy_func: 策略函數
            start_date: 開始日期 (YYYY-MM-DD)
            end_date: 結束日期 (YYYY-MM-DD)
            period: 數據期間（如果未指定 start_date/end_date）
            **strategy_params: 策略參數

        Returns:
            回測結果
        """
        # 獲取歷史數據
        if start_date and end_date:
            # TODO: 實現日期範圍下載
            data = self.data_manager.get_historical_data(symbol, period="max", interval="1d")
            if data is not None:
                mask = (data.index >= start_date) & (data.index <= end_date)
                data = data[mask]
        else:
            data = self.data_manager.get_historical_data(symbol, period=period, interval="1d")

        if data is None or data.empty:
            logger.error(f"無法獲取 {symbol} 的歷史數據")
            return BacktestResult()

        # 初始化回測狀態
        result = BacktestResult()
        cash = self.initial_capital
        position = 0
        equity = cash

        # 記錄初始權益
        result.add_equity_point(data.index[0], equity)

        # 運行策略
        signals = strategy_func(data, **strategy_params)

        # 執行交易
        for i in range(1, len(data)):
            current_date = data.index[i]
            current_price = data.iloc[i]["Close"]

            # 檢查是否有信號
            if i < len(signals):
                signal = signals.iloc[i]

                # 買入信號
                if signal.get("buy", False) and cash > 0:
                    # 計算可買入數量（最小1股）
                    max_shares = cash // (current_price * (1 + self.commission_rate + self.slippage_rate))
                    if max_shares >= 1:
                        shares_to_buy = max_shares
                        cost = shares_to_buy * current_price
                        commission = cost * self.commission_rate
                        total_cost = cost + commission

                        if total_cost <= cash:
                            position += shares_to_buy
                            cash -= total_cost

                            result.add_trade({
                                "date": current_date,
                                "type": "BUY",
                                "symbol": symbol,
                                "price": current_price,
                                "shares": shares_to_buy,
                                "cost": total_cost,
                                "commission": commission,
                            })

                # 賣出信號
                elif signal.get("sell", False) and position > 0:
                    shares_to_sell = position
                    revenue = shares_to_sell * current_price
                    commission = revenue * self.commission_rate
                    total_revenue = revenue - commission

                    position = 0
                    cash += total_revenue

                    result.add_trade({
                        "date": current_date,
                        "type": "SELL",
                        "symbol": symbol,
                        "price": current_price,
                        "shares": shares_to_sell,
                        "revenue": total_revenue,
                        "commission": commission,
                        "pnl": total_revenue - (shares_to_sell * signal.get("buy_price", current_price))
                    })

            # 更新權益
            equity = cash + (position * current_price)
            result.add_equity_point(current_date, equity)

            # 記錄信號
            if i < len(signals):
                result.add_signal({
                    "date": current_date,
                    "signal": signals.iloc[i].to_dict(),
                    "price": current_price,
                    "position": position,
                    "cash": cash,
                    "equity": equity
                })

        # 最終平倉
        if position > 0:
            last_price = data.iloc[-1]["Close"]
            revenue = position * last_price
            commission = revenue * self.commission_rate
            total_revenue = revenue - commission

            result.add_trade({
                "date": data.index[-1],
                "type": "SELL",
                "symbol": symbol,
                "price": last_price,
                "shares": position,
                "revenue": total_revenue,
                "commission": commission,
                "pnl": total_revenue - (position * data.iloc[-2]["Close"] if len(data) > 1 else last_price)
            })

        # 計算績效指標
        result.calculate_metrics()
        return result

    def run_watchlist_strategy(
        self,
        watchlist: List[str],
        strategy_func: Callable,
        allocation: Optional[Dict[str, float]] = None,
        **strategy_params
    ) -> Dict[str, BacktestResult]:
        """對觀察清單運行策略回測（多標的）。

        Args:
            watchlist: 觀察清單代碼列表
            strategy_func: 策略函數
            allocation: 資金分配比例（字典：代碼->比例）
            **strategy_params: 策略參數

        Returns:
            各標的回測結果字典
        """
        results = {}

        # 如果未指定分配比例，平均分配
        if allocation is None:
            allocation = {symbol: 1.0 / len(watchlist) for symbol in watchlist}

        total_allocation = sum(allocation.values())
        if abs(total_allocation - 1.0) > 0.01:  # 允許微小誤差
            logger.warning(f"資金分配總和為 {total_allocation}，將進行標準化")
            allocation = {k: v / total_allocation for k, v in allocation.items()}

        for symbol in watchlist:
            if symbol in allocation:
                # 按比例分配資金
                symbol_capital = self.initial_capital * allocation[symbol]

                # 臨時創建一個分配了資金的引擎
                symbol_engine = BacktestEngine(
                    initial_capital=symbol_capital,
                    commission_rate=self.commission_rate,
                    slippage_rate=self.slippage_rate
                )

                result = symbol_engine.run_strategy(
                    symbol=symbol,
                    strategy_func=strategy_func,
                    **strategy_params
                )

                results[symbol] = result

        self.results = results
        return results

    def aggregate_results(self, results: Dict[str, BacktestResult]) -> Dict[str, Any]:
        """聚合多標的回測結果。

        Args:
            results: 各標的回測結果字典

        Returns:
            聚合績效指標
        """
        if not results:
            return {}

        # 合併所有交易
        all_trades = []
        all_equity_points = {}
        total_initial_capital = self.initial_capital

        for symbol, result in results.items():
            all_trades.extend(result.trades)

            # 合併權益曲線（按日期）
            for point in result.equity_curve:
                date = point["timestamp"]
                if date not in all_equity_points:
                    all_equity_points[date] = 0
                all_equity_points[date] += point["equity"]

        # 計算組合績效
        if all_trades:
            trades_df = pd.DataFrame(all_trades)
            total_pnl = trades_df["pnl"].sum() if "pnl" in trades_df.columns else 0

            # 權益曲線
            equity_curve = []
            for date, equity in sorted(all_equity_points.items()):
                equity_curve.append({
                    "timestamp": date,
                    "equity": equity
                })

            # 計算最大回撤
            if equity_curve:
                equity_df = pd.DataFrame(equity_curve)
                equity_df["peak"] = equity_df["equity"].cummax()
                equity_df["drawdown"] = (equity_df["equity"] - equity_df["peak"]) / equity_df["peak"]
                max_drawdown = equity_df["drawdown"].min()
            else:
                max_drawdown = 0

            # 計算夏普比率
            if len(equity_curve) >= 2:
                returns = []
                for i in range(1, len(equity_curve)):
                    ret = (equity_curve[i]["equity"] - equity_curve[i-1]["equity"]) / equity_curve[i-1]["equity"]
                    returns.append(ret)
                if returns:
                    avg_return = np.mean(returns)
                    std_return = np.std(returns)
                    sharpe_ratio = avg_return / std_return * np.sqrt(252) if std_return > 0 else 0
                else:
                    sharpe_ratio = 0
            else:
                sharpe_ratio = 0

            aggregated = {
                "total_symbols": len(results),
                "total_trades": len(all_trades),
                "total_pnl": total_pnl,
                "total_return": total_pnl / total_initial_capital,
                "max_drawdown": max_drawdown,
                "sharpe_ratio": sharpe_ratio,
                "symbol_results": {symbol: result.metrics for symbol, result in results.items()}
            }

            return aggregated
        else:
            return {}


def format_backtest_report(results: Dict[str, BacktestResult], aggregated: Dict[str, Any]) -> str:
    """格式化回測報告用於顯示或保存。

    Args:
        results: 各標的回測結果
        aggregated: 聚合績效指標

    Returns:
        格式化報告字符串
    """
    if not results:
        return "⚠️ 無回測結果"

    lines = ["📊 夜間回測報告"]
    lines.append("=" * 40)

    # 聚合績效
    lines.append("\n🏆 組合績效摘要：")
    lines.append(f"  標的數量: {aggregated.get('total_symbols', 0)}")
    lines.append(f"  總交易次數: {aggregated.get('total_trades', 0)}")
    lines.append(f"  總損益: ${aggregated.get('total_pnl', 0):.2f}")
    lines.append(f"  總報酬率: {aggregated.get('total_return', 0) * 100:.2f}%")
    lines.append(f"  最大回撤: {aggregated.get('max_drawdown', 0) * 100:.2f}%")
    lines.append(f"  夏普比率: {aggregated.get('sharpe_ratio', 0):.2f}")

    lines.append("\n📈 各標的績效：")
    for symbol, result in results.items():
        metrics = result.metrics
        if metrics:
            lines.append(f"\n  {symbol}:")
            lines.append(f"    勝率: {metrics.get('win_rate', 0) * 100:.1f}%")
            lines.append(f"    交易次數: {metrics.get('total_trades', 0)}")
            lines.append(f"    平均盈虧比: {metrics.get('profit_factor', 0):.2f}")
            lines.append(f"    累積損益: ${metrics.get('total_pnl', 0):.2f}")

    lines.append("\n" + "=" * 40)
    lines.append("💡 僅供參考，過往績效不代表未來表現")

    return "\n".join(lines)


# 單例實例
_backtest_engine_instance = None

def get_backtest_engine(initial_capital: float = 100000.0) -> BacktestEngine:
    """獲取回測引擎單例實例。

    Args:
        initial_capital: 初始資金

    Returns:
        BacktestEngine 實例
    """
    global _backtest_engine_instance
    if _backtest_engine_instance is None:
        _backtest_engine_instance = BacktestEngine(initial_capital=initial_capital)
    return _backtest_engine_instance