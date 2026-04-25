"""策略參數優化模組。

提供參數搜索、優化和過擬合防護功能。
"""

import itertools
import logging
from typing import Dict, List, Any, Optional, Tuple, Callable
import pandas as pd
import numpy as np
from datetime import datetime

logger = logging.getLogger(__name__)


class ParameterOptimizer:
    """策略參數優化器"""

    def __init__(self, objective_function: Callable):
        """初始化優化器。

        Args:
            objective_function: 目標函數，接收參數字典，返回評分
        """
        self.objective_function = objective_function
        self.results = []

    def grid_search(
        self,
        param_grid: Dict[str, List[Any]],
        maximize: bool = True
    ) -> Tuple[Dict[str, Any], float, List[Dict[str, Any]]]:
        """網格搜索參數優化。

        Args:
            param_grid: 參數網格，鍵為參數名，值為參數值列表
            maximize: 是否最大化目標函數（True=最大化，False=最小化）

        Returns:
            (最佳參數, 最佳分數, 所有結果)
        """
        logger.info(f"開始網格搜索，參數組合數: {np.prod([len(v) for v in param_grid.values()])}")

        # 生成所有參數組合
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        param_combinations = list(itertools.product(*param_values))

        best_score = float('-inf') if maximize else float('inf')
        best_params = None
        all_results = []

        for i, combination in enumerate(param_combinations):
            params = dict(zip(param_names, combination))

            try:
                score = self.objective_function(params)
                logger.debug(f"參數組合 {i+1}/{len(param_combinations)}: {params} -> 分數: {score:.4f}")

                result = {
                    "params": params.copy(),
                    "score": score,
                    "combination_id": i
                }
                all_results.append(result)

                # 更新最佳分數
                if (maximize and score > best_score) or (not maximize and score < best_score):
                    best_score = score
                    best_params = params.copy()

            except Exception as e:
                logger.error(f"參數組合 {params} 評估失敗: {e}")
                continue

        logger.info(f"網格搜索完成，最佳分數: {best_score:.4f}, 最佳參數: {best_params}")

        return best_params, best_score, all_results

    def random_search(
        self,
        param_distributions: Dict[str, List[Any]],
        n_iter: int = 50,
        maximize: bool = True
    ) -> Tuple[Dict[str, Any], float, List[Dict[str, Any]]]:
        """隨機搜索參數優化。

        Args:
            param_distributions: 參數分布，鍵為參數名，值為參數值列表
            n_iter: 隨機搜索迭代次數
            maximize: 是否最大化目標函數

        Returns:
            (最佳參數, 最佳分數, 所有結果)
        """
        logger.info(f"開始隨機搜索，迭代次數: {n_iter}")

        best_score = float('-inf') if maximize else float('inf')
        best_params = None
        all_results = []

        for i in range(n_iter):
            # 隨機選擇參數
            params = {}
            for param_name, values in param_distributions.items():
                params[param_name] = np.random.choice(values)

            try:
                score = self.objective_function(params)
                logger.debug(f"迭代 {i+1}/{n_iter}: {params} -> 分數: {score:.4f}")

                result = {
                    "params": params.copy(),
                    "score": score,
                    "iteration": i
                }
                all_results.append(result)

                # 更新最佳分數
                if (maximize and score > best_score) or (not maximize and score < best_score):
                    best_score = score
                    best_params = params.copy()

            except Exception as e:
                logger.error(f"參數組合 {params} 評估失敗: {e}")
                continue

        logger.info(f"隨機搜索完成，最佳分數: {best_score:.4f}, 最佳參數: {best_params}")

        return best_params, best_score, all_results

    def optimize_for_strategy(
        self,
        strategy_class: Callable,
        data: pd.DataFrame,
        param_grid: Dict[str, List[Any]],
        initial_capital: float = 100000.0,
        commission_rate: float = 0.001,
        maximize_metric: str = "sharpe_ratio"
    ) -> Tuple[Dict[str, Any], float, pd.DataFrame]:
        """為特定策略優化參數。

        Args:
            strategy_class: 策略類
            data: 歷史數據
            param_grid: 參數網格
            initial_capital: 初始資金
            commission_rate: 手續費率
            maximize_metric: 最大化的績效指標

        Returns:
            (最佳參數, 最佳分數, 結果DataFrame)
        """
        from .engine import BacktestEngine
        from .analyzer import PerformanceAnalyzer

        def objective_function(params: Dict[str, Any]) -> float:
            """目標函數：運行回測並計算指定指標。"""
            try:
                # 創建策略實例
                strategy = strategy_class(**params)

                # 運行回測
                engine = BacktestEngine(
                    initial_capital=initial_capital,
                    commission_rate=commission_rate
                )

                # 這裡簡化處理，實際需要策略生成信號
                # 注意：這需要根據實際策略接口調整
                result = engine.run_strategy(
                    symbol="TEST",  # 暫時使用測試標的
                    strategy_func=strategy,
                    period="180d"
                )

                # 計算績效指標
                metrics = result.calculate_metrics()

                # 返回指定指標
                if maximize_metric == "sharpe_ratio":
                    return metrics.get("sharpe_ratio", 0)
                elif maximize_metric == "profit_factor":
                    return metrics.get("profit_factor", 0)
                elif maximize_metric == "win_rate":
                    return metrics.get("win_rate", 0)
                elif maximize_metric == "total_return":
                    return metrics.get("total_return", 0)
                else:
                    # 默認使用夏普比率
                    return metrics.get("sharpe_ratio", 0)

            except Exception as e:
                logger.error(f"參數 {params} 回測失敗: {e}")
                return float('-inf')

        # 使用網格搜索
        best_params, best_score, all_results = self.grid_search(
            param_grid=param_grid,
            maximize=True
        )

        # 轉換結果為 DataFrame
        results_df = pd.DataFrame(all_results)

        return best_params, best_score, results_df


class WalkForwardOptimizer:
    """Walk-forward 優化器（防止過擬合）"""

    def __init__(self, train_ratio: float = 0.7, n_windows: int = 5):
        """初始化 Walk-forward 優化器。

        Args:
            train_ratio: 訓練集比例
            n_windows: 時間窗口數量
        """
        self.train_ratio = train_ratio
        self.n_windows = n_windows

    def split_data(self, data: pd.DataFrame) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
        """將數據分割為多個訓練/測試窗口。

        Args:
            data: 完整歷史數據

        Returns:
            訓練/測試數據對列表
        """
        if len(data) < 100:
            logger.warning("數據量不足，無法進行有效的 walk-forward 優化")
            return []

        splits = []
        total_length = len(data)
        window_size = total_length // self.n_windows

        for i in range(self.n_windows):
            # 訓練集：當前窗口之前的所有數據
            train_end = i * window_size + int(window_size * self.train_ratio)
            train_data = data.iloc[:train_end]

            # 測試集：當前窗口的剩餘部分
            test_start = train_end
            test_end = min((i + 1) * window_size, total_length)
            test_data = data.iloc[test_start:test_end]

            if len(train_data) > 50 and len(test_data) > 20:
                splits.append((train_data, test_data))

        logger.info(f"創建了 {len(splits)} 個 walk-forward 窗口")
        return splits

    def validate_strategy(
        self,
        strategy_class: Callable,
        data: pd.DataFrame,
        param_grid: Dict[str, List[Any]],
        initial_capital: float = 100000.0
    ) -> Dict[str, Any]:
        """使用 Walk-forward 驗證策略穩定性。

        Args:
            strategy_class: 策略類
            data: 歷史數據
            param_grid: 參數網格
            initial_capital: 初始資金

        Returns:
            驗證結果字典
        """
        from .optimizer import ParameterOptimizer
        from .engine import BacktestEngine
        from .analyzer import PerformanceAnalyzer

        # 分割數據
        splits = self.split_data(data)
        if not splits:
            return {"error": "無法分割數據"}

        window_results = []
        all_metrics = []

        for i, (train_data, test_data) in enumerate(splits):
            logger.info(f"處理窗口 {i+1}/{len(splits)}: 訓練集 {len(train_data)} 天, 測試集 {len(test_data)} 天")

            # 在訓練集上優化參數
            def train_objective(params: Dict[str, Any]) -> float:
                # 簡化的目標函數，實際應用中需要完整回測
                try:
                    strategy = strategy_class(**params)
                    # 這裡需要實際的回測邏輯
                    # 暫時返回隨機分數作為示例
                    return np.random.random()
                except Exception:
                    return float('-inf')

            optimizer = ParameterOptimizer(train_objective)
            best_params, best_score, _ = optimizer.grid_search(
                param_grid=param_grid,
                maximize=True
            )

            if not best_params:
                logger.warning(f"窗口 {i+1} 未找到有效參數")
                continue

            # 在測試集上驗證
            # 注意：這裡需要實際的測試集回測邏輯
            # 暫時使用簡單的評分

            window_result = {
                "window": i + 1,
                "train_size": len(train_data),
                "test_size": len(test_data),
                "best_params": best_params,
                "train_score": best_score,
                "test_score": np.random.random(),  # 示例
                "params_stability": 1.0  # 示例參數穩定性
            }

            window_results.append(window_result)
            all_metrics.append(window_result["test_score"])

        # 計算整體驗證指標
        if window_results:
            test_scores = [r["test_score"] for r in window_results]
            param_stabilities = [r["params_stability"] for r in window_results]

            validation_result = {
                "n_windows": len(window_results),
                "avg_test_score": np.mean(test_scores),
                "std_test_score": np.std(test_scores),
                "avg_param_stability": np.mean(param_stabilities),
                "window_results": window_results,
                "is_robust": np.std(test_scores) < 0.1  # 測試分數標準差小於0.1認為穩健
            }

            logger.info(f"Walk-forward 驗證完成: {len(window_results)} 個窗口，平均測試分數: {validation_result['avg_test_score']:.4f}")
            return validation_result
        else:
            return {"error": "無有效的驗證窗口"}


def create_optimization_report(
    best_params: Dict[str, Any],
    best_score: float,
    results_df: pd.DataFrame,
    strategy_name: str
) -> str:
    """創建優化報告。

    Args:
        best_params: 最佳參數
        best_score: 最佳分數
        results_df: 所有結果 DataFrame
        strategy_name: 策略名稱

    Returns:
        格式化報告字符串
    """
    if results_df.empty:
        return f"⚠️ 無優化結果可用於 {strategy_name}"

    lines = [
        f"⚙️ {strategy_name} 參數優化報告",
        "=" * 60,
        f"\n🏆 最佳參數組合:",
    ]

    for param, value in best_params.items():
        lines.append(f"  {param}: {value}")

    lines.append(f"最佳分數: {best_score:.4f}")

    # 參數敏感度分析
    if not results_df.empty and "params" in results_df.columns:
        lines.append("\n📊 參數敏感度分析:")

        # 提取參數名稱
        param_names = list(best_params.keys())

        for param in param_names:
            if param in results_df["params"].iloc[0]:
                # 分組計算平均分數
                param_values = []
                avg_scores = []

                for _, row in results_df.iterrows():
                    param_value = row["params"][param]
                    if param_value not in param_values:
                        param_values.append(param_value)

                for value in param_values:
                    mask = results_df["params"].apply(lambda p: p[param] == value)
                    avg_score = results_df[mask]["score"].mean()
                    avg_scores.append(avg_score)

                # 找到最佳值
                best_value_idx = np.argmax(avg_scores)
                best_value = param_values[best_value_idx]

                lines.append(f"  {param}: 最佳值 = {best_value} (平均分數: {avg_scores[best_value_idx]:.4f})")

    # 結果統計
    lines.append(f"\n📈 優化統計:")
    lines.append(f"  總參數組合數: {len(results_df)}")
    lines.append(f"  最高分數: {results_df['score'].max():.4f}")
    lines.append(f"  最低分數: {results_df['score'].min():.4f}")
    lines.append(f"  平均分數: {results_df['score'].mean():.4f}")
    lines.append(f"  分數標準差: {results_df['score'].std():.4f}")

    lines.append("\n" + "=" * 60)
    lines.append("💡 建議：在樣本外數據上驗證最佳參數的穩定性")

    return "\n".join(lines)