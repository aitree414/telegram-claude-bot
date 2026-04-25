"""回測績效分析模組。

提供專業的績效指標計算、風險分析和報告生成功能。
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class PerformanceAnalyzer:
    """績效分析器"""

    @staticmethod
    def calculate_detailed_metrics(
        trades: List[Dict[str, Any]],
        equity_curve: List[Dict[str, Any]],
        initial_capital: float
    ) -> Dict[str, Any]:
        """計算詳細的績效指標。

        Args:
            trades: 交易記錄列表
            equity_curve: 權益曲線列表
            initial_capital: 初始資金

        Returns:
            詳細績效指標字典
        """
        if not trades or not equity_curve:
            return {}

        # 轉換為 DataFrame
        trades_df = pd.DataFrame(trades)
        equity_df = pd.DataFrame(equity_curve)

        # 基本指標
        total_trades = len(trades_df)
        winning_trades = trades_df[trades_df.get("pnl", 0) > 0]
        losing_trades = trades_df[trades_df.get("pnl", 0) < 0]

        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0

        # 平均盈虧
        avg_win = winning_trades["pnl"].mean() if len(winning_trades) > 0 else 0
        avg_loss = abs(losing_trades["pnl"].mean()) if len(losing_trades) > 0 else 0

        # 盈虧比（平均盈利 / 平均虧損）
        profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float('inf')

        # 盈利因子（總盈利 / 總虧損）
        total_profit = winning_trades["pnl"].sum() if len(winning_trades) > 0 else 0
        total_loss = abs(losing_trades["pnl"].sum()) if len(losing_trades) > 0 else 0
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')

        # 總損益
        total_pnl = trades_df["pnl"].sum() if "pnl" in trades_df.columns else 0

        # 年化報酬率
        if len(equity_curve) >= 2:
            start_date = equity_curve[0]["timestamp"]
            end_date = equity_curve[-1]["timestamp"]

            if isinstance(start_date, str):
                start_date = pd.to_datetime(start_date)
            if isinstance(end_date, str):
                end_date = pd.to_datetime(end_date)

            days = (end_date - start_date).days
            if days > 0:
                total_return = total_pnl / initial_capital
                annualized_return = (1 + total_return) ** (365 / days) - 1
            else:
                annualized_return = 0
        else:
            annualized_return = 0

        # 最大回撤
        if not equity_df.empty:
            equity_df["peak"] = equity_df["equity"].cummax()
            equity_df["drawdown"] = (equity_df["equity"] - equity_df["peak"]) / equity_df["peak"]
            max_drawdown = equity_df["drawdown"].min()

            # 最大回撤持續時間
            drawdown_duration = 0
            current_duration = 0
            for dd in equity_df["drawdown"]:
                if dd < 0:
                    current_duration += 1
                    drawdown_duration = max(drawdown_duration, current_duration)
                else:
                    current_duration = 0
        else:
            max_drawdown = 0
            drawdown_duration = 0

        # 夏普比率
        if len(equity_curve) >= 2:
            returns = []
            for i in range(1, len(equity_curve)):
                ret = (equity_curve[i]["equity"] - equity_curve[i-1]["equity"]) / equity_curve[i-1]["equity"]
                returns.append(ret)

            if returns:
                avg_return = np.mean(returns)
                std_return = np.std(returns)
                # 年化夏普比率（假設無風險利率為0）
                sharpe_ratio = avg_return / std_return * np.sqrt(252) if std_return > 0 else 0
            else:
                sharpe_ratio = 0
        else:
            sharpe_ratio = 0

        # 索提諾比率（只考慮下行風險）
        if len(equity_curve) >= 2:
            returns = []
            for i in range(1, len(equity_curve)):
                ret = (equity_curve[i]["equity"] - equity_curve[i-1]["equity"]) / equity_curve[i-1]["equity"]
                returns.append(ret)

            if returns:
                negative_returns = [r for r in returns if r < 0]
                if negative_returns:
                    downside_std = np.std(negative_returns)
                    avg_return = np.mean(returns)
                    sortino_ratio = avg_return / downside_std * np.sqrt(252) if downside_std > 0 else 0
                else:
                    sortino_ratio = float('inf')
            else:
                sortino_ratio = 0
        else:
            sortino_ratio = 0

        # 連續盈虧統計
        consecutive_wins = 0
        consecutive_losses = 0
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        current_consecutive = 0
        current_type = None

        for _, trade in trades_df.iterrows():
            pnl = trade.get("pnl", 0)
            trade_type = "win" if pnl > 0 else "loss" if pnl < 0 else "neutral"

            if trade_type == current_type and trade_type in ["win", "loss"]:
                current_consecutive += 1
            else:
                if current_type == "win":
                    max_consecutive_wins = max(max_consecutive_wins, current_consecutive)
                elif current_type == "loss":
                    max_consecutive_losses = max(max_consecutive_losses, current_consecutive)

                current_type = trade_type if trade_type in ["win", "loss"] else None
                current_consecutive = 1 if current_type else 0

        # 檢查最後一個序列
        if current_type == "win":
            max_consecutive_wins = max(max_consecutive_wins, current_consecutive)
        elif current_type == "loss":
            max_consecutive_losses = max(max_consecutive_losses, current_consecutive)

        # 風險調整後報酬
        risk_adjusted_return = annualized_return / abs(max_drawdown) if max_drawdown < 0 else annualized_return

        metrics = {
            # 基礎績效
            "total_trades": total_trades,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "total_return": total_pnl / initial_capital,
            "annualized_return": annualized_return,

            # 盈虧統計
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_loss_ratio": profit_loss_ratio,
            "profit_factor": profit_factor,
            "avg_pnl_per_trade": total_pnl / total_trades if total_trades > 0 else 0,

            # 風險指標
            "max_drawdown": max_drawdown,
            "max_drawdown_duration": drawdown_duration,
            "sharpe_ratio": sharpe_ratio,
            "sortino_ratio": sortino_ratio,
            "risk_adjusted_return": risk_adjusted_return,

            # 序列統計
            "max_consecutive_wins": max_consecutive_wins,
            "max_consecutive_losses": max_consecutive_losses,

            # 資金使用
            "initial_capital": initial_capital,
            "final_equity": equity_curve[-1]["equity"] if equity_curve else initial_capital,
        }

        return metrics

    @staticmethod
    def generate_performance_report(
        metrics: Dict[str, Any],
        strategy_name: str,
        symbol: str,
        period: str
    ) -> str:
        """生成績效報告。

        Args:
            metrics: 績效指標字典
            strategy_name: 策略名稱
            symbol: 標的代碼
            period: 回測期間

        Returns:
            格式化報告字符串
        """
        if not metrics:
            return f"⚠️ 無績效數據可用於 {symbol}"

        lines = [
            f"📊 {strategy_name} 績效報告",
            f"標的: {symbol} | 期間: {period}",
            "=" * 50,
        ]

        # 基礎績效
        lines.append("\n🎯 基礎績效：")
        lines.append(f"  總交易次數: {metrics.get('total_trades', 0)}")
        lines.append(f"  勝率: {metrics.get('win_rate', 0) * 100:.1f}%")
        lines.append(f"  總損益: ${metrics.get('total_pnl', 0):.2f}")
        lines.append(f"  總報酬率: {metrics.get('total_return', 0) * 100:.2f}%")
        lines.append(f"  年化報酬率: {metrics.get('annualized_return', 0) * 100:.2f}%")

        # 盈虧統計
        lines.append("\n💰 盈虧統計：")
        lines.append(f"  平均盈利: ${metrics.get('avg_win', 0):.2f}")
        lines.append(f"  平均虧損: ${metrics.get('avg_loss', 0):.2f}")
        lines.append(f"  盈虧比: {metrics.get('profit_loss_ratio', 0):.2f}")
        lines.append(f"  盈利因子: {metrics.get('profit_factor', 0):.2f}")
        lines.append(f"  每筆交易平均損益: ${metrics.get('avg_pnl_per_trade', 0):.2f}")

        # 風險指標
        lines.append("\n⚠️ 風險指標：")
        lines.append(f"  最大回撤: {metrics.get('max_drawdown', 0) * 100:.2f}%")
        lines.append(f"  最大回撤持續時間: {metrics.get('max_drawdown_duration', 0)} 天")
        lines.append(f"  夏普比率: {metrics.get('sharpe_ratio', 0):.2f}")
        lines.append(f"  索提諾比率: {metrics.get('sortino_ratio', 0):.2f}")
        lines.append(f"  風險調整後報酬: {metrics.get('risk_adjusted_return', 0):.2f}")

        # 序列統計
        lines.append("\n📈 序列統計：")
        lines.append(f"  最大連續盈利: {metrics.get('max_consecutive_wins', 0)} 次")
        lines.append(f"  最大連續虧損: {metrics.get('max_consecutive_losses', 0)} 次")

        # 資金使用
        lines.append("\n💵 資金使用：")
        lines.append(f"  初始資金: ${metrics.get('initial_capital', 0):.2f}")
        lines.append(f"  最終權益: ${metrics.get('final_equity', 0):.2f}")

        lines.append("\n" + "=" * 50)
        lines.append("💡 注意：過往績效不代表未來表現")

        return "\n".join(lines)

    @staticmethod
    def compare_strategies(
        strategy_results: Dict[str, Dict[str, Any]]
    ) -> pd.DataFrame:
        """比較多個策略的績效。

        Args:
            strategy_results: 策略名稱到績效指標的映射

        Returns:
            比較表格 DataFrame
        """
        if not strategy_results:
            return pd.DataFrame()

        # 提取關鍵指標
        comparison_data = []
        for strategy_name, metrics in strategy_results.items():
            if not metrics:
                continue

            row = {
                "strategy": strategy_name,
                "total_return": metrics.get("total_return", 0) * 100,  # 百分比
                "annualized_return": metrics.get("annualized_return", 0) * 100,
                "win_rate": metrics.get("win_rate", 0) * 100,
                "profit_factor": metrics.get("profit_factor", 0),
                "max_drawdown": metrics.get("max_drawdown", 0) * 100,
                "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                "total_trades": metrics.get("total_trades", 0),
            }
            comparison_data.append(row)

        df = pd.DataFrame(comparison_data)

        if not df.empty:
            # 排序（按總報酬率降序）
            df = df.sort_values("total_return", ascending=False)

        return df

    @staticmethod
    def generate_comparison_report(comparison_df: pd.DataFrame) -> str:
        """生成策略比較報告。

        Args:
            comparison_df: 策略比較 DataFrame

        Returns:
            格式化比較報告
        """
        if comparison_df.empty:
            return "⚠️ 無策略數據可用於比較"

        lines = ["🏆 策略績效比較", "=" * 60]

        # 表格頭
        header = f"{'策略':<20} {'總報酬率':<10} {'年化報酬':<10} {'勝率':<8} {'盈利因子':<10} {'最大回撤':<10} {'夏普比率':<10} {'交易次數':<8}"
        lines.append(header)
        lines.append("-" * 96)

        # 表格內容
        for _, row in comparison_df.iterrows():
            line = f"{row['strategy']:<20} " \
                   f"{row['total_return']:>9.1f}% " \
                   f"{row['annualized_return']:>9.1f}% " \
                   f"{row['win_rate']:>7.1f}% " \
                   f"{row['profit_factor']:>9.2f} " \
                   f"{row['max_drawdown']:>9.1f}% " \
                   f"{row['sharpe_ratio']:>9.2f} " \
                   f"{row['total_trades']:>8}"
            lines.append(line)

        # 最佳策略
        if not comparison_df.empty:
            best_by_return = comparison_df.iloc[0]
            best_by_sharpe = comparison_df.loc[comparison_df['sharpe_ratio'].idxmax()] if 'sharpe_ratio' in comparison_df.columns else None

            lines.append("\n🎖️ 最佳策略：")
            lines.append(f"  最高總報酬率: {best_by_return['strategy']} ({best_by_return['total_return']:.1f}%)")
            if best_by_sharpe is not None:
                lines.append(f"  最高夏普比率: {best_by_sharpe['strategy']} ({best_by_sharpe['sharpe_ratio']:.2f})")

        lines.append("\n" + "=" * 60)
        lines.append("💡 綜合考慮報酬率、風險和夏普比率選擇最佳策略")

        return "\n".join(lines)