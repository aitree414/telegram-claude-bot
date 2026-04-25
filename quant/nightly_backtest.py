#!/usr/bin/env python3
"""夜間回測引擎主程序。

此程序讀取觀察清單，運行多策略回測，生成績效報告，
並實現自動化的夜間回測工作流程。
"""

import sys
import logging
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

# 添加項目根目錄到 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from quant.backtest.engine import get_backtest_engine, format_backtest_report
from quant.backtest.strategies import (
    MovingAverageCrossover,
    BollingerBandsStrategy,
    RSIStrategy,
    MACDStrategy,
    CombinedStrategy,
    create_strategy
)
from quant.backtest.analyzer import PerformanceAnalyzer
from quant.backtest.optimizer import ParameterOptimizer, create_optimization_report
from quant.backtest.validator import StrategyValidator
from quant.data.manager import get_data_manager

# 配置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(project_root / "logs" / "nightly_backtest.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class NightlyBacktestEngine:
    """夜間回測引擎"""

    def __init__(self, initial_capital: float = 100000.0):
        """初始化夜間回測引擎。

        Args:
            initial_capital: 初始資金
        """
        self.initial_capital = initial_capital
        self.backtest_engine = get_backtest_engine(initial_capital)
        self.data_manager = get_data_manager()
        self.analyzer = PerformanceAnalyzer()
        self.validator = StrategyValidator()

        # 默認策略配置
        self.default_strategies = [
            {
                "name": "MA_Crossover_5_20",
                "class": MovingAverageCrossover,
                "params": {"fast_period": 5, "slow_period": 20}
            },
            {
                "name": "Bollinger_Bands_20_2",
                "class": BollingerBandsStrategy,
                "params": {"period": 20, "std_dev": 2.0}
            },
            {
                "name": "RSI_14_30_70",
                "class": RSIStrategy,
                "params": {"period": 14, "overbought": 70, "oversold": 30}
            },
            {
                "name": "MACD_12_26_9",
                "class": MACDStrategy,
                "params": {"fast_period": 12, "slow_period": 26, "signal_period": 9}
            },
            {
                "name": "Combined_Strategy",
                "class": CombinedStrategy,
                "params": {"ma_fast": 5, "ma_slow": 20, "rsi_period": 14}
            }
        ]

    def load_watchlist(self) -> List[str]:
        """加載觀察清單。

        Returns:
            股票代碼列表
        """
        watchlist_path = Path.home() / "telegram-claude-bot" / "watchlist.json"
        backup_path = project_root / "data" / "watchlist.json"

        symbols = []

        # 嘗試主要路徑
        for path in [watchlist_path, backup_path]:
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        symbols = data.get("symbols", [])
                        logger.info(f"從 {path} 加載了 {len(symbols)} 個標的")
                        break
                except Exception as e:
                    logger.error(f"加載觀察清單 {path} 失敗: {e}")

        # 如果沒有找到，使用默認清單
        if not symbols:
            default_symbols = ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA", "2330.TW", "2317.TW"]
            symbols = default_symbols
            logger.warning(f"使用默認觀察清單: {len(symbols)} 個標的")

        return symbols

    def run_single_symbol_backtest(
        self,
        symbol: str,
        strategy_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """對單一標的運行回測。

        Args:
            symbol: 股票代碼
            strategy_config: 策略配置

        Returns:
            回測結果
        """
        logger.info(f"開始回測 {symbol}，策略: {strategy_config['name']}")

        try:
            # 創建策略實例
            strategy_class = strategy_config["class"]
            strategy_params = strategy_config.get("params", {})
            strategy = strategy_class(**strategy_params)

            # 運行回測
            result = self.backtest_engine.run_strategy(
                symbol=symbol,
                strategy_func=strategy,
                period="180d"  # 回測 180 天
            )

            # 計算詳細指標
            metrics = self.analyzer.calculate_detailed_metrics(
                trades=result.trades,
                equity_curve=result.equity_curve,
                initial_capital=self.initial_capital
            )

            return {
                "symbol": symbol,
                "strategy_name": strategy_config["name"],
                "result": result,
                "metrics": metrics,
                "success": True
            }

        except Exception as e:
            logger.error(f"回測 {symbol} 失敗: {e}")
            return {
                "symbol": symbol,
                "strategy_name": strategy_config["name"],
                "error": str(e),
                "success": False
            }

    def run_all_strategies(self, symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        """運行所有默認策略。

        Args:
            symbols: 股票代碼列表，如果為 None 則加載觀察清單

        Returns:
            所有回測結果
        """
        if symbols is None:
            symbols = self.load_watchlist()

        if not symbols:
            logger.error("無有效的觀察清單")
            return {}

        all_results = {}
        strategy_results = {}

        for strategy_config in self.default_strategies:
            strategy_name = strategy_config["name"]
            logger.info(f"運行策略: {strategy_name}")

            symbol_results = []
            successful_symbols = []

            for symbol in symbols:
                result = self.run_single_symbol_backtest(symbol, strategy_config)
                symbol_results.append(result)

                if result["success"]:
                    successful_symbols.append(symbol)

            # 聚合策略績效
            if successful_symbols:
                # 收集所有成功回測的指標
                all_metrics = []
                for result in symbol_results:
                    if result["success"]:
                        all_metrics.append(result["metrics"])

                if all_metrics:
                    # 計算平均績效
                    avg_metrics = {}
                    for key in all_metrics[0].keys():
                        values = [m.get(key, 0) for m in all_metrics if key in m]
                        if values:
                            avg_metrics[key] = sum(values) / len(values)

                    strategy_results[strategy_name] = {
                        "symbol_results": symbol_results,
                        "avg_metrics": avg_metrics,
                        "successful_symbols": successful_symbols,
                        "success_rate": len(successful_symbols) / len(symbols)
                    }

            all_results[strategy_name] = symbol_results

        # 策略比較
        comparison_df = self.analyzer.compare_strategies(
            {name: data["avg_metrics"] for name, data in strategy_results.items()}
        )

        return {
            "timestamp": datetime.now().isoformat(),
            "symbols": symbols,
            "all_results": all_results,
            "strategy_results": strategy_results,
            "comparison": comparison_df.to_dict("records") if not comparison_df.empty else [],
            "best_strategy": comparison_df.iloc[0]["strategy"] if not comparison_df.empty else None
        }

    def optimize_strategy_parameters(
        self,
        symbol: str,
        strategy_name: str,
        param_grid: Dict[str, List[Any]]
    ) -> Dict[str, Any]:
        """優化策略參數。

        Args:
            symbol: 股票代碼（用於優化）
            strategy_name: 策略名稱
            param_grid: 參數網格

        Returns:
            優化結果
        """
        logger.info(f"開始優化 {strategy_name} 參數")

        # 獲取歷史數據
        data = self.data_manager.get_historical_data(symbol, period="360d", interval="1d")
        if data is None:
            logger.error(f"無法獲取 {symbol} 的歷史數據")
            return {"error": "數據獲取失敗"}

        # 創建策略類（根據名稱）
        strategy_map = {
            "MA_Crossover": MovingAverageCrossover,
            "Bollinger_Bands": BollingerBandsStrategy,
            "RSI": RSIStrategy,
            "MACD": MACDStrategy,
            "Combined": CombinedStrategy,
        }

        strategy_base_name = strategy_name.split("_")[0]
        if strategy_base_name not in strategy_map:
            logger.error(f"未知策略類型: {strategy_base_name}")
            return {"error": f"未知策略類型: {strategy_base_name}"}

        strategy_class = strategy_map[strategy_base_name]

        # 創建優化器
        def objective_function(params: Dict[str, Any]) -> float:
            """目標函數：運行回測並返回夏普比率。"""
            try:
                strategy = strategy_class(**params)
                result = self.backtest_engine.run_strategy(
                    symbol=symbol,
                    strategy_func=strategy,
                    period="180d"
                )
                metrics = result.calculate_metrics()
                return metrics.get("sharpe_ratio", 0)
            except Exception as e:
                logger.error(f"參數 {params} 評估失敗: {e}")
                return float('-inf')

        optimizer = ParameterOptimizer(objective_function)

        # 執行優化
        best_params, best_score, results_df = optimizer.grid_search(
            param_grid=param_grid,
            maximize=True
        )

        return {
            "symbol": symbol,
            "strategy_name": strategy_name,
            "best_params": best_params,
            "best_score": best_score,
            "results_count": len(results_df),
            "optimization_report": create_optimization_report(
                best_params, best_score, results_df, strategy_name
            )
        }

    def generate_nightly_report(self, results: Dict[str, Any]) -> str:
        """生成夜間回測報告。

        Args:
            results: 回測結果

        Returns:
            格式化報告字符串
        """
        if not results:
            return "⚠️ 無回測結果可用於生成報告"

        lines = [
            "🌙 夜間回測報告",
            f"生成時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 60,
        ]

        # 觀察清單
        symbols = results.get("symbols", [])
        lines.append(f"\n📋 觀察清單: {len(symbols)} 個標的")
        if symbols:
            lines.append(f"  標的: {', '.join(symbols[:10])}" + ("..." if len(symbols) > 10 else ""))

        # 策略比較
        comparison = results.get("comparison", [])
        if comparison:
            lines.append("\n🏆 策略績效排名:")
            for i, row in enumerate(comparison[:5], 1):  # 顯示前5名
                lines.append(
                    f"  {i}. {row['strategy']}: "
                    f"報酬率={row.get('total_return', 0):.1f}%, "
                    f"夏普比率={row.get('sharpe_ratio', 0):.2f}, "
                    f"勝率={row.get('win_rate', 0):.1f}%"
                )

        # 最佳策略
        best_strategy = results.get("best_strategy")
        if best_strategy:
            lines.append(f"\n🎯 本日最佳策略: {best_strategy}")

            # 顯示最佳策略的詳細績效
            strategy_results = results.get("strategy_results", {}).get(best_strategy)
            if strategy_results:
                avg_metrics = strategy_results.get("avg_metrics", {})
                lines.append(f"  平均勝率: {avg_metrics.get('win_rate', 0) * 100:.1f}%")
                lines.append(f"  平均夏普比率: {avg_metrics.get('sharpe_ratio', 0):.2f}")
                lines.append(f"  平均最大回撤: {avg_metrics.get('max_drawdown', 0) * 100:.1f}%")
                lines.append(f"  成功標的: {len(strategy_results.get('successful_symbols', []))}/{len(symbols)}")

        # 策略成功率
        strategy_results = results.get("strategy_results", {})
        if strategy_results:
            lines.append("\n📈 策略成功率:")
            for strategy_name, data in strategy_results.items():
                success_rate = data.get("success_rate", 0)
                lines.append(f"  {strategy_name}: {success_rate * 100:.1f}%")

        # 風險提示
        lines.append("\n⚠️ 風險提示:")
        lines.append("  1. 過往績效不代表未來表現")
        lines.append("  2. 回測結果受數據質量和參數設置影響")
        lines.append("  3. 建議在實盤前進行樣本外測試")
        lines.append("  4. 注意市場環境變化對策略的影響")

        # 建議
        lines.append("\n💡 明日交易建議:")
        if best_strategy:
            lines.append(f"  1. 考慮使用 {best_strategy} 策略")
            lines.append(f"  2. 關注 {', '.join(symbols[:3])} 等標的")
            lines.append("  3. 設置適當的止損位")
            lines.append("  4. 控制單筆交易風險（建議 < 2%）")
        else:
            lines.append("  1. 市場環境不明朗，建議觀望")
            lines.append("  2. 減少交易頻率")
            lines.append("  3. 加強風險控制")

        lines.append("\n" + "=" * 60)
        lines.append("報告結束 - 祝你交易順利！")

        return "\n".join(lines)

    def save_report(self, report: str, results: Dict[str, Any]) -> None:
        """保存報告到文件。

        Args:
            report: 報告內容
            results: 原始結果數據
        """
        # 創建報告目錄
        report_dir = project_root / "reports" / "nightly_backtest"
        report_dir.mkdir(parents=True, exist_ok=True)

        # 保存文本報告
        report_date = datetime.now().strftime("%Y%m%d")
        report_file = report_dir / f"backtest_report_{report_date}.txt"

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)

        logger.info(f"報告已保存到: {report_file}")

        # 保存 JSON 數據（用於後續分析）
        json_file = report_dir / f"backtest_data_{report_date}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)

        logger.info(f"原始數據已保存到: {json_file}")

    def run(self) -> None:
        """運行完整的夜間回測流程。"""
        logger.info("=" * 60)
        logger.info("開始夜間回測流程")
        logger.info("=" * 60)

        try:
            # 1. 加載觀察清單
            symbols = self.load_watchlist()
            logger.info(f"加載了 {len(symbols)} 個觀察標的")

            # 2. 運行所有策略
            results = self.run_all_strategies(symbols)
            if not results:
                logger.error("回測失敗，無結果")
                return

            # 3. 生成報告
            report = self.generate_nightly_report(results)

            # 4. 保存報告
            self.save_report(report, results)

            # 5. 輸出報告摘要
            print("\n" + "=" * 60)
            print("夜間回測完成！")
            print("=" * 60)
            print(report[:2000] + "..." if len(report) > 2000 else report)

            logger.info("夜間回測流程完成")

        except Exception as e:
            logger.error(f"夜間回測流程失敗: {e}")
            raise


def main():
    """主函數。"""
    try:
        # 初始化夜間回測引擎
        engine = NightlyBacktestEngine(initial_capital=100000.0)

        # 運行回測
        engine.run()

    except KeyboardInterrupt:
        logger.info("用戶中斷夜間回測")
        print("\n夜間回測已被用戶中斷")
        sys.exit(1)
    except Exception as e:
        logger.error(f"夜間回測主程序失敗: {e}")
        print(f"錯誤: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()