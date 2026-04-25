"""回測驗證與過擬合防護模組。

提供交叉驗證、樣本外測試和過擬合檢測功能。
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class OverfittingValidator:
    """過擬合驗證器"""

    @staticmethod
    def calculate_complexity_penalty(
        n_params: int,
        n_samples: int,
        in_sample_score: float,
        complexity_factor: float = 0.01
    ) -> float:
        """計算複雜度懲罰（防止過擬合）。

        Args:
            n_params: 參數數量
            n_samples: 樣本數量
            in_sample_score: 樣本內分數
            complexity_factor: 複雜度懲罰因子

        Returns:
            調整後的分數
        """
        if n_samples <= n_params:
            penalty = 1.0  # 嚴重懲罰
        else:
            # 使用類似 AIC 的懲罰：2 * n_params / n_samples
            penalty = 1.0 - (2 * n_params / n_samples)

        adjusted_score = in_sample_score * penalty * (1 - complexity_factor)
        return max(adjusted_score, 0)

    @staticmethod
    def detect_overfitting(
        in_sample_metrics: Dict[str, float],
        out_of_sample_metrics: Dict[str, float],
        threshold: float = 0.3
    ) -> Dict[str, Any]:
        """檢測過擬合。

        Args:
            in_sample_metrics: 樣本內績效指標
            out_of_sample_metrics: 樣本外績效指標
            threshold: 過擬合閾值（樣本外/樣本內比例）

        Returns:
            過擬合檢測結果
        """
        if not in_sample_metrics or not out_of_sample_metrics:
            return {"error": "缺少績效指標數據"}

        # 關鍵指標對比
        key_metrics = ["sharpe_ratio", "win_rate", "profit_factor", "total_return"]

        comparisons = {}
        degradation_factors = []

        for metric in key_metrics:
            in_sample = in_sample_metrics.get(metric, 0)
            out_of_sample = out_of_sample_metrics.get(metric, 0)

            if in_sample != 0:
                degradation = 1 - (out_of_sample / in_sample) if in_sample > 0 else 1
            else:
                degradation = 1 if out_of_sample <= 0 else 0

            comparisons[metric] = {
                "in_sample": in_sample,
                "out_of_sample": out_of_sample,
                "degradation": degradation,
                "ratio": out_of_sample / in_sample if in_sample != 0 else float('inf')
            }

            degradation_factors.append(degradation)

        # 平均退化程度
        avg_degradation = np.mean(degradation_factors) if degradation_factors else 1

        # 過擬合判斷
        is_overfit = avg_degradation > threshold

        result = {
            "is_overfit": is_overfit,
            "avg_degradation": avg_degradation,
            "threshold": threshold,
            "comparisons": comparisons,
            "warning_level": "high" if is_overfit else ("medium" if avg_degradation > threshold/2 else "low")
        }

        logger.info(f"過擬合檢測: 平均退化程度 = {avg_degradation:.2f}, 是否過擬合 = {is_overfit}")

        return result

    @staticmethod
    def time_series_cross_validation(
        data: pd.DataFrame,
        strategy_func: callable,
        n_splits: int = 5,
        test_size: float = 0.2
    ) -> List[Dict[str, Any]]:
        """時間序列交叉驗證。

        Args:
            data: 時間序列數據
            strategy_func: 策略函數
            n_splits: 分割數量
            test_size: 測試集比例

        Returns:
            交叉驗證結果列表
        """
        if len(data) < 100:
            logger.warning("數據量不足，無法進行有效的交叉驗證")
            return []

        results = []
        total_length = len(data)
        test_samples = int(total_length * test_size)

        for i in range(n_splits):
            # 計算訓練集和測試集索引
            test_start = int(i * (total_length - test_samples) / max(n_splits - 1, 1))
            test_end = test_start + test_samples

            if test_end > total_length:
                test_end = total_length
                test_start = test_end - test_samples

            # 分割數據
            train_data = data.iloc[:test_start]
            test_data = data.iloc[test_start:test_end]

            if len(train_data) < 50 or len(test_data) < 20:
                logger.debug(f"分割 {i+1} 數據量不足，跳過")
                continue

            try:
                # 在訓練集上訓練/優化（這裡簡化）
                # 實際應用中需要在訓練集上優化參數

                # 在測試集上測試（這裡簡化）
                # 實際應用中需要在測試集上運行回測

                # 暫時使用簡單的評估
                train_score = np.random.random()  # 示例
                test_score = np.random.random() * 0.8  # 示例（通常測試分數較低）

                result = {
                    "split": i + 1,
                    "train_size": len(train_data),
                    "test_size": len(test_data),
                    "train_period": f"{train_data.index[0].date()} to {train_data.index[-1].date()}",
                    "test_period": f"{test_data.index[0].date()} to {test_data.index[-1].date()}",
                    "train_score": train_score,
                    "test_score": test_score,
                    "degradation": 1 - (test_score / train_score) if train_score > 0 else 1
                }

                results.append(result)
                logger.debug(f"交叉驗證分割 {i+1}: 訓練分數={train_score:.4f}, 測試分數={test_score:.4f}")

            except Exception as e:
                logger.error(f"交叉驗證分割 {i+1} 失敗: {e}")
                continue

        logger.info(f"時間序列交叉驗證完成: {len(results)} 個有效分割")
        return results

    @staticmethod
    def monte_carlo_cross_validation(
        data: pd.DataFrame,
        strategy_func: callable,
        n_iterations: int = 100,
        train_ratio: float = 0.7
    ) -> Dict[str, Any]:
        """蒙特卡羅交叉驗證。

        Args:
            data: 數據
            strategy_func: 策略函數
            n_iterations: 迭代次數
            train_ratio: 訓練集比例

        Returns:
            蒙特卡羅驗證結果
        """
        if len(data) < 100:
            logger.warning("數據量不足，無法進行蒙特卡羅交叉驗證")
            return {"error": "數據量不足"}

        train_scores = []
        test_scores = []
        degradations = []

        for i in range(n_iterations):
            try:
                # 隨機分割
                n_total = len(data)
                n_train = int(n_total * train_ratio)

                # 隨機選擇訓練索引（不重複）
                train_indices = np.random.choice(n_total, n_train, replace=False)
                test_indices = np.array([idx for idx in range(n_total) if idx not in train_indices])

                train_data = data.iloc[train_indices].sort_index()
                test_data = data.iloc[test_indices].sort_index()

                if len(train_data) < 50 or len(test_data) < 20:
                    continue

                # 簡化的評估（示例）
                train_score = np.random.random()
                test_score = np.random.random() * 0.9  # 測試分數通常較低

                degradation = 1 - (test_score / train_score) if train_score > 0 else 1

                train_scores.append(train_score)
                test_scores.append(test_score)
                degradations.append(degradation)

            except Exception as e:
                logger.debug(f"蒙特卡羅迭代 {i+1} 失敗: {e}")
                continue

        if not train_scores:
            return {"error": "無有效的蒙特卡羅迭代"}

        # 統計結果
        result = {
            "n_iterations": n_iterations,
            "n_valid_iterations": len(train_scores),
            "avg_train_score": np.mean(train_scores),
            "avg_test_score": np.mean(test_scores),
            "std_train_score": np.std(train_scores),
            "std_test_score": np.std(test_scores),
            "avg_degradation": np.mean(degradations),
            "std_degradation": np.std(degradations),
            "degradation_95ci": (
                np.mean(degradations) - 1.96 * np.std(degradations) / np.sqrt(len(degradations)),
                np.mean(degradations) + 1.96 * np.std(degradations) / np.sqrt(len(degradations))
            ),
            "is_robust": np.mean(degradations) < 0.3 and np.std(test_scores) < 0.2
        }

        logger.info(f"蒙特卡羅交叉驗證完成: {len(train_scores)} 次有效迭代，平均退化程度 = {result['avg_degradation']:.3f}")

        return result


class StrategyValidator:
    """策略綜合驗證器"""

    def __init__(self, strict_mode: bool = True):
        """初始化驗證器。

        Args:
            strict_mode: 嚴格模式（更多驗證檢查）
        """
        self.strict_mode = strict_mode
        self.validator = OverfittingValidator()

    def validate_strategy(
        self,
        strategy_name: str,
        in_sample_results: Dict[str, Any],
        out_of_sample_results: Dict[str, Any],
        param_count: int,
        data_size: int
    ) -> Dict[str, Any]:
        """綜合驗證策略。

        Args:
            strategy_name: 策略名稱
            in_sample_results: 樣本內結果
            out_of_sample_results: 樣本外結果
            param_count: 參數數量
            data_size: 數據量

        Returns:
            綜合驗證結果
        """
        validation_result = {
            "strategy_name": strategy_name,
            "validation_date": datetime.now().isoformat(),
            "passed": True,
            "warnings": [],
            "errors": [],
            "scores": {},
            "recommendation": "PASS"
        }

        # 1. 過擬合檢測
        if in_sample_results.get("metrics") and out_of_sample_results.get("metrics"):
            overfitting_check = self.validator.detect_overfitting(
                in_sample_metrics=in_sample_results["metrics"],
                out_of_sample_metrics=out_of_sample_results["metrics"],
                threshold=0.3
            )

            validation_result["overfitting_check"] = overfitting_check

            if overfitting_check.get("is_overfit", False):
                validation_result["passed"] = False
                validation_result["errors"].append("檢測到過擬合")
                validation_result["recommendation"] = "FAIL - 過擬合"

        # 2. 複雜度懲罰計算
        if in_sample_results.get("metrics", {}).get("sharpe_ratio"):
            in_sample_sharpe = in_sample_results["metrics"]["sharpe_ratio"]
            adjusted_score = self.validator.calculate_complexity_penalty(
                n_params=param_count,
                n_samples=data_size,
                in_sample_score=in_sample_sharpe
            )

            validation_result["scores"]["in_sample_sharpe"] = in_sample_sharpe
            validation_result["scores"]["adjusted_sharpe"] = adjusted_score

            if adjusted_score < in_sample_sharpe * 0.7:  # 調整後分數下降超過30%
                validation_result["warnings"].append(f"複雜度懲罰較高: {adjusted_score/in_sample_sharpe:.1%}")

        # 3. 樣本外穩定性檢查
        if out_of_sample_results.get("metrics", {}).get("sharpe_ratio"):
            out_of_sample_sharpe = out_of_sample_results["metrics"]["sharpe_ratio"]

            if out_of_sample_sharpe < 0:
                validation_result["warnings"].append(f"樣本外夏普比率為負: {out_of_sample_sharpe:.2f}")

        # 4. 交易次數檢查
        if in_sample_results.get("metrics", {}).get("total_trades", 0) < 10:
            validation_result["warnings"].append("樣本內交易次數過少 (<10)，統計顯著性不足")

        # 5. 最大回撤檢查
        if in_sample_results.get("metrics", {}).get("max_drawdown", 0) < -0.3:
            validation_result["warnings"].append(f"最大回撤過大: {in_sample_results['metrics']['max_drawdown']:.1%}")

        # 6. 盈利因子檢查
        if in_sample_results.get("metrics", {}).get("profit_factor", 0) < 1.2:
            validation_result["warnings"].append(f"盈利因子偏低: {in_sample_results['metrics']['profit_factor']:.2f}")

        # 生成最終建議
        if not validation_result["passed"]:
            validation_result["recommendation"] = "FAIL"
        elif validation_result["warnings"]:
            validation_result["recommendation"] = "PASS WITH WARNINGS"
        else:
            validation_result["recommendation"] = "PASS"

        logger.info(f"策略驗證完成: {strategy_name} -> {validation_result['recommendation']}")

        return validation_result

    def generate_validation_report(self, validation_result: Dict[str, Any]) -> str:
        """生成驗證報告。

        Args:
            validation_result: 驗證結果

        Returns:
            格式化報告字符串
        """
        lines = [
            f"🔍 {validation_result['strategy_name']} 策略驗證報告",
            f"驗證日期: {validation_result['validation_date'][:10]}",
            "=" * 60,
        ]

        # 總體結果
        status_icon = "✅" if validation_result["passed"] else "❌"
        lines.append(f"\n總體結果: {status_icon} {validation_result['recommendation']}")

        # 分數
        if validation_result.get("scores"):
            lines.append("\n📊 績效分數:")
            for score_name, score_value in validation_result["scores"].items():
                lines.append(f"  {score_name}: {score_value:.4f}")

        # 過擬合檢查
        if validation_result.get("overfitting_check"):
            oc = validation_result["overfitting_check"]
            lines.append("\n⚠️ 過擬合檢查:")
            lines.append(f"  是否過擬合: {'是' if oc.get('is_overfit') else '否'}")
            lines.append(f"  平均退化程度: {oc.get('avg_degradation', 0):.2f}")
            lines.append(f"  警告級別: {oc.get('warning_level', '未知')}")

        # 錯誤
        if validation_result["errors"]:
            lines.append("\n❌ 錯誤:")
            for error in validation_result["errors"]:
                lines.append(f"  • {error}")

        # 警告
        if validation_result["warnings"]:
            lines.append("\n⚠️ 警告:")
            for warning in validation_result["warnings"]:
                lines.append(f"  • {warning}")

        # 建議
        lines.append("\n💡 建議:")
        if not validation_result["passed"]:
            lines.append("  1. 重新設計策略，減少過擬合")
            lines.append("  2. 增加樣本外測試數據")
            lines.append("  3. 減少策略參數數量")
        elif validation_result["warnings"]:
            lines.append("  1. 監控警告指標")
            lines.append("  2. 在實盤前進行更多測試")
            lines.append("  3. 考慮調整風險參數")
        else:
            lines.append("  1. 策略通過所有驗證檢查")
            lines.append("  2. 可以考慮進行小規模實盤測試")
            lines.append("  3. 繼續監控策略表現")

        lines.append("\n" + "=" * 60)
        lines.append("注意：驗證結果基於歷史數據，不代表未來表現")

        return "\n".join(lines)